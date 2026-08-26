"""Move a save from the four 0-25 ratings to the five 0-20 ratings.

    python migrate_ratings.py ../data/gm2000.db          # do it
    python migrate_ratings.py ../data/gm2000.db --dry     # show it, change nothing

WHAT CHANGES

    experience  -> gone. It started everyone at zero and grew with sim matches,
                   which meant a debut roster was perfectly flat in the ring:
                   Manami Toyota and a valet opened the game identical. Wrestling
                   replaces it and starts from what she could actually do.
    charisma    -> folded into Popularity as its promo component. "Popularity" in
                   wrestling has never been separable from being able to talk.
    popularity  -> rescaled to 0-20 and reseeded from cagematch score + reach.
    looks       -> rescaled to 0-20. YOUR TUNING IS PRESERVED IN PROPORTION,
                   which is the whole reason this is a considered migration and
                   not a re-seed: ×0.8, so 25→20, 24→19, 10→8.
    personal    -> new, seeded at a neutral 10 for everyone.
    achievements-> new, and stored NOWHERE. Computed from this save's title
                   reigns and accolades on every read, so it starts at 0 for
                   absolutely everyone and is earned from the shows you book.

WHY IT IS ONE SCRIPT AND NOT PART OF migrate.py

`attributes.charisma` is NOT NULL with no default, and SQLite cannot drop a
constraint in place — so the table has to be rewritten, not altered. A rewrite
that also has to compute new values from old ones is data surgery, and data
surgery belongs somewhere it can be read, dry-run, and reasoned about, rather
than buried among twenty ALTER statements.

IDEMPOTENCY. Rescaling twice would multiply the roster by 0.64 and there would be
no way to tell from the numbers that it had happened. So the run is gated on a
marker in `game_setting`, and it refuses to run twice. `--force` exists but is
almost certainly the wrong thing to reach for.

A timestamped copy of the database is written beside it first, matching the
data/gm2000.backup-* files already in the repo.

RUN AUTOMATICALLY ON A SERVER TOO. `ensure_migrated()` is the same migration
without the backup or the report, and backend/main.py calls it at boot. That is
not a convenience: on a stateless host the save is pulled down from Blob storage
before anything opens it, so the database the app actually runs on is whatever is
in the store — which may predate this change no matter what the bundled seed
contains. Without this the first request after a deploy dies on
`no such column: a.wrestling`.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import attributes as A  # noqa: E402

MARKER = "ratings_scale_version"
TARGET = "5x20"

# 25 -> 20. Applied to values you tuned by hand, so it is a rescale and not a
# re-derivation: the ordering and the relative gaps you chose are exactly
# preserved, only the ceiling moves.
RESCALE = A.CAT_MAX / 25.0

# How the two old "how over is she" categories combine into the one new one.
# Popularity carried more weight than charisma before and still should, but a
# hand-raised charisma was a real judgement about her act and is not thrown away.
POP_FROM_POPULARITY = 0.55
POP_FROM_CHARISMA = 0.45

# ------------------------------------------------ seeding Wrestling without data
#
# 220 of the 270 wrestlers have no cagematch rating, no usable vote count and no
# match history, so `attributes.wrestling()` would hand every one of them the
# same floor value. The only signal left is their old charisma, which was set by
# hand batch by batch.
#
# BE HONEST ABOUT WHAT THAT SIGNAL IS. Charisma was promo skill, and promo skill
# is not in-ring ability — in this very roster Kelly Kelly and MsChif both sit on
# 13, and one of them is a former ROH-calibre technician. So the map below is not
# a measurement; it is a way of placing 220 wrestlers on a coherent scale without
# claiming to know each one. It is calibrated to put the unrated group on the SAME
# distribution as the 50 rated ones — median to median, top to top — so the two
# halves of the roster can be compared at all:
#
#     charisma  9 (band floor)  ->   7.5      charisma 13 (median) -> 11
#     charisma 16              ->  13.6      charisma 21 (band top) -> 18
#
# Anything derived this way is flagged in the report as `hand`, and CURATED below
# overrides it wherever a formula would be plainly wrong.
HAND_CHARISMA_MEDIAN = 13.0
HAND_WRESTLING_AT_MEDIAN = 11.0
HAND_WRESTLING_SLOPE = 0.875

# Managers are the one case where the map fails predictably rather than randomly.
# Vickie Guerrero carries charisma 19 because she was magnificent on a microphone,
# not because she could wrestle; mapping that straight across would have made her
# one of the best workers in the game.
MANAGER_WRESTLING_MULT = 0.55

# CURATED. Wrestlers whose in-ring reputation is well enough established that a
# proxy off promo skill gives an answer we know to be wrong. These are judgement
# calls, stated openly and in one place so they can be argued with and edited —
# which is the honest way to encode "the data does not know this but we do".
#
# Two kinds of correction, both present:
#   UP    elite workers the charisma proxy undersells — the technicians and
#         Joshi standouts who were never great talkers.
#   DOWN  hugely charismatic performers who were never asked to carry a match.
CURATED_WRESTLING = {
    # --- elite workers the proxy undersells -----------------------------------
    "Sara Del Rey": 19,          "Mercedes Martinez": 18,
    "Cheerleader Melissa": 18,   "MsChif": 16,
    "Io Shirai": 19,             "Kana": 19,
    "Awesome Kong": 18,          "Gail Kim": 18,
    "Beth Phoenix": 17,          "Jazz": 17,
    "Madison Eagles": 17,        "Ayako Hamada": 18,
    "LuFisto": 17,               "Sumie Sakai": 16,
    "Nanae Takahashi": 18,       "Ayumi Kurihara": 17,
    "Hikaru Shida": 17,          "Tsukasa Fujimoto": 17,
    "Arisa Nakajima": 18,        "Syuri": 17,
    "Hiroyo Matsumoto": 17,      "Kagetsu": 17,
    "Portia Perez": 16,          "Daizee Haze": 16,
    "Allison Danger": 15,        "Serena Deeb": 16,
    "Michelle McCool": 15,       "Nattie Neidhart": 17,
    "Molly Holly": 17,           "Victoria": 16,
    "Mickie James": 17,          "Athena": 17,
    "Mia Yim": 17,               "Jessicka Havok": 15,
    "Courtney Rush": 16,         "Cherry Bomb": 15,
    "Kimber Lee": 16,            "Heidi Lovelace": 16,
    "Evie": 17,                  "Toni Storm": 16,
    "Meiko Satomura": 20,        "Emi Sakura": 17,
    "Riho": 16,                  "Sexy Star": 13,
    "Santana Garrett": 16,       "Allysin Kay": 15,
    "Kellie Skater": 15,         "Shazza McKenzie": 14,
    "Jessie McKay": 15,          "Tenille Dashwood": 14,
    "Britani Knight": 16,        "Saraya Knight": 15,
    "Rhia O'Reilly": 14,         "Veda Scott": 13,
    "Kyoko Kimura": 16,          "Misaki Ohata": 16,
    "Ryo Mizunami": 16,          "Mio Shirai": 15,
    "Yumi Ohka": 15,             "Kaori Yoneyama": 16,
    "Hanako Nakamori": 16,       "Kayoko Haruyama": 16,
    "Command Bolshoi": 16,       "Tsubasa Kuragaki": 16,
    "Sonoko Kato": 16,           "Mayumi Ozaki": 16,
    "Marcela": 15,               "Princesa Sugehit": 15,
    "Zeuxis": 15,                "Lluvia": 14,
    "Faby Apache": 16,           "Sarah Stock": 17,
    "Alpha Female": 14,          "Taryn Terrell": 13,
    "Madison Rayne": 14,         "Angel Williams": 15,
    "Talia Madison": 14,         "AJ Lee": 15,
    "Kaitlyn": 13,               "Naomi": 15,
    "Eve Torres": 13,            "Maryse Ouellet": 12,
    "Layla El": 13,              "Alicia Fox": 13,
    # --- great performers who were never in-ring workers ----------------------
    "Kelly Kelly": 8,            "Stacy Keibler": 7,
    "Torrie Wilson": 8,          "Candice Michelle": 9,
    "Maria Kanellis": 9,         "Ashley Massaro": 8,
    "Kristal Marshall": 7,       "Lacey Von Erich": 6,
    "Rosa Mendes": 8,            "Aksana": 8,
    "Brie Bella": 10,            "Nikki Bella": 10,
    "Eva Marie": 5,              "Stephanie McMahon": 7,
    "Sable": 7,                  "Debra": 5,
    "Terri Runnels": 7,          "Sunny": 6,
    "Missy Hyatt": 5,            "Tammy Lynn Sytch": 6,
    "Vickie Guerrero": 5,        "Karen Jarrett": 6,
    "SoCal Val": 5,              "Lauren Jones": 5,
    "Christy Hemme": 9,          "Leyla Milani": 5,
    "Amy Weber": 5,              "Rochelle Loewen": 5,
    "Joy Giovanni": 6,           "Lena Yada": 6,
}


def _cols(con: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def _marker(con: sqlite3.Connection) -> str | None:
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                       "AND name='game_setting'").fetchone():
        return None
    row = con.execute("SELECT value FROM game_setting WHERE key=?", (MARKER,)).fetchone()
    return row[0] if row else None


def _rescale(v: int | None) -> int | None:
    if v is None:
        return None
    return int(max(0, min(A.CAT_MAX, round(v * RESCALE))))


def _hand_wrestling(charisma_25: int, role: str) -> int:
    """Wrestling for someone the harvest has no numbers for at all."""
    v = (HAND_WRESTLING_AT_MEDIAN
         + (charisma_25 - HAND_CHARISMA_MEDIAN) * HAND_WRESTLING_SLOPE)
    if role == "manager":
        v *= MANAGER_WRESTLING_MULT
    return int(max(0, min(A.CAT_MAX, round(v))))


def _derived_wrestling(name, rating, votes, charisma_25, role) -> tuple[int, str]:
    """New Wrestling base, and which signal produced it.

    Curation wins over both formulas. That ordering is the point: a known fact
    about a wrestler should not lose to a proxy, and where we have neither we
    should be able to see which of the two weaker sources answered.
    """
    if name in CURATED_WRESTLING:
        return CURATED_WRESTLING[name], "curated"
    if rating and votes:
        s = A.Source(roles=None, rating=rating, votes=votes, wins=0, losses=0,
                     draws=0, matches=0, promos={}, reigns_pre_reset=0,
                     title_days_pre_reset=0, style=None)
        return A.wrestling(s), "cagematch"
    return _hand_wrestling(charisma_25, role), "hand"


BUDGET_MARKER = "budget_scale_version"
BUDGET_TARGET = "5x20"


def _reproject_budgets(con: sqlite3.Connection) -> str | None:
    """Re-lay the season budget curve to match the new contract prices.

    RETURNS its message rather than printing it. A booting server surfaces the
    startup log as a list on /api/store/status, so a bare print lands in a
    container's stdout — invisible in the one place you would go looking for it.

    The five-category economy costs a brand roughly 20% more to assemble the same
    twenty wrestlers, and Achievements makes every champion you keep dearer every
    year — so game.py raised STARTING_BUDGET and BUDGET_GROWTH. Those constants
    only apply at save creation, though: `brand_budget` is projected 25 seasons
    ahead the day a save is made, so an existing save keeps the old, now too-tight
    numbers forever unless they are redrawn.

    REFUSES ONCE A GAME IS UNDER WAY. Redrawing the cap mid-save could put a brand
    instantly over or under it against contracts already signed against the old
    figures, which is a mess with no clean answer. A save with no contract in it
    has not started, so there is nothing to disturb.
    """
    row = con.execute("SELECT value FROM game_setting WHERE key=?",
                      (BUDGET_MARKER,)).fetchone()
    if row and row[0] == BUDGET_TARGET:
        return None
    signed = con.execute("SELECT COUNT(*) FROM contract").fetchone()[0]
    if signed:
        return (f"budgets left alone — {signed} contracts already signed against "
                "the old cap. Raise them from the League tab if the new prices bite.")

    sys.path.insert(0, str(HERE.parent / "backend"))
    import game  # noqa: PLC0415  — imported here so the harvester does not

    # depend on the backend just to be importable.
    state = con.execute("SELECT season_year FROM game_state WHERE id=1").fetchone()
    if not state:
        return None
    season = state[0]
    brands = [r[0] for r in con.execute("SELECT id FROM brand")]
    con.execute("DELETE FROM brand_budget")
    for bid in brands:
        budget = float(game.STARTING_BUDGET)
        for i in range(game.BUDGET_HORIZON_YEARS):
            con.execute("INSERT INTO brand_budget (brand_id, season_year, budget) "
                        "VALUES (?,?,?)",
                        (bid, season + i, int(round(budget / 10_000) * 10_000)))
            budget *= 1 + game.BUDGET_GROWTH
    con.execute("""INSERT INTO game_setting (key, value) VALUES (?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (BUDGET_MARKER, BUDGET_TARGET))
    con.commit()
    return (f"budgets re-projected: ${game.STARTING_BUDGET:,}/brand growing "
            f"{game.BUDGET_GROWTH:.0%} a year for {game.BUDGET_HORIZON_YEARS} seasons")


