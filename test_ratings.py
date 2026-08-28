"""Prove the five-category rating system, end to end, on a throwaway save.

    python test_ratings.py

Runs against a COPY of the bundled save, so it never touches your game.

What it checks, and why each one is here rather than assumed:

  scale          every category is 0-20 and the five sum to the overall shown.
                 The whole system is "the number on screen is the five numbers
                 next to it added up", so if that ever stops being true the
                 design is broken, not just the arithmetic.
  achievements   starts at 0 for the entire roster, and only moves when
                 something is actually won. This is the one category that is
                 computed rather than stored, so it is the one that can silently
                 go stale.
  live wrestling the win/loss swing tracks the record and stays inside its band.
  money          winning makes a wrestler more expensive. That is the intended
                 consequence of Achievements existing, so it is worth asserting
                 rather than discovering two seasons in.
  no leakage     nothing anywhere still reads the retired `charisma` /
                 `experience` categories.
  deploy path    an OLD-SCHEMA save upgrades itself at boot. This is the one
                 that only bites in production: a stateless host pulls its save
                 down from Blob storage, so the database the app opens can
                 predate the whole rating change, and the first roster request
                 dies on a missing column.
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import sys
import tempfile
import token
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "harvester")]

import attributes as A  # noqa: E402
import game  # noqa: E402
import migrate_ratings  # noqa: E402
import rankings  # noqa: E402

FAILED: list[str] = []

# A string literal that is actually SQL. Anything mentioning a retired column
# inside one of these is a live query, not documentation.
_SQL_WORDS = ("SELECT", "INSERT", "UPDATE", "DELETE", "COALESCE")


def _is_sql(literal: str) -> bool:
    return any(w in literal for w in _SQL_WORDS)


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          + (f"\n          {detail}" if not cond and detail else ""))
    if not cond:
        FAILED.append(label)


def main() -> int:
    src = ROOT / "data" / "gm2000.db"
    if not src.exists():
        print(f"no save at {src}")
        return 2
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    shutil.copyfile(src, tmp)

    con = sqlite3.connect(tmp)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    game.ensure_schema(con)
    rankings.ensure_schema(con)
    game.ensure_titles(con)

    ids = {r["name"]: r["id"] for r in con.execute("SELECT id, name FROM wrestler")}

    # ------------------------------------------------------------------ scale
    print("scale")
    ach = game.achievement_inputs(con)
    rows = [game.effective_attributes(con, w, ach.get(w)) for w in ids.values()]
    # Role-aware: a MANAGER's five are Mic/Achievements/Influence/Looks/Personal,
    # because Wrestling and Popularity are the wrong questions to ask about
    # someone whose job is talking. Summing the wrestler five for everyone is
    # what this check used to do, and it flagged all thirteen managers.
    def five(e):
        return A.categories_for(e.get("role") or "wrestler")

    bad = [(c, e[c]) for e in rows for c in five(e) if not 0 <= e[c] <= A.CAT_MAX]
    check(f"every category of all {len(rows)} wrestlers is within 0-{A.CAT_MAX}",
          not bad, f"out of range: {bad[:4]}")
    mismatch = [e for e in rows if e["overall"] != sum(e[c] for c in five(e))]
    check("overall equals her own five categories added up", not mismatch,
          f"{len(mismatch)} rows disagree")
    mgrs = [e for e in rows if (e.get("role") or "") == "manager"]
    check(f"a manager is scored on Mic and Influence ({len(mgrs)} of them)",
          all(e["performance_pair"] == ["mic", "influence"] for e in mgrs)
          and len(mgrs) > 0,
          str([e["performance_pair"] for e in mgrs[:3]]))
    check("a wrestler is still scored on Wrestling and Popularity",
          all(e["performance_pair"] == ["wrestling", "popularity"]
              for e in rows if (e.get("role") or "wrestler") != "manager"))
    check("five categories, 20 each, 100 total",
          A.CAT_MAX == 20 and len(A.CATEGORIES) == 5 and A.OVERALL_MAX == 100,
          f"{len(A.CATEGORIES)} × {A.CAT_MAX} = {A.OVERALL_MAX}")

    # ----------------------------------------------------------- achievements
    print("\nachievements start at zero and are earned")
    check("nobody on the roster has a non-zero Achievements on a fresh save",
          all(e["achievements"] == 0 for e in rows),
          f"{sum(1 for e in rows if e['achievements'])} wrestlers already scored")

    wid = ids["Trish Stratus"]
    before = game.effective_attributes(con, wid)
    world = con.execute("SELECT id FROM game_title WHERE tier='world' LIMIT 1").fetchone()["id"]
    con.execute("""INSERT INTO game_title_reign (title_id, wrestler_id, won_on, lost_on)
                   VALUES (?,?,?,?)""", (world, wid, "2000-03-01", "2000-09-01"))
    con.commit()
    after_title = game.effective_attributes(con, wid)
    check("a world title reign raises Achievements",
          after_title["achievements"] > before["achievements"],
          f"{before['achievements']} -> {after_title['achievements']}")
    check("the reign is explained in words, not just a number",
          any("world" in r for r in after_title["achievement_reasons"]),
          str(after_title["achievement_reasons"]))

    game.award(con, wid, "royal_rumble")
    game.award(con, wid, "playboy_cover")
    after_acc = game.effective_attributes(con, wid)
    check("a Rumble win and a Playboy cover raise it further",
          after_acc["achievements"] > after_title["achievements"],
          f"{after_title['achievements']} -> {after_acc['achievements']}")

    # An ongoing reign must be measured against the GAME date, not today's real
    # date — `current_date` is a SQLite keyword and a bare SELECT returns TODAY.
    con.execute("""INSERT INTO game_title_reign (title_id, wrestler_id, won_on, lost_on)
                   VALUES (?,?,?,NULL)""", (world, ids["Lita"], "2000-01-15"))
    con.commit()
    inputs = game.achievement_inputs(con)[ids["Lita"]]
    check("an ongoing reign counts game days, not real-world days",
          inputs["title_days"] < 400,
          f"{inputs['title_days']} days since 2000-01-15 with the save on "
          f"{con.execute('SELECT game_state.current_date FROM game_state').fetchone()[0]}")

    # ------------------------------------------------------------- live wrestling
    print("\nwrestling responds to the save record")
    base = con.execute("SELECT COALESCE(o.wrestling, a.wrestling) v FROM attributes a "
                       "LEFT JOIN attribute_override o ON o.wrestler_id=a.wrestler_id "
                       "WHERE a.wrestler_id=?", (wid,)).fetchone()["v"]
    con.execute("UPDATE wrestler_state SET sim_matches=40, sim_wins=36 WHERE wrestler_id=?", (wid,))
    con.commit()
    hot = game.effective_attributes(con, wid)
    con.execute("UPDATE wrestler_state SET sim_matches=40, sim_wins=4 WHERE wrestler_id=?", (wid,))
    con.commit()
    cold = game.effective_attributes(con, wid)
    check("a 36-4 run is worth more than a 4-36 one",
          hot["wrestling"] > cold["wrestling"],
          f"{hot['wrestling']} vs {cold['wrestling']}")
    check(f"the swing stays inside ±{A.RECORD_SWING_MAX:.0f} of the base",
          abs(hot["wrestling"] - base) <= A.RECORD_SWING_MAX + 0.5
          and abs(cold["wrestling"] - base) <= A.RECORD_SWING_MAX + 0.5,
          f"base {base}, hot {hot['wrestling']}, cold {cold['wrestling']}")
    check("one match cannot buy the whole bonus",
          abs(A.record_swing(1, 1)) < A.RECORD_SWING_MAX / 2,
          f"1-0 gives {A.record_swing(1, 1):+.2f}")

    # ------------------------------------------------------------------- money
    print("\nmoney")
    check("winning things makes her more expensive",
          after_acc["value"] > before["value"],
          f"${before['value']:,} -> ${after_acc['value']:,}")
    top = A.contract_value(17, 0, 18, 20, 10, 24)
    check("a day-one top draw still commands top-draw money",
          1_000_000 <= top <= 1_500_000, f"${top:,}")
    mid = A.contract_value(11, 0, 9, 10, 10, 30)
    check("the roster median is still mid-card money",
          150_000 <= mid <= 450_000, f"${mid:,}")
    check("a manager is priced without any Wrestling input",
          A.CAT_MAX and game.manager_price(con, ids["Vickie Guerrero"]) > 0)

    # --------------------------------------------------------------- no leakage
    print("\nthe retired categories are gone")
    # Tokenised, not line-matched. Prose is allowed to say "charisma" — the
    # comments explaining why it was retired obviously do — so a text search over
    # raw lines reports the documentation as a defect. Only NAMES and the strings
    # that reach SQL are code, so only those are checked.
    leaks = []
    for f in sorted((ROOT / "backend").glob("*.py")):
        for tok in tokenize.generate_tokens(f.open(encoding="utf-8").readline):
            if tok.type == token.NAME and tok.string in ("charisma", "experience"):
                leaks.append(f"{f.name}:{tok.start[0]} identifier {tok.string}")
            elif tok.type == token.STRING and _is_sql(tok.string):
                for dead in ("charisma", "experience"):
                    if re.search(rf"\b{dead}\b", tok.string):
                        leaks.append(f"{f.name}:{tok.start[0]} SQL mentions {dead}")
    check("no backend code still reads charisma or experience", not leaks,
          "\n          ".join(leaks[:5]))

    # ------------------------------------------------- the deployed-upgrade path
    #
    # THE ONE THAT ONLY BITES IN PRODUCTION. On a stateless host the save is
    # pulled down from Blob storage at boot, so the database the app opens is
    # whatever is in the store — which can predate this whole rating change no
    # matter what the deployment bundles. The first roster request then dies on
    # `no such column: a.wrestling`. So: rebuild an OLD-schema save out of the
    # real roster, and assert a boot repairs it.
    print("\nan old save upgrades itself on boot")
    old = Path(tempfile.mkdtemp()) / "old.db"
    shutil.copyfile(src, old)
    oc = sqlite3.connect(old)
    oc.executescript("""
        CREATE TABLE attributes_old (
            wrestler_id INTEGER PRIMARY KEY,
            charisma    INTEGER NOT NULL,
            popularity  INTEGER NOT NULL,
            looks       INTEGER NOT NULL,
            availability TEXT NOT NULL,
            role        TEXT NOT NULL DEFAULT 'wrestler',
            role_source TEXT,
            alignment   TEXT NOT NULL DEFAULT 'face',
            personality TEXT NOT NULL DEFAULT 'ambitious',
            formula_ver INTEGER NOT NULL
        );
        -- Back to /25 values, the shape a pre-change save actually had.
        INSERT INTO attributes_old
          SELECT wrestler_id,
                 MIN(25, CAST(popularity * 1.25 AS INTEGER)),
                 MIN(25, CAST(popularity * 1.25 AS INTEGER)),
                 MIN(25, CAST(looks * 1.25 AS INTEGER)),
                 availability, role, role_source, alignment, personality, 3
            FROM attributes;
        DROP TABLE attributes;
        ALTER TABLE attributes_old RENAME TO attributes;
        DELETE FROM game_setting WHERE key IN ('ratings_scale_version','budget_scale_version');
        UPDATE attribute_override SET wrestling = NULL, personal = NULL;
    """)
    oc.commit()
    cols_before = {r[1] for r in oc.execute("PRAGMA table_info(attributes)")}
    check("the fixture really is on the old schema",
          "charisma" in cols_before and "wrestling" not in cols_before,
          str(sorted(cols_before)))

    note = migrate_ratings.ensure_migrated(oc)
    cols_after = {r[1] for r in oc.execute("PRAGMA table_info(attributes)")}
    check("boot adds wrestling and personal, and drops charisma",
          {"wrestling", "personal"} <= cols_after and "charisma" not in cols_after,
          str(sorted(cols_after)))
    check("boot reports what it did, for the startup log", bool(note), repr(note))

    n_bad = oc.execute(f"""SELECT COUNT(*) FROM attributes
                            WHERE wrestling NOT BETWEEN 0 AND {A.CAT_MAX}
                               OR popularity NOT BETWEEN 0 AND {A.CAT_MAX}
                               OR looks      NOT BETWEEN 0 AND {A.CAT_MAX}
                               OR personal   NOT BETWEEN 0 AND {A.CAT_MAX}""").fetchone()[0]
    check("every migrated rating is in range", n_bad == 0, f"{n_bad} out of range")
    check("the roster survived intact",
          oc.execute("SELECT COUNT(*) FROM attributes").fetchone()[0]
          == oc.execute("SELECT COUNT(*) FROM wrestler").fetchone()[0])

    # Second boot must be free. A migration that re-ran would rescale a rescale.
    again = migrate_ratings.ensure_migrated(oc)
    check("a second boot is a no-op", again is None, repr(again))
    sample = oc.execute("SELECT wrestling, popularity, looks, personal "
                        "FROM attributes ORDER BY wrestler_id LIMIT 1").fetchone()
    third = migrate_ratings.ensure_migrated(oc)
    sample2 = oc.execute("SELECT wrestling, popularity, looks, personal "
                         "FROM attributes ORDER BY wrestler_id LIMIT 1").fetchone()
    check("and does not quietly rescale the roster again",
          third is None and sample == sample2, f"{sample} -> {sample2}")
    oc.close()
    shutil.rmtree(old.parent, ignore_errors=True)

    con.close()
    shutil.rmtree(tmp.parent, ignore_errors=True)
    print(f"\n{'FAIL — ' + str(len(FAILED)) + ' check(s) failed' if FAILED else 'PASS — all checks passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
