"""Injuries and rest you can plan around.

WHAT WAS WRONG. An injury was a date: `injured_until`, set to some number of
weeks the sim picked, with no indication of how bad it was or what it was. That
made an injury a random unbookable flag rather than something to plan around,
and it meant the difference between "she tweaked a knee, back in a fortnight"
and "she is gone for the rest of the season" was invisible.

Stamina had the mirror problem. It gated booking, but there was no way to
DECIDE to rest somebody — the only way to freshen a wrestler up was to forget
about her, which is the same input the game punishes you for. So a granted rest
now exists as its own state: she is deliberately unbookable and recovers at
double rate, and everyone can see it was a choice.

  SEVERITY   a name, a range of weeks, and a re-injury risk that lingers after
             she is back. A bad injury does not stop mattering the day she
             returns.
  RESTING    GM-granted time off. Unbookable, recovers fast, morale improves.
  RISK       a per-wrestler read on how likely the next match is to break her,
             so "do not book her tonight" is an informed call rather than a
             hunch.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import game

# severity -> label, week range, and the lingering re-injury multiplier that
# applies for RECOVERY_TAIL_DAYS after she comes back.
SEVERITIES = {
    "knock":  {"label": "Knock",        "weeks": (1, 2),  "relapse": 1.15,
               "note": "Bumps and bruises. Back almost immediately."},
    "strain": {"label": "Strain",       "weeks": (2, 4),  "relapse": 1.35,
               "note": "Soft tissue. Needs a few weeks and will nag."},
    "tear":   {"label": "Tear",         "weeks": (5, 9),  "relapse": 1.7,
               "note": "Serious. Out for a couple of months."},
    "break":  {"label": "Break",        "weeks": (10, 18), "relapse": 2.1,
               "note": "Badly hurt. Most of a season, and she comes back fragile."},
}

# How long after a return the relapse multiplier keeps applying.
RECOVERY_TAIL_DAYS = 42

# What actually got hurt. Cosmetic, but it is the difference between a flag and
# a person — and it makes two injuries in a season read as two events.
BODY_PARTS = ["knee", "shoulder", "ribs", "ankle", "neck", "back", "elbow",
              "hamstring", "wrist", "concussion"]

# Above this fatigue, booking her is genuinely reckless and the UI says so.
RECKLESS_FATIGUE = 82
TIRED_FATIGUE = 60

# Rest recovers stamina at this multiple of the normal weekly rate. Resting is
# worth doing precisely because it is faster than simply not being booked.
REST_RECOVERY_MULT = 2.4


def severity_for(weeks: int) -> str:
    """Name a layoff length. The sim rolls weeks; this gives it meaning."""
    for key in ("knock", "strain", "tear", "break"):
        lo, hi = SEVERITIES[key]["weeks"]
        if weeks <= hi:
            return key
    return "break"


def record_injury(con: sqlite3.Connection, wid: int, weeks: int, held_on: str,
                  part: str | None = None) -> dict:
    """Write an injury with a severity and a note, not just a date."""
    sev = severity_for(weeks)
    part = part or BODY_PARTS[(wid * 7 + weeks) % len(BODY_PARTS)]
    until = (date.fromisoformat(held_on) + timedelta(weeks=weeks)).isoformat()
    note = f"{SEVERITIES[sev]['label'].lower()} — {part}"
    con.execute(
        """UPDATE wrestler_state SET injured_until=?, injury_severity=?, injury_note=?
           WHERE wrestler_id=?""", (until, sev, note, wid))
    return {"wrestler_id": wid, "weeks": weeks, "until": until,
            "severity": sev, "severity_label": SEVERITIES[sev]["label"],
            "part": part, "note": note}


def relapse_multiplier(con: sqlite3.Connection, wid: int, today: str) -> float:
    """Extra injury risk carried from a recent return.

    A wrestler who has just come back from a tear is more likely to go down
    again, which is what makes rushing somebody back a real gamble rather than a
    free choice.
    """
    s = con.execute(
        "SELECT injured_until, injury_severity FROM wrestler_state WHERE wrestler_id=?",
        (wid,)).fetchone()
    if not s or not s["injured_until"] or not s["injury_severity"]:
        return 1.0
    try:
        back = date.fromisoformat(s["injured_until"])
        now = date.fromisoformat(today)
    except ValueError:
        return 1.0
    if now < back:
        return 1.0                      # still out; the sim will not book her
    if (now - back).days > RECOVERY_TAIL_DAYS:
        return 1.0
    return SEVERITIES.get(s["injury_severity"], {}).get("relapse", 1.0)


def is_resting(con: sqlite3.Connection, wid: int, today: str) -> bool:
    s = con.execute("SELECT rested_until FROM wrestler_state WHERE wrestler_id=?",
                    (wid,)).fetchone()
    return bool(s and s["rested_until"] and s["rested_until"] > today)


def rest(con: sqlite3.Connection, wid: int, weeks: int) -> dict:
    """Deliberately stand her down. The GM's lever against burnout."""
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if not st:
        raise game.SigningError("no active save")
    weeks = max(1, min(8, int(weeks)))
    until = (date.fromisoformat(st["current_date"]) + timedelta(weeks=weeks)).isoformat()
    con.execute("UPDATE wrestler_state SET rested_until=?, "
                "morale = MAX(0, MIN(100, morale + ?)) WHERE wrestler_id=?",
                (until, 3 + weeks, wid))
    game.log_event(con, "medical",
                   f"{game._wname(con, wid)} is rested for {weeks} week"
                   f"{'s' if weeks != 1 else ''}.", icon="🛌")
    con.commit()
    return {"wrestler_id": wid, "weeks": weeks, "rested_until": until}