def main(dbpath: Path, dry: bool = False, force: bool = False) -> int:
    if not dbpath.exists():
        print(f"no database at {dbpath}")
        return 2

    con = sqlite3.connect(dbpath)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=OFF")

    # Budgets are re-projected under their own marker, so a save that already has
    # the new ratings can still pick up the new cap without --force.
    if not dry:
        budgets = _reproject_budgets(con)
        if budgets:
            print(budgets)

    seen = _marker(con)
    if seen == TARGET and not force:
        print(f"already on the {TARGET} scale — nothing to do.\n"
              "  (rescaling twice would silently multiply every rating by 0.64,\n"
              "   so this refuses rather than risking it. --force overrides.)")
        return 0

    if not _cols(con, "attributes"):
        print("no attributes table — run normalize.py first")
        return 2

    rows, plan = _build_plan(con)

    # ---------------------------------------------------------------- report
    print(f"{len(plan)} wrestlers")
    src = {}
    for p in plan:
        src[p["why"]] = src.get(p["why"], 0) + 1
    print("  Wrestling seeded from:", ", ".join(f"{k} {v}" for k, v in sorted(src.items())))

    def eff(p, key):
        o = p.get("o_" + key)
        return o if o is not None else p[key]

    ranked = sorted(plan, key=lambda p: -(p["wrestling"] + eff(p, "popularity")
                                          + eff(p, "looks") + p["personal"]))
    print("\n  highest day-one overall (Achievements is 0 for everyone):")
    for p in ranked[:12]:
        ov = p["wrestling"] + eff(p, "popularity") + eff(p, "looks") + p["personal"]
        print(f"    {ov:3d}  {p['name'][:26]:26s} "
              f"wrs {p['wrestling']:2d}  ach  0  pop {eff(p,'popularity'):2d}  "
              f"lks {eff(p,'looks'):2d}  per {p['personal']:2d}")
    print("  lowest:")
    for p in ranked[-5:]:
        ov = p["wrestling"] + eff(p, "popularity") + eff(p, "looks") + p["personal"]
        print(f"    {ov:3d}  {p['name'][:26]:26s} "
              f"wrs {p['wrestling']:2d}  ach  0  pop {eff(p,'popularity'):2d}  "
              f"lks {eff(p,'looks'):2d}  per {p['personal']:2d}")

    if dry:
        print("\n--dry: nothing written.")
        con.close()
        return 0

    # ---------------------------------------------------------------- write
    backup = dbpath.with_name(f"{dbpath.stem}.pre-ratings-{int(time.time())}.db")
    shutil.copyfile(dbpath, backup)
    print(f"\nbacked up to {backup.name}")

    summary = _apply(con, rows, plan)
    con.commit()
    print(summary)
    kept = con.execute("SELECT COUNT(*) FROM attribute_override").fetchone()[0]
    print(f"attribute_override preserved: {kept} rows")
    con.close()
    return 0


