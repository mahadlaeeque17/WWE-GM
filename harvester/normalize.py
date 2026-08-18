"""Build the SQLite store from the harvested JSON.

    python normalize.py ../data/raw/roster_1980_2000.json ../data/gm2000.db

Rebuilds SOURCE tables and re-derives attributes. It deliberately does NOT touch
`attribute_override` or any game table, so re-running after a formula change
leaves hand-edited ratings and a save in progress intact.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import attributes as A

HERE = Path(__file__).parent

# Tables normalize.py owns and may safely wipe. Everything else is off limits.
SOURCE_TABLES = ("ring_name", "promotion_year", "title_reign", "attributes", "wrestler")


def fix_encoding(text: str | None) -> str | None:
    """Pages are ISO-8859-1 but arrive decoded as UTF-8, so non-ASCII
    birthplaces come through mangled (`S<?>dkorea`). Round-trip them."""
    if not text:
        return text
    try:
        return text.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore") or text
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def parse_birth_year(birthday: str | None) -> int | None:
    if not birthday:
        return None
    m = re.search(r"(\d{4})", birthday)
    return int(m.group(1)) if m else None


def parse_reign_days(text: str) -> int:
    if not text:
        return 0
    if text.strip().startswith("<"):
        return 0
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else 0


def parse_reign_count(title: str) -> int:
    m = re.search(r"\((\d+)x\)", title)
    return int(m.group(1)) if m else 1


def load_dated_reigns(path: Path) -> dict[int, list[dict]]:
    """Dated reigns keyed by wrestler id. The worker Titles tab has no dates,
    which would credit Trish with seven titles she had not yet won in 2000."""
    if not path.exists():
        return {}
    by_wrestler: dict[int, list[dict]] = {}
    for r in json.loads(path.read_text(encoding="utf-8"))["reigns"]:
        won = r.get("won")
        year = int(won[-4:]) if won else None
        for h in r["holders"]:
            by_wrestler.setdefault(h["id"], []).append(
                {"title": r["title"], "won": won, "lost": r.get("lost"),
                 "days": r.get("days") or 0, "year": year}
            )
    return by_wrestler


def load_per_year(path: Path) -> dict[int, list[dict]]:
    """Per-promotion-per-year rows from the raw sweep.

    Cagematch lists a wrestler once PER GIMMICK per year, so the same
    (wrestler, promotion, year) can appear several times — Sherri's 1987 shows
    up as both "Sensational Sherri" (44 matches) and "Sherri Martel" (2). These
    must be SUMMED. Feeding the raw rows to an INSERT OR REPLACE keyed on
    (wrestler_id, promotion, year) keeps only the last and silently discards the
    rest, which cost Sherri 176 of her 232 WWE matches before it was caught.
    """
    if not path.exists():
        return {}
    merged: dict[tuple[int, str, int], dict] = {}
    for r in json.loads(path.read_text(encoding="utf-8")).get("promotion_years", []):
        key = (r["id"], r["promo"], r["year"])
        acc = merged.get(key)
        if acc is None:
            merged[key] = dict(r)
        else:
            for f in ("matches", "wins", "losses", "draws"):
                acc[f] += r[f]

    out: dict[int, list[dict]] = {}
    for (wid, _, _), r in merged.items():
        out.setdefault(wid, []).append(r)
    return out


def load_vitals(path: Path) -> dict[int, dict]:
    """Height and weight live in the stage-1 female index, not the roster file.
    The cruiserweight title needs weights, so pull them across."""
    if not path.exists():
        return {}
    idx = json.loads(path.read_text(encoding="utf-8")).get("female_index", [])
    return {r["id"]: r for r in idx}


def main(src: Path, dbpath: Path) -> None:
    data = json.loads(src.read_text(encoding="utf-8"))
    dated = load_dated_reigns(src.parent / "title_reigns.json")
    per_year = load_per_year(src.parent / "harvest_cache.json")
    vitals = load_vitals(src.parent / "harvest_cache.json")
    now = datetime.now(timezone.utc).isoformat()

    dbpath.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(dbpath)
    con.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))

    kept_overrides = con.execute("SELECT COUNT(*) FROM attribute_override").fetchone()[0]

    # Permanently banned wrestlers must never be rebuilt from the harvest — this
    # is what makes "remove permanently" survive a re-normalize.
    banned = {r[0] for r in con.execute("SELECT wrestler_id FROM banned_wrestler")}

    for t in SOURCE_TABLES:
        con.execute(f"DELETE FROM {t}")

    for w in data["wrestlers"]:
        wid = w["id"]
        if wid in banned:
            continue
        titles = w.get("titles") or []
        prof = w.get("profile") or {}

        my_reigns = dated.get(wid, [])
        pre = [r for r in my_reigns if r["year"] and r["year"] < A.RESET_YEAR]

        src_rec = A.Source(
            roles=prof.get("roles"),
            rating=w.get("rating"),
            votes=w.get("votes"),
            wins=w["wins"], losses=w["losses"], draws=w["draws"],
            matches=w["matches"], promos=w["promos"],
            reigns_pre_reset=len(pre),
            title_days_pre_reset=sum(r["days"] for r in pre),
            style=prof.get("style"),
        )
        attrs = A.derive(src_rec)
        age, precision = A.parse_age_at_reset(w.get("born"))

        con.execute(
            """INSERT INTO wrestler
               (id, name, birthday, birth_year, age_at_reset, age_precision,
                birthplace, height_cm, weight_kg, rating, votes, adj_rating,
                career_start, career_end, style, harvested_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (wid, w["name"], w.get("born"), parse_birth_year(w.get("born")),
             age, precision, fix_encoding(w.get("from")),
             (vitals.get(wid) or {}).get("height_cm"),
             (vitals.get(wid) or {}).get("weight_kg"),
             w.get("rating"), w.get("votes"),
             round(A.adjusted_rating(w.get("rating"), w.get("votes")), 3),
             prof.get("start"), prof.get("end"), prof.get("style"), now),
        )

        for nm in (w.get("names") or []):
            if nm.strip():
                con.execute(
                    "INSERT OR IGNORE INTO ring_name (wrestler_id, name, is_primary) VALUES (?,?,?)",
                    (wid, nm.strip(), 1 if nm.strip() == w["name"].strip() else 0),
                )

        detail = per_year.get(wid)
        if detail:
            for r in detail:
                con.execute(
                    """INSERT OR REPLACE INTO promotion_year
                       (wrestler_id, promotion, year, matches, wins, losses, draws)
                       VALUES (?,?,?,?,?,?,?)""",
                    (wid, r["promo"], r["year"], r["matches"], r["wins"], r["losses"], r["draws"]),
                )
        else:
            for promo, p in w["promos"].items():
                con.execute(
                    """INSERT OR REPLACE INTO promotion_year
                       (wrestler_id, promotion, year, matches, wins, losses, draws)
                       VALUES (?,?,?,?,?,?,?)""",
                    (wid, promo, p["y1"], p["m"], p["w"], p["l"], p["d"]),
                )

        if my_reigns:
            for r in my_reigns:
                con.execute(
                    """INSERT INTO title_reign (wrestler_id, title, won_on, lost_on, days)
                       VALUES (?,?,?,?,?)""",
                    (wid, r["title"], r["won"], r["lost"], r["days"]),
                )
        else:
            for t in titles:
                if t:
                    con.execute(
                        "INSERT INTO title_reign (wrestler_id, title, days) VALUES (?,?,?)",
                        (wid, t[0], parse_reign_days(t[1]) if len(t) > 1 else None),
                    )

        con.execute(
            """INSERT INTO attributes
               (wrestler_id, charisma, popularity, looks, availability,
                role, role_source, personality, formula_ver)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (wid, attrs["charisma"], attrs["popularity"], attrs["looks"],
             attrs["availability"], attrs["role"], attrs["role_source"],
             attrs["personality"], attrs["formula_ver"]),
        )

        # Seed sim state without disturbing an existing save.
        con.execute("INSERT OR IGNORE INTO wrestler_state (wrestler_id) VALUES (?)", (wid,))

    con.commit()

    n = con.execute("SELECT COUNT(*) FROM wrestler").fetchone()[0]
    ages = con.execute(
        "SELECT age_precision, COUNT(*) FROM wrestler GROUP BY age_precision"
    ).fetchall()
    print(f"{n} wrestlers -> {dbpath}")
    for a, c in con.execute("SELECT availability, COUNT(*) FROM attributes GROUP BY availability"):
        print(f"  {a}: {c}")
    print("  age precision: " + ", ".join(f"{p}={c}" for p, c in ages))
    print(f"  user overrides preserved: {kept_overrides}")
    con.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
