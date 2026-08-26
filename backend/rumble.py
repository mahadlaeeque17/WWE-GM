"""The Royal Rumble — the one match type the sim could not book.

WHY IT NEEDED ITS OWN MODULE. `sim.simulate_match` resolves a match between fixed
teams: everyone is in at the bell, one side wins. A Rumble is a different shape
entirely — thirty entrants arriving on a clock, eliminations happening throughout,
and a winner decided by who is still standing rather than by who was pinned. None
of that fits a teams-based resolver, and bending one into the other would have
made both worse.

It is worth building because a Rumble win is the single most valuable thing a
wrestler can win in one night: 3 points of Achievements, which is more than a
secondary title reign. The accolade already existed in ACCOLADES, marked "sim" —
and nothing could award it.

DETERMINISTIC, like everything else in the sim. Same save seed plus the same
entrants always produces the same match, so a result can be argued with rather
than reshuffled by reloading. The seed is derived from the save seed and the show
id exactly as `sim._rng` does it.

WHAT DECIDES IT. Each survival roll weighs a wrestler's Wrestling, Achievements
and Popularity against everyone else in the ring. Ring generalship matters most,
star power matters (Rumbles protect stars), and a champion is harder to throw out
than a rookie. It is a weighted draw, not a coin flip and not a foregone
conclusion — the best wrestler in the match is the favourite, never a certainty.
"""

from __future__ import annotations

import random
import sqlite3

import game

# A traditional Rumble. Fewer entrants is allowed — a 20-woman version works
# identically — but two must start and the field cannot be smaller than that.
FULL_FIELD = 30
MIN_FIELD = 4

# Seconds between entrances. 90 is the modern pace; the number only affects the
# times printed in the log, not who wins.
ENTRY_GAP = 90

# How many eliminations happen in the interval before each new entrant, BY HOW
# CROWDED THE RING ALREADY IS.
#
# A flat distribution here does not work, and the first version proved it: at a
# mean of one elimination per entrant the ring sits at two people for the whole
# match, so nobody accumulates ring time and the last five entrants get thrown
# out in a four-minute pile-up at the end. That is not a Rumble, it is a series
# of singles matches.
#
# Making the rate depend on ring size gives it the shape it should have. Below
# four the mean is 0.33 so the ring fills; from seven up the mean exceeds one so
# it thins; the equilibrium sits around eight or nine bodies, which is what a real
# Rumble looks like in its middle third.
ELIMS_BY_CROWD = (
    (3, (0, 0, 1)),
    (6, (0, 1, 1)),
    (9, (1, 1, 2)),
    (99, (1, 2, 2, 3)),
)


def _elim_count(rng: random.Random, ring_size: int) -> int:
    for cap, dist in ELIMS_BY_CROWD:
        if ring_size <= cap:
            return rng.choice(dist)
    return 1

# How much each rating counts toward staying in. Wrestling dominates; Achievements
# earns real weight because a Rumble protects the people who have won things.
SURVIVAL_WEIGHTS = {"wrestling": 0.52, "achievements": 0.22, "popularity": 0.18,
                    "personal": 0.08}

# Nobody is unthrowable. Without a floor a 20-Wrestling entrant would be
# mathematically safe against a field of rookies, and the match would stop being
# a match.
MIN_SURVIVAL_WEIGHT = 0.6

# Iron-woman bonus: surviving the whole thing from an early number is a feat, and
# the sim already has an accolade for it.
IRON_WOMAN_FROM_NUMBER = 5


def _rng(seed: int, show_id: int) -> random.Random:
    """One stream per Rumble, derived from the save seed — see sim._rng."""
    return random.Random((seed * 1_000_003) ^ (show_id * 7_919) ^ 0x52554D42)


def _survival(attrs: dict) -> float:
    return max(MIN_SURVIVAL_WEIGHT,
               sum(attrs[k] * w for k, w in SURVIVAL_WEIGHTS.items()))


def _pick_out(rng: random.Random, ring: list[int], weights: dict[int, float]) -> int:
    """Choose who gets thrown out. Weighted INVERSELY to survival."""
    inv = [1.0 / weights[w] for w in ring]
    total = sum(inv)
    roll = rng.random() * total
    acc = 0.0
    for wid, chance in zip(ring, inv):
        acc += chance
        if roll <= acc:
            return wid
    return ring[-1]


