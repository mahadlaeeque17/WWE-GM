"""Feuds as STORIES rather than heat counters.

THE PROBLEM THIS FIXES. A feud was a number that went up every time you booked
the pair together. That makes a rivalry a series of matches, which is not how
wrestling works — the match is the payoff and everything before it is the build.
Worse, it had no memory: nothing in the save could say "she has beaten me twice
and I need the cage match", because nothing recorded that she had beaten her
twice.

So a feud now has:

  BEATS    every match, promo, run-in and turn between the two, written down in
           order with who won. This is the story so far, and it is what lets the
           booker and the GM both reason about what should happen NEXT.

  A STAGE  build → escalation → blow-off, derived from heat. The stage decides
           what kind of segment the pre-booker reaches for: talking early,
           physicality in the middle, a gimmick match at the end.

  A PLANNED BLOW-OFF  the GM can point a feud at a pay-per-view. Until that
           date the booker deliberately WITHHOLDS the singles match — it books
           promos, run-ins and multi-woman matches that keep them apart instead.
           That is the difference between a feud and four weeks of the same
           match, and it is the single most valuable thing a GM can decide.

WHY WITHHOLDING IS THE INTERESTING RULE. Anyone can book the blow-off tonight.
The skill is not booking it tonight — and a booker that always reached for the
hottest available pairing made that skill impossible to express.
"""
from __future__ import annotations

import sqlite3
from datetime import date

import game

# Heat thresholds for the three stages. The top one is game.FEUD_BLOWOFF_HEAT so
# there is exactly one definition of "ready to pay off" in the codebase.
STAGE_ESCALATION = 45
STAGES = {
    "build": ("Build", "Early. Talking, not fighting — save the match."),
    "escalation": ("Escalation", "It has turned physical. Keep it away from a clean finish."),
    "blowoff": ("Ready to blow off", "The crowd wants the match. Give it a gimmick and pay it off."),
    "settled": ("Settled", "Over."),
}


def stage_for(heat: int, status: str = "active") -> str:
    if status != "active":
        return "settled"
    if heat >= game.FEUD_BLOWOFF_HEAT:
        return "blowoff"
    if heat >= STAGE_ESCALATION:
        return "escalation"
    return "build"


