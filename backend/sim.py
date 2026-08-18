"""Phase 3 — the simulation core.

Deterministic by construction: every roll comes from a seeded RNG whose seed is
derived from (save seed, show id, match slot). The same booking on the same save
always produces the same show, which makes results reproducible and bugs
findable. No AI in this layer — Groq writes narrative on top of what happens
here, it never decides who wins.

Match quality and outcomes read the four rating categories:

    Experience  ring generalship. Drives quality hardest, and it is EARNED —
                everyone starts at 0, so early shows are deliberately rough.
    Charisma    crowd connection. Lifts quality and heat.
    Popularity  draw. Drives heat and attendance more than match quality.
    Looks       presentation. A modest contributor.
"""

from __future__ import annotations

import math
import random
import sqlite3
from datetime import date, datetime, timedelta

import game
import booking
import rankings

# How much each category contributes to in-ring match quality.
QUALITY_WEIGHTS = {"experience": 0.45, "charisma": 0.30, "looks": 0.10, "popularity": 0.15}

# How much each contributes to crowd heat (how much they care).
HEAT_WEIGHTS = {"popularity": 0.50, "charisma": 0.30, "experience": 0.12, "looks": 0.08}

BASE_INJURY_CHANCE = 0.012
FATIGUE_PER_MATCH = 9
FATIGUE_RECOVERY_PER_DAY = 4

# Good vs evil sells. A match with a face AND a heel tells a cleaner story and
# draws better; an all-face or all-heel match has no natural conflict.
FACE_HEEL_BONUS = 5
SAME_ALIGN_PENALTY = -3

# A pay-per-view is the big stage: the workers rise to it and the house is hot.
PPV_QUALITY_BONUS = 7
PPV_ATTENDANCE_MULT = 2.6


def stars_from_quality(quality: float) -> float:
    """0–100 quality → a 0–5 star rating in half-star steps (Meltzer style)."""
    return max(0.0, min(5.0, round(quality / 20 * 2) / 2))

# ---------------------------------------------------------------- style clash
#
# Every worker has a style (cagematch's, e.g. "Technician, High Flyer"). Some
# pairings tell themselves — a technician bumping for a high flyer, a monster
# throwing a cruiserweight around — and some grind (two powerhouses plodding
# through a match nobody asked for). Chemistry is a QUALITY modifier in points,
# averaged over every pair of workers in the match. It never touches who wins.
#
# Keys are the primary style token; an unknown/missing style is treated as
# "Allrounder", which adapts to anyone rather than being punished for missing
# data — the same principle the roster uses everywhere else.
STYLE_CANON = {
    "technician": "Technician", "high flyer": "High Flyer", "highflyer": "High Flyer",
    "powerhouse": "Powerhouse", "brawler": "Brawler", "hardcore": "Hardcore",
    "allrounder": "Allrounder",
}

def _canon_style(style: str | None) -> str:
    if not style:
        return "Allrounder"
    first = style.split(",")[0].strip().lower()
    return STYLE_CANON.get(first, "Allrounder")

# Symmetric chemistry table, in quality points. Positive = the styles mesh.
_CHEM: dict[frozenset, float] = {
    frozenset({"Technician", "High Flyer"}): 6,
    frozenset({"Technician", "Brawler"}): 3,
    frozenset({"Technician", "Powerhouse"}): 1,
    frozenset({"Technician", "Hardcore"}): -1,
    frozenset({"Technician"}): 3,
    frozenset({"High Flyer", "Powerhouse"}): 5,
    frozenset({"High Flyer", "Brawler"}): -2,
    frozenset({"High Flyer", "Hardcore"}): -3,
    frozenset({"High Flyer"}): 2,
    frozenset({"Powerhouse", "Brawler"}): 2,
    frozenset({"Powerhouse", "Hardcore"}): 1,
    frozenset({"Powerhouse"}): -6,
    frozenset({"Brawler", "Hardcore"}): 5,
    frozenset({"Brawler"}): 2,
    frozenset({"Hardcore"}): 4,
}

