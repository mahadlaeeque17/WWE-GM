"""Phase 7 — rankings and progression.

Three systems that all read the same thing (what actually happened on the shows)
and all write nothing the GM has not seen:

  POWER 25       A weekly, cross-brand top 25 in the style of the old WWE.com
                 Power 25 — rank, last week, movement, and a one-line reason.
                 Each week is a persisted ISSUE, because "last week" and the
                 movement arrows are history, not something you can recompute.

  CONTENDERS     A per-title ladder of who has earned a shot, respecting the
                 belt's brand, tier, team size and weight limit. Rank 1 is the
                 #1 contender unless the GM has pinned someone by hand.

  PROGRESSION    Season-end growth and regression of charisma / popularity /
                 looks, from what she did that year. Emitted as SUGGESTIONS
                 only: nothing touches a rating until the GM approves it.

Deliberate design notes
-----------------------

*Experience is not in the progression engine.* It is already earned in the sim
(`30·log10(matches+1)`) and updates itself. The three categories that were
frozen forever at their seeded value are charisma, popularity and looks — those
are the actual gap, so those are what moves.

*Approved changes are written to `attribute_override`.* That is the layer
`normalize.py` never touches, and it is honest: an approved progression IS a
user-decided value, so it shows with the ✎ marker like any hand edit.

*Nothing here is random.* Same save, same shows, same numbers — matching the
rule the sim already follows. The AI layer is never consulted; the blurbs are
built from facts (records, titles, movement), not generated prose.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import game

# ---------------------------------------------------------------- schema

SCHEMA = """
-- One Power 25 issue per week. week_of is the show date the issue covers.
CREATE TABLE IF NOT EXISTS power_issue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    week_of     TEXT NOT NULL UNIQUE,
    season_year INTEGER NOT NULL,
    created_on  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS power_entry (
    issue_id    INTEGER NOT NULL REFERENCES power_issue(id) ON DELETE CASCADE,
    rank_no     INTEGER NOT NULL,
    wrestler_id INTEGER NOT NULL REFERENCES wrestler(id),
    score       REAL NOT NULL,
    last_week   INTEGER,                 -- NULL = NR, not ranked last week
    note        TEXT,
    PRIMARY KEY (issue_id, rank_no)
);
-- Per-title contender ladder, snapshotted alongside each Power 25 issue.
CREATE TABLE IF NOT EXISTS contender_entry (
    issue_id    INTEGER NOT NULL REFERENCES power_issue(id) ON DELETE CASCADE,
    title_id    INTEGER NOT NULL REFERENCES game_title(id),
    rank_no     INTEGER NOT NULL,
    wrestler_id INTEGER NOT NULL REFERENCES wrestler(id),
    score       REAL NOT NULL,
    last_week   INTEGER,
    note        TEXT,
    PRIMARY KEY (issue_id, title_id, rank_no)
);
-- The GM can pin a #1 contender by hand; the pin outranks the computed ladder.
CREATE TABLE IF NOT EXISTS contender_lock (
    title_id    INTEGER PRIMARY KEY REFERENCES game_title(id),
    wrestler_id INTEGER REFERENCES wrestler(id),
    locked_on   TEXT
);
-- Rating progression. NOTHING is applied to a rating until status='approved'.
CREATE TABLE IF NOT EXISTS rating_change (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    season_year  INTEGER NOT NULL,
    wrestler_id  INTEGER NOT NULL REFERENCES wrestler(id),
    category     TEXT NOT NULL,          -- charisma | popularity | looks
    from_value   INTEGER NOT NULL,
    to_value     INTEGER NOT NULL,       -- what gets applied; the GM may edit it
    suggested    INTEGER NOT NULL,       -- what the engine originally proposed
    reason       TEXT NOT NULL,
    score        REAL,
    status       TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | rejected
    created_on   TEXT NOT NULL,
    resolved_on  TEXT,
    UNIQUE (season_year, wrestler_id, category)
);
CREATE INDEX IF NOT EXISTS idx_power_entry_w ON power_entry(wrestler_id);
CREATE INDEX IF NOT EXISTS idx_rating_change_status ON rating_change(status, season_year);
"""


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    con.commit()


# ---------------------------------------------------------------- tuning

# How far back a Power 25 issue looks. Five weeks: long enough that one bad
# night does not erase a month, short enough that the board actually moves.
WINDOW_DAYS = 35

POWER_SIZE = 25
CONTENDER_SIZE = 10

# What a belt is worth to your standing while you are holding it, before it is
# scaled by the belt's live prestige.
TIER_WEIGHT = {
    "world": 22.0, "secondary": 12.0, "tag": 10.0,
    "cruiserweight": 9.0, "hardcore": 8.0, "manager": 8.0,
}

# Per-match points before slot / PPV / recency multipliers.
WIN_POINTS = 10.0
DRAW_POINTS = 2.0
LOSS_POINTS = -4.0
LOSS_TO_CHAMPION_POINTS = -1.0      # losing to the champion barely hurts
TITLE_MATCH_BONUS = 6.0
TITLE_WON_BONUS = 25.0
TITLE_RETAINED_BONUS = 12.0

MAIN_EVENT_MULT = 1.6
SEMI_MAIN_MULT = 1.25
PPV_MULT = 1.5

# Standing weights — what you are worth even in a week you did not wrestle.
MOMENTUM_WEIGHT = 0.35              # (momentum - 50) * this
POPULARITY_WEIGHT = 0.80            # popularity is /25, so up to +20
FEUD_HEAT_WEIGHT = 0.15
IDLE_PENALTY = 0.55                 # score multiplier when she did not work at all


def _rows(con, sql, args=()):
    return con.execute(sql, args).fetchall()


def _season(con) -> tuple[str, int]:
    """The in-game date and season.

    `SELECT *`, deliberately. `current_date` is a SQLite keyword, so naming the
    column explicitly — `SELECT current_date FROM game_state` — silently returns
    TODAY'S REAL DATE instead of the column, with no error. That published a
    Power 25 issue dated 2026 for a save sitting in January 2000.
    """
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if st is None:
        raise game.SigningError("no active save")
    return st["current_date"], st["season_year"]


def _signed(con, season: int) -> dict[int, str]:
    """wrestler_id -> brand_id for everyone under contract this season."""
    return {r["wrestler_id"]: r["brand_id"] for r in _rows(
        con,
        """SELECT wrestler_id, brand_id FROM contract
           WHERE terminated_on IS NULL AND start_year<=? AND end_year>=?""",
        (season, season))}


def _signed_roles(con, season: int) -> dict[int, str]:
    """wrestler_id -> the role she is signed AS this season (wrestler | manager)."""
    return {r["wrestler_id"]: r["role"] for r in _rows(
        con,
        """SELECT wrestler_id, role FROM contract
           WHERE terminated_on IS NULL AND start_year<=? AND end_year>=?""",
        (season, season))}


def _champions(con) -> dict[int, list[sqlite3.Row]]:
    """wrestler_id -> the belts she is currently holding."""
    out: dict[int, list] = {}
    for r in _rows(con, """SELECT r.wrestler_id, t.id title_id, t.name, t.short_name,
                                  t.tier, t.prestige, r.won_on
                           FROM game_title_reign r JOIN game_title t ON t.id=r.title_id
                           WHERE r.lost_on IS NULL AND t.active=1"""):
        out.setdefault(r["wrestler_id"], []).append(r)
    return out


# ---------------------------------------------------------------- power scores

def power_scores(con: sqlite3.Connection, as_of: str | None = None,
                 window_days: int = WINDOW_DAYS) -> list[dict]:
    """Score every signed wrestler on the last `window_days` of television.

    Returns one dict per wrestler, ordered best first, carrying the facts the
    blurb is written from — so the note never claims something the numbers do
    not support.
    """
    today, season = _season(con)
    as_of = as_of or today
    since = (date.fromisoformat(as_of[:10]) - timedelta(days=window_days)).isoformat()

    signed = _signed(con, season)
    if not signed:
        return []
    champs = _champions(con)
    champion_ids = set(champs)

    # Main event = the last slot on its show. One pass, then a lookup.
    last_slot = {r["show_id"]: r["mx"] for r in _rows(
        con, "SELECT show_id, MAX(slot) mx FROM sim_match GROUP BY show_id")}

    # Title changes in the window, so a win that WON a belt is scored as one.
    won_belt = {}
    for r in _rows(con, """SELECT r.won_at_match, r.wrestler_id, t.name, t.short_name
                           FROM game_title_reign r JOIN game_title t ON t.id=r.title_id
                           WHERE r.won_on >= ? AND r.won_on <= ? AND r.won_at_match IS NOT NULL""",
                   (since, as_of)):
        won_belt[(r["won_at_match"], r["wrestler_id"])] = r

    stats: dict[int, dict] = {
        wid: {"wrestler_id": wid, "brand_id": brand, "match_points": 0.0,
              "matches": 0, "wins": 0, "losses": 0, "draws": 0,
              "quality_sum": 0.0, "main_events": 0, "ppv": 0,
              "titles_won": [], "titles_retained": 0, "last_seen": None}
        for wid, brand in signed.items()}

    for r in _rows(con, """SELECT p.wrestler_id, p.is_winner, m.id match_id, m.show_id, m.slot,
                                  m.quality, m.title_id, m.finish, s.held_on, s.is_ppv, s.name show_name
                           FROM sim_match_participant p
                           JOIN sim_match m ON m.id = p.match_id
                           JOIN show s      ON s.id = m.show_id
                           WHERE s.held_on >= ? AND s.held_on <= ?""", (since, as_of)):
        st = stats.get(r["wrestler_id"])
        if st is None:
            continue          # not under contract now — off the board by definition

        st["matches"] += 1
        st["quality_sum"] += r["quality"] or 0.0
        if st["last_seen"] is None or r["held_on"] > st["last_seen"]:
            st["last_seen"] = r["held_on"]

        draw = r["finish"] == "draw"
        won = bool(r["is_winner"]) and not draw
        if draw:
            st["draws"] += 1
            pts = DRAW_POINTS
        elif won:
            st["wins"] += 1
            pts = WIN_POINTS
        else:
            st["losses"] += 1
            # Losing to the reigning champion is not the same as losing to anyone.
            beaten_by_champ = any(
                x["wrestler_id"] in champion_ids for x in _rows(
                    con, "SELECT wrestler_id FROM sim_match_participant "
                         "WHERE match_id=? AND is_winner=1", (r["match_id"],)))
            pts = LOSS_TO_CHAMPION_POINTS if beaten_by_champ else LOSS_POINTS

        # Quality of the match itself, centred on a 50 show.
        pts += ((r["quality"] or 50.0) - 50.0) / 5.0

        if r["title_id"]:
            pts += TITLE_MATCH_BONUS
            hit = won_belt.get((r["match_id"], r["wrestler_id"]))
            if hit:
                pts += TITLE_WON_BONUS
                st["titles_won"].append({"name": hit["name"], "short": hit["short_name"],
                                         "show": r["show_name"]})
            elif won:
                pts += TITLE_RETAINED_BONUS
                st["titles_retained"] += 1

        mult = 1.0
        if r["slot"] == last_slot.get(r["show_id"]):
            mult *= MAIN_EVENT_MULT
            st["main_events"] += 1
        elif r["slot"] == (last_slot.get(r["show_id"]) or 0) - 1:
            mult *= SEMI_MAIN_MULT
        if r["is_ppv"]:
            mult *= PPV_MULT
            st["ppv"] += 1

        # Recency: this week's win is worth more than one from five weeks ago.
        days_ago = (date.fromisoformat(as_of[:10]) - date.fromisoformat(r["held_on"][:10])).days
        mult *= max(0.45, 1.0 - days_ago / (window_days * 1.6))

        st["match_points"] += pts * mult

    # Standing: momentum, star power, live rivalries, belts held.
    heat = {}
    for r in _rows(con, "SELECT a_id, b_id, heat FROM feud WHERE status='active'"):
        heat[r["a_id"]] = max(heat.get(r["a_id"], 0), r["heat"])
        heat[r["b_id"]] = max(heat.get(r["b_id"], 0), r["heat"])

    out = []
    for wid, st in stats.items():
        try:
            eff = game.effective_attributes(con, wid)
        except ValueError:
            continue
        mom = con.execute("SELECT momentum FROM wrestler_state WHERE wrestler_id=?",
                          (wid,)).fetchone()
        momentum = mom["momentum"] if mom else 50

        score = st["match_points"]
        score += (momentum - 50) * MOMENTUM_WEIGHT
        score += eff["popularity"] * POPULARITY_WEIGHT
        score += heat.get(wid, 0) * FEUD_HEAT_WEIGHT

        held = champs.get(wid, [])
        for belt in held:
            score += TIER_WEIGHT.get(belt["tier"], 8.0) * ((belt["prestige"] or 50) / 70.0)

        if st["matches"] == 0:
            score *= IDLE_PENALTY

        st.update({
            "score": round(score, 2),
            "momentum": momentum,
            "popularity": eff["popularity"],
            "overall": eff["overall"],
            "avg_quality": round(st["quality_sum"] / st["matches"], 1) if st["matches"] else None,
            "titles_held": [{"name": b["name"], "short": b["short_name"], "tier": b["tier"]}
                            for b in held],
            "feud_heat": heat.get(wid, 0),
        })
        out.append(st)

    out.sort(key=lambda s: (-s["score"], s["wrestler_id"]))
    for i, s in enumerate(out, start=1):
        s["power_rank"] = i          # over the WHOLE roster, not just the top 25
    return out


# ---------------------------------------------------------------- blurbs

def _name(con, wid: int) -> str:
    return game._wname(con, wid)


def _variant(seed: int, options: list[str]) -> str:
    """Pick one phrasing deterministically.

    On a week where nobody wrestled, every entry falls into the same branch and
    the whole board reads as one sentence copy-pasted twenty-five times. Keyed
    on rank rather than randomised so re-reading an issue never changes it.
    """
    return options[seed % len(options)]


def _record(st: dict) -> str:
    if not st["matches"]:
        return "no matches"
    r = f"{st['wins']}-{st['losses']}"
    if st["draws"]:
        r += f"-{st['draws']}"
    return r


def _blurb(con, st: dict, rank: int, last: int | None) -> str:
    """One line of copy in Power 25 house voice, built only from what happened.

    MOVEMENT DECIDES THE SENTENCE, not the biggest fact. Leading with "winning
    the title has catapulted her" while she is *falling* — which is exactly what
    the first version did to anyone who won a belt and then lost ground — reads
    as a bug even though every word of it is true.
    """
    name = _name(con, st["wrestler_id"])
    won = st["titles_won"]
    held = st["titles_held"]
    rose = last is not None and last > rank
    fell = last is not None and last < rank

    # The title-win line only leads when the belt still means something for her
    # THIS week — she is climbing, she is new, or she is still carrying it.
    # Won-and-then-lost-it inside the same window reads as a stale headline.
    still_has = any(b["name"] == won[0]["name"] for b in held) if won else False
    if won and not fell and (rose or last is None or still_has):
        belt = won[0]["name"]
        verb = "catapulted" if (rose and last - rank >= 3) or last is None else "carried"
        return (f"Winning the {belt} at {won[0]['show']} has {verb} {name} "
                f"to No. {rank} of the POWER 25.")
    if last is None:
        if st["matches"]:
            return (f"{name} makes her POWER 25 debut on the back of a {_record(st)} run "
                    f"over the last month.")
        return f"{name} enters the POWER 25 on reputation alone — now she has to defend it."
    if rose:
        gain = last - rank
        spots = f"{gain} spot{'s' if gain > 1 else ''}"
        if held:
            return f"Another month with the {held[0]['name']} moves {name} up {spots}."
        if st["main_events"]:
            return (f"A {_record(st)} stretch and {st['main_events']} main event"
                    f"{'s' if st['main_events'] != 1 else ''} lift {name} {spots}.")
        if st["matches"]:
            return f"A {_record(st)} stretch lifts {name} {spots}."
        return _variant(rank, [
            f"{name} climbs {spots} without wrestling a match — that is how quiet "
            f"the month above her was.",
            f"Nobody ahead of {name} did anything with the month. She is up {spots} "
            f"on other people's inactivity.",
            f"{name} inherits {spots} she did not earn. The division left them lying there.",
        ])
    if fell:
        drop = rank - last
        places = f"{drop} place{'s' if drop > 1 else ''}"
        if not st["matches"]:
            return _variant(rank, [
                f"{name} has not been seen in a ring for weeks, and the POWER 25 "
                f"does not wait — down {places}.",
                f"You cannot hold a ranking from catering. {name} falls {places}.",
                f"{name} loses {places} without setting foot in a ring. "
                f"She has simply not been booked.",
            ])
        if won:
            return (f"{name} won the {won[0]['name']} and still slid {places} — "
                    f"a {_record(st)} month does not hold a top spot.")
        if st["losses"] > st["wins"]:
            return (f"{st['losses']} defeat{'s' if st['losses'] != 1 else ''} in the last month "
                    f"cost {name} {places}.")
        return f"{name} holds her ground but slips {places} as others climb past her."
    # No movement.
    if held and st["matches"]:
        return (f"{name} keeps the {held[0]['name']} — and her place — with a "
                f"{_record(st)} month.")
    if held:
        return (f"{name} still has the {held[0]['name']}, and that alone is holding "
                f"her at No. {rank}. She has not defended it in weeks.")
    if not st["matches"]:
        return _variant(rank, [
            f"{name} sat the month out. She stays put, for now.",
            f"No matches, no movement. {name} holds at No. {rank} by default.",
            f"The board cannot rank what it does not see — {name} is frozen at No. {rank}.",
        ])
    return f"A steady {_record(st)} keeps {name} exactly where she was."


def _buzz(con, entries: list[dict]) -> list[dict]:
    """The 'What you're saying' rail from the old Power 25 page — reactions
    generated from the actual movers, so they always refer to something real."""
    out = []
    risers = [e for e in entries if e["last_week"] and e["last_week"] - e["rank_no"] >= 3]
    fallers = [e for e in entries if e["last_week"] and e["rank_no"] - e["last_week"] >= 3]
    top = entries[0] if entries else None
    if top:
        out.append({"quote": f"\"{_name(con, top['wrestler_id'])} at No. 1 and nobody is close. "
                             f"She is the whole division right now.\"",
                    "reply": "The Academy replies: The board agrees — for this week."})
    if risers:
        r = risers[0]
        out.append({"quote": f"\"About time {_name(con, r['wrestler_id'])} got some respect. "
                             f"{r['last_week']} to {r['rank_no']} is still not high enough.\"",
                    "reply": "The Academy replies: Keep winning and she keeps climbing."})
    if fallers:
        f = fallers[0]
        out.append({"quote": f"\"{_name(con, f['wrestler_id'])} dropping to No. {f['rank_no']}? "
                             f"That is what happens when you lose.\"",
                    "reply": "The Academy replies: The rankings only read the results."})
    return out[:3]


# ---------------------------------------------------------------- issues

def _prev_issue(con, week_of: str):
    return con.execute(
        "SELECT * FROM power_issue WHERE week_of < ? ORDER BY week_of DESC LIMIT 1",
        (week_of,)).fetchone()


def generate_issue(con: sqlite3.Connection, week_of: str | None = None) -> dict:
    """Build (or rebuild) the Power 25 and every contender ladder for one week.

    Rebuilding the SAME week is safe — the entries are replaced. Movement is
    always measured against the previous issue, never against a recomputation,
    so an old issue stays exactly as it was published.
    """
    ensure_schema(con)
    today, season = _season(con)
    week_of = (week_of or today)[:10]

    prev = _prev_issue(con, week_of)
    prev_rank: dict[int, int] = {}
    if prev:
        prev_rank = {r["wrestler_id"]: r["rank_no"] for r in _rows(
            con, "SELECT wrestler_id, rank_no FROM power_entry WHERE issue_id=?", (prev["id"],))}

    row = con.execute("SELECT id FROM power_issue WHERE week_of=?", (week_of,)).fetchone()
    if row:
        issue_id = row["id"]
        con.execute("DELETE FROM power_entry WHERE issue_id=?", (issue_id,))
        con.execute("DELETE FROM contender_entry WHERE issue_id=?", (issue_id,))
    else:
        issue_id = con.execute(
            "INSERT INTO power_issue (week_of, season_year, created_on) VALUES (?,?,?)",
            (week_of, season, game.now_iso())).lastrowid

    scored = power_scores(con, as_of=week_of)
    entries = []
    for i, st in enumerate(scored[:POWER_SIZE], start=1):
        last = prev_rank.get(st["wrestler_id"])
        note = _blurb(con, st, i, last)
        con.execute(
            "INSERT INTO power_entry (issue_id, rank_no, wrestler_id, score, last_week, note) "
            "VALUES (?,?,?,?,?,?)", (issue_id, i, st["wrestler_id"], st["score"], last, note))
        entries.append({"rank_no": i, "wrestler_id": st["wrestler_id"], "score": st["score"],
                        "last_week": last, "note": note})

    by_id = {s["wrestler_id"]: s for s in scored}
    ladders = _build_contenders(con, issue_id, week_of, by_id, prev)

    con.commit()
    return {"issue_id": issue_id, "week_of": week_of, "season_year": season,
            "entries": len(entries), "ladders": ladders}


# ---------------------------------------------------------------- contenders

# A contender is not simply the next name on the Power 25 — the Power 25 is
# cross-brand and belt-blind. This re-scores the eligible pool for one specific
# championship.
_TIER_RANK = {"world": 0, "secondary": 1, "tag": 2, "cruiserweight": 2,
              "hardcore": 2, "manager": 3}

CONTENDER_POWER_WEIGHT = 0.55
CONTENDER_FORM_WEIGHT = 0.20        # win rate in the window
CONTENDER_DRAW_WEIGHT = 0.15        # popularity — a challenger has to sell it
DROUGHT_BONUS_PER_WEEK = 0.6        # never been given a shot? you rise anyway
DROUGHT_CAP = 12.0

# Where on the power board a challenger for this tier of belt should sit.
#
# Without this every belt produced the SAME ladder in the same order — the
# strongest names in the brand were simultaneously No. 1 contender to the world
# title, the secondary title and everything else, which is not how a card is
# built. Distance from the band is a penalty, so the top of the board chases the
# world title and the mid-card chases the mid-card belt.
TIER_BAND = {"world": 4, "secondary": 11, "tag": 12,
             "cruiserweight": 13, "hardcore": 13, "manager": 6}
TIER_FIT_PER_PLACE = 1.6
TIER_FIT_MAX = 20.0


def _eligible(con, title, season: int, signed: dict[int, str]) -> list[int]:
    """Everyone who could legally challenge for this belt right now.

    `game.title_eligible` covers the weight limit and brand exclusivity but not
    the signed ROLE — and the Manager's Championship is held by managers while
    every other belt is contested by wrestlers, so that filter has to be here or
    a valet ends up ranked for the world title.
    """
    champ = con.execute(
        "SELECT wrestler_id FROM game_title_reign WHERE title_id=? AND lost_on IS NULL",
        (title["id"],)).fetchone()
    champ_id = champ["wrestler_id"] if champ else None
    want_role = "manager" if title["tier"] == "manager" else "wrestler"
    roles = _signed_roles(con, season)
    out = []
    for wid in signed:
        if wid == champ_id or roles.get(wid) != want_role:
            continue
        ok, _why = game.title_eligible(con, title["id"], wid)
        if ok:
            out.append(wid)
    return out


def _build_contenders(con, issue_id: int, week_of: str, by_id: dict[int, dict], prev) -> int:
    _today, season = _season(con)
    signed = _signed(con, season)
    titles = _rows(con, "SELECT * FROM game_title WHERE active=1 ORDER BY id")
    if not titles:
        return 0

    max_power = max((s["score"] for s in by_id.values()), default=1.0) or 1.0
    since_shot = _weeks_since_title_shot(con, week_of)

    prev_rank_by_title: dict[int, dict[int, int]] = {}
    if prev:
        for r in _rows(con, "SELECT title_id, wrestler_id, rank_no FROM contender_entry "
                            "WHERE issue_id=?", (prev["id"],)):
            prev_rank_by_title.setdefault(r["title_id"], {})[r["wrestler_id"]] = r["rank_no"]

    built = 0
    for t in titles:
        pool = _eligible(con, t, season, signed)
        if not pool:
            continue
        scored = []
        for wid in pool:
            st = by_id.get(wid)
            if st is None:
                continue
            # A reigning world champion is not "chasing" the secondary belt. She
            # is legally eligible, and title_eligible correctly says so, but
            # ranking her as its No. 1 contender is nonsense — she has already
            # got the bigger one.
            if any(_TIER_RANK.get(b["tier"], 9) < _TIER_RANK.get(t["tier"], 9)
                   for b in st["titles_held"]):
                continue
            form = (st["wins"] / st["matches"]) if st["matches"] else 0.0
            band = TIER_BAND.get(t["tier"], 10)
            fit = min(TIER_FIT_MAX,
                      abs(st.get("power_rank", band) - band) * TIER_FIT_PER_PLACE)
            s = (CONTENDER_POWER_WEIGHT * (st["score"] / max_power) * 100.0
                 + CONTENDER_FORM_WEIGHT * form * 100.0
                 + CONTENDER_DRAW_WEIGHT * st["popularity"] * 4.0
                 + min(DROUGHT_CAP, since_shot.get(wid, 8) * DROUGHT_BONUS_PER_WEEK)
                 - fit)
            scored.append((round(s, 2), wid, st))
        scored.sort(key=lambda x: (-x[0], x[1]))

        # A hand-pinned #1 contender jumps the queue, but keeps the rest intact.
        lock = con.execute("SELECT wrestler_id FROM contender_lock WHERE title_id=?",
                           (t["id"],)).fetchone()
        if lock and lock["wrestler_id"]:
            locked = lock["wrestler_id"]
            scored = ([x for x in scored if x[1] == locked]
                      + [x for x in scored if x[1] != locked])

        prev_ranks = prev_rank_by_title.get(t["id"], {})
        for i, (s, wid, st) in enumerate(scored[:CONTENDER_SIZE], start=1):
            note = _contender_note(con, st, i, bool(lock and lock["wrestler_id"] == wid),
                                   since_shot.get(wid))
            con.execute(
                """INSERT INTO contender_entry
                     (issue_id, title_id, rank_no, wrestler_id, score, last_week, note)
                   VALUES (?,?,?,?,?,?,?)""",
                (issue_id, t["id"], i, wid, s, prev_ranks.get(wid), note))
        built += 1
    return built


def _weeks_since_title_shot(con, as_of: str) -> dict[int, int]:
    """How long since each wrestler last worked a championship match. A long
    wait is itself an argument for a shot — without it the same two names sit
    at the top of the ladder forever."""
    out: dict[int, int] = {}
    for r in _rows(con, """SELECT p.wrestler_id, MAX(s.held_on) last_shot
                           FROM sim_match_participant p
                           JOIN sim_match m ON m.id=p.match_id
                           JOIN show s ON s.id=m.show_id
                           WHERE m.title_id IS NOT NULL AND s.held_on <= ?
                           GROUP BY p.wrestler_id""", (as_of,)):
        days = (date.fromisoformat(as_of[:10]) - date.fromisoformat(r["last_shot"][:10])).days
        out[r["wrestler_id"]] = max(0, days // 7)
    return out


def _contender_note(con, st: dict, rank: int, locked: bool, weeks_waiting: int | None) -> str:
    name = _name(con, st["wrestler_id"])
    if locked:
        return f"{name} has been named No. 1 contender by the general manager."
    if rank == 1:
        if st["matches"]:
            return (f"{_record(st)} over the last month, and nobody in the division has "
                    f"a better case. {name} is next.")
        return f"{name} tops the ladder on standing alone — she needs a match to keep it."
    if weeks_waiting is not None and weeks_waiting >= 10:
        return f"{name} has waited {weeks_waiting} weeks for a title shot."
    if st["matches"]:
        return f"{_record(st)} in the window, momentum {st['momentum']}."
    return f"{name} has not worked recently — she is here on reputation."


def latest_issue(con: sqlite3.Connection, week_of: str | None = None) -> dict:
    """The published Power 25 (and the contender ladders alongside it)."""
    ensure_schema(con)
    if week_of:
        issue = con.execute("SELECT * FROM power_issue WHERE week_of=?", (week_of,)).fetchone()
    else:
        issue = con.execute("SELECT * FROM power_issue ORDER BY week_of DESC LIMIT 1").fetchone()
    if not issue:
        return {"issue": None, "entries": [], "buzz": [], "issues": []}

    entries = []
    for r in _rows(con, """SELECT e.*, w.name FROM power_entry e
                           JOIN wrestler w ON w.id=e.wrestler_id
                           WHERE e.issue_id=? ORDER BY e.rank_no""", (issue["id"],)):
        d = dict(r)
        last = d["last_week"]
        d["movement"] = ("new" if last is None
                         else "up" if last > d["rank_no"]
                         else "down" if last < d["rank_no"] else "same")
        d["delta"] = None if last is None else last - d["rank_no"]
        d["titles"] = [x["short_name"] or x["name"] for x in _rows(
            con, """SELECT t.name, t.short_name FROM game_title_reign r
                    JOIN game_title t ON t.id=r.title_id
                    WHERE r.lost_on IS NULL AND r.wrestler_id=?""", (d["wrestler_id"],))]
        d["brand_id"] = con.execute(
            """SELECT brand_id FROM contract WHERE wrestler_id=? AND terminated_on IS NULL
               ORDER BY id DESC LIMIT 1""", (d["wrestler_id"],)).fetchone()
        d["brand_id"] = d["brand_id"][0] if d["brand_id"] else None
        entries.append(d)

    issues = [dict(r) for r in _rows(
        con, "SELECT id, week_of, season_year FROM power_issue ORDER BY week_of DESC LIMIT 30")]
    return {"issue": dict(issue), "entries": entries,
            "buzz": _buzz(con, entries), "issues": issues}


def contenders(con: sqlite3.Connection, week_of: str | None = None) -> list[dict]:
    """Every belt's ladder from the latest issue, champion first."""
    ensure_schema(con)
    if week_of:
        issue = con.execute("SELECT * FROM power_issue WHERE week_of=?", (week_of,)).fetchone()
    else:
        issue = con.execute("SELECT * FROM power_issue ORDER BY week_of DESC LIMIT 1").fetchone()

    out = []
    for t in _rows(con, "SELECT * FROM game_title WHERE active=1 ORDER BY "
                        "CASE tier WHEN 'world' THEN 0 WHEN 'secondary' THEN 1 ELSE 2 END, id"):
        champ = con.execute(
            """SELECT r.wrestler_id, w.name, r.won_on FROM game_title_reign r
               JOIN wrestler w ON w.id=r.wrestler_id
               WHERE r.title_id=? AND r.lost_on IS NULL""", (t["id"],)).fetchone()
        lock = con.execute("SELECT wrestler_id FROM contender_lock WHERE title_id=?",
                           (t["id"],)).fetchone()
        rows = [] if not issue else [dict(r) for r in _rows(
            con, """SELECT c.*, w.name FROM contender_entry c
                    JOIN wrestler w ON w.id=c.wrestler_id
                    WHERE c.issue_id=? AND c.title_id=? ORDER BY c.rank_no""",
            (issue["id"], t["id"]))]
        for d in rows:
            last = d["last_week"]
            d["movement"] = ("new" if last is None else "up" if last > d["rank_no"]
                             else "down" if last < d["rank_no"] else "same")
            d["delta"] = None if last is None else last - d["rank_no"]
        out.append({
            "title": {"id": t["id"], "name": t["name"], "short_name": t["short_name"],
                      "tier": t["tier"], "brand_id": t["brand_id"], "prestige": t["prestige"]},
            "champion": dict(champ) if champ else None,
            "locked_contender": lock["wrestler_id"] if lock and lock["wrestler_id"] else None,
            "contenders": rows,
        })
    return out