def simulate(
    con: sqlite3.Connection,
    entrants: list[int],
    name: str = "Royal Rumble",
    held_on: str | None = None,
    brand_id: str | None = None,
) -> dict:
    """Run a Rumble and persist it. Returns the entry order and the full timeline.

    Persists a `show` row so the match appears in history like any other, awards
    `royal_rumble` to the winner (which moves her Achievements immediately), and
    credits an `iron_woman` accolade to a winner who went the distance from an
    early number.
    """
    state = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if state is None:
        raise game.SigningError("no active save — start a new game first")

    order = list(dict.fromkeys(entrants))          # de-dupe, keep the given order
    if len(order) != len(entrants):
        raise game.SigningError("a wrestler cannot be in the Rumble twice")
    if len(order) < MIN_FIELD:
        raise game.SigningError(f"a Rumble needs at least {MIN_FIELD} entrants")
    if len(order) > FULL_FIELD:
        raise game.SigningError(f"a Rumble holds at most {FULL_FIELD} entrants")

    held_on = held_on or state["current_date"]
    missing = [w for w in order if not con.execute(
        "SELECT 1 FROM wrestler WHERE id=?", (w,)).fetchone()]
    if missing:
        raise game.SigningError(f"no such wrestler: {missing[:4]}")

    cur = con.execute(
        "INSERT INTO show (brand_id, name, held_on, is_ppv, ppv_name) VALUES (?,?,?,1,?)",
        (brand_id, name, held_on, name))
    show_id = cur.lastrowid
    rng = _rng(state["rng_seed"], show_id)

    ach = game.achievement_inputs(con)
    attrs = {w: game.effective_attributes(con, w, ach.get(w)) for w in order}
    weights = {w: _survival(attrs[w]) for w in order}

    ring: list[int] = [order[0], order[1]]
    entered_at = {order[0]: 0, order[1]: 0}
    timeline: list[dict] = [
        {"t": 0, "kind": "enter", "wrestler_id": order[0], "number": 1},
        {"t": 0, "kind": "enter", "wrestler_id": order[1], "number": 2},
    ]
    elims: dict[int, int] = {w: 0 for w in order}
    lasted: dict[int, int] = {}

    def throw_out(t: int, by: int | None) -> None:
        victim = _pick_out(rng, ring, weights)
        ring.remove(victim)
        lasted[victim] = t - entered_at[victim]
        if by is not None and by != victim:
            elims[by] += 1
        timeline.append({"t": t, "kind": "out", "wrestler_id": victim,
                         "by": by if by != victim else None})

    # Each entrant after the first two arrives at the top of an interval; the
    # eliminations for that interval happen just before she gets there.
    for i, wid in enumerate(order[2:], start=3):
        t = (i - 2) * ENTRY_GAP
        for _ in range(_elim_count(rng, len(ring))):
            if len(ring) <= 1:
                break
            # The thrower is drawn from the ring, favouring the strong.
            candidates = [w for w in ring]
            by = rng.choices(candidates, weights=[weights[w] for w in candidates])[0]
            throw_out(t, by)
        ring.append(wid)
        entered_at[wid] = t
        timeline.append({"t": t, "kind": "enter", "wrestler_id": wid, "number": i})

    # Everyone is in; run it down to one.
    t = (len(order) - 1) * ENTRY_GAP
    while len(ring) > 1:
        t += ENTRY_GAP // 2
        candidates = [w for w in ring]
        by = rng.choices(candidates, weights=[weights[w] for w in candidates])[0]
        throw_out(t, by)

    winner = ring[0]
    lasted[winner] = t - entered_at[winner]
    timeline.append({"t": t, "kind": "win", "wrestler_id": winner})

    # A Rumble is a match, so it belongs in the match record — otherwise it is
    # invisible to the Power 25, the season grade and every "what happened this
    # year" query in the app.
    quality = min(100.0, 58.0 + len(order) * 0.7
                  + attrs[winner]["wrestling"] * 0.9)
    mcur = con.execute(
        "INSERT INTO sim_match (show_id, slot, quality, finish, stipulation) "
        "VALUES (?,?,?,?,?)",
        (show_id, 1, round(quality, 1), "rumble", f"{len(order)}-woman Royal Rumble"))
    match_id = mcur.lastrowid
    for w in order:
        con.execute(
            "INSERT INTO sim_match_participant (match_id, wrestler_id, team, is_winner) "
            "VALUES (?,?,?,?)", (match_id, w, 0, 1 if w == winner else 0))
        con.execute("INSERT OR IGNORE INTO wrestler_state (wrestler_id) VALUES (?)", (w,))
        con.execute(
            "UPDATE wrestler_state SET sim_matches = sim_matches + 1, "
            "sim_wins = sim_wins + ?, sim_losses = sim_losses + ?, "
            "ppv_appearances = ppv_appearances + 1 WHERE wrestler_id = ?",
            (1 if w == winner else 0, 0 if w == winner else 1, w))

    con.execute("UPDATE show SET rating=?, attendance=? WHERE id=?",
                (round(quality, 1), int(9_000 + len(order) * 420), show_id))

    # The payoff. This is the whole reason the match exists.
    game.award(con, winner, "royal_rumble", state["season_year"],
               f"won the {len(order)}-woman {name} from number {order.index(winner) + 1}")
    iron = order.index(winner) + 1 <= IRON_WOMAN_FROM_NUMBER
    if iron:
        game.award(con, winner, "iron_woman", state["season_year"],
                   f"went the distance from number {order.index(winner) + 1}")

    most = max(elims.items(), key=lambda kv: kv[1])
    game.log_event(
        con, "award",
        f"{game._wname(con, winner)} wins the {name} from number "
        f"{order.index(winner) + 1}, last eliminating "
        f"{game._wname(con, timeline[-2]['wrestler_id'])}.", brand_id, "🏆")
    con.commit()

    def row(wid: int) -> dict:
        return {"wrestler_id": wid, "name": game._wname(con, wid),
                "number": order.index(wid) + 1,
                "eliminations": elims[wid], "lasted": lasted.get(wid, 0)}

    return {
        "show_id": show_id, "match_id": match_id, "name": name, "held_on": held_on,
        "entrants": [row(w) for w in order],
        "timeline": [{**e, "name": game._wname(con, e["wrestler_id"]),
                      "by_name": game._wname(con, e["by"]) if e.get("by") else None}
                     for e in timeline],
        "winner": row(winner),
        "iron_woman": iron,
        "most_eliminations": row(most[0]) if most[1] else None,
        "quality": round(quality, 1),
    }