def style_chemistry(styles: list[str | None]) -> float:
    """Average pairwise chemistry across everyone in the match, in quality points."""
    canon = [_canon_style(s) for s in styles]
    pairs, total = 0, 0.0
    for i in range(len(canon)):
        for j in range(i + 1, len(canon)):
            a, b = canon[i], canon[j]
            if "Allrounder" in (a, b):
                total += 2.0            # adapts to anyone
            else:
                total += _CHEM.get(frozenset({a, b}), 0.0)
            pairs += 1
    return total / pairs if pairs else 0.0

# ---------------------------------------------------------------- morale & prestige

# Morale swings after a match; a happy locker room works harder, a buried one
# coasts. Values are deltas applied in _apply_match, clamped to 0-100.
MORALE = {
    "win": 4, "loss": -3, "draw": 1,
    "title_win": 8, "title_loss": -6,
    "main_event": 2, "jobbed": -2,     # jobbed = clean loss in the opener
    "idle": -1,                        # left off the show entirely
}
MORALE_DEFAULT = 50

# A title match is worth more the more the belt means. Replaces a flat bonus.
PRESTIGE_QUALITY_SCALE = 0.09     # world belt (85) -> +7.6 quality, secondary (60) -> +5.4
PRESTIGE_HEAT_SCALE = 0.08
# Prestige eases toward the quality of the belt's matches, but ASYMMETRICALLY:
# a classic lifts it quickly, a stinker only chips at it — and it never falls
# below the floor its tier commands, so a green early roster cannot vaporise the
# meaning of the world title. As experience is earned and matches improve, the
# belt climbs back on its own.
PRESTIGE_RISE = 0.12
PRESTIGE_FALL = 0.04
PRESTIGE_HOTSHOT_PENALTY = 4      # a title change on a weak match cheapens the belt
PRESTIGE_FLOOR = {
    "world": 70, "secondary": 48, "tag": 52,
    "cruiserweight": 44, "hardcore": 44, "manager": 46,
}


def _rng(seed: int, show_id: int, slot: int) -> random.Random:
    """One independent stream per match, derived from the save seed.

    Deriving rather than sharing a single generator means re-simulating match 3
    cannot shift the results of match 4.
    """
    return random.Random((seed * 1_000_003) ^ (show_id * 9_176) ^ (slot * 31))


def _score(attrs: dict, weights: dict) -> float:
    return sum(attrs[k] * w for k, w in weights.items())


def _clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, v))


def participants_attrs(con: sqlite3.Connection, wrestler_ids: list[int]) -> dict[int, dict]:
    return {wid: game.effective_attributes(con, wid) for wid in wrestler_ids}