def lock_contender(con: sqlite3.Connection, title_id: int, wrestler_id: int | None) -> dict:
    """Pin (or unpin) a #1 contender by hand. A pin outranks the computed ladder
    from the next issue on; it does not rewrite issues already published."""
    ensure_schema(con)
    if wrestler_id is None:
        con.execute("DELETE FROM contender_lock WHERE title_id=?", (title_id,))
    else:
        t = con.execute("SELECT tier, name FROM game_title WHERE id=?", (title_id,)).fetchone()
        if not t:
            raise game.SigningError("no such title")
        # title_eligible covers weight and brand exclusivity but says nothing
        # about being signed at all — without this, an undrafted free agent can
        # be named No. 1 contender to a belt she cannot appear on a show for.
        _today, season = _season(con)
        role = _signed_roles(con, season).get(wrestler_id)
        if role is None:
            raise game.SigningError(f"{_name(con, wrestler_id)} is not under contract")
        want = "manager" if t["tier"] == "manager" else "wrestler"
        if role != want:
            raise game.SigningError(
                f"{_name(con, wrestler_id)} is signed as a {role}; the {t['name']} "
                f"is contested by {want}s")
        ok, why = game.title_eligible(con, title_id, wrestler_id)
        if not ok:
            raise game.SigningError(why)
        con.execute(
            """INSERT INTO contender_lock (title_id, wrestler_id, locked_on) VALUES (?,?,?)
               ON CONFLICT(title_id) DO UPDATE SET wrestler_id=excluded.wrestler_id,
                 locked_on=excluded.locked_on""",
            (title_id, wrestler_id, game.now_iso()))
        t = con.execute("SELECT name FROM game_title WHERE id=?", (title_id,)).fetchone()
        game.log_event(con, "title",
                       f"{_name(con, wrestler_id)} is named No. 1 contender to the "
                       f"{t['name'] if t else 'title'}.", icon="🥇")
    con.commit()
    return {"title_id": title_id, "wrestler_id": wrestler_id}


