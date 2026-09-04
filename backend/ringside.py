"""Managers at ringside — what a second actually does to a match.

WHY THIS EXISTS. Managers were in the game but had almost nothing to do: they
could be signed, paid, rated on Mic and Influence, and put on either side of a
Manager's Championship match. Outside that one belt they had no effect on
anything, which made a whole rating category decorative and made "should I spend
cap space on a manager?" a question with no answer.

A second now does three separate things, and keeping them separate is the design:

  LIFTS HER SIDE     Influence is exactly "how much she elevates whoever she
                     stands beside", so it feeds the side's strength. Modest —
                     a great manager tilts a close match, she does not overturn
                     a talent gap. That ceiling is the whole reason the effect is
                     safe to give her.

  LIFTS THE MATCH    Mic work adds crowd investment: a manager at ringside is
                     another character in the story, so the segment means more.
                     This applies to BOTH sides' seconds, because a good manager
                     opposite a good manager is a better match than neither.

  INTERFERES         A heel manager especially can steal one. This is the only
                     place a second can change the WINNER outright rather than
                     nudging the odds, and it is deliberately rare and always
                     reported, so a stolen match never looks like a bug.

WHAT A SECOND IS NOT. She is not a participant: she takes no fatigue, cannot be
injured, does not get a win or a loss on her record, and is not "booked" for the
purposes of the one-match-per-wrestler rule. She can second on a night she also
wrestles — being at ringside is not a match.
"""
from __future__ import annotations

import sqlite3

import game

# Influence (0-20) scaled into a side-strength multiplier. A 20-influence
# manager is worth about +9% to her side; an average one about +4%. Kept small
# on purpose: the point of a manager is to swing a close match, and anything
# larger would make signing one strictly better than signing a wrestler.
STRENGTH_PER_INFLUENCE = 0.0045

# Mic (0-20) scaled into quality points, applied once per second in the match.
# A great talker at ringside is worth roughly +2.5 to the match.
QUALITY_PER_MIC = 0.125

# Crowd heat from her presence, in the same units as the match's own heat term.
HEAT_PER_MIC = 0.10

# Chance she gets involved decisively, before her own numbers scale it. A heel
# manager is far likelier to cheat than a face is to help fairly, because that
# is what the roles are for.
BASE_INTERFERE = 0.055
HEEL_INTERFERE_MULT = 2.1

# Interference cannot happen in a no-DQ match in the GM's favour by cheating —
# there is nothing to cheat past. It still happens, it just cannot be a DQ.
INTERFERE_QUALITY = -3.0        # a screwy finish is a worse match


def effect_of(attrs: dict) -> dict:
    """What one manager brings, from her Mic and Influence.

    Reads the same effective attributes everything else does, so a manager who
    has been re-rated (or switched from wrestling — see game.working_role) brings
    what her current numbers say she brings.
    """
    mic = attrs.get("mic") or 0
    influence = attrs.get("influence") or 0
    return {
        "strength_mult": 1.0 + influence * STRENGTH_PER_INFLUENCE,
        "quality": mic * QUALITY_PER_MIC,
        "heat": mic * HEAT_PER_MIC,
        "interfere_chance": BASE_INTERFERE * (influence / 12.0)
        * (HEEL_INTERFERE_MULT if (attrs.get("alignment") == "heel") else 1.0),
        "mic": mic, "influence": influence,
        "alignment": attrs.get("alignment") or "face",
    }


def validate(con: sqlite3.Connection, seconds: list[int | None],
             teams: list[list[int]], season: int) -> None:
    """Refuse a ringside assignment that cannot mean anything.

    Checked before the sim runs so a nonsense second never quietly does nothing:
    a silent no-op is worse than an error, because the GM would think the
    manager was working.
    """
    named = [s for s in seconds if s]
    if len(named) != len(set(named)):
        raise ValueError("a manager cannot second both sides of the same match")
    in_ring = {w for t in teams for w in t}
    for mid in named:
        if mid in in_ring:
            raise ValueError(
                f"{game._wname(con, mid)} is IN this match — she cannot also be "
                f"at ringside for it.")
        # She has to be signed, and she has to be somebody who manages: either
        # signed as a manager, or a both-eligible wrestler switched to managing.
        row = con.execute(
            """SELECT c.role, COALESCE(o.role, a.role) capability, o.active_role
                 FROM contract c
                 JOIN attributes a ON a.wrestler_id = c.wrestler_id
                 LEFT JOIN attribute_override o ON o.wrestler_id = c.wrestler_id
                WHERE c.wrestler_id=? AND c.terminated_on IS NULL
                  AND c.start_year<=? AND c.end_year>=?""",
            (mid, season, season)).fetchone()
        if not row:
            raise ValueError(f"{game._wname(con, mid)} is not under contract.")
        manages = (row["role"] == "manager"
                   or game.working_role(row["capability"], row["active_role"]) == "manager"
                   or row["capability"] in ("manager", "both"))
        if not manages:
            raise ValueError(
                f"{game._wname(con, mid)} is a wrestler, not a manager — she cannot "
                f"be seconded to a match.")