def simulate_match(
    con: sqlite3.Connection,
    show_id: int,
    slot: int,
    teams: list[list[int]],
    seed: int,
    title_id: int | None = None,
    is_ppv: bool = False,
    stipulation: str | None = None,
    prod_bonus: float = 0.0,
) -> dict:
    """Resolve one match. `teams` is a list of sides, each a list of wrestler ids.

    Returns the result WITHOUT writing it — the caller commits, so a whole show
    can be simulated and inspected before anything is persisted.
    """
    if len(teams) < 2 or any(not t for t in teams):
        raise ValueError("a match needs at least two non-empty sides")

    rng = _rng(seed, show_id, slot)
    everyone = [w for t in teams for w in t]
    attrs = participants_attrs(con, everyone)

    state = {
        wid: con.execute("SELECT * FROM wrestler_state WHERE wrestler_id=?", (wid,)).fetchone()
        for wid in everyone
    }
    styles = {
        wid: con.execute("SELECT style FROM wrestler WHERE id=?", (wid,)).fetchone()["style"]
        for wid in everyone
    }
    prestige = 50
    title_tier = None
    if title_id:
        row = con.execute("SELECT prestige, tier FROM game_title WHERE id=?", (title_id,)).fetchone()
        if row and row["prestige"] is not None:
            prestige = row["prestige"]
            title_tier = row["tier"]

    def morale_of(wid: int) -> int:
        m = state[wid]["morale"] if "morale" in state[wid].keys() else None
        return MORALE_DEFAULT if m is None else m

    # --- team strength -----------------------------------------------------
    # Best wrestler on a side carries it, with diminishing help from partners:
    # a great singles worker plus a rookie is stronger than two mediocre hands,
    # but not by the sum of their parts.
    team_strength = []
    for t in teams:
        scores = sorted((_score(attrs[w], QUALITY_WEIGHTS) for w in t), reverse=True)
        s = scores[0] + sum(v * 0.35 / (i + 1) for i, v in enumerate(scores[1:], start=1))
        momentum = sum(state[w]["momentum"] for w in t) / len(t)
        fatigue = sum(state[w]["fatigue"] for w in t) / len(t)
        morale = sum(morale_of(w) for w in t) / len(t)
        # Morale is a modest thumb on the scale: a motivated side (100) is ~8%
        # stronger, a demoralised one (0) ~8% weaker. It can swing a close match
        # but never overturns a real talent gap.
        s = s * (0.85 + momentum / 333) * (1 - fatigue / 400) * (0.92 + morale / 625)
        team_strength.append(max(1.0, s))

    # --- outcome -----------------------------------------------------------
    # Softmax over strength so a stronger side is favoured but never certain;
    # the temperature keeps upsets live without making results random.
    temp = 14.0
    weights = [math.exp(s / temp) for s in team_strength]
    total = sum(weights)
    roll = rng.random() * total
    winner_idx, acc = 0, 0.0
    for i, w in enumerate(weights):
        acc += w
        if roll <= acc:
            winner_idx = i
            break

    stip = booking.stip(stipulation)
    draw = rng.random() < 0.04
    if stip["no_dq"]:
        # No-DQ stipulations can't end on a DQ or countout — it's anything goes.
        finish = "draw" if draw else rng.choices(["pinfall", "submission"], weights=[75, 25])[0]
    else:
        finish = "draw" if draw else rng.choices(
            ["pinfall", "submission", "dq", "countout"], weights=[68, 20, 7, 5])[0]

    # --- quality -----------------------------------------------------------
    q_scores = [_score(attrs[w], QUALITY_WEIGHTS) for w in everyone]
    avg_q = sum(q_scores) / len(q_scores)
    best_q = max(q_scores)
    # The best worker in the match pulls the floor up — that is what carrying is.
    base = avg_q * 0.65 + best_q * 0.35

    heat = sum(_score(attrs[w], HEAT_WEIGHTS) for w in everyone) / len(everyone)

    # Style chemistry: the workers either tell a story together or grind. Points.
    chemistry = style_chemistry([styles[w] for w in everyone])

    # Face vs heel: a clear good-vs-evil match tells itself; all-face/all-heel
    # matches lack that conflict.
    aligns = {attrs[w].get("alignment", "face") for w in everyone}
    if "face" in aligns and "heel" in aligns:
        alignment_bonus = FACE_HEEL_BONUS
    else:
        alignment_bonus = SAME_ALIGN_PENALTY

    # Morale of the whole match — a motivated card just goes better.
    avg_morale = sum(morale_of(w) for w in everyone) / len(everyone)
    morale_bonus = (avg_morale - MORALE_DEFAULT) * 0.06     # ±3 points

    # Rivalry heat: a match between two wrestlers in an active feud means more,
    # and a high-heat blow-off is the payoff — a real quality lift.
    feud_bonus = 0.0
    feud_heat = 0
    for ti in range(len(teams)):
        for tj in range(ti + 1, len(teams)):
            for a in teams[ti]:
                for b in teams[tj]:
                    f = game.feud_between(con, a, b)
                    if f and f["heat"] > feud_heat:
                        feud_heat = f["heat"]
    if feud_heat:
        feud_bonus = feud_heat * 0.10 + (5 if feud_heat >= game.FEUD_BLOWOFF_HEAT else 0)

    variance = rng.gauss(0, 6)
    slot_bonus = min(6, slot * 0.8)          # later on the card means more time
    # A title match is worth more the more the belt means, and a prestigious
    # belt also draws a hotter crowd.
    title_bonus = prestige * PRESTIGE_QUALITY_SCALE if title_id else 0
    heat += prestige * PRESTIGE_HEAT_SCALE if title_id else 0
    ppv_bonus = PPV_QUALITY_BONUS if is_ppv else 0
    if is_ppv:
        heat += 6                                # a hot pay-per-view crowd
    dq_penalty = -8 if finish in ("dq", "countout") else 0

    quality = _clamp(base * 0.78 + heat * 0.18 + variance + slot_bonus
                     + title_bonus + chemistry + morale_bonus
                     + alignment_bonus + ppv_bonus + dq_penalty + feud_bonus
                     + stip["quality"] + prod_bonus)

    # --- injuries ----------------------------------------------------------
    injured = []
    for wid in everyone:
        chance = BASE_INJURY_CHANCE * (1 + state[wid]["fatigue"] / 120)
        age = attrs[wid].get("age")
        if age:
            chance *= 1 + max(0, age - 35) * 0.03
        if rng.random() < chance:
            injured.append({"wrestler_id": wid, "weeks": rng.randint(2, 10)})

    return {
        "slot": slot,
        "teams": teams,
        "winner_team": None if draw else winner_idx,
        "winners": [] if draw else teams[winner_idx],
        "losers": [] if draw else [w for i, t in enumerate(teams) if i != winner_idx for w in t],
        "finish": finish,
        "quality": round(quality, 1),
        "stars": stars_from_quality(quality),
        "heat": round(heat, 1),
        "chemistry": round(chemistry, 1),
        "alignment_bonus": alignment_bonus,
        "title_id": title_id,
        "title_tier": title_tier,
        "title_prestige": prestige if title_id else None,
        "stipulation": stipulation,
        "injured": injured,
    }