def suggest_field(con: sqlite3.Connection, size: int = FULL_FIELD) -> list[dict]:
    """A sensible default field: the best healthy signed wrestlers available.

    Exists so the Rumble is one click from playable. Ordered by overall so the
    strongest go in last, which is both how it is really booked and what makes
    the entry numbers mean something.
    """
    state = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if state is None:
        return []
    season, today = state["season_year"], state["current_date"]
    ids = [r[0] for r in con.execute(
        """SELECT c.wrestler_id FROM contract c
             JOIN attributes a ON a.wrestler_id = c.wrestler_id
             LEFT JOIN attribute_override o ON o.wrestler_id = c.wrestler_id
             LEFT JOIN wrestler_state s ON s.wrestler_id = c.wrestler_id
            WHERE c.terminated_on IS NULL AND c.start_year<=? AND c.end_year>=?
              AND c.role='wrestler'
              AND COALESCE(o.role, a.role) <> 'manager'
              AND (s.injured_until IS NULL OR s.injured_until <= ?)""",
        (season, season, today))]
    ach = game.achievement_inputs(con)
    ranked = sorted(ids, key=lambda w: game.effective_attributes(con, w, ach.get(w))["overall"])
    picked = ranked[-size:] if len(ranked) > size else ranked
    return [{"wrestler_id": w, "name": game._wname(con, w),
             "overall": game.effective_attributes(con, w, ach.get(w))["overall"]}
            for w in picked]
