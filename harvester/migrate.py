"""Schema migrations.

    python migrate.py ../data/gm2000.db

`CREATE TABLE IF NOT EXISTS` never alters an existing table, so new columns need
adding explicitly. Derived tables can simply be dropped and rebuilt; tables
holding YOUR data (attribute_override, excluded_wrestler, contracts, sim
history) must be altered in place.

Safe to run repeatedly.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).parent


def columns(con: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    except sqlite3.OperationalError:
        return set()


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def main(dbpath: Path) -> None:
    con = sqlite3.connect(dbpath)
    con.execute("PRAGMA foreign_keys = OFF")
    done: list[str] = []

    # --- derived tables: safe to rebuild from the harvest -------------------
    if table_exists(con, "attributes") and "role" not in columns(con, "attributes"):
        con.execute("DROP TABLE attributes")
        done.append("attributes rebuilt (added role, role_source)")

    # --- wrestler_image: reshaped from one-per-year to a gallery ------------
    # The old rows point at files stored as "<year>.jpg" which no longer exist,
    # so there is nothing worth migrating — re-sync from Drive afterwards.
    if table_exists(con, "wrestler_image") and "is_profile" not in columns(con, "wrestler_image"):
        n = con.execute("SELECT COUNT(*) FROM wrestler_image").fetchone()[0]
        con.execute("DROP INDEX IF EXISTS idx_img_wrestler")
        con.execute("DROP TABLE wrestler_image")
        done.append(f"wrestler_image rebuilt as a gallery ({n} stale rows dropped)")

    # --- user data: ALTER, never drop --------------------------------------
    if table_exists(con, "attribute_override") and "role" not in columns(con, "attribute_override"):
        con.execute("ALTER TABLE attribute_override ADD COLUMN role TEXT")
        done.append("attribute_override gained a role column (edits preserved)")

    if table_exists(con, "game_title"):
        for col, ddl in [
            ("short_name", "TEXT"),
            ("tier", "TEXT NOT NULL DEFAULT 'world'"),
            ("team_size", "INTEGER NOT NULL DEFAULT 1"),
            ("max_weight_kg", "INTEGER"),
            ("hardcore", "INTEGER NOT NULL DEFAULT 0"),
            ("active", "INTEGER NOT NULL DEFAULT 1"),
        ]:
            if col not in columns(con, "game_title"):
                con.execute(f"ALTER TABLE game_title ADD COLUMN {col} {ddl}")
                done.append(f"game_title.{col} added")

    # draft gained a kind (wrestler/manager) and a UNIQUE that now includes it.
    if table_exists(con, "draft") and "draft_kind" not in columns(con, "draft"):
        con.execute("DROP TABLE IF EXISTS draft_pick")
        con.execute("DROP TABLE draft")
        done.append("draft rebuilt (added draft_kind, traded-pick ownership)")
    elif table_exists(con, "draft_pick") and "original_brand" not in columns(con, "draft_pick"):
        con.execute("ALTER TABLE draft_pick ADD COLUMN original_brand TEXT")
        done.append("draft_pick.original_brand added")

    if table_exists(con, "contract") and "origin" not in columns(con, "contract"):
        con.execute("ALTER TABLE contract ADD COLUMN origin TEXT NOT NULL DEFAULT 'draft'")
        con.execute("ALTER TABLE contract ADD COLUMN extended_from INTEGER")
        done.append("contract gained origin/extended_from")

    if table_exists(con, "contract") and "perks" not in columns(con, "contract"):
        con.execute("ALTER TABLE contract ADD COLUMN perks TEXT")
        con.execute("ALTER TABLE contract ADD COLUMN signing_bonus INTEGER NOT NULL DEFAULT 0")
        done.append("contract gained perks/signing_bonus (negotiation)")

    # --- batch 3: alignment, personality, draft class, PPVs, career tracking --
    for col, ddl in [("alignment", "TEXT NOT NULL DEFAULT 'face'"),
                     ("personality", "TEXT NOT NULL DEFAULT 'mercenary'")]:
        if table_exists(con, "attributes") and col not in columns(con, "attributes"):
            con.execute(f"ALTER TABLE attributes ADD COLUMN {col} {ddl}")
            done.append(f"attributes.{col} added")
    for col in ("alignment", "personality"):
        if table_exists(con, "attribute_override") and col not in columns(con, "attribute_override"):
            con.execute(f"ALTER TABLE attribute_override ADD COLUMN {col} TEXT")
            done.append(f"attribute_override.{col} added")
    if table_exists(con, "attribute_override") and "draft_class" not in columns(con, "attribute_override"):
        con.execute("ALTER TABLE attribute_override ADD COLUMN draft_class INTEGER")
        done.append("attribute_override.draft_class added")
    for col, ddl in [("career_earnings", "INTEGER NOT NULL DEFAULT 0"),
                     ("ppv_appearances", "INTEGER NOT NULL DEFAULT 0")]:
        if table_exists(con, "wrestler_state") and col not in columns(con, "wrestler_state"):
            con.execute(f"ALTER TABLE wrestler_state ADD COLUMN {col} {ddl}")
            done.append(f"wrestler_state.{col} added")
    if table_exists(con, "contract") and "role" not in columns(con, "contract"):
        con.execute("ALTER TABLE contract ADD COLUMN role TEXT NOT NULL DEFAULT 'wrestler'")
        done.append("contract.role added")
    if table_exists(con, "show") and "is_ppv" not in columns(con, "show"):
        con.execute("ALTER TABLE show ADD COLUMN is_ppv INTEGER NOT NULL DEFAULT 0")
        con.execute("ALTER TABLE show ADD COLUMN ppv_name TEXT")
        done.append("show gained is_ppv/ppv_name")

    con.commit()

    # apply the current schema for anything genuinely new
    con.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
    con.commit()

    preserved = {
        t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("attribute_override", "excluded_wrestler", "contract", "sim_match")
        if table_exists(con, t)
    }

    print("migrations applied:" if done else "nothing to migrate")
    for d in done:
        print(f"  {d}")
    print("\nuser data preserved:")
    for t, n in preserved.items():
        print(f"  {t}: {n} rows")
    con.close()


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "../data/gm2000.db"))
