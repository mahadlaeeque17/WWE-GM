"""What the building sounded like — per segment, and per woman in it.

WHY A SHOW RATING WAS NOT ENOUGH. A show rating is one number for the night, and
one number cannot say "the main event was technically fine and nobody cared" or
"that promo got the biggest reaction on the show". Those are the two sentences
that actually teach a GM how to book, so they need to exist as data.

TWO DIFFERENT MEASUREMENTS, and keeping them apart is the whole design:

  REACTION   how hot the segment was, 0-100, with a label. Driven by quality,
             star power, how clear the conflict is, and rivalry heat.

  POP        how the crowd took ONE woman, -100 (booed out of the building) to
             +100 (cheered through the roof). This is NOT a measure of how well
             she did — a heel being loudly booed is a heel doing her job.

The interesting number is the MISMATCH between pop and alignment. A heel who is
so over that the crowd cheers her anyway is the single most famous thing in
wrestling booking, and it is only detectable if you measure "cheered vs booed"
separately from "good vs bad". That mismatch is what turns.py reads to propose a
turn — see the note there on why a turn is a suggestion and never automatic.
"""
from __future__ import annotations

import sqlite3

import game

# 0-100 reaction bands. The bottom two are distinct on purpose: a crowd that is
# hostile (they are rejecting this) is a different problem from a crowd that is
# flat (they have stopped listening), and the fixes are opposites.
REACTION_BANDS = [
    (0,  "hostile",  "The crowd is rejecting this."),
    (18, "flat",     "Dead air. Nobody is invested."),
    (34, "polite",   "Watching, not caring."),
    (50, "into it",  "The building is with it."),
    (66, "hot",      "Real heat — they are loud."),
    (80, "red hot",  "Best reaction of the night territory."),
    (91, "nuclear",  "The place came apart."),
]

# A heel is BOOED by design, a face CHEERED by design. These are the baselines
# the crowd starts from before anything she does is taken into account.
BASE_POP = {"face": 26.0, "heel": -30.0}

# How far past her own baseline she has to land before it reads as the crowd
# genuinely turning on (or onto) her rather than just a loud night.
MISMATCH_HEEL_CHEERED = 22.0
MISMATCH_FACE_BOOED = -18.0


def reaction_band(score: float) -> tuple[str, str]:
    label, note = REACTION_BANDS[0][1], REACTION_BANDS[0][2]
    for lo, lab, n in REACTION_BANDS:
        if score >= lo:
            label, note = lab, n
    return label, note


# What a reaction is made of. These weights matter more than they look.
#
# The first cut had quality at 0.62 and the star-power term at 0.30, and since
# that term arrives on a 0-20 scale it could only ever contribute about seven
# points — which made the reaction a near-restatement of the match quality and
# defeated the whole reason for having two numbers. The interesting cases are
# precisely the ones where they DIVERGE: a technically fine match between two
# women nobody is invested in, and an ordinary match between two stars in a
# blood feud. So quality was cut and star power scaled up to where it can
# genuinely swing the result.
REACT_QUALITY = 0.45
REACT_STARS = 1.40         # applied to a 0-20 score, so worth up to ~28 points
REACT_FEUD_CAP = 14.0
REACT_CONFLICT = 6.0       # a clear face-vs-heel argument
REACT_NO_CONFLICT = -5.0
REACT_MAIN = 5.0
REACT_PPV = 6.0


def segment_reaction(quality: float, heat: float, feud_heat: int, aligns: set[str],
                     is_ppv: bool, is_main: bool) -> dict:
    """How hot one segment was.

    Quality counts, but deliberately does NOT dominate — see the weights above.
    A clean match between two women nobody is invested in can be technically
    good and draw nothing, and an ordinary match between two stars in a blood
    feud can bring the house down. Those two facts are the lesson this number
    exists to teach, and a reaction that just tracked quality could teach
    neither.
    """
    score = quality * REACT_QUALITY + heat * REACT_STARS
    if "face" in aligns and "heel" in aligns:
        score += REACT_CONFLICT         # a clear conflict is easier to care about
    elif len(aligns) == 1:
        score += REACT_NO_CONFLICT      # no natural argument
    score += min(REACT_FEUD_CAP, feud_heat * 0.16)
    if is_main:
        score += REACT_MAIN
    if is_ppv:
        score += REACT_PPV
    score = max(0.0, min(100.0, score))
    label, note = reaction_band(score)
    return {"reaction_score": round(score, 1), "reaction": label, "reaction_note": note}