# ================================================================ PROGRESSION

# Every category is out of 25, so a single point is a 4% move. These caps are
# what stop a ten-season save from turning the whole roster into 25s.
MAX_DELTA_PER_CATEGORY = 3
MAX_OVERALL_DELTA = 6
CAT_MIN, CAT_MAX = 1, 25

# Age shapes how fast someone grows and how hard they fall. (min_age, growth×, decline×)
AGE_BANDS = [
    (0,  1.35, 0.60),      # 25 and under — improves fast, rarely regresses
    (26, 1.00, 1.00),      # prime
    (34, 0.60, 1.20),      # starting to slip
    (38, 0.35, 1.60),      # veteran — the drop-off is real
]


def _age_band(age: int | None) -> tuple[float, float]:
    a = age if age is not None else 30
    band = AGE_BANDS[0]
    for b in AGE_BANDS:
        if a >= b[0]:
            band = b
    return band[1], band[2]


def season_performance(con: sqlite3.Connection, season: int) -> list[dict]:
    """What each signed wrestler actually did in one season."""
    signed = _signed(con, season)
    if not signed:
        return []
    last_slot = {r["show_id"]: r["mx"] for r in _rows(
        con, "SELECT show_id, MAX(slot) mx FROM sim_match GROUP BY show_id")}
    lo, hi = f"{season}-01-01", f"{season}-12-31"

    perf = {wid: {"wrestler_id": wid, "matches": 0, "wins": 0, "losses": 0, "draws": 0,
                  "quality_sum": 0.0, "main_events": 0, "ppv": 0, "titles_won": 0,
                  "weeks_top10": 0, "weeks_top25": 0, "nominations": 0, "feud_heat": 0}
            for wid in signed}

    for r in _rows(con, """SELECT p.wrestler_id, p.is_winner, m.slot, m.show_id, m.quality,
                                  m.finish, s.is_ppv
                           FROM sim_match_participant p
                           JOIN sim_match m ON m.id=p.match_id
                           JOIN show s ON s.id=m.show_id
                           WHERE s.held_on BETWEEN ? AND ?""", (lo, hi)):
        st = perf.get(r["wrestler_id"])
        if st is None:
            continue
        st["matches"] += 1
        st["quality_sum"] += r["quality"] or 0.0
        if r["finish"] == "draw":
            st["draws"] += 1
        elif r["is_winner"]:
            st["wins"] += 1
        else:
            st["losses"] += 1
        if r["slot"] == last_slot.get(r["show_id"]):
            st["main_events"] += 1
        if r["is_ppv"]:
            st["ppv"] += 1

    for r in _rows(con, """SELECT wrestler_id, COUNT(*) n FROM game_title_reign
                           WHERE won_on BETWEEN ? AND ? GROUP BY wrestler_id""", (lo, hi)):
        if r["wrestler_id"] in perf:
            perf[r["wrestler_id"]]["titles_won"] = r["n"]

    for r in _rows(con, """SELECT e.wrestler_id, SUM(CASE WHEN e.rank_no<=10 THEN 1 ELSE 0 END) t10,
                                  COUNT(*) t25
                           FROM power_entry e JOIN power_issue i ON i.id=e.issue_id
                           WHERE i.season_year=? GROUP BY e.wrestler_id""", (season,)):
        if r["wrestler_id"] in perf:
            perf[r["wrestler_id"]]["weeks_top10"] = r["t10"]
            perf[r["wrestler_id"]]["weeks_top25"] = r["t25"]

    for r in _rows(con, """SELECT wrestler_id, COUNT(*) n FROM award_nomination
                           WHERE season_year=? AND wrestler_id IS NOT NULL
                           GROUP BY wrestler_id""", (season,)):
        if r["wrestler_id"] in perf:
            perf[r["wrestler_id"]]["nominations"] = r["n"]

    for r in _rows(con, "SELECT a_id, b_id, heat FROM feud"):
        for wid in (r["a_id"], r["b_id"]):
            if wid in perf:
                perf[wid]["feud_heat"] = max(perf[wid]["feud_heat"], r["heat"])

    for wid, st in perf.items():
        ms = con.execute("SELECT momentum, morale FROM wrestler_state WHERE wrestler_id=?",
                         (wid,)).fetchone()
        st["momentum"] = ms["momentum"] if ms else 50
        st["morale"] = ms["morale"] if ms else 50
        st["avg_quality"] = round(st["quality_sum"] / st["matches"], 1) if st["matches"] else None
        st["win_pct"] = (st["wins"] / st["matches"]) if st["matches"] else 0.0
    return list(perf.values())