def _build_plan(con: sqlite3.Connection):
    """Read the old ratings and compute the new ones. Writes nothing."""
    rows = con.execute(
        """SELECT w.id, w.name, w.rating, w.votes,
                  a.charisma, a.popularity, a.looks, a.availability,
                  a.role, a.role_source, a.alignment, a.personality,
                  o.charisma AS o_charisma, o.popularity AS o_popularity,
                  o.looks AS o_looks,
                  (SELECT COALESCE(SUM(matches),0) FROM promotion_year py
                     WHERE py.wrestler_id = w.id) AS matches
             FROM wrestler w
             JOIN attributes a ON a.wrestler_id = w.id
             LEFT JOIN attribute_override o ON o.wrestler_id = w.id
            ORDER BY w.id""").fetchall()

    plan = []
    for r in rows:
        cha_eff = r["o_charisma"] if r["o_charisma"] is not None else r["charisma"]
        pop_eff = r["o_popularity"] if r["o_popularity"] is not None else r["popularity"]

        wrs, why = _derived_wrestling(r["name"], r["rating"], r["votes"],
                                      r["charisma"], r["role"])

        # Derived popularity: reseeded from source where there is source, and
        # otherwise carried over from the old blended pair.
        if r["rating"] and r["votes"]:
            s = A.Source(roles=None, rating=r["rating"], votes=r["votes"], wins=0,
                         losses=0, draws=0, matches=r["matches"] or 0, promos={},
                         reigns_pre_reset=0, title_days_pre_reset=0, style=None)
            pop_new = A.popularity(s)
        else:
            pop_new = _rescale(round(POP_FROM_CHARISMA * r["charisma"]
                                     + POP_FROM_POPULARITY * r["popularity"]))

        # Overrides: only carry one across if the GM had actually set one, so
        # that an untouched wrestler still tracks the formula.
        o_pop = None
        if r["o_charisma"] is not None or r["o_popularity"] is not None:
            o_pop = _rescale(round(POP_FROM_CHARISMA * cha_eff
                                   + POP_FROM_POPULARITY * pop_eff))

        plan.append({
            "id": r["id"], "name": r["name"], "why": why,
            "wrestling": wrs,
            "popularity": pop_new,
            "looks": _rescale(r["looks"]),
            "personal": A.PERSONAL_DEFAULT,
            "o_popularity": o_pop,
            "o_looks": _rescale(r["o_looks"]),
            "old": (r["charisma"], r["popularity"], r["looks"]),
        })

    return rows, plan


