"""Add manager stats and the yearly card table.

    python migrate_cards.py ../data/gm2000.db

MANAGER STATS. A manager was being scored on Wrestling and Popularity, which is
the wrong pair of questions to ask about someone whose job is talking and getting
her client over. She now has her own two:

    MIC  mic work — the thing she is actually hired for
    INF  influence — how much she elevates whoever she stands beside

Achievements, Looks and Personal carry over unchanged, so a manager card is still
five categories out of twenty. This is exactly what FIFA does with goalkeepers:
same scale, same card, a completely different set of names for the two stats that
describe the job. `manager_price` already ignored Wrestling, so the money side of
the game has quietly agreed with this all along.

Both are plain nullable ALTERs — no table rewrite — and seeded from the value
that already carried her promo ability. Popularity absorbed the old Charisma
category, so it is the closest thing to a mic rating the save has.

CARD TABLE. One row per wrestler per season: the five categories as they stood,
the overall, her role, style, brand and whether that year earned a special. It is
a SNAPSHOT on purpose — the point of a 2003 card is that it says what she was in
2003, so it must not move when her ratings change afterwards.

Safe to run repeatedly.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import attributes as A  # noqa: E402

CARD_SCHEMA = """
-- A wrestler's ratings frozen at the end of one season.
--
-- Denormalised on purpose. Every column here could be derived from the save
-- TODAY, but not as it was THEN: her ratings move, she changes brand, she stops
-- being a manager. A card that recomputed itself would stop being a record of
-- 2003 and become another view of the present, which is the one thing it must
-- not be.
CREATE TABLE IF NOT EXISTS rating_card (
    wrestler_id   INTEGER NOT NULL REFERENCES wrestler(id),
    season_year   INTEGER NOT NULL,
    role          TEXT NOT NULL,            -- wrestler | manager | both
    -- The two role-dependent stats, already resolved: Wrestling/Popularity for
    -- a wrestler, Mic/Influence for a manager. Stored resolved so a card never
    -- has to know which set of labels applied back then.
    stat_a        INTEGER NOT NULL,
    stat_b        INTEGER NOT NULL,
    achievements  INTEGER NOT NULL,
    looks         INTEGER NOT NULL,
    personal      INTEGER NOT NULL,
    overall       INTEGER NOT NULL,
    style         TEXT,
    brand_id      TEXT,
    tier          TEXT NOT NULL,            -- bronze | silver | gold | elite
    special       TEXT,                     -- what earned it, NULL for a plain card
    record        TEXT,                     -- "24-6-1" that season
    created_on    TEXT NOT NULL,
    PRIMARY KEY (wrestler_id, season_year)
);
CREATE INDEX IF NOT EXISTS idx_card_season ON rating_card(season_year, overall DESC);
"""


def _cols(con: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def ensure_schema(con: sqlite3.Connection) -> str | None:
    """Add the manager columns and the card table to an already-open save.

    THIS IS THE PATH A BOOTING SERVER TAKES, and it exists because the first
    version did not have one. The deployed app runs on whatever database came
    down from Blob storage, and this migration only ever ran as a script on a
    laptop — so production got code that selected `a.mic` against a table with
    no such column, and the roster endpoint returned 500 for every request. The
    ratings migration had already taught this lesson once; the card migration
    shipped without it anyway.

    MUST RUN AFTER migrate_ratings.ensure_migrated(). That one REWRITES the
    attributes table to drop the retired charisma column, and its replacement
    DDL knows nothing about mic/influence — so adding these first would simply
    lose them again on an old save.

    Returns a one-line summary, or None if there was nothing to do.
    """
    done: list[str] = []
    for table, ddl in (("attributes", "INTEGER NOT NULL DEFAULT 10"),
                       ("attribute_override", "INTEGER")):
        have = _cols(con, table)
        if not have:
            continue
        for col in ("mic", "influence"):
            if col not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
                done.append(f"{table}.{col}")

    # Seed a manager's mic/influence from the value that already carried her
    # promo ability. Only rows still on the default are touched, so this cannot
    # flatten a hand edit on a later boot.
    if done:
        n = con.execute("""UPDATE attributes SET mic = popularity, influence = popularity
                            WHERE mic = 10 AND influence = 10""").rowcount
        if n:
            done.append(f"seeded {n} from popularity")

    had_cards = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rating_card'"
    ).fetchone()
    con.executescript(CARD_SCHEMA)
    if not had_cards:
        done.append("rating_card created")

    if not done:
        return None
    con.commit()
    return "card schema: " + ", ".join(done)


def main(dbpath: Path) -> int:
    if not dbpath.exists():
        print(f"no database at {dbpath}")
        return 2
    con = sqlite3.connect(dbpath)
    con.row_factory = sqlite3.Row
    done: list[str] = []

    # Exactly what a booting server does — one implementation, so the CLI and
    # production cannot drift apart.
    summary = ensure_schema(con)
    if summary:
        done.append(summary)
    print("migrations applied:" if done else "nothing to migrate")
    for d in done:
        print(f"  {d}")
    print(f"\nformula version {A.FORMULA_VERSION}; "
          f"cards on file: {con.execute('SELECT COUNT(*) FROM rating_card').fetchone()[0]}")
    con.close()
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(main(Path(args[0] if args else "../data/gm2000.db")))