def season_context(con: sqlite3.Connection, season: int) -> dict:
    """League-wide baselines for the season, so the grade is RELATIVE.

    Two things forced this. Match quality in this sim is not anchored to 55 —
    it starts low because experience starts at zero and climbs across the save,
    so a fixed baseline quietly marks the whole roster down in year one and up
    in year eight. And counting main events and Power-10 weeks as raw totals
    made the score depend on how many shows you happened to run: forty weeks of
    television maxed out every headliner at 100/100. Both are now rates against
    what the league actually did.
    """
    lo, hi = f"{season}-01-01", f"{season}-12-31"
    row = con.execute(
        """SELECT AVG(m.quality) q, COUNT(*) n FROM sim_match m JOIN show s ON s.id=m.show_id
           WHERE s.held_on BETWEEN ? AND ?""", (lo, hi)).fetchone()
    issues = con.execute("SELECT COUNT(*) FROM power_issue WHERE season_year=?",
                         (season,)).fetchone()[0]
    return {"league_quality": row["q"] if row and row["q"] is not None else 55.0,
            "matches": row["n"] if row else 0,
            "issues": issues}


def _season_score(st: dict, ctx: dict) -> float:
    """One 0-100 number for how the year went. 50 is a flat, forgettable season."""
    s = 50.0
    if st["matches"]:
        s += 24.0 * (st["win_pct"] - 0.5)                              # ±12
        s += 0.35 * ((st["avg_quality"] or ctx["league_quality"]) - ctx["league_quality"])
        s += 10.0 * (st["main_events"] / st["matches"])                # how often she headlined
        s += 5.0 * (st["ppv"] / st["matches"])
    else:
        s -= 12.0                                                      # invisible all year
    if ctx["issues"]:
        s += 10.0 * min(1.0, st["weeks_top10"] / ctx["issues"])
        s += 4.0 * min(1.0, st["weeks_top25"] / ctx["issues"])
    s += min(12.0, 6.0 * st["titles_won"])
    s += min(8.0, 4.0 * st["nominations"])
    s += 0.12 * (st["momentum"] - 50)
    s += 0.06 * (st["feud_heat"] - 25)
    return max(0.0, min(100.0, s))