def clear_rest(con: sqlite3.Connection, wid: int) -> dict:
    """Call her back early. Costs a little goodwill — she was promised the time."""
    con.execute("UPDATE wrestler_state SET rested_until=NULL, "
                "morale = MAX(0, MIN(100, morale - 4)) WHERE wrestler_id=?", (wid,))
    con.commit()
    return {"wrestler_id": wid, "rested_until": None}


def risk(con: sqlite3.Connection, wid: int, today: str) -> dict:
    """How dangerous it is to book her tonight, in words.

    The whole point of surfacing this is that "she is at 14% stamina and just
    came back from a tear" should be a sentence the GM reads BEFORE booking her,
    not a thing she infers from an injury two weeks later.
    """
    s = con.execute(
        """SELECT fatigue, injured_until, injury_severity, injury_note, rested_until
             FROM wrestler_state WHERE wrestler_id=?""", (wid,)).fetchone()
    fatigue = (s["fatigue"] if s else 0) or 0
    stamina = max(0, 100 - fatigue)
    relapse = relapse_multiplier(con, wid, today)
    out_now = bool(s and s["injured_until"] and s["injured_until"] > today)
    resting = bool(s and s["rested_until"] and s["rested_until"] > today)

    reasons = []
    score = 1.0
    if fatigue >= RECKLESS_FATIGUE:
        score *= 2.2
        reasons.append(f"stamina down to {stamina}/100")
    elif fatigue >= TIRED_FATIGUE:
        score *= 1.5
        reasons.append(f"tired ({stamina}/100)")
    if relapse > 1.0:
        score *= relapse
        reasons.append(f"just back from a {s['injury_severity']}")
    try:
        age = game.effective_attributes(con, wid).get("age")
        if age and age >= 38:
            score *= 1.0 + (age - 37) * 0.06
            reasons.append(f"{age} years old")
    except ValueError:
        pass

    level = ("reckless" if score >= 2.6 else "risky" if score >= 1.7
             else "elevated" if score >= 1.25 else "fine")
    return {"wrestler_id": wid, "stamina": stamina, "fatigue": fatigue,
            "risk": round(score, 2), "level": level,
            "reasons": reasons, "out": out_now, "resting": resting,
            "injured_until": s["injured_until"] if s else None,
            "rested_until": s["rested_until"] if s else None,
            "injury_note": s["injury_note"] if s else None,
            "injury_severity": s["injury_severity"] if s else None}


def report(con: sqlite3.Connection, brand_id: str | None = None) -> dict:
    """The medical room: who is out, who is due back, who should be rested.

    Grouped by what the GM can DO about each one, which is why "needs rest" is a
    separate list from "injured" — one is a decision and the other is a fact.
    """
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if not st:
        return {"out": [], "resting": [], "at_risk": [], "returning": []}
    today, season = st["current_date"], st["season_year"]
    sql = """SELECT c.wrestler_id, c.brand_id FROM contract c
             WHERE c.terminated_on IS NULL AND c.start_year<=? AND c.end_year>=?"""
    args: list = [season, season]
    if brand_id:
        sql += " AND c.brand_id=?"
        args.append(brand_id)

    out, resting, at_risk, returning = [], [], [], []
    for r in con.execute(sql, tuple(args)):
        wid = r["wrestler_id"]
        d = risk(con, wid, today)
        d["name"] = game._wname(con, wid)
        d["brand_id"] = r["brand_id"]
        if d["out"]:
            d["weeks_left"] = max(0, (date.fromisoformat(d["injured_until"])
                                      - date.fromisoformat(today)).days // 7)
            out.append(d)
        elif d["resting"]:
            d["weeks_left"] = max(0, (date.fromisoformat(d["rested_until"])
                                      - date.fromisoformat(today)).days // 7)
            resting.append(d)
        else:
            if d["level"] in ("risky", "reckless"):
                at_risk.append(d)
            if relapse_multiplier(con, wid, today) > 1.0:
                returning.append(d)
    return {
        "out": sorted(out, key=lambda x: x["weeks_left"]),
        "resting": sorted(resting, key=lambda x: x["weeks_left"]),
        "at_risk": sorted(at_risk, key=lambda x: -x["risk"]),
        "returning": returning,
        "severities": [{"key": k, **v} for k, v in SEVERITIES.items()],
    }


def tick_recovery(con: sqlite3.Connection, days: int) -> dict:
    """Advance recovery for everyone standing down, and clear finished spells.

    Resting recovers faster than simply not being booked — that difference is
    the reason to grant time off instead of quietly leaving somebody off the
    card.
    """
    import sim
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if not st:
        return {"recovered": 0, "returned": []}
    today = st["current_date"]
    per_day = sim.FATIGUE_RECOVERY_PER_DAY
    con.execute(
        "UPDATE wrestler_state SET fatigue = MAX(0, fatigue - ?) "
        "WHERE rested_until IS NOT NULL AND rested_until > ?",
        (int(per_day * days * REST_RECOVERY_MULT), today))
    con.execute("UPDATE wrestler_state SET rested_until=NULL WHERE rested_until <= ?",
                (today,))
    returned = []
    for r in con.execute(
        """SELECT wrestler_id, injury_note FROM wrestler_state
            WHERE injured_until IS NOT NULL AND injured_until <= ?
              AND injured_until > date(?, ?)""", (today, today, f"-{days} day")):
        returned.append({"wrestler_id": r["wrestler_id"],
                         "name": game._wname(con, r["wrestler_id"]),
                         "note": r["injury_note"]})
    for x in returned:
        game.log_event(con, "medical", f"{x['name']} is cleared to return.", icon="🩹")
    con.commit()
    return {"recovered": days, "returned": returned}