def _apply_match(con: sqlite3.Connection, show_id: int, held_on: str, res: dict) -> int:
    cur = con.execute(
        "INSERT INTO sim_match (show_id, slot, title_id, quality, finish, stipulation) "
        "VALUES (?,?,?,?,?,?)",
        (show_id, res["slot"], res["title_id"], res["quality"], res["finish"],
         res.get("stipulation")),
    )
    match_id = cur.lastrowid

    for ti, team in enumerate(res["teams"]):
        for wid in team:
            won = 1 if res["winner_team"] == ti else 0
            con.execute(
                "INSERT INTO sim_match_participant (match_id, wrestler_id, team, is_winner) "
                "VALUES (?,?,?,?)", (match_id, wid, ti, won),
            )

    everyone = [w for t in res["teams"] for w in t]
    is_main = res.get("is_main_event", False)
    # A manager belt is decided by the wrestlers but held by their managers, so
    # the wrestlers themselves get no personal title-morale swing for it.
    is_title = res["title_id"] is not None
    is_wrestler_title = is_title and res.get("title_tier") != "manager"
    for wid in everyone:
        won = wid in res["winners"]
        lost = wid in res["losers"]

        # Morale: winning lifts it, losing dents it, and the context matters —
        # winning a belt is a high, being pinned clean in the opener is a low.
        dm = MORALE["draw"] if res["finish"] == "draw" else (MORALE["win"] if won else MORALE["loss"])
        if is_wrestler_title and res["finish"] in ("pinfall", "submission"):
            dm += MORALE["title_win"] if won else (MORALE["title_loss"] if lost else 0)
        if is_main:
            dm += MORALE["main_event"]
        elif lost and res["slot"] == 1 and res["finish"] in ("pinfall", "submission"):
            dm += MORALE["jobbed"]

        con.execute(
            """UPDATE wrestler_state SET
                 sim_matches = sim_matches + 1,
                 sim_wins    = sim_wins   + ?,
                 sim_losses  = sim_losses + ?,
                 sim_draws   = sim_draws  + ?,
                 fatigue     = MIN(100, fatigue + ?),
                 momentum    = MAX(0, MIN(100, momentum + ?)),
                 morale      = MAX(0, MIN(100, morale + ?))
               WHERE wrestler_id = ?""",
            (1 if won else 0, 1 if lost else 0, 1 if res["finish"] == "draw" else 0,
             FATIGUE_PER_MATCH,
             8 if won else (-6 if lost else 0),
             dm,
             wid),
        )

    for inj in res["injured"]:
        until = (date.fromisoformat(held_on) + timedelta(weeks=inj["weeks"])).isoformat()
        con.execute("UPDATE wrestler_state SET injured_until=? WHERE wrestler_id=?",
                    (until, inj["wrestler_id"]))
        game.log_event(con, "injury",
                       f"{game._wname(con, inj['wrestler_id'])} is hurt — out about {inj['weeks']} weeks.",
                       icon="🩹")

    # Rivalry heat: everyone who worked an opponent they're feuding with heats it up.
    bumped = set()
    for ti in range(len(res["teams"])):
        for tj in range(ti + 1, len(res["teams"])):
            for a in res["teams"][ti]:
                for b in res["teams"][tj]:
                    f = game.feud_between(con, a, b)
                    if f and f["id"] not in bumped:
                        game.bump_feud_heat(con, f["id"], game.FEUD_HEAT_PER_MATCH)
                        bumped.add(f["id"])

    # Title changes only on a clean finish — a DQ or countout keeps the belt.
    # For a manager belt the new holder is the winning side's MANAGER, resolved
    # in run_show and passed as title_holder; for every other belt it is the
    # wrestler who won.
    changed_hands = False
    new_champ = res.get("title_holder")
    if new_champ is None and res["winners"]:
        new_champ = res["winners"][0]
    if res["title_id"] and new_champ and res["finish"] in ("pinfall", "submission"):
        champ = con.execute(
            "SELECT * FROM game_title_reign WHERE title_id=? AND lost_on IS NULL",
            (res["title_id"],),
        ).fetchone()
        if champ is None or champ["wrestler_id"] != new_champ:
            changed_hands = True
            if champ:
                con.execute("UPDATE game_title_reign SET lost_on=? WHERE id=?",
                            (held_on, champ["id"]))
            con.execute(
                "INSERT INTO game_title_reign (title_id, wrestler_id, won_on, won_at_match) "
                "VALUES (?,?,?,?)", (res["title_id"], new_champ, held_on, match_id),
            )
            # A new champion banks a title bonus — real money on top of the cap.
            game.pay_bonus(con, new_champ,
                           game.TITLE_BONUS.get(res.get("title_tier") or "", 60_000),
                           morale=0)
            tname = con.execute("SELECT name FROM game_title WHERE id=?",
                                (res["title_id"],)).fetchone()
            game.log_event(con, "title",
                           f"{game._wname(con, new_champ)} wins the {tname['name'] if tname else 'title'}!",
                           icon="🏆")

    # Prestige drifts toward the quality of the matches the belt headlines: put
    # it in classics and it grows, protect it with stinkers and it withers. A
    # title change on a weak match (a hotshot) cheapens it on top of that.
    if res["title_id"]:
        cur = con.execute("SELECT prestige, tier FROM game_title WHERE id=?",
                          (res["title_id"],)).fetchone()
        if cur and cur["prestige"] is not None:
            p0 = cur["prestige"]
            rate = PRESTIGE_RISE if res["quality"] > p0 else PRESTIGE_FALL
            p = p0 + (res["quality"] - p0) * rate
            if changed_hands and res["quality"] < p0 - 5:
                p -= PRESTIGE_HOTSHOT_PENALTY
            floor = PRESTIGE_FLOOR.get(cur["tier"], 40)
            con.execute("UPDATE game_title SET prestige=? WHERE id=?",
                        (int(max(floor, min(100, round(p)))), res["title_id"]))
    return match_id