def _apply(con: sqlite3.Connection, rows, plan) -> str:
    """Do the writes. Caller commits, so a failure leaves nothing half-done."""
    # attributes must be REWRITTEN: charisma is NOT NULL with no default and
    # SQLite cannot drop that in place.
    con.executescript("""
        CREATE TABLE attributes_new (
            wrestler_id   INTEGER PRIMARY KEY REFERENCES wrestler(id),
            wrestling     INTEGER NOT NULL,
            popularity    INTEGER NOT NULL,
            looks         INTEGER NOT NULL,
            personal      INTEGER NOT NULL DEFAULT 10,
            availability  TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT 'wrestler',
            role_source   TEXT,
            alignment     TEXT NOT NULL DEFAULT 'face',
            personality   TEXT NOT NULL DEFAULT 'ambitious',
            formula_ver   INTEGER NOT NULL
        );
    """)
    by_id = {p["id"]: p for p in plan}
    for r in rows:
        p = by_id[r["id"]]
        con.execute(
            """INSERT INTO attributes_new (wrestler_id, wrestling, popularity, looks,
                 personal, availability, role, role_source, alignment, personality,
                 formula_ver) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (r["id"], p["wrestling"], p["popularity"], p["looks"], p["personal"],
             r["availability"], r["role"], r["role_source"], r["alignment"],
             r["personality"], A.FORMULA_VERSION))
    con.executescript("DROP TABLE attributes; "
                      "ALTER TABLE attributes_new RENAME TO attributes;")

    # attribute_override only needs columns adding — they are all nullable.
    ocols = _cols(con, "attribute_override")
    for col in ("wrestling", "personal"):
        if col not in ocols:
            con.execute(f"ALTER TABLE attribute_override ADD COLUMN {col} INTEGER")
    for p in plan:
        con.execute(
            """UPDATE attribute_override SET popularity=?, looks=? WHERE wrestler_id=?""",
            (p["o_popularity"], p["o_looks"], p["id"]))

    # The season-end engine used to suggest changes to charisma. That category no
    # longer exists, so pending suggestions against it can never be applied —
    # they are dropped rather than left to fail silently on approval.
    dropped = 0
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                   "AND name='rating_change'").fetchone():
        dropped = con.execute("DELETE FROM rating_change WHERE category='charisma' "
                              "AND status='pending'").rowcount

    con.execute("""INSERT INTO game_setting (key, value) VALUES (?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (MARKER, TARGET))

    msg = f"migrated {len(plan)} wrestlers to the {TARGET} scale"
    if dropped:
        msg += f", dropped {dropped} pending charisma suggestions (category retired)"
    return msg


def ensure_migrated(con: sqlite3.Connection) -> str | None:
    """Bring an already-open save forward. Returns None if nothing was needed.

    This is the path a BOOTING SERVER takes, and it exists because on a
    stateless host the database the app runs on is whatever was in Blob storage,
    not whatever shipped in the deployment. A save uploaded before this change
    has no `attributes.wrestling` column, and the first roster request would die
    on it — so the check has to happen at boot rather than being something a
    human remembers to run.

    No backup file: the durable copy in the store is still the pre-migration
    save until the next write pushes this one up, and writing a backup into a
    container's /tmp would be a backup that dies with the container. Nothing is
    printed either — the caller owns the startup log.
    """
    # Sets its own row factory rather than trusting the caller's. The plan reads
    # columns by NAME, so a plain tuple connection fails deep inside with
    # "tuple indices must be integers" — a long way from the actual mistake.
    # Restored afterwards, so a caller that wanted tuples still gets them.
    prior_factory = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        return _ensure_migrated(con)
    finally:
        con.row_factory = prior_factory


def _ensure_migrated(con: sqlite3.Connection) -> str | None:
    notes = [n for n in (_reproject_budgets(con),) if n]
    if _marker(con) == TARGET:
        return "; ".join(notes) or None
    if not _cols(con, "attributes"):
        return "; ".join(notes) or None
    if "charisma" not in _cols(con, "attributes"):
        # Newer than the marker suggests — the columns are already right, so the
        # save was migrated by a build that predates the marker. Stamp it and
        # stop, rather than rewriting a table that is already correct.
        con.execute("""INSERT INTO game_setting (key, value) VALUES (?,?)
                       ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                    (MARKER, TARGET))
        con.commit()
        return "; ".join(notes) or None
    rows, plan = _build_plan(con)
    notes.append(_apply(con, rows, plan))
    con.commit()
    return "; ".join(notes)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    sys.exit(main(Path(args[0] if args else "../data/gm2000.db"),
                  dry="--dry" in flags, force="--force" in flags))