def wrestler_pop(alignment: str, popularity: float, momentum: float, quality: float,
                 won: bool, beaten_clean: bool, cheap_finish: bool,
                 feud_heat: int) -> float:
    """How the crowd took HER. -100 booed .. +100 cheered.

    A heel starts underwater and climbs with star power: an over-enough heel
    ends up in positive territory no matter how she is booked, which is precisely
    the phenomenon worth modelling. A face starts above water and sinks if she is
    unover and losing — apathy, not hatred, is how a face goes stale.

    `cheap_finish` (a DQ or countout win) pushes a heel further DOWN, because
    cheating to win is a heel doing her job well.
    """
    base = BASE_POP.get(alignment, BASE_POP["face"])
    # Star power is the dominant term. Scaled off /20 categories.
    pop = base + popularity * 3.1
    pop += (momentum - 50) * 0.14
    # A great match lifts everybody in it; a bad one drains the room.
    pop += (quality - 50) * 0.28
    if won:
        pop += 8 if alignment == "face" else 4
    if beaten_clean:
        pop -= 10 if alignment == "face" else 3
    if cheap_finish and alignment == "heel":
        pop -= 9                          # cheating is the job
    # Heat cuts both ways: being ABOUT something makes the reaction louder,
    # in whichever direction it was already going.
    pop *= 1.0 + min(0.22, feud_heat * 0.0022)
    return max(-100.0, min(100.0, pop))


def mismatch(alignment: str, pop: float) -> str | None:
    """Is the crowd reacting to her the wrong way round?

    Returns the alignment she is DRIFTING toward, or None. This is the only
    place the rule lives, so turns.py and the UI cannot disagree about it.
    """
    if alignment == "heel" and pop >= MISMATCH_HEEL_CHEERED:
        return "face"
    if alignment == "face" and pop <= MISMATCH_FACE_BOOED:
        return "heel"
    return None


def record_pops(con: sqlite3.Connection, kind: str, segment_id: int,
                pops: dict[int, tuple[float, str]]) -> None:
    """Persist per-wrestler reactions for one segment."""
    for wid, (pop, align) in pops.items():
        con.execute(
            "INSERT OR REPLACE INTO segment_pop (segment_kind, segment_id, wrestler_id, "
            "pop, alignment) VALUES (?,?,?,?,?)",
            (kind, segment_id, wid, round(pop, 1), align))


def recent_pop(con: sqlite3.Connection, wid: int, limit: int = 8) -> dict:
    """Her last few crowd reactions, averaged — the evidence for a turn.

    One loud night proves nothing; a run of them is the crowd telling you
    something. `limit` is that run.
    """
    rows = [dict(r) for r in con.execute(
        """SELECT p.pop, p.alignment, p.segment_kind, p.segment_id
             FROM segment_pop p
            WHERE p.wrestler_id=?
            ORDER BY p.rowid DESC LIMIT ?""", (wid, limit))]
    if not rows:
        return {"samples": 0, "avg_pop": None, "alignment": None, "drifting": None}
    avg = sum(r["pop"] for r in rows) / len(rows)
    align = rows[0]["alignment"]
    return {"samples": len(rows), "avg_pop": round(avg, 1), "alignment": align,
            "drifting": mismatch(align or "face", avg)}


def show_reactions(con: sqlite3.Connection, show_id: int) -> dict:
    """Every segment's reaction on one show, plus the loudest moment of the night.

    "Biggest reaction of the night" is the single most useful line a show recap
    can carry, and it is often not the main event — which is the point.
    """
    segs = []
    for m in con.execute(
        "SELECT id, slot, quality, reaction, reaction_score FROM sim_match "
        "WHERE show_id=? ORDER BY slot", (show_id,)):
        segs.append({"kind": "match", "id": m["id"], "slot": m["slot"],
                     "quality": m["quality"], "reaction": m["reaction"],
                     "reaction_score": m["reaction_score"]})
    for p in con.execute(
        "SELECT id, slot, kind, quality, reaction, reaction_score FROM sim_promo "
        "WHERE show_id=? ORDER BY slot", (show_id,)):
        segs.append({"kind": "promo", "id": p["id"], "slot": p["slot"],
                     "promo_kind": p["kind"], "quality": p["quality"],
                     "reaction": p["reaction"], "reaction_score": p["reaction_score"]})
    rated = [s for s in segs if s["reaction_score"] is not None]
    loudest = max(rated, key=lambda s: s["reaction_score"]) if rated else None
    return {"segments": segs, "loudest": loudest,
            "avg_reaction": round(sum(s["reaction_score"] for s in rated) / len(rated), 1)
            if rated else None}
