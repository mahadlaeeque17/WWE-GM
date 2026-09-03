"""Phase 4 — the GM layer: brands, budgets, contracts, free agency, trades.

Budgets work like an NBA salary cap: each brand gets a pot for the season that
grows a fixed percentage each year. Contract values are driven by the four
rating categories and by age, so a 24-year-old and a 41-year-old with identical
ratings do not cost the same.

Everything here reads EFFECTIVE attributes (override falling back to derived),
so a hand-edited rating immediately changes what a wrestler costs.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harvester"))
import attributes as A  # noqa: E402

RESET_YEAR = 2000

BRANDS = [
    ("RAW", "Raw", "#b32036"),
    ("SMACKDOWN", "SmackDown", "#2b6cb0"),
]

# Season budget per brand, and how fast it grows. The NBA cap was ~$34M in 2000
# and grew roughly 5-10% a year; this is the same shape scaled to a roster of
# ~20 women whose contracts top out near $1.2M.
#
# Both numbers were lifted when Achievements arrived. The steeper contract curve
# costs a brand about 20% more to assemble the same twenty wrestlers, and — the
# part that compounds — Achievements only ever goes UP, so every champion you
# keep gets more expensive every year you keep her. 6% growth was set against a
# roster whose ratings were frozen; against one that climbs it slowly strangles
# you, and "I cannot re-sign anybody" is a worse game than "I must choose".
STARTING_BUDGET = 12_000_000
BUDGET_GROWTH = 0.07

# How far ahead budgets are projected when a save is created.
BUDGET_HORIZON_YEARS = 25

MAX_CONTRACT_YEARS = 5
MIN_CONTRACT_YEARS = 1


# ---------------------------------------------------------------- helpers

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- extra schema
#
# Feuds, a news log, an approvals queue for the AI opponent, and year-end award
# nominations all live in tables added after the original schema. They are pure
# NEW tables (no ALTERs), so CREATE TABLE IF NOT EXISTS is enough — call
# ensure_schema() at startup and on new_game.
EXTRA_SCHEMA = """
CREATE TABLE IF NOT EXISTS game_setting (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS feud (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    a_id       INTEGER NOT NULL REFERENCES wrestler(id),
    b_id       INTEGER NOT NULL REFERENCES wrestler(id),
    brand_id   TEXT,
    heat       INTEGER NOT NULL DEFAULT 25,
    status     TEXT NOT NULL DEFAULT 'active',   -- active | settled
    note       TEXT,
    started_on TEXT,
    settled_on TEXT
);
CREATE TABLE IF NOT EXISTS event_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    on_date     TEXT NOT NULL,
    season_year INTEGER,
    kind        TEXT NOT NULL,
    brand_id    TEXT,
    icon        TEXT,
    text        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS proposal (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,                    -- draft_pick | show | trade
    brand_id   TEXT,
    summary    TEXT NOT NULL,
    payload    TEXT NOT NULL,                    -- JSON
    status     TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    created_on TEXT
);
CREATE TABLE IF NOT EXISTS award_nomination (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    season_year INTEGER NOT NULL,
    kind        TEXT NOT NULL,
    wrestler_id INTEGER,
    detail      TEXT,
    score       REAL,
    status      TEXT NOT NULL DEFAULT 'nominated' -- nominated | won
);
CREATE TABLE IF NOT EXISTS wrestler_bio (
    wrestler_id INTEGER PRIMARY KEY REFERENCES wrestler(id),
    nickname    TEXT,
    bio         TEXT,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS sim_promo (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    show_id  INTEGER NOT NULL REFERENCES show(id),
    slot     INTEGER NOT NULL,
    kind     TEXT NOT NULL,
    quality  REAL,
    feud_id  INTEGER REFERENCES feud(id),
    topic    TEXT,
    note     TEXT
);
CREATE TABLE IF NOT EXISTS sim_promo_participant (
    promo_id    INTEGER NOT NULL REFERENCES sim_promo(id),
    wrestler_id INTEGER NOT NULL REFERENCES wrestler(id),
    seat        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (promo_id, wrestler_id)
);
CREATE INDEX IF NOT EXISTS idx_event_date ON event_log(on_date DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_feud_status ON feud(status);
CREATE INDEX IF NOT EXISTS idx_promo_show ON sim_promo(show_id, slot);
CREATE INDEX IF NOT EXISTS idx_promo_part ON sim_promo_participant(wrestler_id);
"""


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(EXTRA_SCHEMA)
    # Guarded ALTERs — CREATE TABLE IF NOT EXISTS never adds columns, so newer
    # per-row fields (match stipulation, show city/cost) are added here.
    def _cols(t):
        return {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
    mcols = _cols("sim_match")
    if "stipulation" not in mcols:
        con.execute("ALTER TABLE sim_match ADD COLUMN stipulation TEXT")
    # The STRUCTURE of the match (singles, tag, triple threat, fatal 4-way …),
    # separate from the stipulation which is the rules. NULL on rows written
    # before match types existed; readers infer the shape from the sides.
    if "match_type" not in mcols:
        con.execute("ALTER TABLE sim_match ADD COLUMN match_type TEXT")
    scols = _cols("show")
    if "city" not in scols:
        con.execute("ALTER TABLE show ADD COLUMN city TEXT")
    if "cost" not in scols:
        con.execute("ALTER TABLE show ADD COLUMN cost INTEGER")
    con.commit()


def get_setting(con: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = con.execute("SELECT value FROM game_setting WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(con: sqlite3.Connection, key: str, value: str | None) -> None:
    if value is None:
        con.execute("DELETE FROM game_setting WHERE key=?", (key,))
    else:
        con.execute("INSERT INTO game_setting (key, value) VALUES (?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    con.commit()


# ---------------------------------------------------------------- news log

def log_event(con: sqlite3.Connection, kind: str, text: str,
              brand_id: str | None = None, icon: str | None = None) -> None:
    """Record a headline for the news feed. Best-effort — never raises."""
    try:
        st = con.execute("SELECT season_year, game_state.current_date FROM game_state WHERE id=1").fetchone()
        on_date = st["current_date"] if st else now_iso()[:10]
        season = st["season_year"] if st else None
        con.execute(
            "INSERT INTO event_log (on_date, season_year, kind, brand_id, icon, text) "
            "VALUES (?,?,?,?,?,?)", (on_date, season, kind, brand_id, icon, text))
    except Exception:
        pass


def news(con: sqlite3.Connection, limit: int = 40) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT * FROM event_log ORDER BY id DESC LIMIT ?", (limit,))]


# ---------------------------------------------------------------- bios

def set_bio(con: sqlite3.Connection, wrestler_id: int,
            nickname: str | None, bio: str | None) -> dict:
    con.execute(
        """INSERT INTO wrestler_bio (wrestler_id, nickname, bio, updated_at)
           VALUES (?,?,?,?)
           ON CONFLICT(wrestler_id) DO UPDATE SET
             nickname=excluded.nickname, bio=excluded.bio, updated_at=excluded.updated_at""",
        (wrestler_id, (nickname or "").strip() or None, (bio or "").strip() or None, now_iso()))
    con.commit()
    return {"wrestler_id": wrestler_id, "nickname": nickname, "bio": bio}


def bios(con: sqlite3.Connection) -> dict[int, dict]:
    return {r["wrestler_id"]: {"nickname": r["nickname"], "bio": r["bio"]}
            for r in con.execute("SELECT wrestler_id, nickname, bio FROM wrestler_bio")}


# ------------------------------------------------------------- achievements
#
# Achievements is the one rating with no stored value anywhere. It is a fact
# about the save — what she has actually won on the shows you booked — so it is
# read from the record every time and never cached. A stored copy would go stale
# the instant a belt changed hands and then sit on the roster page contradicting
# the trophy cabinet directly below it.

def achievement_inputs(con: sqlite3.Connection) -> dict[int, dict]:
    """Every wrestler's in-save honours, in ONE pass over the tables.

    Bulk rather than per-wrestler because the roster endpoint needs all 270 at
    once, and three subqueries × 270 rows is a page load you can feel. The
    per-wrestler path reads out of the same dict.
    """
    reigns: dict[int, dict[str, int]] = {}
    days: dict[int, int] = {}
    for r in con.execute(
            """SELECT r.wrestler_id AS wid, t.tier AS tier,
                      COUNT(*) AS n,
                      COALESCE(SUM(
                        -- game_state.current_date must stay table-qualified: a
                        -- bare `current_date` is a SQLite keyword and returns
                        -- TODAY, which would credit an ongoing reign with every
                        -- day since the year 2000.
                        CASE WHEN r.lost_on IS NULL
                             THEN julianday(COALESCE((SELECT game_state.current_date
                                                        FROM game_state WHERE id=1),
                                                     r.won_on)) - julianday(r.won_on)
                             ELSE julianday(r.lost_on) - julianday(r.won_on) END), 0) AS d
                 FROM game_title_reign r
                 JOIN game_title t ON t.id = r.title_id
                GROUP BY r.wrestler_id, t.tier"""):
        reigns.setdefault(r["wid"], {})[r["tier"]] = r["n"]
        days[r["wid"]] = days.get(r["wid"], 0) + int(max(0, r["d"] or 0))

    accolades: dict[int, dict[str, int]] = {}
    for r in con.execute("""SELECT wrestler_id AS wid, kind, COUNT(*) AS n
                              FROM accomplishment GROUP BY wrestler_id, kind"""):
        accolades.setdefault(r["wid"], {})[r["kind"]] = r["n"]

    out: dict[int, dict] = {}
    for wid in set(reigns) | set(accolades):
        out[wid] = {"reigns": reigns.get(wid, {}),
                    "title_days": days.get(wid, 0),
                    "accolades": accolades.get(wid, {})}
    return out


_EMPTY_ACHIEVEMENTS = {"reigns": {}, "title_days": 0, "accolades": {}}


def achievement_score(inputs: dict | None) -> int:
    i = inputs or _EMPTY_ACHIEVEMENTS
    return A.achievements(i["reigns"], i["title_days"], i["accolades"])


def achievement_reasons(inputs: dict | None) -> list[str]:
    i = inputs or _EMPTY_ACHIEVEMENTS
    return A.achievement_breakdown(i["reigns"], i["title_days"], i["accolades"])


def effective_attributes(con: sqlite3.Connection, wrestler_id: int,
                         ach_inputs: dict | None = None) -> dict:
    """The five ratings for one wrestler. Override wins, derived is the fallback.

    Two of the five are not simply read:

      wrestling      the stored base PLUS a live swing from her save win/loss
                     record, so form shows up without a booked squash run being
                     mistaken for ability.
      achievements   computed from the save's title reigns and accolades. Zero
                     until she wins something.

    `ach_inputs` lets a caller that already ran `achievement_inputs()` pass the
    row in rather than re-querying — that is the difference between one query and
    two per wrestler in the sim's inner loops.
    """
    row = con.execute(
        """
        SELECT
          COALESCE(o.wrestling,  a.wrestling)  AS wrestling_base,
          COALESCE(o.popularity, a.popularity) AS popularity,
          COALESCE(o.looks,      a.looks)      AS looks,
          COALESCE(o.personal,   a.personal)   AS personal,
          -- A manager is scored on these two instead of Wrestling/Popularity.
          -- Always fetched, because a `both` wrestler can be looked at either
          -- way and one query is cheaper than knowing in advance which.
          COALESCE(o.mic,        a.mic)        AS mic,
          COALESCE(o.influence,  a.influence)  AS influence,
          COALESCE(o.age_at_reset, w.age_at_reset) AS age,
          COALESCE(o.alignment,  a.alignment)  AS alignment,
          COALESCE(o.personality, a.personality) AS personality,
          COALESCE(o.role,       a.role)       AS role,
          COALESCE(s.sim_matches, 0)           AS sim_matches,
          COALESCE(s.sim_wins, 0)              AS sim_wins
        FROM wrestler w
        JOIN attributes a         ON a.wrestler_id = w.id
        LEFT JOIN attribute_override o ON o.wrestler_id = w.id
        LEFT JOIN wrestler_state s     ON s.wrestler_id = w.id
        WHERE w.id = ?
        """,
        (wrestler_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"no such wrestler: {wrestler_id}")

    d = dict(row)
    if ach_inputs is None:
        ach_inputs = achievement_inputs(con).get(wrestler_id)
    return with_derived(d, ach_inputs)


def with_derived(d: dict, ach_inputs: dict | None) -> dict:
    """Finish a half-built attribute row: the two live categories, then totals.

    Split out of effective_attributes so the bulk roster query can share exactly
    this arithmetic instead of reimplementing it — the old duplicate in main.py
    was the reason a rating could read one way on the roster page and another on
    the wrestler panel.

    ROLE-AWARE, and it has to be. A manager is scored on Mic and Influence where a
    wrestler gets Wrestling and Popularity, so totalling the wrestler five for
    everyone gave a manager one overall on the roster and a different one on her
    own card. Same bug the duplicate arithmetic used to cause, one layer up.
    """
    d["wrestling"] = A.wrestling_live(d["wrestling_base"], d["sim_wins"], d["sim_matches"])
    d["record_swing"] = round(A.record_swing(d["sim_wins"], d["sim_matches"]), 1)
    d["achievements"] = achievement_score(ach_inputs)
    d["achievement_reasons"] = achievement_reasons(ach_inputs)

    a_key, b_key = A.performance_pair(d.get("role") or "wrestler")
    d["overall"] = A.overall(d[a_key], d["achievements"], d[b_key],
                             d["looks"], d["personal"])
    d["value"] = A.contract_value(d[a_key], d["achievements"], d[b_key],
                                  d["looks"], d["personal"], d["age"])
    # Which two the overall was actually built from, so the UI can label a card
    # or a chart without re-deriving the role rule.
    d["performance_pair"] = [a_key, b_key]
    return d


def asking_price(con: sqlite3.Connection, wrestler_id: int) -> int:
    return effective_attributes(con, wrestler_id)["value"]


# ---------------------------------------------------------------- titles

# Two per brand, three shared. Names are era-appropriate: WWF ran Intercontinental
# and European belts in 2000, WCW ran United States, Television and Cruiserweight,
# and "Queen of Extreme" was ECW's own phrase for Francine.
#
# (name, short, brand, tier, prestige, team_size, max_weight_kg, hardcore)
TITLES = [
    ("Raw Women's World Championship",       "RAW WORLD", "RAW",       "world",     85, 1, None, 0),
    ("Raw Women's Intercontinental Championship", "RAW IC", "RAW",     "secondary", 60, 1, None, 0),
    ("SmackDown Women's World Championship", "SD WORLD",  "SMACKDOWN", "world",     85, 1, None, 0),
    ("SmackDown Women's United States Championship", "SD US", "SMACKDOWN", "secondary", 60, 1, None, 0),
    # Shared — brand_id NULL. Anyone on either roster can challenge.
    ("World Women's Tag Team Championship",  "TAG",       None,        "tag",         70, 2, None, 0),
    ("Women's Cruiserweight Championship",   "CRUISER",   None,        "cruiserweight", 55, 1, 62, 0),
    ("Queen of Extreme Championship",        "EXTREME",   None,        "hardcore",    50, 1, None, 1),
    # Held by a MANAGER, not a wrestler. Two wrestlers fight on behalf of their
    # managers; the winner's manager holds the belt. Shared across both brands.
    ("Women's Manager's Championship",       "MANAGER",   None,        "manager",     55, 1, None, 0),
]

# Cruiserweight limit. 62kg puts ~31 of the roster in the division — enough for
# it to sustain its own feuds without being so open it stops meaning anything.
CRUISERWEIGHT_LIMIT_KG = 62


def seed_titles(con: sqlite3.Connection) -> int:
    for name, short, brand, tier, prestige, team, weight, hardcore in TITLES:
        con.execute(
            """INSERT INTO game_title
               (name, short_name, brand_id, tier, prestige, team_size, max_weight_kg, hardcore)
               VALUES (?,?,?,?,?,?,?,?)""",
            (name, short, brand, tier, prestige, team, weight, hardcore),
        )
    return len(TITLES)


def ensure_titles(con: sqlite3.Connection) -> int:
    """Add any belt in TITLES that a live save is missing — so an existing save
    picks up newly introduced championships (e.g. the Manager's Championship)
    without a restart. Matched by name, so it never duplicates."""
    if not con.execute("SELECT 1 FROM game_state WHERE id=1").fetchone():
        return 0
    added = 0
    for name, short, brand, tier, prestige, team, weight, hardcore in TITLES:
        if not con.execute("SELECT 1 FROM game_title WHERE name=?", (name,)).fetchone():
            con.execute(
                """INSERT INTO game_title
                   (name, short_name, brand_id, tier, prestige, team_size, max_weight_kg, hardcore)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (name, short, brand, tier, prestige, team, weight, hardcore))
            added += 1
    if added:
        con.commit()
    return added


def _age_on(birthday: str | None, birth_year: int | None, iso_date: str) -> int | None:
    """Age on a yyyy-mm-dd date, from a cagematch birthday (dd.mm.yyyy) or a bare
    birth year. None when the date of birth is unknown."""
    import re
    if not iso_date:
        return None
    y, m, d = int(iso_date[:4]), int(iso_date[5:7]), int(iso_date[8:10])
    if birthday:
        mm = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", birthday.strip())
        if mm:
            bd, bm, by = int(mm.group(1)), int(mm.group(2)), int(mm.group(3))
            age = y - by - ((m, d) < (bm, bd))
            return age if 0 <= age <= 100 else None
    if birth_year:
        age = y - birth_year
        return age if 0 <= age <= 100 else None
    return None


def _days_between(a: str, b: str) -> int:
    return max(0, (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days)


def title_lineage(con: sqlite3.Connection, title_id: int) -> dict:
    """Full championship history and records for one belt."""
    t = con.execute("SELECT * FROM game_title WHERE id=?", (title_id,)).fetchone()
    if not t:
        raise SigningError("no such title")
    # NB: `current_date` is a SQLite keyword — a bare SELECT of it returns TODAY,
    # not the column. Table-qualify (or SELECT *) to read the stored game date.
    st = con.execute("SELECT game_state.current_date FROM game_state WHERE id=1").fetchone()
    today = st["current_date"] if st else now_iso()[:10]

    rows = con.execute(
        """SELECT r.id, r.wrestler_id, r.won_on, r.lost_on,
                  COALESCE(o.display_name, w.name) name,
                  w.birthday, w.birth_year,
                  (SELECT id FROM wrestler_image i WHERE i.wrestler_id=r.wrestler_id
                     AND i.is_profile=1 LIMIT 1) profile_image_id
           FROM game_title_reign r
           JOIN wrestler w ON w.id = r.wrestler_id
           LEFT JOIN attribute_override o ON o.wrestler_id = r.wrestler_id
           WHERE r.title_id=? ORDER BY r.won_on, r.id""", (title_id,)).fetchall()

    reigns, per_wrestler = [], {}
    for i, r in enumerate(rows, start=1):
        end = r["lost_on"] or today
        days = _days_between(r["won_on"], end)
        age = _age_on(r["birthday"], r["birth_year"], r["won_on"])
        per_wrestler[r["wrestler_id"]] = per_wrestler.get(r["wrestler_id"], 0) + 1
        reigns.append({
            "reign_no": i, "wrestler_id": r["wrestler_id"], "name": r["name"],
            "profile_image_id": r["profile_image_id"],
            "won_on": r["won_on"], "lost_on": r["lost_on"],
            "days": days, "ongoing": r["lost_on"] is None, "age_at_win": age,
        })

    def _record(key, pick):
        cands = [x for x in reigns if x[key] is not None]
        return pick(cands, key=lambda x: x[key]) if cands else None

    current = [x for x in reigns if x["ongoing"]]
    stats = {
        "total_reigns": len(reigns),
        "distinct_champions": len(per_wrestler),
        "first_champion": reigns[0] if reigns else None,
        "current_champions": current,
        "longest_reign": _record("days", max),
        "shortest_reign": (min([x for x in reigns if not x["ongoing"]],
                               key=lambda x: x["days"]) if any(not x["ongoing"] for x in reigns) else None),
        "oldest_at_win": _record("age_at_win", max),
        "youngest_at_win": _record("age_at_win", min),
        "most_reigns": (max(
            ({"wrestler_id": wid, "name": next(x["name"] for x in reigns if x["wrestler_id"] == wid),
              "reigns": n} for wid, n in per_wrestler.items()),
            key=lambda x: x["reigns"]) if per_wrestler else None),
    }
    return {"title": dict(t), "reigns": reigns, "stats": stats, "as_of": today}


def title_eligible(con: sqlite3.Connection, title_id: int, wrestler_id: int) -> tuple[bool, str]:
    """Can she challenge for this belt? Weight limits and brand exclusivity."""
    t = con.execute("SELECT * FROM game_title WHERE id=?", (title_id,)).fetchone()
    if not t:
        return False, "no such title"

    if t["max_weight_kg"]:
        w = con.execute("SELECT weight_kg, name FROM wrestler WHERE id=?", (wrestler_id,)).fetchone()
        # An unknown weight is not a disqualification — cagematch simply has no
        # figure for ~5% of the roster and that is not their fault.
        if w["weight_kg"] and w["weight_kg"] > t["max_weight_kg"]:
            return False, f"{w['name']} is {w['weight_kg']}kg, over the {t['max_weight_kg']}kg limit"

    if t["brand_id"]:
        state = con.execute("SELECT season_year FROM game_state WHERE id=1").fetchone()
        c = active_contract(con, wrestler_id, state["season_year"]) if state else None
        if c and c["brand_id"] != t["brand_id"]:
            return False, f"{t['name']} is exclusive to {t['brand_id']}"
    return True, ""


# ---------------------------------------------------------------- accolades

# Sim-awarded ones are handed out by the engine; manual ones you record yourself.
ACCOLADES = {
    # sim-awarded
    "royal_rumble": ("Royal Rumble winner", "sim"),
    "money_in_the_bank": ("Money in the Bank winner", "sim"),
    "kotr": ("Queen of the Ring", "sim"),
    "wrestlemania": ("WrestleMania appearance", "sim"),
    "mania_main_event": ("WrestleMania main event", "sim"),
    "survivor_sole": ("Survivor Series sole survivor", "sim"),
    "iron_woman": ("Iron Woman match winner", "sim"),
    "grand_slam": ("Grand Slam (every singles title)", "sim"),
    # manual
    "playboy_cover": ("Playboy cover", "manual"),
    "babe_of_year": ("Babe of the Year", "manual"),
    "woman_of_year": ("Woman of the Year", "manual"),
    "match_of_year": ("Match of the Year", "manual"),
    "feud_of_year": ("Feud of the Year", "manual"),
    "most_improved": ("Most Improved", "manual"),
    "rookie_of_year": ("Rookie of the Year", "manual"),
    "hall_of_fame": ("Hall of Fame induction", "manual"),
    "slammy": ("Slammy Award", "manual"),
}


# --------------------------------------------------------------- bonuses
#
# Real money the promotion pays on top of the salary cap for winning things —
# it lands in a wrestler's career earnings and lifts her morale, but it is NOT
# charged against a brand's budget (it is the promotion's money, not the brand's
# cap space). Championships pay on the belt's tier; the marquee awards pay a
# flat purse.
TITLE_BONUS = {
    "world": 250_000, "secondary": 120_000, "tag": 90_000,
    "cruiserweight": 80_000, "hardcore": 70_000, "manager": 100_000,
}
ACCOLADE_BONUS = {
    "playboy_cover": 150_000, "babe_of_year": 120_000, "woman_of_year": 200_000,
    "rookie_of_year": 100_000, "match_of_year": 80_000, "feud_of_year": 70_000,
    "most_improved": 60_000, "slammy": 40_000, "hall_of_fame": 300_000,
    "royal_rumble": 120_000, "money_in_the_bank": 120_000, "kotr": 90_000,
    "mania_main_event": 100_000, "iron_woman": 80_000,
}
BONUS_MORALE = 6


def pay_bonus(con: sqlite3.Connection, wrestler_id: int, amount: int,
              morale: int = BONUS_MORALE) -> None:
    """Bank a one-time bonus: career earnings up, a morale lift, no cap hit."""
    if amount <= 0:
        return
    con.execute(
        "UPDATE wrestler_state SET career_earnings = career_earnings + ?, "
        "morale = MAX(0, MIN(100, morale + ?)) WHERE wrestler_id=?",
        (amount, morale, wrestler_id))


def award(con: sqlite3.Connection, wrestler_id: int, kind: str,
          season_year: int | None = None, detail: str | None = None) -> dict:
    if kind not in ACCOLADES:
        raise SigningError(f"unknown accolade '{kind}'")
    state = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    con.execute(
        """INSERT INTO accomplishment (wrestler_id, kind, season_year, detail, awarded_on)
           VALUES (?,?,?,?,?)""",
        (wrestler_id, kind, season_year or (state["season_year"] if state else None),
         detail, state["current_date"] if state else now_iso()[:10]),
    )
    bonus = ACCOLADE_BONUS.get(kind, 0)
    if bonus:
        pay_bonus(con, wrestler_id, bonus)
    con.commit()
    return {"wrestler_id": wrestler_id, "kind": kind, "label": ACCOLADES[kind][0],
            "bonus": bonus}


def unaward(con: sqlite3.Connection, accomplishment_id: int) -> dict:
    con.execute("DELETE FROM accomplishment WHERE id=?", (accomplishment_id,))
    con.commit()
    return {"removed": accomplishment_id}


def check_grand_slam(con: sqlite3.Connection, wrestler_id: int) -> bool:
    """Award the Grand Slam once she has held every singles title.

    The Manager's Championship is a singles belt by team_size but is held by a
    manager, not a wrestler, so it is excluded from the wrestling Grand Slam.
    """
    singles = [r[0] for r in con.execute(
        "SELECT id FROM game_title WHERE team_size = 1 AND active = 1 AND tier != 'manager'")]
    held = {r[0] for r in con.execute(
        "SELECT DISTINCT title_id FROM game_title_reign WHERE wrestler_id=?", (wrestler_id,))}
    if singles and set(singles).issubset(held):
        already = con.execute(
            "SELECT 1 FROM accomplishment WHERE wrestler_id=? AND kind='grand_slam'",
            (wrestler_id,)).fetchone()
        if not already:
            award(con, wrestler_id, "grand_slam")
            return True
    return False


# ---------------------------------------------------------------- setup

def new_game(con: sqlite3.Connection, seed: int = 2000, start: str = "2000-01-01") -> dict:
    """Create a fresh save. Wipes game state; leaves source data and overrides."""
    ensure_schema(con)   # feuds / news / proposals / awards tables must exist first
    for t in ("feud", "event_log", "proposal", "award_nomination"):
        con.execute(f"DELETE FROM {t}")
    # Strict child-before-parent order. The API runs with PRAGMA foreign_keys=ON,
    # so deleting game_title while sim_match.title_id still points at it aborts
    # the whole reset with an IntegrityError.
    #
    #   sim_match_participant -> sim_match, wrestler
    #   game_title_reign      -> game_title, sim_match, wrestler
    #   sim_match             -> show, game_title
    #   draft_pick            -> draft, brand, wrestler, contract
    #   show, game_title      -> brand
    #   contract, brand_budget-> brand
    #
    # contract.extended_from points at another CONTRACT row, so deleting the
    # table row-by-row can trip over its own self-reference. Break those links
    # first, then the bulk delete is unordered-safe within the table.
    con.execute("UPDATE contract SET extended_from = NULL")
    # NOTE: trade_asset/trade_offer, pick_asset and brand_cash all reference
    # brand(id). They are empty the very first time a save is created, so the
    # original order happened to work — but on a RESTART (a live save) they are
    # full, and deleting `brand` while they still point at it aborts the whole
    # reset with a FOREIGN KEY error. That is exactly why "Restart save" looked
    # dead: the request 500'd. Every child of brand must go first.
    for t in ("sim_match_participant", "game_title_reign", "sim_match",
              "accomplishment", "trade_asset", "trade_offer",
              "faction_member", "faction", "tag_team_member", "tag_team",
              "holdout", "season_role",
              "draft_pick", "draft", "show", "game_title",
              "pick_asset", "brand_cash", "contract",
              "brand_budget", "brand", "game_state"):
        con.execute(f"DELETE FROM {t}")

    con.execute("UPDATE wrestler_state SET sim_matches=0, sim_wins=0, sim_losses=0, "
                "sim_draws=0, momentum=50, morale=50, fatigue=0, injured_until=NULL, "
                "career_earnings=0, ppv_appearances=0")

    season = int(start[:4])
    con.execute(
        "INSERT INTO game_state (id, current_date, season_year, rng_seed, created_at) "
        "VALUES (1,?,?,?,?)",
        (start, season, seed, now_iso()),
    )

    for bid, name, colour in BRANDS:
        con.execute("INSERT INTO brand (id, name, colour) VALUES (?,?,?)", (bid, name, colour))
        budget = STARTING_BUDGET
        for i in range(BUDGET_HORIZON_YEARS):
            con.execute(
                "INSERT INTO brand_budget (brand_id, season_year, budget) VALUES (?,?,?)",
                (bid, season + i, int(round(budget / 10_000) * 10_000)),
            )
            budget *= 1 + BUDGET_GROWTH

    seed_titles(con)

    for bid, _, _ in BRANDS:
        con.execute("INSERT OR REPLACE INTO brand_cash (brand_id, balance) VALUES (?,0)", (bid,))

    # Draft picks exist as tradeable assets from day one, several seasons ahead,
    # so a brand can deal a future first-rounder before that draft is created.
    # Wrestler and manager drafts run a different number of rounds.
    for offset in range(PICK_HORIZON_YEARS):
        for kind in ("wrestler", "manager"):
            kind_rounds = DRAFT_STRUCTURE[kind]["rounds"]
            for rnd in range(1, kind_rounds + 1):
                for bid, _, _ in BRANDS:
                    con.execute(
                        """INSERT OR REPLACE INTO pick_asset
                           (season_year, round_no, original_brand, owner_brand, draft_kind)
                           VALUES (?,?,?,?,?)""",
                        (season + offset, rnd, bid, bid, kind),
                    )

    con.commit()
    return {"season_year": season, "seed": seed, "start": start, "titles": len(TITLES)}


def ensure_budget(con: sqlite3.Connection, brand_id: str, season: int) -> int:
    """Budgets are projected at save creation, but a long save can outrun the
    horizon — extend it rather than failing."""
    row = con.execute(
        "SELECT budget FROM brand_budget WHERE brand_id=? AND season_year=?",
        (brand_id, season),
    ).fetchone()
    if row:
        return row["budget"] if isinstance(row, sqlite3.Row) else row[0]

    last = con.execute(
        "SELECT season_year, budget FROM brand_budget WHERE brand_id=? "
        "ORDER BY season_year DESC LIMIT 1", (brand_id,),
    ).fetchone()
    year, budget = (last[0], last[1]) if last else (season, STARTING_BUDGET)
    while year < season:
        year += 1
        budget = int(round(budget * (1 + BUDGET_GROWTH) / 10_000) * 10_000)
        con.execute("INSERT OR REPLACE INTO brand_budget (brand_id, season_year, budget) "
                    "VALUES (?,?,?)", (brand_id, year, budget))
    con.commit()
    return budget


def brand_finances(con: sqlite3.Connection, season: int) -> list[dict]:
    out = []
    for b in con.execute("SELECT * FROM brand ORDER BY id"):
        bid = b["id"]
        budget = ensure_budget(con, bid, season)
        committed = con.execute(
            """SELECT COALESCE(SUM(annual_value),0) FROM contract
               WHERE brand_id=? AND terminated_on IS NULL
                 AND start_year <= ? AND end_year >= ?""",
            (bid, season, season),
        ).fetchone()[0]
        roster = con.execute(
            """SELECT COUNT(*) FROM contract
               WHERE brand_id=? AND terminated_on IS NULL
                 AND start_year <= ? AND end_year >= ?""",
            (bid, season, season),
        ).fetchone()[0]
        out.append({
            "brand_id": bid, "name": b["name"], "colour": b["colour"],
            "season_year": season, "budget": budget,
            "committed": committed, "available": budget - committed,
            "roster_size": roster,
        })
    return out


# ---------------------------------------------------------------- contracts

class SigningError(Exception):
    pass


def active_contract(con: sqlite3.Connection, wrestler_id: int, season: int):
    return con.execute(
        """SELECT * FROM contract
           WHERE wrestler_id=? AND terminated_on IS NULL
             AND start_year <= ? AND end_year >= ?""",
        (wrestler_id, season, season),
    ).fetchone()


def _write_contract(con: sqlite3.Connection, wrestler_id: int, brand_id: str,
                    value: int, years: int, start_year: int, signed_on: str,
                    origin: str, extended_from: int | None = None,
                    perks: list[str] | None = None, signing_bonus: int = 0,
                    role: str = "wrestler") -> int:
    import json
    cur = con.execute(
        """INSERT INTO contract
           (wrestler_id, brand_id, annual_value, years, start_year, end_year,
            signed_on, origin, extended_from, perks, signing_bonus, role)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (wrestler_id, brand_id, value, years, start_year, start_year + years - 1,
         signed_on, origin, extended_from,
         json.dumps(perks) if perks else None, signing_bonus, role),
    )
    # A signing bonus is money in her pocket now — count it toward career earnings.
    if signing_bonus:
        con.execute(
            "UPDATE wrestler_state SET career_earnings = career_earnings + ? WHERE wrestler_id=?",
            (signing_bonus, wrestler_id))
    return cur.lastrowid


def extend(con: sqlite3.Connection, wrestler_id: int, years: int,
           annual_value: int | None = None) -> dict:
    """Extend an existing deal, NBA-style.

    Rules, deliberately matching the brief:
      - only a wrestler already under contract can be extended
      - a ONE-YEAR contract cannot be extended at all
      - the extension begins the season after the current deal ends
      - the brand must fit the new money under the budget of that first season
    """
    state = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if state is None:
        raise SigningError("no active save — start a new game first")
    season = state["season_year"]

    current = active_contract(con, wrestler_id, season)
    if not current:
        raise SigningError("not under contract — she has to be drafted first")

    if current["years"] <= 1:
        raise SigningError("one-year contracts cannot be extended")

    if current["origin"] == "extension":
        raise SigningError("an extension cannot itself be extended")

    if not (MIN_CONTRACT_YEARS <= years <= MAX_CONTRACT_YEARS):
        raise SigningError(f"extension must be {MIN_CONTRACT_YEARS}-{MAX_CONTRACT_YEARS} years")

    already = con.execute(
        "SELECT 1 FROM contract WHERE extended_from=? AND terminated_on IS NULL",
        (current["id"],),
    ).fetchone()
    if already:
        raise SigningError("this contract has already been extended")

    ask = asking_price(con, wrestler_id)
    value = annual_value if annual_value is not None else ask
    if value < ask:
        raise SigningError(f"she will not extend below her asking price of ${ask:,}")

    start = current["end_year"] + 1
    budget = ensure_budget(con, current["brand_id"], start)
    committed = con.execute(
        """SELECT COALESCE(SUM(annual_value),0) FROM contract
           WHERE brand_id=? AND terminated_on IS NULL
             AND start_year <= ? AND end_year >= ?""",
        (current["brand_id"], start, start),
    ).fetchone()[0]
    if value > budget - committed:
        raise SigningError(
            f"{current['brand_id']} has ${budget - committed:,} free in {start}, "
            f"extension costs ${value:,}"
        )

    cid = _write_contract(con, wrestler_id, current["brand_id"], value, years,
                          start, state["current_date"], "extension", current["id"])
    con.commit()
    return {"contract_id": cid, "wrestler_id": wrestler_id,
            "brand_id": current["brand_id"], "annual_value": value,
            "years": years, "start_year": start, "end_year": start + years - 1}


FREE_AGENT_YEARS = 1


def free_agent_sign(con: sqlite3.Connection, wrestler_id: int, brand_id: str,
                    annual_value: int, perks: list[str] | None = None,
                    signing_bonus: int = 0) -> dict:
    """Sign a free agent — anyone not currently under contract — to a ONE-YEAR
    deal with the brand of her choosing, at the salary the negotiation settled.

    Free agency exists alongside the draft now: the draft hands out the multi-year
    deals, free agency is short, negotiated, one-year business.
    """
    state = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if state is None:
        raise SigningError("no active save — start a new game first")
    season = state["season_year"]

    if not con.execute("SELECT 1 FROM wrestler WHERE id=?", (wrestler_id,)).fetchone():
        raise SigningError("no such wrestler")
    if active_contract(con, wrestler_id, season):
        raise SigningError("already under contract — not a free agent")
    if brand_id not in {b[0] for b in BRANDS}:
        raise SigningError("unknown brand")
    if is_holdout(con, wrestler_id, brand_id, season):
        raise SigningError("she is holding out from this brand for the year — "
                           "clear the holdout to reopen talks")

    value = max(A.MIN_VALUE, int(annual_value))
    fin = {f["brand_id"]: f for f in brand_finances(con, season)}[brand_id]
    if value > fin["available"]:
        raise SigningError(
            f"{fin['name']} has ${fin['available']:,} free, this deal costs ${value:,}")

    cid = _write_contract(con, wrestler_id, brand_id, value, FREE_AGENT_YEARS,
                          season, state["current_date"], "free_agent",
                          perks=perks, signing_bonus=signing_bonus)
    con.commit()
    return {"contract_id": cid, "wrestler_id": wrestler_id, "brand_id": brand_id,
            "annual_value": value, "years": FREE_AGENT_YEARS,
            "perks": perks or [], "signing_bonus": signing_bonus}


def release(con: sqlite3.Connection, wrestler_id: int) -> dict:
    state = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    c = active_contract(con, wrestler_id, state["season_year"])
    if not c:
        raise SigningError("not under contract")
    con.execute("UPDATE contract SET terminated_on=? WHERE id=?",
                (state["current_date"], c["id"]))
    log_event(con, "release", f"{c['brand_id']} release {_wname(con, wrestler_id)}.",
              c["brand_id"], "👋")
    con.commit()
    return {"released": wrestler_id, "was_brand": c["brand_id"]}


# ---------------------------------------------------------------- trade offers

def propose_trade(con: sqlite3.Connection, from_brand: str, to_brand: str,
                  assets: list[dict], note: str | None = None) -> dict:
    """Record a proposed trade for your approval. Nothing moves until accepted.

    Each asset is {side, kind, ...} where side is the brand GIVING it up:
        {"side": "RAW", "kind": "wrestler", "wrestler_id": 356}
        {"side": "RAW", "kind": "pick", "pick_season": 2001, "pick_round": 1}
        {"side": "SMACKDOWN", "kind": "cash", "cash": 250000}
    """
    state = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if state is None:
        raise SigningError("no active save")
    if from_brand == to_brand:
        raise SigningError("a trade needs two different brands")

    cur = con.execute(
        "INSERT INTO trade_offer (from_brand, to_brand, note, created_on) VALUES (?,?,?,?)",
        (from_brand, to_brand, note, state["current_date"]),
    )
    offer_id = cur.lastrowid

    for a in assets:
        con.execute(
            """INSERT INTO trade_asset
               (offer_id, side, kind, wrestler_id, pick_season, pick_round, cash)
               VALUES (?,?,?,?,?,?,?)""",
            (offer_id, a["side"], a["kind"], a.get("wrestler_id"),
             a.get("pick_season"), a.get("pick_round"), a.get("cash")),
        )
    con.commit()
    return {"offer_id": offer_id, "assets": len(assets)}


def trade_offers(con: sqlite3.Connection, status: str | None = "pending") -> list[dict]:
    q = "SELECT * FROM trade_offer"
    args: tuple = ()
    if status:
        q += " WHERE status=?"
        args = (status,)
    q += " ORDER BY id DESC"

    out = []
    for o in con.execute(q, args):
        assets = [dict(r) for r in con.execute(
            """SELECT a.*, w.name AS wrestler_name FROM trade_asset a
               LEFT JOIN wrestler w ON w.id = a.wrestler_id
               WHERE a.offer_id=?""", (o["id"],))]
        for a in assets:
            if a["kind"] == "wrestler" and a["wrestler_id"]:
                eff = effective_attributes(con, a["wrestler_id"], ach.get(a["wrestler_id"]))
                a["value"] = eff["value"]
                a["overall"] = eff["overall"]
        out.append({**dict(o), "assets": assets})
    return out


def _validate_and_apply(con: sqlite3.Connection, offer: sqlite3.Row,
                        assets: list[sqlite3.Row], season: int, today: str) -> dict:
    """Move everything, checking each brand still fits its budget afterwards."""
    fin = {f["brand_id"]: f for f in brand_finances(con, season)}
    delta = {b: 0 for b in fin}          # salary change per brand

    for a in assets:
        giver = a["side"]
        taker = offer["to_brand"] if giver == offer["from_brand"] else offer["from_brand"]

        if a["kind"] == "wrestler":
            c = active_contract(con, a["wrestler_id"], season)
            if not c:
                raise SigningError(f"wrestler {a['wrestler_id']} is not under contract")
            if c["brand_id"] != giver:
                raise SigningError(f"{giver} does not hold that contract")
            delta[giver] -= c["annual_value"]
            delta[taker] += c["annual_value"]

        elif a["kind"] == "pick":
            pick = con.execute(
                """SELECT * FROM pick_asset WHERE season_year=? AND round_no=?
                   AND owner_brand=? AND used=0""",
                (a["pick_season"], a["pick_round"], giver),
            ).fetchone()
            if not pick:
                raise SigningError(
                    f"{giver} does not own an unused {a['pick_season']} round-{a['pick_round']} pick")

        elif a["kind"] == "cash":
            bal = con.execute(
                "SELECT balance FROM brand_cash WHERE brand_id=?", (giver,)).fetchone()
            have = (bal["balance"] if bal else 0) + fin[giver]["available"]
            if a["cash"] > have:
                raise SigningError(f"{giver} cannot cover ${a['cash']:,}")

    for b, d in delta.items():
        if fin[b]["available"] - d < 0:
            raise SigningError(
                f"{fin[b]['name']} would be ${abs(fin[b]['available'] - d):,} over budget")

    # --- everything validated, now move it ---
    for a in assets:
        giver = a["side"]
        taker = offer["to_brand"] if giver == offer["from_brand"] else offer["from_brand"]

        if a["kind"] == "wrestler":
            c = active_contract(con, a["wrestler_id"], season)
            con.execute("UPDATE contract SET brand_id=? WHERE id=?", (taker, c["id"]))
        elif a["kind"] == "pick":
            con.execute(
                """UPDATE pick_asset SET owner_brand=?
                   WHERE season_year=? AND round_no=? AND owner_brand=? AND used=0""",
                (taker, a["pick_season"], a["pick_round"], giver),
            )
        elif a["kind"] == "cash":
            for brand, sign in ((giver, -1), (taker, 1)):
                con.execute(
                    "INSERT INTO brand_cash (brand_id, balance) VALUES (?,?) "
                    "ON CONFLICT(brand_id) DO UPDATE SET balance = balance + ?",
                    (brand, sign * a["cash"], sign * a["cash"]),
                )

    con.execute("UPDATE trade_offer SET status='accepted', resolved_on=? WHERE id=?",
                (today, offer["id"]))
    con.commit()
    return {"offer_id": offer["id"], "status": "accepted", "assets_moved": len(assets)}


def resolve_trade(con: sqlite3.Connection, offer_id: int, accept: bool) -> dict:
    """Your call. Rejecting simply closes the offer; nothing moves."""
    state = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    offer = con.execute("SELECT * FROM trade_offer WHERE id=?", (offer_id,)).fetchone()
    if not offer:
        raise SigningError("no such offer")
    if offer["status"] != "pending":
        raise SigningError(f"offer is already {offer['status']}")

    if not accept:
        con.execute("UPDATE trade_offer SET status='rejected', resolved_on=? WHERE id=?",
                    (state["current_date"], offer_id))
        con.commit()
        return {"offer_id": offer_id, "status": "rejected"}

    assets = list(con.execute("SELECT * FROM trade_asset WHERE offer_id=?", (offer_id,)))
    if not assets:
        raise SigningError("offer has no assets")
    return _validate_and_apply(con, offer, assets, state["season_year"], state["current_date"])


def owned_picks(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute(
        """SELECT * FROM pick_asset WHERE used=0
           ORDER BY season_year, draft_kind, round_no, original_brand""")]


def trade(con: sqlite3.Connection, wrestler_ids_a: list[int], wrestler_ids_b: list[int]) -> dict:
    """Swap wrestlers between the two brands, carrying contracts with them.

    Both sides must still fit their budget afterwards — a trade cannot be used
    as a back door around the cap.
    """
    state = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    season = state["season_year"]

    moving = []
    for wid in wrestler_ids_a + wrestler_ids_b:
        c = active_contract(con, wid, season)
        if not c:
            raise SigningError(f"wrestler {wid} is not under contract")
        moving.append((wid, c))

    brands = {c["brand_id"] for _, c in moving}
    if len(brands) != 2:
        raise SigningError("a trade needs wrestlers from both brands")

    a_brand = active_contract(con, wrestler_ids_a[0], season)["brand_id"] if wrestler_ids_a else None
    b_brand = active_contract(con, wrestler_ids_b[0], season)["brand_id"] if wrestler_ids_b else None
    if a_brand is None or b_brand is None or a_brand == b_brand:
        raise SigningError("a trade needs wrestlers from both brands")

    out_a = sum(c["annual_value"] for w, c in moving if c["brand_id"] == a_brand)
    out_b = sum(c["annual_value"] for w, c in moving if c["brand_id"] == b_brand)

    fin = {f["brand_id"]: f for f in brand_finances(con, season)}
    a_after = fin[a_brand]["available"] + out_a - out_b
    b_after = fin[b_brand]["available"] + out_b - out_a
    if a_after < 0:
        raise SigningError(f"{fin[a_brand]['name']} would be ${-a_after:,} over budget")
    if b_after < 0:
        raise SigningError(f"{fin[b_brand]['name']} would be ${-b_after:,} over budget")

    for wid, c in moving:
        dest = b_brand if c["brand_id"] == a_brand else a_brand
        con.execute("UPDATE contract SET brand_id=? WHERE id=?", (dest, c["id"]))
    con.commit()
    return {"moved": len(moving), "a_available": a_after, "b_available": b_after}


# ---------------------------------------------------------------- draft

# The draft, per the 2000 relaunch brief:
#   Wrestler draft — 2 rounds of 10 picks (5 per brand each round) => 20 picks,
#                    TEN per brand. Round 1 = first-round, round 2 = second-round.
#   Manager  draft — 3 rounds of 2 picks (1 per brand each round)  =>  6 picks,
#                    THREE per brand.
# A round is a full slate, not a single pick, so "10 in the first round, 10 in
# the second" maps straight onto the two rounds.
DRAFT_STRUCTURE = {
    "wrestler": {"rounds": 2, "per_round": 10},   # 5 per brand per round
    "manager":  {"rounds": 3, "per_round": 2},    # 1 per brand per round
}
DEFAULT_PICK_YEARS = 2
PICK_HORIZON_YEARS = 4        # how many seasons of tradeable picks exist

# Contract length by round: first-rounders get 3 years, everyone after gets 2.
FIRST_ROUND_YEARS = 3
SECOND_ROUND_YEARS = 2

# First-round picks are the marquee talent — they open negotiations demanding a
# premium; later rounds are depth and open cheaper. This sets the BASE the
# negotiation runs against (see negotiate.py), not a locked price.
FIRST_ROUND_FACTOR = 1.25
SECOND_ROUND_FACTOR = 0.80

# Managers do not wrestle, so they are paid a fraction of a wrestler's value —
# but it still comes out of the same budget, so stacking them has a cost.
MANAGER_PAY_FACTOR = 0.12
MANAGER_MIN_VALUE = 25_000


def draft_tier(pick_number: int, kind: str = "wrestler") -> tuple[str, float]:
    """Which round a pick sits in, and its money multiplier.

    Rounds are full slates (10 wrestler picks each), so the round is the pick
    number divided by the slate size — round 1 is the premium first round, any
    later round is the discounted second round.
    """
    per_round = DRAFT_STRUCTURE.get(kind, DRAFT_STRUCTURE["wrestler"])["per_round"]
    round_no = (pick_number - 1) // per_round + 1
    if round_no <= 1:
        return "first", FIRST_ROUND_FACTOR
    return "second", SECOND_ROUND_FACTOR


def draft_years(tier: str) -> int:
    return FIRST_ROUND_YEARS if tier == "first" else SECOND_ROUND_YEARS


def manager_price(con: sqlite3.Connection, wrestler_id: int,
                  attrs: dict | None = None) -> int:
    """A manager is bought on presence, not workrate.

    Popularity carries most of it — promo skill is one of its components, and
    talking is most of the job. Achievements counts for a manager the way it does
    for a wrestler: a valet who has guided somebody to a belt is a known
    quantity. WRESTLING IS ABSENT ENTIRELY, which is the whole point of pricing
    managers separately: nobody hires Sunny to work a twenty-minute match.

    `attrs` lets a caller that has already computed her ratings hand them in.
    Without it the roster endpoint re-derived all five per row — including a full
    achievements scan each time — for a number it was holding a moment earlier.
    """
    a = attrs if attrs is not None else effective_attributes(con, wrestler_id)
    presence = (a["popularity"] * 0.50 + a["looks"] * 0.20
                + a["achievements"] * 0.18 + a["personal"] * 0.12) / A.CAT_MAX
    raw = A.BASE_VALUE * MANAGER_PAY_FACTOR * (presence ** 1.5) * A.age_multiplier(a["age"])
    return max(MANAGER_MIN_VALUE, int(round(raw / 5_000) * 5_000))


def role_of(con: sqlite3.Connection, wrestler_id: int) -> str:
    r = con.execute(
        """SELECT COALESCE(o.role, a.role) AS role FROM attributes a
           LEFT JOIN attribute_override o ON o.wrestler_id = a.wrestler_id
           WHERE a.wrestler_id = ?""", (wrestler_id,)).fetchone()
    return r["role"] if r else "wrestler"


def start_draft(con: sqlite3.Connection, rounds: int | None = None,
                first_pick: str = "RAW", kind: str = "wrestler") -> dict:
    """Open a draft for the current season.

    A round is a full slate (10 picks for wrestlers, 2 for managers) that snakes
    between the brands and flips its starting brand each round, so neither brand
    keeps the top of every round. `rounds` is ignored for the wrestler/manager
    drafts — the structure is fixed by DRAFT_STRUCTURE — but kept for signature
    compatibility.
    """
    struct = DRAFT_STRUCTURE.get(kind, DRAFT_STRUCTURE["wrestler"])
    rounds = struct["rounds"]
    per_round = struct["per_round"]

    state = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if state is None:
        raise SigningError("no active save — start a new game first")
    season = state["season_year"]

    # The manager draft only opens once the wrestler draft is done — undrafted
    # wrestlers are exactly who becomes eligible to be signed as a manager.
    if kind == "manager":
        wd = con.execute(
            "SELECT status FROM draft WHERE season_year=? AND draft_kind='wrestler'",
            (season,)).fetchone()
        if not wd or wd["status"] != "complete":
            raise SigningError("run the wrestler draft first — the manager pool is "
                               "everyone left undrafted")

    existing = con.execute(
        "SELECT * FROM draft WHERE season_year=? AND draft_kind=?", (season, kind)).fetchone()
    if existing:
        con.execute("DELETE FROM draft_pick WHERE draft_id=?", (existing["id"],))
        con.execute("DELETE FROM draft WHERE id=?", (existing["id"],))

    other = "SMACKDOWN" if first_pick == "RAW" else "RAW"
    cur = con.execute(
        "INSERT INTO draft (season_year, status, first_pick, draft_kind, created_at) "
        "VALUES (?,?,?,?,?)",
        (season, "active", first_pick, kind, now_iso()),
    )
    draft_id = cur.lastrowid

    # A pick belongs to whoever OWNS that brand's slate for the round — slates can
    # be traded, so the brand on the clock is not always the original owner.
    n = 1
    for rnd in range(rounds):
        lead = first_pick if rnd % 2 == 0 else other
        follow = other if rnd % 2 == 0 else first_pick
        # Alternate lead/follow across the round's slots (5 each for wrestlers).
        slate = [lead if i % 2 == 0 else follow for i in range(per_round)]
        for slot_brand in slate:
            owner = con.execute(
                """SELECT owner_brand FROM pick_asset
                   WHERE season_year=? AND round_no=? AND original_brand=? AND draft_kind=?""",
                (season, rnd + 1, slot_brand, kind),
            ).fetchone()
            con.execute(
                "INSERT INTO draft_pick (draft_id, pick_number, brand_id, original_brand) "
                "VALUES (?,?,?,?)",
                (draft_id, n, owner["owner_brand"] if owner else slot_brand, slot_brand),
            )
            n += 1
    con.commit()
    return {"draft_id": draft_id, "season_year": season, "kind": kind,
            "rounds": rounds, "picks": n - 1, "first_pick": first_pick}


def draft_board(con: sqlite3.Connection, kind: str = "wrestler") -> dict:
    """Current draft, its picks, and who is still available."""
    state = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if state is None:
        return {"draft": None, "picks": [], "available": [], "on_the_clock": None, "kind": kind}
    season = state["season_year"]

    d = con.execute(
        "SELECT * FROM draft WHERE season_year=? AND draft_kind=?", (season, kind)).fetchone()
    if not d:
        return {"draft": None, "picks": [], "available": [], "on_the_clock": None, "kind": kind}

    picks = [dict(r) for r in con.execute(
        """SELECT p.*, w.name AS wrestler_name, c.annual_value, c.years
           FROM draft_pick p
           LEFT JOIN wrestler w ON w.id = p.wrestler_id
           LEFT JOIN contract c ON c.id = p.contract_id
           WHERE p.draft_id=? ORDER BY p.pick_number""", (d["id"],))]

    total_picks = len(picks)
    for p in picks:
        p["tier"], p["tier_factor"] = draft_tier(p["pick_number"], kind)
        p["years"] = draft_years(p["tier"])

    on_clock = next((p for p in picks if p["wrestler_id"] is None), None)
    return {
        "draft": {**dict(d), "total_picks": total_picks,
                  "first_round_factor": FIRST_ROUND_FACTOR,
                  "second_round_factor": SECOND_ROUND_FACTOR},
        "picks": picks,
        "on_the_clock": on_clock,
        "kind": kind,
        "available": undrafted(con, season, kind),
    }


# ---------------------------------------------------------------- holdouts

def record_holdout(con: sqlite3.Connection, wrestler_id: int, brand_id: str) -> dict:
    st = con.execute("SELECT season_year, game_state.current_date FROM game_state WHERE id=1").fetchone()
    if not st:
        return {}
    con.execute(
        "INSERT OR IGNORE INTO holdout (season_year, wrestler_id, brand_id, created_on) "
        "VALUES (?,?,?,?)", (st["season_year"], wrestler_id, brand_id, st["current_date"]))
    log_event(con, "holdout",
              f"{_wname(con, wrestler_id)} walked out on {brand_id} — holding out this year.",
              brand_id, "🚪")
    con.commit()
    return {"held_out": wrestler_id, "brand_id": brand_id, "season": st["season_year"]}


def clear_holdout(con: sqlite3.Connection, wrestler_id: int, brand_id: str) -> dict:
    st = con.execute("SELECT season_year FROM game_state WHERE id=1").fetchone()
    con.execute("DELETE FROM holdout WHERE season_year=? AND wrestler_id=? AND brand_id=?",
                (st["season_year"] if st else 0, wrestler_id, brand_id))
    con.commit()
    return {"cleared": wrestler_id, "brand_id": brand_id}


def holdouts(con: sqlite3.Connection, season: int) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT wrestler_id, brand_id FROM holdout WHERE season_year=?", (season,))]


def is_holdout(con: sqlite3.Connection, wrestler_id: int, brand_id: str, season: int) -> bool:
    return con.execute(
        "SELECT 1 FROM holdout WHERE season_year=? AND wrestler_id=? AND brand_id=?",
        (season, wrestler_id, brand_id)).fetchone() is not None


# ---------------------------------------------------------------- season role

def set_season_role(con: sqlite3.Connection, wrestler_id: int, role: str | None) -> dict:
    """Pin a BOTH-eligible wrestler to one pool for this season (or clear it)."""
    st = con.execute("SELECT season_year FROM game_state WHERE id=1").fetchone()
    season = st["season_year"] if st else RESET_YEAR
    if role in ("wrestler", "manager"):
        con.execute(
            "INSERT INTO season_role (season_year, wrestler_id, role) VALUES (?,?,?) "
            "ON CONFLICT(season_year, wrestler_id) DO UPDATE SET role=excluded.role",
            (season, wrestler_id, role))
    else:
        con.execute("DELETE FROM season_role WHERE season_year=? AND wrestler_id=?",
                    (season, wrestler_id))
    con.commit()
    return {"wrestler_id": wrestler_id, "season_role": role}


def undrafted(con: sqlite3.Connection, season: int, kind: str = "wrestler") -> list[int]:
    """The draft pool — everyone eligible and not currently on a brand roster.

    The wrestler draft runs FIRST and takes anyone who works in the ring
    (role wrestler/both). The manager draft runs after it, and the pool is now
    simply *everyone still unsigned* — the brief is that anyone who does not get
    picked in the wrestler draft becomes eligible to be signed as a manager. A
    wrestler taken in the wrestler draft already holds a contract, so the live-
    contract gate keeps her out of the manager pool automatically.

    Gates that always apply: draft class (entered by this season), no live
    contract, and not removed. Holdouts are per-brand and enforced at pick time,
    so a holdout can still be drafted by the OTHER brand.
    """
    if kind == "manager":
        # No role filter — everyone left unsigned is manager-eligible.
        return [r[0] for r in con.execute(
            """SELECT w.id FROM wrestler w
               JOIN attributes a ON a.wrestler_id = w.id
               LEFT JOIN attribute_override o ON o.wrestler_id = w.id
               WHERE COALESCE(o.draft_class, ?) <= ?
                 AND NOT EXISTS (
                 SELECT 1 FROM contract c
                 WHERE c.wrestler_id = w.id AND c.terminated_on IS NULL
                   AND c.start_year <= ? AND c.end_year >= ?)
                 AND NOT EXISTS (
                 SELECT 1 FROM excluded_wrestler x WHERE x.wrestler_id = w.id)
               ORDER BY w.id""",
            (RESET_YEAR, season, season, season),
        )]

    roles = ("wrestler", "both")
    return [r[0] for r in con.execute(
        f"""SELECT w.id FROM wrestler w
           JOIN attributes a ON a.wrestler_id = w.id
           LEFT JOIN attribute_override o ON o.wrestler_id = w.id
           LEFT JOIN season_role sr ON sr.wrestler_id = w.id AND sr.season_year = ?
           WHERE COALESCE(o.role, a.role) IN ({','.join('?' * len(roles))})
             AND COALESCE(o.draft_class, ?) <= ?
             AND (sr.role IS NULL OR sr.role != 'manager')
             AND NOT EXISTS (
             SELECT 1 FROM contract c
             WHERE c.wrestler_id = w.id AND c.terminated_on IS NULL
               AND c.start_year <= ? AND c.end_year >= ?)
             AND NOT EXISTS (
             SELECT 1 FROM excluded_wrestler x WHERE x.wrestler_id = w.id)
           ORDER BY w.id""",
        (season, *roles, RESET_YEAR, season, season, season),
    )]


# ---------------------------------------------------------------- removal

def exclude(con: sqlite3.Connection, wrestler_id: int, reason: str | None = None) -> dict:
    """Remove a wrestler from the game.

    Terminates any live contract on the way out — otherwise her salary would go
    on counting against a brand's budget for someone who no longer exists.
    Sim history is left intact so past shows still make sense.
    """
    row = con.execute("SELECT name FROM wrestler WHERE id=?", (wrestler_id,)).fetchone()
    if not row:
        raise SigningError("no such wrestler")

    state = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if state:
        con.execute(
            "UPDATE contract SET terminated_on=? WHERE wrestler_id=? AND terminated_on IS NULL",
            (state["current_date"], wrestler_id),
        )
        # Free any draft pick she was taken with, so the board stays honest.
        con.execute(
            "UPDATE draft_pick SET wrestler_id=NULL, contract_id=NULL, picked_on=NULL "
            "WHERE wrestler_id=?", (wrestler_id,),
        )

    con.execute(
        "INSERT OR REPLACE INTO excluded_wrestler (wrestler_id, reason, excluded_at) "
        "VALUES (?,?,?)", (wrestler_id, reason, now_iso()),
    )
    con.commit()
    return {"removed": wrestler_id, "name": row["name"]}


def restore(con: sqlite3.Connection, wrestler_id: int) -> dict:
    con.execute("DELETE FROM excluded_wrestler WHERE wrestler_id=?", (wrestler_id,))
    con.commit()
    row = con.execute("SELECT name FROM wrestler WHERE id=?", (wrestler_id,)).fetchone()
    return {"restored": wrestler_id, "name": row["name"] if row else None}


def ban(con: sqlite3.Connection, wrestler_id: int) -> dict:
    """Permanently delete a wrestler — she disappears from the game for good.

    Unlike the old soft-remove, this HARD-deletes every trace and records her id
    in banned_wrestler so a future normalize.py re-harvest can never resurrect
    her (normalize checks that table before inserting). Foreign keys are ON, so
    children go before parents and back-references are nulled first.
    """
    row = con.execute("SELECT name FROM wrestler WHERE id=?", (wrestler_id,)).fetchone()
    if not row:
        raise SigningError("no such wrestler")

    # Break back-references that point AT this wrestler from rows we keep.
    con.execute("UPDATE draft_pick SET wrestler_id=NULL, contract_id=NULL, picked_on=NULL "
                "WHERE wrestler_id=?", (wrestler_id,))
    con.execute("UPDATE faction SET leader_id=NULL WHERE leader_id=?", (wrestler_id,))
    # feud references her from TWO columns — clear both sides first.
    con.execute("DELETE FROM feud WHERE a_id=? OR b_id=?", (wrestler_id, wrestler_id))

    # Delete every row that references her, then the wrestler herself. Order
    # matters with foreign_keys ON, and this MUST cover every table that FK-refs
    # wrestler(id) — including the newer ones (wrestler_bio, award_nomination) or
    # the final DELETE FROM wrestler is blocked and the whole ban aborts.
    for stmt in (
        "DELETE FROM sim_match_participant WHERE wrestler_id=?",
        "DELETE FROM game_title_reign WHERE wrestler_id=?",
        "DELETE FROM accomplishment WHERE wrestler_id=?",
        "DELETE FROM award_nomination WHERE wrestler_id=?",
        "DELETE FROM trade_asset WHERE wrestler_id=?",
        "DELETE FROM tag_team_member WHERE wrestler_id=?",
        "DELETE FROM faction_member WHERE wrestler_id=?",
        "DELETE FROM holdout WHERE wrestler_id=?",
        "DELETE FROM season_role WHERE wrestler_id=?",
        "DELETE FROM contract WHERE wrestler_id=?",
        "DELETE FROM wrestler_image WHERE wrestler_id=?",
        "DELETE FROM wrestler_state WHERE wrestler_id=?",
        "DELETE FROM attribute_override WHERE wrestler_id=?",
        "DELETE FROM wrestler_bio WHERE wrestler_id=?",
        "DELETE FROM excluded_wrestler WHERE wrestler_id=?",
        "DELETE FROM attributes WHERE wrestler_id=?",
        "DELETE FROM ring_name WHERE wrestler_id=?",
        "DELETE FROM promotion_year WHERE wrestler_id=?",
        "DELETE FROM title_reign WHERE wrestler_id=?",
        "DELETE FROM wrestler WHERE id=?",
    ):
        con.execute(stmt, (wrestler_id,))

    con.execute("INSERT OR REPLACE INTO banned_wrestler (wrestler_id, banned_at) VALUES (?,?)",
                (wrestler_id, now_iso()))
    con.commit()
    return {"banned": wrestler_id, "name": row["name"]}


def excluded_ids(con: sqlite3.Connection) -> set[int]:
    return {r[0] for r in con.execute("SELECT wrestler_id FROM excluded_wrestler")}


def make_pick(con: sqlite3.Connection, wrestler_id: int,
              years: int | None = None, annual_value: int | None = None,
              kind: str = "wrestler", perks: list[str] | None = None,
              signing_bonus: int = 0) -> dict:
    """Sign the pick on the clock to the salary the negotiation settled on.

    The salary/perks/bonus arrive already agreed from the negotiation engine —
    this just validates the pick, enforces the cap, and writes the deal. Contract
    length is fixed by the round: 3 years for a first-rounder, 2 for the rest.
    """
    state = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if state is None:
        raise SigningError("no active save — start a new game first")
    season = state["season_year"]

    d = con.execute(
        "SELECT * FROM draft WHERE season_year=? AND draft_kind=? AND status='active'",
        (season, kind)).fetchone()
    if not d:
        raise SigningError(f"no active {kind} draft — open one from the Draft tab")

    pick = con.execute(
        "SELECT * FROM draft_pick WHERE draft_id=? AND wrestler_id IS NULL "
        "ORDER BY pick_number LIMIT 1", (d["id"],),
    ).fetchone()
    if not pick:
        con.execute("UPDATE draft SET status='complete' WHERE id=?", (d["id"],))
        con.commit()
        raise SigningError("every pick has been used — the draft is complete")

    if active_contract(con, wrestler_id, season):
        raise SigningError("already on a roster")
    if is_holdout(con, wrestler_id, pick["brand_id"], season):
        raise SigningError("she is holding out from this brand for the year — "
                           "clear the holdout to reopen talks")

    tier, factor = draft_tier(pick["pick_number"], kind)
    years = draft_years(tier)     # round decides length, not the caller

    base_ask = manager_price(con, wrestler_id) if kind == "manager" else asking_price(con, wrestler_id)
    ask = max(A.MIN_VALUE, int(round(base_ask * factor / 10_000) * 10_000))
    value = max(A.MIN_VALUE, int(annual_value if annual_value is not None else ask))

    fin = {f["brand_id"]: f for f in brand_finances(con, season)}[pick["brand_id"]]
    if value > fin["available"]:
        raise SigningError(
            f"{fin['name']} has ${fin['available']:,} available, this deal costs ${value:,} "
            f"— renegotiate lower, or pass"
        )

    cid = _write_contract(con, wrestler_id, pick["brand_id"], value, years,
                          season, state["current_date"], "draft",
                          perks=perks, signing_bonus=signing_bonus, role=kind)
    con.execute(
        "UPDATE draft_pick SET wrestler_id=?, contract_id=?, picked_on=? WHERE id=?",
        (wrestler_id, cid, state["current_date"], pick["id"]),
    )

    remaining = con.execute(
        "SELECT COUNT(*) FROM draft_pick WHERE draft_id=? AND wrestler_id IS NULL",
        (d["id"],),
    ).fetchone()[0]
    if remaining == 0:
        con.execute("UPDATE draft SET status='complete' WHERE id=?", (d["id"],))
    log_event(con, "signing",
              f"{pick['brand_id']} draft {_wname(con, wrestler_id)} ({kind}) — ${value:,}/yr.",
              pick["brand_id"], "✍️")
    con.commit()

    return {"pick_number": pick["pick_number"], "brand_id": pick["brand_id"],
            "wrestler_id": wrestler_id, "annual_value": value, "years": years,
            "tier": tier, "perks": perks or [], "signing_bonus": signing_bonus,
            "picks_remaining": remaining}


def pass_pick(con: sqlite3.Connection, kind: str = "wrestler") -> dict:
    """Skip the pick on the clock — needed when a brand cannot afford anyone."""
    state = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    d = con.execute(
        "SELECT * FROM draft WHERE season_year=? AND draft_kind=? AND status='active'",
        (state["season_year"], kind)).fetchone()
    if not d:
        raise SigningError("no active draft")
    pick = con.execute(
        "SELECT * FROM draft_pick WHERE draft_id=? AND wrestler_id IS NULL "
        "ORDER BY pick_number LIMIT 1", (d["id"],),
    ).fetchone()
    if not pick:
        raise SigningError("no picks left")
    con.execute("DELETE FROM draft_pick WHERE id=?", (pick["id"],))
    con.commit()
    return {"passed": pick["pick_number"], "brand_id": pick["brand_id"]}


def free_agents(con: sqlite3.Connection, season: int) -> list[int]:
    return [r[0] for r in con.execute(
        """SELECT w.id FROM wrestler w
           WHERE NOT EXISTS (
             SELECT 1 FROM contract c
             WHERE c.wrestler_id = w.id AND c.terminated_on IS NULL
               AND c.start_year <= ? AND c.end_year >= ?)""",
        (season, season),
    )]


# ---------------------------------------------------------------- stables

def _members(con: sqlite3.Connection, table: str, id_col: str, gid: int) -> list[dict]:
    return [dict(r) for r in con.execute(
        f"""SELECT m.wrestler_id, COALESCE(o.display_name, w.name) AS name
            FROM {table} m JOIN wrestler w ON w.id=m.wrestler_id
            LEFT JOIN attribute_override o ON o.wrestler_id=w.id
            WHERE m.{id_col}=? ORDER BY name""", (gid,))]


def list_stables(con: sqlite3.Connection) -> dict:
    teams = []
    for t in con.execute("SELECT * FROM tag_team WHERE active=1 ORDER BY name"):
        teams.append({**dict(t), "members": _members(con, "tag_team_member", "team_id", t["id"])})
    factions = []
    for f in con.execute("SELECT * FROM faction WHERE active=1 ORDER BY name"):
        d = {**dict(f), "members": _members(con, "faction_member", "faction_id", f["id"])}
        if f["leader_id"]:
            lr = con.execute(
                "SELECT COALESCE(o.display_name,w.name) n FROM wrestler w "
                "LEFT JOIN attribute_override o ON o.wrestler_id=w.id WHERE w.id=?",
                (f["leader_id"],)).fetchone()
            d["leader_name"] = lr["n"] if lr else None
        factions.append(d)
    return {"tag_teams": teams, "factions": factions}


def stables_all(con: sqlite3.Connection) -> dict[int, dict]:
    """Every wrestler's teams and factions, in two queries rather than 2N.

    The roster endpoint needs this for all 370 at once; calling stables_of per
    row was 740 statements for what fits in two.
    """
    out: dict[int, dict] = {}

    def slot(wid: int) -> dict:
        return out.setdefault(wid, {"tag_teams": [], "factions": []})

    for r in con.execute(
            """SELECT m.wrestler_id AS wid, t.id, t.name
                 FROM tag_team t JOIN tag_team_member m ON m.team_id = t.id
                WHERE t.active = 1"""):
        slot(r["wid"])["tag_teams"].append({"id": r["id"], "name": r["name"]})

    for r in con.execute(
            """SELECT m.wrestler_id AS wid, f.id, f.name,
                      (f.leader_id = m.wrestler_id) AS is_leader
                 FROM faction f JOIN faction_member m ON m.faction_id = f.id
                WHERE f.active = 1"""):
        slot(r["wid"])["factions"].append(
            {"id": r["id"], "name": r["name"], "is_leader": r["is_leader"]})
    return out


_NO_STABLES = {"tag_teams": [], "factions": []}


def stables_of(con: sqlite3.Connection, wid: int) -> dict:
    """The teams/factions a wrestler belongs to — for her profile."""
    teams = [dict(r) for r in con.execute(
        """SELECT t.id, t.name FROM tag_team t JOIN tag_team_member m ON m.team_id=t.id
           WHERE m.wrestler_id=? AND t.active=1""", (wid,))]
    factions = [dict(r) for r in con.execute(
        """SELECT f.id, f.name, (f.leader_id=?) AS is_leader
           FROM faction f JOIN faction_member m ON m.faction_id=f.id
           WHERE m.wrestler_id=? AND f.active=1""", (wid, wid))]
    return {"tag_teams": teams, "factions": factions}


def create_team(con: sqlite3.Connection, name: str, brand_id: str | None,
                members: list[int]) -> dict:
    cur = con.execute(
        "INSERT INTO tag_team (name, brand_id, formed_on, active) VALUES (?,?,?,1)",
        (name.strip() or "New Team", brand_id, now_iso()[:10]))
    tid = cur.lastrowid
    for wid in dict.fromkeys(members):
        con.execute("INSERT OR IGNORE INTO tag_team_member (team_id, wrestler_id) VALUES (?,?)",
                    (tid, wid))
    con.commit()
    return {"id": tid}


def update_team(con: sqlite3.Connection, tid: int, name: str | None = None,
                brand_id: str | None = "__keep__", members: list[int] | None = None) -> dict:
    if name is not None:
        con.execute("UPDATE tag_team SET name=? WHERE id=?", (name.strip(), tid))
    if brand_id != "__keep__":
        con.execute("UPDATE tag_team SET brand_id=? WHERE id=?", (brand_id, tid))
    if members is not None:
        con.execute("DELETE FROM tag_team_member WHERE team_id=?", (tid,))
        for wid in dict.fromkeys(members):
            con.execute("INSERT OR IGNORE INTO tag_team_member (team_id, wrestler_id) VALUES (?,?)",
                        (tid, wid))
    con.commit()
    return {"id": tid}


def disband_team(con: sqlite3.Connection, tid: int) -> dict:
    con.execute("DELETE FROM tag_team_member WHERE team_id=?", (tid,))
    con.execute("DELETE FROM tag_team WHERE id=?", (tid,))
    con.commit()
    return {"disbanded": tid}


def create_faction(con: sqlite3.Connection, name: str, brand_id: str | None,
                   leader_id: int | None, members: list[int]) -> dict:
    cur = con.execute(
        "INSERT INTO faction (name, brand_id, leader_id, formed_on, active) VALUES (?,?,?,?,1)",
        (name.strip() or "New Faction", brand_id, leader_id, now_iso()[:10]))
    fid = cur.lastrowid
    for wid in dict.fromkeys(list(members) + ([leader_id] if leader_id else [])):
        con.execute("INSERT OR IGNORE INTO faction_member (faction_id, wrestler_id) VALUES (?,?)",
                    (fid, wid))
    con.commit()
    return {"id": fid}


def update_faction(con: sqlite3.Connection, fid: int, name: str | None = None,
                   brand_id: str | None = "__keep__", leader_id: int | None = "__keep__",
                   members: list[int] | None = None) -> dict:
    if name is not None:
        con.execute("UPDATE faction SET name=? WHERE id=?", (name.strip(), fid))
    if brand_id != "__keep__":
        con.execute("UPDATE faction SET brand_id=? WHERE id=?", (brand_id, fid))
    if leader_id != "__keep__":
        con.execute("UPDATE faction SET leader_id=? WHERE id=?", (leader_id, fid))
    if members is not None:
        con.execute("DELETE FROM faction_member WHERE faction_id=?", (fid,))
        keep = list(members)
        lead = con.execute("SELECT leader_id FROM faction WHERE id=?", (fid,)).fetchone()
        if lead and lead[0]:
            keep.append(lead[0])
        for wid in dict.fromkeys(keep):
            con.execute("INSERT OR IGNORE INTO faction_member (faction_id, wrestler_id) VALUES (?,?)",
                        (fid, wid))
    con.commit()
    return {"id": fid}


def disband_faction(con: sqlite3.Connection, fid: int) -> dict:
    con.execute("DELETE FROM faction_member WHERE faction_id=?", (fid,))
    con.execute("DELETE FROM faction WHERE id=?", (fid,))
    con.commit()
    return {"disbanded": fid}


# ---------------------------------------------------------------- feuds

FEUD_HEAT_PER_MATCH = 12      # booking rivals together builds heat
FEUD_HEAT_PER_PROMO = 8
FEUD_BLOWOFF_HEAT = 70        # at/above this, a match is a blow-off (big bonus)


def _wname(con: sqlite3.Connection, wid: int) -> str:
    r = con.execute("SELECT COALESCE(o.display_name, w.name) n FROM wrestler w "
                    "LEFT JOIN attribute_override o ON o.wrestler_id=w.id WHERE w.id=?",
                    (wid,)).fetchone()
    return r["n"] if r else str(wid)


def feud_between(con: sqlite3.Connection, a: int, b: int):
    return con.execute(
        """SELECT * FROM feud WHERE status='active'
           AND ((a_id=? AND b_id=?) OR (a_id=? AND b_id=?))""", (a, b, b, a)).fetchone()


def create_feud(con: sqlite3.Connection, a_id: int, b_id: int,
                brand_id: str | None = None, note: str | None = None) -> dict:
    if a_id == b_id:
        raise SigningError("a feud needs two different wrestlers")
    if feud_between(con, a_id, b_id):
        raise SigningError("those two are already feuding")
    st = con.execute("SELECT game_state.current_date FROM game_state WHERE id=1").fetchone()
    cur = con.execute(
        "INSERT INTO feud (a_id, b_id, brand_id, heat, status, note, started_on) "
        "VALUES (?,?,?,?, 'active', ?, ?)",
        (a_id, b_id, brand_id, 25, note, st["current_date"] if st else now_iso()[:10]))
    log_event(con, "feud", f"{_wname(con, a_id)} and {_wname(con, b_id)} are now feuding.",
              brand_id, "🔥")
    con.commit()
    return {"id": cur.lastrowid}


def bump_feud_heat(con: sqlite3.Connection, feud_id: int, delta: int) -> None:
    con.execute("UPDATE feud SET heat = MAX(0, MIN(100, heat + ?)) WHERE id=?", (delta, feud_id))


def set_feud_heat(con: sqlite3.Connection, feud_id: int, heat: int) -> dict:
    con.execute("UPDATE feud SET heat = MAX(0, MIN(100, ?)) WHERE id=?", (heat, feud_id))
    con.commit()
    return {"id": feud_id, "heat": heat}


def settle_feud(con: sqlite3.Connection, feud_id: int) -> dict:
    st = con.execute("SELECT game_state.current_date FROM game_state WHERE id=1").fetchone()
    f = con.execute("SELECT * FROM feud WHERE id=?", (feud_id,)).fetchone()
    con.execute("UPDATE feud SET status='settled', settled_on=? WHERE id=?",
                (st["current_date"] if st else now_iso()[:10], feud_id))
    if f:
        log_event(con, "feud", f"The {_wname(con, f['a_id'])}–{_wname(con, f['b_id'])} feud is settled.",
                  f["brand_id"], "🤝")
    con.commit()
    return {"settled": feud_id}


def list_feuds(con: sqlite3.Connection, status: str | None = "active") -> list[dict]:
    q = "SELECT * FROM feud"
    args: tuple = ()
    if status:
        q += " WHERE status=?"; args = (status,)
    q += " ORDER BY heat DESC, id DESC"
    out = []
    for f in con.execute(q, args):
        d = dict(f)
        d["a_name"] = _wname(con, f["a_id"])
        d["b_name"] = _wname(con, f["b_id"])
        out.append(d)
    return out


# ---------------------------------------------------------------- proposals (AI opponent)
#
# The AI opponent never acts directly: it files PROPOSALS the GM approves or
# rejects. Approving applies the real action; rejecting discards it. This is what
# makes "even against the AI, I approve everything" true.

def create_proposal(con: sqlite3.Connection, kind: str, summary: str,
                    payload: dict, brand_id: str | None = None) -> int:
    import json
    st = con.execute("SELECT game_state.current_date FROM game_state WHERE id=1").fetchone()
    cur = con.execute(
        "INSERT INTO proposal (kind, brand_id, summary, payload, created_on) VALUES (?,?,?,?,?)",
        (kind, brand_id, summary, json.dumps(payload), st["current_date"] if st else now_iso()[:10]))
    con.commit()
    return cur.lastrowid


def list_proposals(con: sqlite3.Connection, status: str = "pending") -> list[dict]:
    import json
    out = []
    for p in con.execute("SELECT * FROM proposal WHERE status=? ORDER BY id DESC", (status,)):
        d = dict(p)
        try:
            d["payload"] = json.loads(p["payload"])
        except Exception:
            d["payload"] = {}
        out.append(d)
    return out


def reject_proposal(con: sqlite3.Connection, pid: int) -> dict:
    con.execute("UPDATE proposal SET status='rejected' WHERE id=?", (pid,))
    con.commit()
    return {"rejected": pid}


def approve_proposal(con: sqlite3.Connection, pid: int) -> dict:
    """Apply a pending AI proposal. Import sim lazily to avoid a cycle."""
    import json
    p = con.execute("SELECT * FROM proposal WHERE id=? AND status='pending'", (pid,)).fetchone()
    if not p:
        raise SigningError("no such pending proposal")
    payload = json.loads(p["payload"])
    result: dict = {}
    if p["kind"] == "draft_pick":
        result = make_pick(con, payload["wrestler_id"], None,
                           payload.get("annual_value"), payload.get("kind", "wrestler"),
                           perks=payload.get("perks", []), signing_bonus=payload.get("signing_bonus", 0))
    elif p["kind"] == "show":
        import sim
        result = sim.run_show(con, payload["brand_id"], payload["name"], payload["card"],
                              is_ppv=payload.get("is_ppv", False), ppv_name=payload.get("ppv_name"),
                              promo_card=payload.get("promos") or [])
    elif p["kind"] == "trade":
        result = resolve_trade(con, payload["offer_id"], True)
    else:
        raise SigningError(f"unknown proposal kind {p['kind']}")
    con.execute("UPDATE proposal SET status='approved' WHERE id=?", (pid,))
    con.commit()
    return {"approved": pid, "result": result}


# ---------------------------------------------------------------- AI opponent

def ai_brand(con: sqlite3.Connection) -> str | None:
    b = get_setting(con, "ai_brand")
    return b if b in {x[0] for x in BRANDS} else None


def propose_ai_pick(con: sqlite3.Connection) -> dict:
    """The AI drafts for its brand — as a PROPOSAL the GM must approve."""
    ai = ai_brand(con)
    if not ai:
        raise SigningError("no AI brand is set — assign one on the Home tab")
    st = con.execute("SELECT season_year FROM game_state WHERE id=1").fetchone()
    season = st["season_year"]

    kind = None
    for k in ("wrestler", "manager"):
        if con.execute("SELECT 1 FROM draft WHERE season_year=? AND draft_kind=? AND status='active'",
                       (season, k)).fetchone():
            kind = k
            break
    if not kind:
        raise SigningError("no active draft for the AI to pick in")

    board = draft_board(con, kind)
    oc = board["on_the_clock"]
    if not oc:
        raise SigningError("the draft is complete")
    if oc["brand_id"] != ai:
        raise SigningError(f"it's {oc['brand_id']}'s pick, not the AI's")
    if con.execute("SELECT 1 FROM proposal WHERE kind='draft_pick' AND status='pending'").fetchone():
        raise SigningError("there's already a pending AI pick — review it first")

    fin = {f["brand_id"]: f for f in brand_finances(con, season)}[ai]
    factor = oc["tier_factor"]
    ach = achievement_inputs(con)
    best = None
    for wid in board["available"]:
        # One read per wrestler, not two: the draft board can be 250 long and the
        # value and the overall come out of the same call.
        eff = effective_attributes(con, wid, ach.get(wid))
        base = manager_price(con, wid) if kind == "manager" else eff["value"]
        price = max(A.MIN_VALUE, int(round(base * factor / 10_000) * 10_000))
        if price <= fin["available"]:
            ov = eff["overall"]
            if best is None or ov > best[1]:
                best = (wid, ov, price)
    if not best:
        raise SigningError("the AI cannot afford anyone — pass the pick for it manually")
    wid, ov, price = best
    summary = f"{ai} (AI) wants to draft {_wname(con, wid)} — OVR {ov}, ${price:,}/yr"
    pid = create_proposal(con, "draft_pick", summary,
                          {"wrestler_id": wid, "annual_value": price, "kind": kind,
                           "perks": [], "signing_bonus": 0}, ai)
    return {"proposal_id": pid, "summary": summary}


def propose_ai_show(con: sqlite3.Connection, is_ppv: bool = False) -> dict:
    """The AI books its brand's card — as a PROPOSAL to approve."""
    ai = ai_brand(con)
    if not ai:
        raise SigningError("no AI brand is set")
    import sim
    import autobook
    # The proposal has to be a full SHOW, not just matches: the format is four
    # matches and two promos on television and six on a pay-per-view, and an
    # approval that ran half a card would quietly break it.
    kind = "ppv" if is_ppv else "tv"
    fmt = autobook.SHOW_FORMATS[kind]
    card = sim.auto_card(con, ai, fmt["matches"], kind)
    promo_card = sim.auto_promos(con, ai, fmt["promos"], kind)
    name = calendar(con).get("ppv") if is_ppv else f"{ai} show"
    summary = (f"{ai} (AI) proposes a {len(card)}-match, {len(promo_card)}-promo card"
               + (" for the PPV" if is_ppv else ""))
    pid = create_proposal(con, "show", summary,
                          {"brand_id": ai, "name": name, "card": card,
                           "promos": promo_card,
                           "is_ppv": is_ppv, "ppv_name": name if is_ppv else None}, ai)
    return {"proposal_id": pid, "summary": summary}


def ai_monthly(con: sqlite3.Connection) -> dict:
    """Called when the calendar advances a month: the AI brand files whatever
    proposals fit the moment, for the GM to approve. Every generator is tried
    defensively — a step that doesn't apply is simply skipped."""
    ai = ai_brand(con)
    if not ai:
        return {"ai_brand": None, "proposals": 0}

    pending = {p["kind"] for p in list_proposals(con, "pending")}
    made = 0

    # 1) If a draft is live and the AI is on the clock, it wants a pick.
    if "draft_pick" not in pending:
        try:
            propose_ai_pick(con); made += 1
        except SigningError:
            pass

    # 2) Otherwise book its monthly show.
    if "show" not in pending:
        try:
            propose_ai_show(con); made += 1
        except (SigningError, ValueError):
            pass

    # 3) Occasionally float a trade (roughly a third of months, deterministic).
    # SELECT * — `current_date` is a SQLite keyword, so naming it explicitly
    # returns today's REAL date rather than the column, and this gated the AI's
    # trades on the wall-clock month instead of the game month.
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    month = int(st["current_date"][5:7]) if st else 1
    if month % 3 == 0 and not con.execute(
            "SELECT 1 FROM trade_offer WHERE status='pending'").fetchone():
        try:
            propose_ai_trade(con); made += 1
        except SigningError:
            pass

    if made:
        log_event(con, "ai", f"{ai} (AI) filed {made} proposal(s) for your approval.", ai, "🤖")
    return {"ai_brand": ai, "proposals": made}


def propose_ai_trade(con: sqlite3.Connection) -> dict:
    """The AI offers a straight, value-matched swap — a normal pending trade_offer."""
    ai = ai_brand(con)
    if not ai:
        raise SigningError("no AI brand is set")
    human = "SMACKDOWN" if ai == "RAW" else "RAW"
    season = con.execute("SELECT season_year FROM game_state WHERE id=1").fetchone()["season_year"]

    ach = achievement_inputs(con)

    def value_of(w):
        return effective_attributes(con, w, ach.get(w))["value"]

    def roster(b):
        ids = [r[0] for r in con.execute(
            """SELECT wrestler_id FROM contract WHERE brand_id=? AND terminated_on IS NULL
               AND start_year<=? AND end_year>=? AND role='wrestler'""", (b, season, season))]
        return sorted(ids, key=value_of)

    a_ros, h_ros = roster(ai), roster(human)
    if len(a_ros) < 3 or len(h_ros) < 3:
        raise SigningError("not enough signed wrestlers on both brands for a trade")
    give = a_ros[len(a_ros) // 2]
    gv = value_of(give)
    want = min(h_ros, key=lambda w: abs(value_of(w) - gv))
    assets = [{"side": ai, "kind": "wrestler", "wrestler_id": give},
              {"side": human, "kind": "wrestler", "wrestler_id": want}]
    offer = propose_trade(con, ai, human, assets, note=f"{ai} (AI) proposes a swap")
    log_event(con, "trade", f"{ai} (AI) offers a trade — review it in Trades.", ai, "🔁")
    return {"offer_id": offer["offer_id"],
            "summary": f"{ai} offers {_wname(con, give)} for your {_wname(con, want)}"}


# ---------------------------------------------------------------- year-end awards

# What the sim can nominate automatically, and how many nominees to surface.
AWARD_NOMINEES = 3


def generate_nominations(con: sqlite3.Connection, season: int) -> int:
    """Auto-nominate the year's bests for the GM to crown. Idempotent per season."""
    con.execute("DELETE FROM award_nomination WHERE season_year=? AND status='nominated'", (season,))
    n = 0

    def add(kind, wid, detail, score):
        nonlocal n
        con.execute(
            "INSERT INTO award_nomination (season_year, kind, wrestler_id, detail, score) "
            "VALUES (?,?,?,?,?)", (season, kind, wid, detail, score))
        n += 1

    yr = str(season)
    # Match of the Year — top-quality matches this season.
    for m in con.execute(
        """SELECT m.id, m.quality, m.stipulation FROM sim_match m JOIN show s ON s.id=m.show_id
           WHERE substr(s.held_on,1,4)=? ORDER BY m.quality DESC LIMIT ?""", (yr, AWARD_NOMINEES)):
        parts = [r["wrestler_id"] for r in con.execute(
            "SELECT wrestler_id FROM sim_match_participant WHERE match_id=?", (m["id"],))]
        winner = con.execute(
            "SELECT wrestler_id FROM sim_match_participant WHERE match_id=? AND is_winner=1 LIMIT 1",
            (m["id"],)).fetchone()
        # A big multi-woman match is named by WHAT IT WAS, not by four of the
        # thirty people in it. Listing "A vs B vs C vs D" for a Royal Rumble reads
        # as a fatal four-way and hides the match that actually happened.
        if len(parts) > 4 and m["stipulation"]:
            names = m["stipulation"]
            if winner:
                names = f"{_wname(con, winner['wrestler_id'])} won the {names}"
        else:
            names = " vs ".join(_wname(con, w) for w in parts[:4])
        add("match_of_year", winner["wrestler_id"] if winner else (parts[0] if parts else None),
            f"{names} ★{round((m['quality'] or 0)/20,1)}", m["quality"])

    # Feud of the Year — hottest rivalries.
    for f in con.execute(
        "SELECT * FROM feud ORDER BY heat DESC LIMIT ?", (AWARD_NOMINEES,)):
        add("feud_of_year", f["a_id"],
            f"{_wname(con, f['a_id'])} vs {_wname(con, f['b_id'])} (heat {f['heat']})", f["heat"])

    # Rookie of the Year — this season's draft class, by sim wins.
    for r in con.execute(
        """SELECT w.id, COALESCE(s.sim_wins,0) wins, COALESCE(s.sim_matches,0) m
           FROM wrestler w
           JOIN attributes a ON a.wrestler_id=w.id
           LEFT JOIN attribute_override o ON o.wrestler_id=w.id
           LEFT JOIN wrestler_state s ON s.wrestler_id=w.id
           WHERE COALESCE(o.draft_class, ?) = ? AND COALESCE(s.sim_matches,0) > 0
           ORDER BY wins DESC, m DESC LIMIT ?""", (RESET_YEAR, season, AWARD_NOMINEES)):
        add("rookie_of_year", r["id"], f"{_wname(con, r['id'])} — {r['wins']}W in {r['m']} matches", r["wins"])

    # Woman of the Year — best overall in-ring season (wins + title reigns won this year).
    for r in con.execute(
        """SELECT w.id, COALESCE(s.sim_wins,0) wins,
                  (SELECT COUNT(*) FROM game_title_reign gr WHERE gr.wrestler_id=w.id
                     AND substr(gr.won_on,1,4)=?) reigns
           FROM wrestler w LEFT JOIN wrestler_state s ON s.wrestler_id=w.id
           WHERE COALESCE(s.sim_matches,0) > 0
           ORDER BY (COALESCE(s.sim_wins,0) + 8*(SELECT COUNT(*) FROM game_title_reign gr
                     WHERE gr.wrestler_id=w.id AND substr(gr.won_on,1,4)=?)) DESC
           LIMIT ?""", (yr, yr, AWARD_NOMINEES)):
        add("woman_of_year", r["id"], f"{_wname(con, r['id'])} — {r['wins']}W, {r['reigns']} title win(s)",
            r["wins"] + 8 * r["reigns"])

    # Most Improved — the biggest APPROVED rating gains of the season.
    #
    # The only award with a genuinely objective source: `rating_change` records
    # every progression the GM approved, so "who got better this year" is already
    # written down. Nominating on anything else would be guessing at it.
    for r in con.execute(
        """SELECT wrestler_id, SUM(to_value - from_value) gain
             FROM rating_change
            WHERE season_year=? AND status='approved' AND to_value > from_value
            GROUP BY wrestler_id
            ORDER BY gain DESC LIMIT ?""", (season, AWARD_NOMINEES)):
        add("most_improved", r["wrestler_id"],
            f"{_wname(con, r['wrestler_id'])} — +{r['gain']} across her ratings", r["gain"])

    # Babe of the Year — on Looks and Personal, which are the GM's own numbers.
    #
    # Deliberately circular, and that is the honest way to do it: this award has
    # never been about anything measurable, so it is scored on the two categories
    # the GM owns outright rather than dressed up as a performance metric. Only
    # wrestlers who actually worked are eligible, so it cannot go to someone who
    # spent the year off television.
    for r in con.execute(
        """SELECT w.id, COALESCE(o.looks, a.looks) lk, COALESCE(o.personal, a.personal) pe
             FROM wrestler w
             JOIN attributes a ON a.wrestler_id = w.id
             LEFT JOIN attribute_override o ON o.wrestler_id = w.id
             LEFT JOIN wrestler_state s ON s.wrestler_id = w.id
            WHERE COALESCE(s.sim_matches, 0) > 0
            ORDER BY (COALESCE(o.looks, a.looks) + COALESCE(o.personal, a.personal)) DESC,
                     w.id LIMIT ?""", (AWARD_NOMINEES,)):
        add("babe_of_year", r["id"],
            f"{_wname(con, r['id'])} — looks {r['lk']}, personal {r['pe']}",
            r["lk"] + r["pe"])

    # A Slammy for the year's most talked-about act — momentum plus feud heat,
    # which between them are the closest thing the sim has to "buzz".
    for r in con.execute(
        """SELECT w.id, COALESCE(s.momentum, 50) mom,
                  COALESCE((SELECT MAX(f.heat) FROM feud f
                             WHERE f.a_id = w.id OR f.b_id = w.id), 0) heat
             FROM wrestler w
             LEFT JOIN wrestler_state s ON s.wrestler_id = w.id
            WHERE COALESCE(s.sim_matches, 0) > 0
            ORDER BY (COALESCE(s.momentum, 50)
                      + COALESCE((SELECT MAX(f.heat) FROM feud f
                                   WHERE f.a_id = w.id OR f.b_id = w.id), 0)) DESC
            LIMIT ?""", (AWARD_NOMINEES,)):
        add("slammy", r["id"],
            f"{_wname(con, r['id'])} — momentum {r['mom']}, feud heat {r['heat']}",
            r["mom"] + r["heat"])

    con.commit()
    if n:
        log_event(con, "award", f"Year-end award nominations are in for {season}.", None, "🏆")
    return n


def list_nominations(con: sqlite3.Connection, season: int | None = None) -> list[dict]:
    q = "SELECT * FROM award_nomination"
    args: tuple = ()
    if season is not None:
        q += " WHERE season_year=?"; args = (season,)
    q += " ORDER BY season_year DESC, kind, score DESC"
    out = []
    for r in con.execute(q, args):
        d = dict(r)
        d["name"] = _wname(con, r["wrestler_id"]) if r["wrestler_id"] else None
        d["label"] = ACCOLADES.get(r["kind"], (r["kind"],))[0]
        out.append(d)
    return out


def crown_award(con: sqlite3.Connection, nomination_id: int) -> dict:
    """The GM's pick wins — award it (paying the bonus) and clear the rest of that kind."""
    nom = con.execute("SELECT * FROM award_nomination WHERE id=?", (nomination_id,)).fetchone()
    if not nom:
        raise SigningError("no such nomination")
    con.execute("UPDATE award_nomination SET status='rejected' WHERE season_year=? AND kind=? AND status='nominated'",
                (nom["season_year"], nom["kind"]))
    con.execute("UPDATE award_nomination SET status='won' WHERE id=?", (nomination_id,))
    res = {}
    if nom["wrestler_id"]:
        res = award(con, nom["wrestler_id"], nom["kind"], nom["season_year"], nom["detail"])
        log_event(con, "award", f"{_wname(con, nom['wrestler_id'])} wins {ACCOLADES.get(nom['kind'],(nom['kind'],))[0]} {nom['season_year']}.",
                  None, "🏆")
    con.commit()
    return {"crowned": nomination_id, **res}


# ---------------------------------------------------------------- streaks

def streaks(con: sqlite3.Connection) -> dict[int, int]:
    """Current win(+)/loss(-) streak per wrestler, from most recent results."""
    seen: dict[int, int] = {}
    done: set[int] = set()
    for r in con.execute(
        """SELECT p.wrestler_id, p.is_winner, m.finish
           FROM sim_match_participant p JOIN sim_match m ON m.id=p.match_id
           ORDER BY m.id DESC"""):
        wid = r["wrestler_id"]
        if wid in done or r["finish"] == "draw":
            continue
        won = r["is_winner"] == 1
        cur = seen.get(wid, 0)
        if cur == 0:
            seen[wid] = 1 if won else -1
        elif (cur > 0) == won:
            seen[wid] = cur + (1 if won else -1)
        else:
            done.add(wid)   # streak broken; keep what we have
    return seen


# ---------------------------------------------------------------- calendar & PPVs

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

# Each YEAR is a SEASON that BUILDS to WrestleMania in December, so the slate is
# reordered from the historical calendar: WrestleMania is the December finale and
# the Royal Rumble sits in November, the go-home show whose winner headlines it.
# The rest fill the road there, one marquee show on the last Sunday of each month.
PPV_SCHEDULE = {
    1: "New Year's Revolution", 2: "No Way Out", 3: "Backlash", 4: "Judgment Day",
    5: "Bad Blood", 6: "Queen of the Ring", 7: "Fully Loaded", 8: "SummerSlam",
    9: "Unforgiven", 10: "No Mercy", 11: "Royal Rumble", 12: "WrestleMania",
}


def ppv_for_month(month: int, year: int) -> str | None:
    name = PPV_SCHEDULE.get(month)
    return f"{name} {year}" if name else None


def _last_sunday(year: int, month: int) -> int:
    """Day-of-month of the last Sunday — when the pay-per-view lands."""
    d = date(year, month, _days_in_month(year, month))
    return d.day - ((d.weekday() - 6) % 7)


def _days_in_month(year: int, month: int) -> int:
    nxt = date(year + (month == 12), (month % 12) + 1, 1)
    return (nxt - date(year, month, 1)).days


SNME_PER_MONTH = 2


def month_snme(seed: int, year: int, month: int) -> list[int]:
    """The two Saturday Night's Main Event dates in a month.

    Two a month rather than one a season, so the calendar has a big Saturday
    every fortnight to build television toward — the pay-per-view is no longer
    the only date on the sheet that matters.

    Deterministic from the save seed, the year and the month, so the calendar is
    stable across reloads and different from month to month. They are spread
    apart on purpose (one in each half of the month) rather than drawn at random,
    which would happily put both on consecutive weekends.
    """
    import random
    saturdays = [d for d in range(1, _days_in_month(year, month) + 1)
                 if date(year, month, d).weekday() == 5]
    if len(saturdays) <= SNME_PER_MONTH:
        return saturdays
    rng = random.Random(seed * 7919 + year * 100 + month)
    mid = len(saturdays) // 2
    return sorted([rng.choice(saturdays[:mid]), rng.choice(saturdays[mid:])])


WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def month_shows(seed: int, year: int, month: int) -> list[dict]:
    """Every show due in a month: Raw each Monday, SmackDown each Friday, two
    Saturday Night's Main Events, and the pay-per-view on the last Sunday."""
    ppv_day = _last_sunday(year, month)
    snme_days = set(month_snme(seed, year, month))
    shows = []
    for day in range(1, _days_in_month(year, month) + 1):
        wd = date(year, month, day).weekday()
        if wd == 6 and day == ppv_day:
            shows.append({"day": day, "weekday": "Sun", "type": "PPV",
                          "name": ppv_for_month(month, year)})
        elif day in snme_days:
            shows.append({"day": day, "weekday": "Sat", "type": "SNME",
                          "name": "Saturday Night's Main Event"})
        elif wd == 0:
            shows.append({"day": day, "weekday": "Mon", "type": "RAW", "name": "Raw"})
        elif wd == 4:
            shows.append({"day": day, "weekday": "Fri", "type": "SMACKDOWN",
                          "name": "SmackDown"})
    return shows


def calendar(con: sqlite3.Connection) -> dict:
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if not st:
        return {"active": False}
    d = date.fromisoformat(st["current_date"])
    year, seed = st["season_year"], st["rng_seed"]
    snme_days = month_snme(seed, year, d.month)
    first_weekday = date(year, d.month, 1).weekday()   # 0=Mon .. 6=Sun
    return {
        "active": True, "date": st["current_date"], "season_year": year,
        "month": d.month, "month_name": MONTHS[d.month - 1],
        "ppv": ppv_for_month(d.month, year),
        "ppv_day": _last_sunday(year, d.month),
        "days_in_month": _days_in_month(year, d.month),
        "first_weekday": first_weekday,
        "shows": month_shows(seed, year, d.month),
        "snme_days": snme_days,
        "is_finale": d.month == 12,     # WrestleMania month ends the season
        "schedule": [{"month": m, "month_name": MONTHS[m - 1], "name": PPV_SCHEDULE[m]}
                     for m in range(1, 13)],
    }


# --------------------------------------------------------------- perk promises
#
# A perk negotiated into a contract is a PROMISE, checked against what actually
# happened in the ring that season. Break a promise and her morale takes a hit
# at the season rollover — so trading the spotlight for a lower salary and then
# not delivering it has a real cost.
LIGHT_SCHEDULE_MAX = 8        # "reduced schedule" broken if worked more than this
CREATIVE_CLEAN_LOSS_MAX = 4   # "creative control" broken if beaten clean this often
PERK_BREAK_MORALE = 8         # morale lost per broken promise (capped per wrestler)


def _perks_of(perks_json: str | None) -> list[str]:
    import json
    if not perks_json:
        return []
    try:
        return [p for p in json.loads(perks_json) if p]
    except Exception:
        return []


def perk_status(con: sqlite3.Connection, wrestler_id: int, season: int) -> list[dict]:
    """How each promised perk is tracking against this season's booking.

    Returns one row per perk: whether it is currently being delivered and a
    short human detail. Used live on the profile and at season end to dock morale
    for promises that were not kept.
    """
    import negotiate
    c = active_contract(con, wrestler_id, season)
    if not c:
        return []
    perks = _perks_of(c["perks"])
    if not perks:
        return []

    rows = con.execute(
        """SELECT m.slot, m.title_id, m.finish, p.is_winner,
                  (SELECT MAX(mm.slot) FROM sim_match mm WHERE mm.show_id=m.show_id) top_slot
           FROM sim_match_participant p
           JOIN sim_match m ON m.id = p.match_id
           JOIN show s ON s.id = m.show_id
           WHERE p.wrestler_id=? AND substr(s.held_on,1,4)=?""",
        (wrestler_id, str(season))).fetchall()
    n = len(rows)
    main_events = sum(1 for r in rows if r["slot"] == r["top_slot"])
    title_shots = sum(1 for r in rows if r["title_id"])
    clean_losses = sum(1 for r in rows
                       if not r["is_winner"] and r["finish"] in ("pinfall", "submission"))

    out = []
    for p in perks:
        if p == "main_event":
            delivered = main_events >= 1
            detail = f"{main_events} main event{'s' if main_events != 1 else ''} so far"
        elif p == "title_shot":
            delivered = title_shots >= 1
            detail = f"{title_shots} title shot{'s' if title_shots != 1 else ''} so far"
        elif p == "light_schedule":
            delivered = n <= LIGHT_SCHEDULE_MAX
            detail = f"worked {n} match{'es' if n != 1 else ''} (cap {LIGHT_SCHEDULE_MAX})"
        elif p == "creative":
            delivered = clean_losses < CREATIVE_CLEAN_LOSS_MAX
            detail = f"beaten clean {clean_losses}× (limit {CREATIVE_CLEAN_LOSS_MAX})"
        else:
            continue
        out.append({"perk": p, "label": negotiate.PERKS.get(p, (p,))[0],
                    "delivered": delivered, "detail": detail})
    return out


def evaluate_perk_promises(con: sqlite3.Connection, season: int) -> list[dict]:
    """At season's end, dock morale for every promise a brand failed to keep."""
    broken = []
    for c in con.execute(
        """SELECT wrestler_id, perks FROM contract
           WHERE terminated_on IS NULL AND perks IS NOT NULL
             AND start_year <= ? AND end_year >= ?""", (season, season)):
        st = perk_status(con, c["wrestler_id"], season)
        missed = [s for s in st if not s["delivered"]]
        if not missed:
            continue
        penalty = min(20, PERK_BREAK_MORALE * len(missed))
        con.execute("UPDATE wrestler_state SET morale = MAX(0, MIN(100, morale - ?)) "
                    "WHERE wrestler_id=?", (penalty, c["wrestler_id"]))
        nm = con.execute("SELECT COALESCE(o.display_name, w.name) n FROM wrestler w "
                         "LEFT JOIN attribute_override o ON o.wrestler_id=w.id WHERE w.id=?",
                         (c["wrestler_id"],)).fetchone()
        broken.append({"wrestler_id": c["wrestler_id"], "name": nm["n"] if nm else "?",
                       "broken": [s["label"] for s in missed], "morale_lost": penalty})
    return broken


def _accrue_earnings(con: sqlite3.Connection, season: int) -> None:
    """Bank each active contract's salary for the season just completed."""
    for r in con.execute(
        """SELECT wrestler_id, annual_value FROM contract
           WHERE terminated_on IS NULL AND start_year <= ? AND end_year >= ?""",
        (season, season)):
        con.execute("UPDATE wrestler_state SET career_earnings = career_earnings + ? "
                    "WHERE wrestler_id=?", (r["annual_value"], r["wrestler_id"]))


def advance_month(con: sqlite3.Connection) -> dict:
    """Advance the calendar one month. Rolling past December ends the season."""
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if st is None:
        raise SigningError("no active save")
    d = date.fromisoformat(st["current_date"])
    if d.month == 12:
        return advance_season(con)
    nd = date(d.year, d.month + 1, 1)
    con.execute("UPDATE game_state SET current_date=? WHERE id=1", (nd.isoformat(),))
    con.commit()
    ai = ai_monthly(con)
    return {"season_year": st["season_year"], "date": nd.isoformat(),
            "month": nd.month, "month_name": MONTHS[nd.month - 1],
            "ppv": ppv_for_month(nd.month, st["season_year"]), "rolled_season": False,
            "ai": ai}


def advance_season(con: sqlite3.Connection) -> dict:
    """Roll to next year: banks the season's earnings, budgets grow, expired
    contracts lapse, holdouts and season-role pins reset, everyone ages a year."""
    state = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    old_season = state["season_year"]
    new_season = old_season + 1
    new_date = f"{new_season}-01-01"

    _accrue_earnings(con, old_season)

    # Grade the season's promises before the calendar turns — undelivered perks
    # cost morale.
    broken_promises = evaluate_perk_promises(con, old_season)

    expired = con.execute(
        "SELECT COUNT(*) FROM contract WHERE terminated_on IS NULL AND end_year < ?",
        (new_season,),
    ).fetchone()[0]

    # Roll last year's leftovers forward: anyone whose draft class had come due
    # (draft_class <= the season just ended) but who went UNsigned all year — not
    # drafted and not picked up as a free agent — moves into the new season's
    # class so she stays eligible. Wrestlers signed this year keep their class
    # frozen, and future classes (draft_class > old_season) are untouched.
    leftovers = [r[0] for r in con.execute(
        """SELECT w.id FROM wrestler w
           LEFT JOIN attribute_override o ON o.wrestler_id = w.id
           WHERE COALESCE(o.draft_class, ?) <= ?
             AND NOT EXISTS (SELECT 1 FROM contract c WHERE c.wrestler_id = w.id
                   AND c.terminated_on IS NULL AND c.start_year <= ? AND c.end_year >= ?)
             AND NOT EXISTS (SELECT 1 FROM excluded_wrestler x WHERE x.wrestler_id = w.id)""",
        (RESET_YEAR, old_season, old_season, old_season))]
    for wid in leftovers:
        con.execute(
            """INSERT INTO attribute_override (wrestler_id, draft_class, updated_at)
               VALUES (?,?,?) ON CONFLICT(wrestler_id) DO UPDATE SET
                 draft_class = excluded.draft_class, updated_at = excluded.updated_at""",
            (wid, new_season, now_iso()))

    con.execute("UPDATE wrestler SET age_at_reset = age_at_reset + 1 "
                "WHERE age_at_reset IS NOT NULL")
    con.execute("UPDATE attribute_override SET age_at_reset = age_at_reset + 1 "
                "WHERE age_at_reset IS NOT NULL")
    # A new year wipes the slate: last year's holdouts and role pins no longer bind.
    con.execute("DELETE FROM holdout WHERE season_year=?", (old_season,))
    con.execute("DELETE FROM season_role WHERE season_year=?", (old_season,))
    con.execute("UPDATE game_state SET season_year=?, current_date=? WHERE id=1",
                (new_season, new_date))

    for bid, _, _ in BRANDS:
        ensure_budget(con, bid, new_season)

    # Year-end awards: nominate the season's bests for the GM to crown.
    nominations = generate_nominations(con, old_season)
    # Freeze the season that just ended as cards, before anything else can move
    # a rating. This is the moment the snapshot has to happen — a card minted
    # later would be describing a roster that had already changed.
    import cards  # noqa: PLC0415 — imported here to keep game.py standalone
    minted = cards.snapshot(con, old_season)
    log_event(con, "season", f"Season {old_season} is in the books — welcome to {new_season}.",
              None, "📅")
    if expired:
        log_event(con, "contract", f"{expired} contract(s) expired into free agency / Alumni.", None, "⏳")
    if leftovers:
        log_event(con, "draft", f"{len(leftovers)} undrafted talent(s) rolled into the {new_season} draft class.",
                  None, "📋")

    con.commit()
    ai = ai_monthly(con)
    return {"season_year": new_season, "contracts_expired": expired,
            "date": new_date, "month": 1, "month_name": "January",
            "ppv": ppv_for_month(1, new_season), "rolled_season": True,
            "rolled_forward": len(leftovers),
            "broken_promises": broken_promises, "award_nominations": nominations,
            "cards_minted": minted.get("minted", 0),
            "ai": ai}