def _reason(con, st: dict, cat: str, delta: int, score: float, ctx: dict) -> str:
    """Why the engine is proposing this. Facts only — it is the GM's evidence."""
    bits = []
    if st["matches"]:
        rec = f"{st['wins']}-{st['losses']}"
        if st["draws"]:
            rec += f"-{st['draws']}"
        bits.append(rec)
        if st["avg_quality"]:
            # Against the league, not against an absolute — match quality drifts
            # upward across a save as the roster gains experience.
            bits.append(f"match quality {st['avg_quality']} vs league "
                        f"{ctx['league_quality']:.0f}")
    else:
        bits.append("did not work a single match")
    if st["titles_won"]:
        bits.append(f"{st['titles_won']} title reign{'s' if st['titles_won'] != 1 else ''}")
    if st["main_events"]:
        bits.append(f"{st['main_events']} main event{'s' if st['main_events'] != 1 else ''}")
    if st["ppv"]:
        bits.append(f"{st['ppv']} PPV")
    if st["weeks_top10"]:
        bits.append(f"{st['weeks_top10']} week{'s' if st['weeks_top10'] != 1 else ''} in the Power 10")
    if st["nominations"]:
        bits.append(f"{st['nominations']} award nomination{'s' if st['nominations'] != 1 else ''}")
    verb = "up" if delta > 0 else "down"
    return f"Season score {score:.0f}/100 — {', '.join(bits)}. {cat.title()} {verb} {abs(delta)}."