def add_beat(con: sqlite3.Connection, feud_id: int, on_date: str, kind: str, text: str,
             show_id: int | None = None, winner_id: int | None = None) -> int:
    """Write one moment into a rivalry's history."""
    heat = con.execute("SELECT heat FROM feud WHERE id=?", (feud_id,)).fetchone()
    cur = con.execute(
        "INSERT INTO feud_beat (feud_id, on_date, show_id, kind, text, heat_after, winner_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (feud_id, on_date, show_id, kind, text, heat["heat"] if heat else None, winner_id))
    return cur.lastrowid


def beats(con: sqlite3.Connection, feud_id: int) -> list[dict]:
    return [dict(r) for r in con.execute(
        """SELECT b.*, COALESCE(o.display_name, w.name) winner_name
             FROM feud_beat b
             LEFT JOIN wrestler w ON w.id=b.winner_id
             LEFT JOIN attribute_override o ON o.wrestler_id=b.winner_id
            WHERE b.feud_id=? ORDER BY b.on_date, b.id""", (feud_id,))]


def _series(bts: list[dict], a_id: int, b_id: int) -> dict:
    """Who is winning the rivalry. The reason beats are stored at all."""
    a = sum(1 for x in bts if x["kind"] == "match" and x["winner_id"] == a_id)
    b = sum(1 for x in bts if x["kind"] == "match" and x["winner_id"] == b_id)
    drawn = sum(1 for x in bts if x["kind"] == "match" and x["winner_id"] is None)
    return {"a_wins": a, "b_wins": b, "draws": drawn, "matches": a + b + drawn,
            "leader": None if a == b else (a_id if a > b else b_id)}


def sync_stage(con: sqlite3.Connection, feud_id: int) -> str:
    f = con.execute("SELECT heat, status FROM feud WHERE id=?", (feud_id,)).fetchone()
    if not f:
        return "settled"
    s = stage_for(f["heat"], f["status"])
    con.execute("UPDATE feud SET stage=? WHERE id=?", (s, feud_id))
    return s


def plan_blowoff(con: sqlite3.Connection, feud_id: int, on_date: str | None,
                 label: str | None = None) -> dict:
    """Point a feud at a date — or clear the plan.

    Setting this is what tells the booker to protect the pairing until then.
    """
    f = con.execute("SELECT * FROM feud WHERE id=?", (feud_id,)).fetchone()
    if not f:
        raise game.SigningError("no such feud")
    con.execute("UPDATE feud SET planned_blowoff=?, blowoff_label=? WHERE id=?",
                (on_date, label, feud_id))
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    today = st["current_date"] if st else on_date
    if on_date:
        add_beat(con, feud_id, today, "planned",
                 f"Blow-off set for {label or on_date}. Keep them apart until then.")
        game.log_event(con, "feud",
                       f"{game._wname(con, f['a_id'])} vs {game._wname(con, f['b_id'])} "
                       f"is being built to {label or on_date}.", f["brand_id"], "📌")
    con.commit()
    return {"feud_id": feud_id, "planned_blowoff": on_date, "label": label}


def is_protected(con: sqlite3.Connection, feud_id: int, on_date: str) -> bool:
    """Should the booker keep these two OUT of a singles match tonight?

    True while a planned blow-off is still in the future. This is the whole
    mechanism behind "don't give away the match" — everything else about
    storylines is bookkeeping in service of this one boolean.
    """
    f = con.execute("SELECT planned_blowoff FROM feud WHERE id=?", (feud_id,)).fetchone()
    if not f or not f["planned_blowoff"]:
        return False
    return f["planned_blowoff"] > on_date


def next_beat(con: sqlite3.Connection, feud: dict, on_date: str) -> dict:
    """What should happen next in this story, and why.

    Read by the pre-booker to choose a segment and shown verbatim in the UI, so
    the advice the GM reads is the advice the booker actually followed.
    """
    stage = stage_for(feud["heat"], feud["status"])
    protected = bool(feud.get("planned_blowoff")) and feud["planned_blowoff"] > on_date
    bts = beats(con, feud["id"])
    series = _series(bts, feud["a_id"], feud["b_id"])
    a, b = game._wname(con, feud["a_id"]), game._wname(con, feud["b_id"])

    if protected:
        label = feud.get("blowoff_label") or feud["planned_blowoff"]
        return {"want": "keep_apart", "segment": "promo",
                "advice": f"Blow-off booked for {label}. Build it — promos, a run-in, "
                          f"or put them on opposite sides of a tag. Do NOT give away "
                          f"the singles match.",
                "stage": stage, "series": series, "protected": True}
    if stage == "build":
        return {"want": "talk", "segment": "promo",
                "advice": f"Early days at {feud['heat']} heat. A callout or a "
                          f"face-to-face is worth more than a match right now.",
                "stage": stage, "series": series, "protected": False}
    if stage == "escalation":
        if series["matches"] >= 2 and series["leader"]:
            led = game._wname(con, series["leader"])
            other = b if series["leader"] == feud["a_id"] else a
            return {"want": "physical", "segment": "match",
                    "advice": f"{led} leads the series {max(series['a_wins'], series['b_wins'])}"
                              f"-{min(series['a_wins'], series['b_wins'])}. "
                              f"{other} needs a win back, or a run-in — do not let this "
                              f"become one-sided before the blow-off.",
                    "stage": stage, "series": series, "protected": False}
        return {"want": "physical", "segment": "match",
                "advice": f"It has turned physical at {feud['heat']} heat. A run-in "
                          f"beatdown or a no-DQ match keeps it climbing without "
                          f"settling it.",
                "stage": stage, "series": series, "protected": False}
    return {"want": "blowoff", "segment": "match",
            "advice": f"{feud['heat']} heat — the crowd wants this. Pay it off with a "
                      f"gimmick match; a clean finish now settles the feud.",
            "stage": stage, "series": series, "protected": False}


def arc(con: sqlite3.Connection, feud_id: int) -> dict:
    """One rivalry's whole story — for the Rivalries screen."""
    f = con.execute("SELECT * FROM feud WHERE id=?", (feud_id,)).fetchone()
    if not f:
        raise game.SigningError("no such feud")
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    today = st["current_date"] if st else date.today().isoformat()
    d = dict(f)
    d["a_name"] = game._wname(con, f["a_id"])
    d["b_name"] = game._wname(con, f["b_id"])
    stage = stage_for(f["heat"], f["status"])
    d["stage"] = stage
    d["stage_label"], d["stage_note"] = STAGES[stage]
    d["beats"] = beats(con, feud_id)
    d["next"] = next_beat(con, d, today)
    d["series"] = d["next"]["series"]
    return d


def arcs(con: sqlite3.Connection, status: str | None = "active") -> list[dict]:
    ids = [r["id"] for r in con.execute(
        "SELECT id FROM feud" + (" WHERE status=?" if status else "") + " ORDER BY heat DESC",
        (status,) if status else ())]
    return [arc(con, i) for i in ids]


def settle_stale(con: sqlite3.Connection) -> list[dict]:
    """Close feuds that have been paid off and gone quiet.

    A rivalry that blew off cleanly and has not been touched since is over,
    whatever the heat number says — and leaving it open means the booker keeps
    trying to book a story that already ended.
    """
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if not st:
        return []
    today = date.fromisoformat(st["current_date"])
    closed = []
    for f in con.execute("SELECT * FROM feud WHERE status='active'"):
        bts = beats(con, f["id"])
        if not bts:
            continue
        last = date.fromisoformat(bts[-1]["on_date"])
        quiet_days = (today - last).days
        series = _series(bts, f["a_id"], f["b_id"])
        # Paid off: a decisive series and a clean finish, then five quiet weeks.
        if quiet_days >= 35 and series["matches"] >= 2 and series["leader"] is not None:
            game.settle_feud(con, f["id"])
            add_beat(con, f["id"], st["current_date"], "settled",
                     f"{game._wname(con, series['leader'])} won the rivalry.")
            closed.append({"feud_id": f["id"],
                           "winner": game._wname(con, series["leader"])})
        # Or simply abandoned: nothing at all for ten weeks.
        elif quiet_days >= 70:
            game.settle_feud(con, f["id"])
            add_beat(con, f["id"], st["current_date"], "settled",
                     "Quietly dropped — nobody mentioned it again.")
            closed.append({"feud_id": f["id"], "winner": None})
    con.commit()
    return closed