def run_show(
    con: sqlite3.Connection,
    brand_id: str,
    name: str,
    card: list[dict],
    held_on: str | None = None,
    is_ppv: bool = False,
    ppv_name: str | None = None,
    logistics: dict | None = None,
) -> dict:
    """Simulate and persist a full show.

    `card` is an ordered list of {"teams": [[id,...],[id,...]], "title_id": int|None,
    "stipulation": str|None}. `logistics` (arena/production/effects/advertising)
    spends money for a bigger, better show and settles the week's finances.
    """
    state = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if state is None:
        raise ValueError("no active save — start a new game first")
    held_on = held_on or state["current_date"]
    seed = state["rng_seed"]
    ls = booking.logistics_summary(logistics)
    prod_bonus = ls["quality"]

    if not card:
        raise ValueError("a show needs at least one match")

    booked = [w for m in card for t in m["teams"] for w in t]
    if len(booked) != len(set(booked)):
        raise ValueError("a wrestler is booked in more than one match on this card")

    # A Manager's Championship match is two wrestlers fighting on behalf of two
    # managers — validate the managers up front so a half-booked belt match never
    # reaches the sim.
    for m in card:
        if not m.get("title_id"):
            continue
        t = con.execute("SELECT tier, name FROM game_title WHERE id=?", (m["title_id"],)).fetchone()
        if t and t["tier"] == "manager":
            mgrs = m.get("managers") or []
            if len(mgrs) != len(m["teams"]) or any(not x for x in mgrs):
                raise ValueError(f"{t['name']} needs a manager assigned to each side")
            if len(set(mgrs)) != len(mgrs):
                raise ValueError("a manager cannot represent both sides")
            for mid in mgrs:
                c = con.execute(
                    """SELECT 1 FROM contract WHERE wrestler_id=? AND terminated_on IS NULL
                       AND role='manager' AND start_year<=? AND end_year>=?""",
                    (mid, state["season_year"], state["season_year"])).fetchone()
                if not c:
                    nm = con.execute("SELECT name FROM wrestler WHERE id=?", (mid,)).fetchone()
                    raise ValueError(f"{nm[0] if nm else mid} is not a signed manager")

    for wid in booked:
        s = con.execute("SELECT injured_until FROM wrestler_state WHERE wrestler_id=?",
                        (wid,)).fetchone()
        if s and s["injured_until"] and s["injured_until"] > held_on:
            nm = con.execute("SELECT name FROM wrestler WHERE id=?", (wid,)).fetchone()[0]
            raise ValueError(f"{nm} is injured until {s['injured_until']}")

    # Money gate for the booking screen: you can't spend past your budget.
    cost = booking.show_cost(card, logistics) if logistics is not None else 0
    if logistics is not None:
        budget = booking.brand_cash(con, brand_id) + booking.stipend(con, brand_id)
        if cost > budget:
            raise ValueError(f"This show costs ${cost:,} but only ${budget:,} is available "
                             f"— trim the card or the production.")
    show_count = con.execute("SELECT COUNT(*) FROM show WHERE brand_id=?", (brand_id,)).fetchone()[0]
    city = booking.CITIES[(seed + show_count) % len(booking.CITIES)]

    cur = con.execute(
        "INSERT INTO show (brand_id, name, held_on, is_ppv, ppv_name, city, cost) "
        "VALUES (?,?,?,?,?,?,?)",
        (brand_id, name, held_on, 1 if is_ppv else 0, ppv_name, city, cost)
    )
    show_id = cur.lastrowid

    results = []
    for slot, m in enumerate(card, start=1):
        res = simulate_match(con, show_id, slot, m["teams"], seed, m.get("title_id"),
                             is_ppv=is_ppv, stipulation=m.get("stipulation"), prod_bonus=prod_bonus)
        res["is_main_event"] = (slot == len(card))
        # Manager belt: the winning side's manager becomes/stays champion.
        if res.get("title_tier") == "manager" and m.get("managers") and res["winner_team"] is not None:
            mgrs = m["managers"]
            if res["winner_team"] < len(mgrs):
                res["title_holder"] = mgrs[res["winner_team"]]
        _apply_match(con, show_id, held_on, res)
        results.append(res)

    # The main event counts double toward how the night is remembered.
    qualities = [r["quality"] for r in results]
    weights = [1.0] * (len(qualities) - 1) + [2.0]
    show_rating = sum(q * w for q, w in zip(qualities, weights)) / sum(weights)

    # Attendance & finances. A booked show (logistics present) draws its house
    # from the fanbase/arena model and settles the week's money; a quick auto/AI
    # show keeps the simple heat-based house and touches no money.
    ledger = None
    if logistics is not None:
        ledger = booking.settle(con, brand_id, card, logistics, show_rating)
        attendance = ledger["attendance"]
    else:
        avg_heat = sum(r["heat"] for r in results) / len(results)
        attendance = int(2_000 + avg_heat * 190 + show_rating * 55)
        if is_ppv:
            attendance = int(attendance * PPV_ATTENDANCE_MULT)

    con.execute("UPDATE show SET rating=?, attendance=? WHERE id=?",
                (round(show_rating, 1), attendance, show_id))

    # PPV appearances are a career milestone — credit everyone who worked it.
    if is_ppv and booked:
        con.execute(
            "UPDATE wrestler_state SET ppv_appearances = ppv_appearances + 1 "
            f"WHERE wrestler_id IN ({','.join('?' * len(booked))})", booked)

    # Everyone not booked recovers a little — but a wrestler left off her own
    # brand's show entirely loses a touch of morale (nobody likes catering duty).
    # Wrestlers on the OTHER brand are simply not on this show and are untouched.
    on_this_brand = [r[0] for r in con.execute(
        """SELECT c.wrestler_id FROM contract c
           WHERE c.brand_id=? AND c.terminated_on IS NULL
             AND c.start_year<=? AND c.end_year>=?""",
        (brand_id, state["season_year"], state["season_year"]),
    )]
    idle = [w for w in on_this_brand if w not in booked]
    con.execute(
        "UPDATE wrestler_state SET fatigue = MAX(0, fatigue - ?) WHERE wrestler_id NOT IN "
        f"({','.join('?' * len(booked))})",
        [FATIGUE_RECOVERY_PER_DAY * 7] + booked,
    )
    if idle:
        con.execute(
            "UPDATE wrestler_state SET morale = MAX(0, MIN(100, morale + ?)) "
            f"WHERE wrestler_id IN ({','.join('?' * len(idle))})",
            [MORALE["idle"]] + idle,
        )
    if ledger:
        game.log_event(con, "show",
                       f"{name} in {city} drew {attendance:,} — net ${ledger['net']:,}, "
                       f"fanbase {'+' if ledger['fan_change'] >= 0 else ''}{ledger['fan_change']:,}.",
                       brand_id, "🎪")
    con.commit()

    # A show is what a week of television IS, so the Power 25 is republished the
    # moment one is in the books. Wrapped: a ranking failure must never lose a
    # show that has already been simulated and committed.
    try:
        rankings.generate_issue(con, held_on)
    except Exception as e:                                   # noqa: BLE001
        game.log_event(con, "ratings", f"Power 25 could not be rebuilt: {e}", icon="⚠️")
        con.commit()

    return {
        "show_id": show_id, "name": name, "brand_id": brand_id, "held_on": held_on,
        "rating": round(show_rating, 1), "attendance": attendance, "city": city, "cost": cost,
        "is_ppv": is_ppv, "ppv_name": ppv_name, "matches": results, "ledger": ledger,
    }