def evaluate_season(con: sqlite3.Connection, season: int) -> dict:
    """Grade a season and QUEUE the rating moves. Applies nothing.

    Re-running replaces the season's still-PENDING suggestions and leaves
    anything already approved or rejected alone — so an accidental second run
    can never undo a decision the GM already made.
    """
    ensure_schema(con)
    resolved = {(r["wrestler_id"], r["category"]) for r in _rows(
        con, "SELECT wrestler_id, category FROM rating_change "
             "WHERE season_year=? AND status<>'pending'", (season,))}
    con.execute("DELETE FROM rating_change WHERE season_year=? AND status='pending'", (season,))

    ctx = season_context(con, season)
    created = 0
    for st in season_performance(con, season):
        wid = st["wrestler_id"]
        try:
            eff = game.effective_attributes(con, wid)
        except ValueError:
            continue
        score = _season_score(st, ctx)
        grow, decline = _age_band(eff["age"])

        raw = {
            # Popularity is exposure: titles, main events, being on the board.
            "popularity": (score - 52.0) / 9.0,
            # Charisma is slower — it moves on quality, heat and recognition.
            "charisma": (score - 55.0) / 12.0 + (0.5 if st["nominations"] else 0.0),
            # Looks barely moves. Age takes it away; a young star on the rise
            # grows into her presentation.
            "looks": (-0.5 if (eff["age"] or 30) >= 36 else 0.0)
                     + (0.5 if (eff["age"] or 30) <= 24 and score > 65 else 0.0),
        }
        if st["matches"] == 0:
            raw["popularity"] = min(raw["popularity"], -1.5)

        proposals, total = [], 0
        for cat in ("popularity", "charisma", "looks"):
            v = raw[cat] * (grow if raw[cat] > 0 else decline)
            delta = int(round(v))
            delta = max(-MAX_DELTA_PER_CATEGORY, min(MAX_DELTA_PER_CATEGORY, delta))
            cur = eff[cat]
            new = max(CAT_MIN, min(CAT_MAX, cur + delta))
            delta = new - cur
            if delta == 0 or (wid, cat) in resolved:
                continue
            proposals.append((cat, cur, new, delta))
            total += abs(delta)

        # Whole-person cap: trim the smallest moves until the overall swing fits.
        while total > MAX_OVERALL_DELTA and proposals:
            proposals.sort(key=lambda p: abs(p[3]))
            cat, cur, new, delta = proposals.pop(0)
            total -= abs(delta)

        for cat, cur, new, delta in proposals:
            con.execute(
                """INSERT INTO rating_change (season_year, wrestler_id, category, from_value,
                     to_value, suggested, reason, score, status, created_on)
                   VALUES (?,?,?,?,?,?,?,?, 'pending', ?)""",
                (season, wid, cat, cur, new, new, _reason(con, st, cat, delta, score, ctx),
                 round(score, 1), game.now_iso()))
            created += 1

    con.commit()
    if created:
        game.log_event(con, "ratings",
                       f"{created} rating change{'s' if created != 1 else ''} proposed for "
                       f"season {season} — awaiting your approval.", icon="📈")
    return {"season_year": season, "created": created}