def resolve(con: sqlite3.Connection, seconds: list[int | None],
            attrs_of) -> list[dict | None]:
    """Turn a per-side list of manager ids into their effects.

    `attrs_of` is a callable so the caller can reuse the effective-attributes
    lookup it has already done rather than paying for it twice in the sim's
    inner loop.
    """
    out: list[dict | None] = []
    for mid in seconds:
        if not mid:
            out.append(None)
            continue
        try:
            a = attrs_of(mid)
        except ValueError:
            out.append(None)
            continue
        e = effect_of(a)
        e["wrestler_id"] = mid
        e["name"] = game._wname(con, mid)
        out.append(e)
    return out


def record(con: sqlite3.Connection, match_id: int,
           resolved: list[dict | None], interfered: int | None) -> None:
    """Persist who was at ringside and what she was worth, per side."""
    for team, e in enumerate(resolved):
        if not e:
            continue
        note = "interfered" if e["wrestler_id"] == interfered else None
        con.execute(
            """INSERT OR REPLACE INTO sim_match_second
                 (match_id, wrestler_id, team, quality, note) VALUES (?,?,?,?,?)""",
            (match_id, e["wrestler_id"], team, round(e["quality"], 2), note))


def for_match(con: sqlite3.Connection, match_id: int) -> list[dict]:
    """Who was at ringside — for the result view."""
    return [dict(r) for r in con.execute(
        """SELECT s.wrestler_id, s.team, s.quality, s.note,
                  COALESCE(o.display_name, w.name) name,
                  (SELECT id FROM wrestler_image i WHERE i.wrestler_id=s.wrestler_id
                     AND i.is_profile=1 LIMIT 1) profile_image_id
             FROM sim_match_second s
             JOIN wrestler w ON w.id=s.wrestler_id
             LEFT JOIN attribute_override o ON o.wrestler_id=s.wrestler_id
            WHERE s.match_id=? ORDER BY s.team""", (match_id,))]


def bookable(con: sqlite3.Connection, brand_ids: list[str], season: int) -> list[dict]:
    """Everyone who can be put at ringside for these brands.

    Signed managers plus both-eligible wrestlers switched to managing — the same
    rule `validate` enforces, read the other way round so the booking screen
    offers exactly what the sim will accept.
    """
    marks = ",".join("?" * len(brand_ids))
    rows = con.execute(
        f"""SELECT c.wrestler_id id, COALESCE(o.display_name, w.name) name,
                   c.brand_id, c.role,
                   COALESCE(o.role, a.role) capability, o.active_role
              FROM contract c
              JOIN wrestler w ON w.id=c.wrestler_id
              JOIN attributes a ON a.wrestler_id=c.wrestler_id
              LEFT JOIN attribute_override o ON o.wrestler_id=c.wrestler_id
             WHERE c.brand_id IN ({marks}) AND c.terminated_on IS NULL
               AND c.start_year<=? AND c.end_year>=?
             ORDER BY name""", (*brand_ids, season, season)).fetchall()
    ach = game.achievement_inputs(con)
    out = []
    for r in rows:
        manages = (r["role"] == "manager"
                   or game.working_role(r["capability"], r["active_role"]) == "manager"
                   or r["capability"] in ("manager", "both"))
        if not manages:
            continue
        try:
            a = game.effective_attributes(con, r["id"], ach.get(r["id"]))
        except ValueError:
            continue
        e = effect_of(a)
        out.append({
            "id": r["id"], "name": r["name"], "brand_id": r["brand_id"],
            "mic": e["mic"], "influence": e["influence"],
            "alignment": e["alignment"],
            # What she is worth, in the words the booking screen shows.
            "lift": f"+{(e['strength_mult'] - 1) * 100:.0f}% to her side",
            "quality": round(e["quality"], 1),
            "signed_as_manager": r["role"] == "manager",
        })
    return out