def auto_card(con: sqlite3.Connection, brand_id: str, matches: int = 4) -> list[dict]:
    """Build a plausible card from the brand's healthy roster.

    Pairs by overall so matches are competitive, and puts the strongest available
    pairing on last. Used for quick sims and as the rival GM's booking until the
    Groq layer takes that over.
    """
    state = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    season, today = state["season_year"], state["current_date"]

    roster = [r[0] for r in con.execute(
        """SELECT c.wrestler_id FROM contract c
           JOIN wrestler_state s ON s.wrestler_id = c.wrestler_id
           WHERE c.brand_id=? AND c.terminated_on IS NULL
             AND c.start_year<=? AND c.end_year>=?
             AND (s.injured_until IS NULL OR s.injured_until <= ?)""",
        (brand_id, season, season, today),
    )]
    if len(roster) < 2:
        raise ValueError(f"{brand_id} needs at least 2 healthy wrestlers under contract")

    ranked = sorted(roster, key=lambda w: game.effective_attributes(con, w)["overall"], reverse=True)
    pairs = []
    pool = ranked[:]
    while len(pool) >= 2 and len(pairs) < matches:
        a = pool.pop(0)
        b = pool.pop(0)
        pairs.append({"teams": [[a], [b]], "title_id": None})

    # Pairing top-down puts the best wrestlers in the FIRST pair, so the card has
    # to be reversed — the main event goes on last, and the belt goes on the main
    # event. Without this the title match is the two weakest workers on the show.
    pairs.reverse()

    if pairs:
        title = con.execute("SELECT id FROM game_title WHERE brand_id=?", (brand_id,)).fetchone()
        if title:
            pairs[-1]["title_id"] = title["id"]
    return pairs