def list_changes(con: sqlite3.Connection, status: str = "pending",
                 season: int | None = None) -> list[dict]:
    ensure_schema(con)
    sql = """SELECT c.*, w.name FROM rating_change c JOIN wrestler w ON w.id=c.wrestler_id
             WHERE 1=1"""
    args: list = []
    if status and status != "all":
        sql += " AND c.status=?"
        args.append(status)
    if season:
        sql += " AND c.season_year=?"
        args.append(season)
    sql += " ORDER BY ABS(c.to_value - c.from_value) DESC, w.name, c.category"
    out = []
    for r in _rows(con, sql, tuple(args)):
        d = dict(r)
        d["delta"] = d["to_value"] - d["from_value"]
        out.append(d)
    return out


def resolve_change(con: sqlite3.Connection, change_id: int, approve: bool,
                   to_value: int | None = None) -> dict:
    """Approve (optionally at a value the GM edited) or reject one suggestion.

    Approval is the ONLY path that writes a rating, and it writes to
    `attribute_override` — the layer a re-harvest never overwrites.
    """
    ensure_schema(con)
    c = con.execute("SELECT * FROM rating_change WHERE id=?", (change_id,)).fetchone()
    if not c:
        raise game.SigningError("no such rating change")
    if c["status"] != "pending":
        raise game.SigningError(f"already {c['status']}")

    if not approve:
        con.execute("UPDATE rating_change SET status='rejected', resolved_on=? WHERE id=?",
                    (game.now_iso(), change_id))
        con.commit()
        return {"id": change_id, "status": "rejected"}

    val = c["to_value"] if to_value is None else int(to_value)
    val = max(CAT_MIN, min(CAT_MAX, val))
    cat = c["category"]
    if cat not in ("charisma", "popularity", "looks"):
        raise game.SigningError(f"cannot apply {cat}")

    con.execute(
        f"""INSERT INTO attribute_override (wrestler_id, {cat}, updated_at) VALUES (?,?,?)
            ON CONFLICT(wrestler_id) DO UPDATE SET {cat}=excluded.{cat},
              updated_at=excluded.updated_at""",
        (c["wrestler_id"], val, game.now_iso()))
    con.execute("UPDATE rating_change SET status='approved', to_value=?, resolved_on=? WHERE id=?",
                (val, game.now_iso(), change_id))
    arrow = "▲" if val > c["from_value"] else "▼"
    game.log_event(con, "ratings",
                   f"{_name(con, c['wrestler_id'])} {cat} {c['from_value']} → {val} {arrow}",
                   icon="📈")
    con.commit()
    return {"id": change_id, "status": "approved", "wrestler_id": c["wrestler_id"],
            "category": cat, "value": val}


def resolve_all(con: sqlite3.Connection, approve: bool, season: int | None = None) -> dict:
    """Bulk approve or reject everything still pending."""
    ids = [r["id"] for r in list_changes(con, "pending", season)]
    done = 0
    for i in ids:
        try:
            resolve_change(con, i, approve)
            done += 1
        except game.SigningError:
            continue
    return {"resolved": done, "approved": approve}
