"""Phase 3 — the simulation core.

Deterministic by construction: every roll comes from a seeded RNG whose seed is
derived from (save seed, show id, match slot). The same booking on the same save
always produces the same show, which makes results reproducible and bugs
findable. No AI in this layer — Groq writes narrative on top of what happens
here, it never decides who wins.

Match quality and outcomes read the five rating categories:

    Wrestling     ring ability. Drives quality hardest. Unlike the `experience`
                  it replaced it does NOT start at zero, so an opening-night card
                  is separated by who is actually in it.
    Achievements  what she has won in this save. Small on quality, real on heat —
                  this is the loop that makes a title reign build somebody.
    Popularity    draw. Drives heat and attendance more than match quality.
    Looks         presentation. A modest contributor.
    Personal      your own read on her. Deliberately given weight, so the sim
                  does not quietly disagree with the GM.
"""

from __future__ import annotations

import math
import random
import sqlite3
from datetime import date, datetime, timedelta

import game
import booking
import brandwar
import crowd
import matches as MT
import medical
import promos as PR
import rankings
import storylines

# How much each category contributes to in-ring match quality.
#
# Wrestling dominates, which is the point of the category existing: under the old
# weights this was `experience`, which everyone started on 0, so a debut card was
# a wall of identical two-star matches no matter who was in it. Achievements
# counts a little — a champion has been trusted in big matches and works like it —
# and Personal counts a little because it is YOUR read on her and the sim should
# not silently disagree with you.
QUALITY_WEIGHTS = {"wrestling": 0.60, "popularity": 0.22, "achievements": 0.10,
                   "looks": 0.04, "personal": 0.04}

# How much each contributes to crowd heat (how much they care).
#
# Achievements earns real weight here in a way it does not for quality: a crowd
# reacts to someone who has won things, and this is the loop that makes a title
# reign feel like it built somebody. Wrestling matters least of the three — being
# excellent and being cared about are different problems.
HEAT_WEIGHTS = {"popularity": 0.48, "achievements": 0.20, "wrestling": 0.16,
                "looks": 0.10, "personal": 0.06}

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
# meaning of the world title. As Wrestling grows and matches improve, the
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
    ach = game.achievement_inputs(con)
    return {wid: game.effective_attributes(con, wid, ach.get(wid))
            for wid in wrestler_ids}


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
    match_type: str | None = None,
    is_main: bool = False,
) -> dict:
    """Resolve one match. `teams` is a list of sides, each a list of wrestler ids.

    `match_type` is the STRUCTURE (singles, tag, triple threat, fatal 4-way …)
    and `stipulation` the RULES (steel cage, tables, no-DQ). They compose; see
    matches.py for why they are separate axes.

    Returns the result WITHOUT writing it — the caller commits, so a whole show
    can be simulated and inspected before anything is persisted.
    """
    if len(teams) < 2 or any(not t for t in teams):
        raise ValueError("a match needs at least two non-empty sides")
    # A card row written before match types existed (or by the auto/AI booker)
    # carries no type — name its shape rather than refusing it.
    match_type = match_type or MT.infer(teams)
    MT.validate(match_type, teams)

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
    mt = MT.get(match_type)
    # A three-or-more-corner match almost never ends in a draw — somebody always
    # steals the pin, which is the whole appeal of the shape.
    draw = rng.random() < (0.015 if len(teams) > 2 else 0.04)
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
                     + stip["quality"] + prod_bonus + mt["quality"])

    # --- who took the fall -------------------------------------------------
    # In a multi-corner match only ONE woman is actually beaten, and protecting
    # the other losers is most of the reason to book the shape: a fatal 4-way
    # lets three women leave without being pinned. The fall goes to the weakest
    # side that did not win.
    fell_team = None
    if not draw and len(teams) > 2 and finish in ("pinfall", "submission"):
        losers = [i for i in range(len(teams)) if i != winner_idx]
        fell_team = min(losers, key=lambda i: team_strength[i])

    # --- injuries ----------------------------------------------------------
    # A cage/ladder/TLC match and a chaotic multi-corner match are both harder
    # on the body than a clean singles.
    risk = mt["fatigue"] * (1.0 + stip["quality"] * 0.05)
    injured = []
    today = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()["current_date"]
    for wid in everyone:
        chance = BASE_INJURY_CHANCE * risk * (1 + state[wid]["fatigue"] / 120)
        age = attrs[wid].get("age")
        if age:
            chance *= 1 + max(0, age - 35) * 0.03
        # A wrestler recently back from a bad injury is likelier to go down
        # again — which is what makes rushing somebody back a real gamble.
        chance *= medical.relapse_multiplier(con, wid, today)
        if rng.random() < chance:
            weeks = rng.choices([rng.randint(1, 2), rng.randint(2, 4),
                                 rng.randint(5, 9), rng.randint(10, 18)],
                                weights=[46, 34, 15, 5])[0]
            injured.append({"wrestler_id": wid, "weeks": weeks})

    # --- the crowd ---------------------------------------------------------
    # Two different measurements. REACTION is how hot the segment was; POP is
    # how the building took each individual woman, which is a different question
    # — a heel being loudly booed is a heel doing her job. See crowd.py.
    react = crowd.segment_reaction(quality, heat, feud_heat, aligns, is_ppv, is_main)
    cheap = finish in ("dq", "countout")
    pops: dict[int, tuple[float, str]] = {}
    for ti, t in enumerate(teams):
        for wid in t:
            al = attrs[wid].get("alignment") or "face"
            pops[wid] = (crowd.wrestler_pop(
                al, attrs[wid]["popularity"], state[wid]["momentum"], quality,
                won=(not draw and ti == winner_idx),
                beaten_clean=(fell_team is not None and ti == fell_team)
                             or (fell_team is None and not draw and ti != winner_idx
                                 and finish in ("pinfall", "submission")),
                cheap_finish=cheap and not draw and ti == winner_idx,
                feud_heat=feud_heat), al)

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
        "match_type": match_type,
        "match_type_label": mt["label"],
        "fell_team": fell_team,
        "fatigue_cost": round(FATIGUE_PER_MATCH * mt["fatigue"]),
        "injured": injured,
        "feud_heat": feud_heat,
        "pops": pops,
        **react,
    }


def _apply_match(con: sqlite3.Connection, show_id: int, held_on: str, res: dict) -> int:
    cur = con.execute(
        "INSERT INTO sim_match (show_id, slot, title_id, quality, finish, stipulation, "
        "match_type, reaction, reaction_score) VALUES (?,?,?,?,?,?,?,?,?)",
        (show_id, res["slot"], res["title_id"], res["quality"], res["finish"],
         res.get("stipulation"), res.get("match_type"),
         res.get("reaction"), res.get("reaction_score")),
    )
    match_id = cur.lastrowid
    # How the building took each woman, which is a different question from how
    # good the match was — and the input the turn system reads.
    if res.get("pops"):
        crowd.record_pops(con, "match", match_id, res["pops"])

    for ti, team in enumerate(res["teams"]):
        for wid in team:
            won = 1 if res["winner_team"] == ti else 0
            con.execute(
                "INSERT INTO sim_match_participant (match_id, wrestler_id, team, is_winner) "
                "VALUES (?,?,?,?)", (match_id, wid, ti, won),
            )

    everyone = [w for t in res["teams"] for w in t]
    is_main = res.get("is_main_event", False)
    # Multi-corner match: only the side that took the fall is treated as beaten
    # for morale and momentum. Everyone else lost the match but was not beaten,
    # and the numbers should say so.
    fell = res.get("fell_team")
    protected = {w for i, t in enumerate(res["teams"]) for w in t
                 if fell is not None and i != fell and i != res["winner_team"]}
    fatigue_cost = res.get("fatigue_cost") or FATIGUE_PER_MATCH
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
        if wid in protected:
            dm = MORALE["draw"]          # she lost the match but was not beaten
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
             fatigue_cost,
             8 if won else (-2 if wid in protected else (-6 if lost else 0)),
             dm,
             wid),
        )

    for inj in res["injured"]:
        rec = medical.record_injury(con, inj["wrestler_id"], inj["weeks"], held_on)
        inj.update(rec)
        game.log_event(con, "injury",
                       f"{game._wname(con, inj['wrestler_id'])} is hurt — "
                       f"{rec['note']}, out about {inj['weeks']} weeks.",
                       icon="🩹")

    # Rivalry heat, and the BEAT that records what happened. The beat is what
    # turns a feud from a heat counter into a story with a history — see
    # storylines.py.
    bumped = set()
    for ti in range(len(res["teams"])):
        for tj in range(ti + 1, len(res["teams"])):
            for a in res["teams"][ti]:
                for b in res["teams"][tj]:
                    f = game.feud_between(con, a, b)
                    if f and f["id"] not in bumped:
                        game.bump_feud_heat(con, f["id"], game.FEUD_HEAT_PER_MATCH)
                        bumped.add(f["id"])
                        winner = None
                        if res["winner_team"] == ti:
                            winner = a
                        elif res["winner_team"] == tj:
                            winner = b
                        mt_label = MT.get(res.get("match_type"))["label"]
                        stip_key = res.get("stipulation")
                        gimmick = (f" ({booking.stip(stip_key)['label']})"
                                   if stip_key and stip_key != "normal" else "")
                        if winner:
                            txt = (f"{game._wname(con, winner)} beat "
                                   f"{game._wname(con, b if winner == a else a)} "
                                   f"via {res['finish']}{gimmick} — {res['quality']:.0f}/100")
                        else:
                            txt = (f"{game._wname(con, a)} and {game._wname(con, b)} "
                                   f"went to a {res['finish']}{gimmick}")
                        if mt_label != "Singles":
                            txt += f" in a {mt_label}"
                        storylines.add_beat(con, f["id"], held_on, "match", txt,
                                            show_id=show_id, winner_id=winner)
                        storylines.sync_stage(con, f["id"])

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
    promo_card: list[dict] | None = None,
) -> dict:
    """Simulate and persist a full show.

    `card` is an ordered list of {"teams": [[id,...],[id,...]], "match_type":
    str|None, "title_id": int|None, "stipulation": str|None}. `promo_card` is the
    talking half — an ordered list of {"kind": str, "wrestler_ids": [id,...]}.
    `logistics` (arena/production/effects/advertising) spends money for a bigger,
    better show and settles the week's finances.
    """
    state = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if state is None:
        raise ValueError("no active save — start a new game first")
    held_on = held_on or state["current_date"]
    seed = state["rng_seed"]
    ls = booking.logistics_summary(logistics)
    prod_bonus = ls["quality"]
    promo_card = promo_card or []
    PR.ensure_schema(con)

    if not card:
        raise ValueError("a show needs at least one match")

    # Validate every shape BEFORE anything is written, so a bad row on match 4
    # cannot leave three simulated matches behind.
    for i, m in enumerate(card, start=1):
        mtype = m.get("match_type") or MT.infer(m["teams"])
        try:
            MT.validate(mtype, m["teams"])
        except ValueError as e:
            raise ValueError(f"Match {i}: {e}") from None
    for i, p in enumerate(promo_card, start=1):
        try:
            PR.validate(p.get("kind"), p.get("wrestler_ids") or [])
        except ValueError as e:
            raise ValueError(f"Promo {i}: {e}") from None

    booked = [w for m in card for t in m["teams"] for w in t]
    if len(booked) != len(set(booked)):
        raise ValueError("a wrestler is booked in more than one match on this card")

    # A promo and a match are different segments of the same night, so somebody
    # can do both — but not two promos.
    talkers = [w for p in promo_card for w in (p.get("wrestler_ids") or [])]
    if len(talkers) != len(set(talkers)):
        raise ValueError("a wrestler is in more than one promo segment on this card")

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

    # A woman switched to managing does not wrestle. The pre-booker already
    # leaves her out, but that is only a suggestion — this is the rule, so a
    # hand-booked card cannot put her in a match she is not eligible for.
    for wid in booked:
        cap = con.execute(
            """SELECT COALESCE(o.role, a.role) cap, o.active_role
                 FROM attributes a
                 LEFT JOIN attribute_override o ON o.wrestler_id=a.wrestler_id
                WHERE a.wrestler_id=?""", (wid,)).fetchone()
        if cap and game.working_role(cap["cap"], cap["active_role"]) == "manager":
            raise ValueError(
                f"{game._wname(con, wid)} is working as a manager — switch her back "
                f"to wrestling before you book her in a match.")

    # Injury gates MATCHES only. A woman on the shelf can still come out and
    # talk, which is how a feud survives an injury instead of dying with it.
    # Granted REST gates matches the same way: time off you promised her is not
    # time off if you book her through it.
    for wid in booked:
        s = con.execute(
            "SELECT injured_until, rested_until FROM wrestler_state WHERE wrestler_id=?",
            (wid,)).fetchone()
        if s and s["injured_until"] and s["injured_until"] > held_on:
            nm = con.execute("SELECT name FROM wrestler WHERE id=?", (wid,)).fetchone()[0]
            raise ValueError(f"{nm} is injured until {s['injured_until']}")
        if s and s["rested_until"] and s["rested_until"] > held_on:
            nm = con.execute("SELECT name FROM wrestler WHERE id=?", (wid,)).fetchone()[0]
            raise ValueError(f"{nm} is resting until {s['rested_until']} — you granted "
                             f"her the time off. Cancel the rest first if you need her.")

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
        is_main = (slot == len(card))
        res = simulate_match(con, show_id, slot, m["teams"], seed, m.get("title_id"),
                             is_ppv=is_ppv, stipulation=m.get("stipulation"),
                             prod_bonus=prod_bonus, match_type=m.get("match_type"),
                             is_main=is_main)
        res["is_main_event"] = is_main
        # Manager belt: the winning side's manager becomes/stays champion.
        if res.get("title_tier") == "manager" and m.get("managers") and res["winner_team"] is not None:
            mgrs = m["managers"]
            if res["winner_team"] < len(mgrs):
                res["title_holder"] = mgrs[res["winner_team"]]
        _apply_match(con, show_id, held_on, res)
        results.append(res)

    # Promos run after the matches so a segment can react to what the crowd has
    # already seen; slots continue the card's numbering.
    promo_results = []
    for i, p in enumerate(promo_card):
        pres = PR.simulate_promo(con, show_id, len(card) + i + 1, p.get("kind") or PR.DEFAULT,
                                 p.get("wrestler_ids") or [], seed,
                                 topic=p.get("topic"), is_ppv=is_ppv)
        PR.apply_promo(con, show_id, pres)
        promo_results.append(pres)

    # The main event counts double toward how the night is remembered; a promo
    # counts half, because a great segment is a great segment but the main event
    # is what the night IS.
    qualities = [r["quality"] for r in results]
    weights = [1.0] * (len(qualities) - 1) + [2.0]
    qualities += [r["quality"] for r in promo_results]
    weights += [PR.PROMO_SHOW_WEIGHT] * len(promo_results)
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

    # PPV appearances are a career milestone — credit everyone who worked it,
    # in a match or on the mic.
    appeared = sorted(set(booked) | set(talkers))
    if is_ppv and appeared:
        con.execute(
            "UPDATE wrestler_state SET ppv_appearances = ppv_appearances + 1 "
            f"WHERE wrestler_id IN ({','.join('?' * len(appeared))})", appeared)

    # Everyone not booked recovers a little — but a wrestler left off her own
    # brand's show entirely loses a touch of morale (nobody likes catering duty).
    # Wrestlers on the OTHER brand are simply not on this show and are untouched.
    on_this_brand = [r[0] for r in con.execute(
        """SELECT c.wrestler_id FROM contract c
           WHERE c.brand_id=? AND c.terminated_on IS NULL
             AND c.start_year<=? AND c.end_year>=?""",
        (brand_id, state["season_year"], state["season_year"]),
    )]
    idle = [w for w in on_this_brand if w not in appeared]
    con.execute(
        "UPDATE wrestler_state SET fatigue = MAX(0, fatigue - ?) WHERE wrestler_id NOT IN "
        f"({','.join('?' * len(appeared))})",
        [FATIGUE_RECOVERY_PER_DAY * 7] + appeared,
    )
    # A pay-per-view is a co-branded night: nobody is "left off her own brand's
    # show" by a card that was only ever going to hold six matches.
    if is_ppv:
        idle = []
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

    # The scoreboard. Wrapped for the same reason: a rating is a nice-to-have on
    # top of a show that has already happened, and must never lose one.
    tv = None
    try:
        tv = brandwar.rate_show(con, show_id)
    except Exception as e:                                   # noqa: BLE001
        game.log_event(con, "ratings", f"TV rating could not be scored: {e}", icon="⚠️")
        con.commit()
    if tv and not is_ppv and tv.get("tv_rating") is not None:
        prev = tv.get("previous")
        arrow = "" if prev is None else (" ▲" if tv["tv_rating"] > prev
                                         else " ▼" if tv["tv_rating"] < prev else " =")
        game.log_event(con, "tv",
                       f"{name} drew a {tv['tv_rating']} rating "
                       f"({tv['viewers']:,} homes){arrow}", brand_id, "📺")
        con.commit()
    elif tv and is_ppv and tv.get("buyrate") is not None:
        game.log_event(con, "tv",
                       f"{name} did a {tv['buyrate']} buyrate "
                       f"(~{tv['buys']:,} buys)", brand_id, "💸")
        con.commit()

    return {
        "show_id": show_id, "name": name, "brand_id": brand_id, "held_on": held_on,
        "rating": round(show_rating, 1), "attendance": attendance, "city": city, "cost": cost,
        "is_ppv": is_ppv, "ppv_name": ppv_name, "matches": results,
        "promos": promo_results, "ledger": ledger, "tv": tv,
        "crowd": crowd.show_reactions(con, show_id),
    }


def auto_card(con: sqlite3.Connection, brand_id: str, matches: int = 4,
              kind: str = "tv") -> list[dict]:
    """Build a plausible card from the brand's healthy roster.

    Delegates to the real booker in autobook.py — rivalries first, belts on the
    biggest match, face-vs-heel, stamina respected, mixed shapes — and only falls
    back to the old pair-by-overall ladder if that cannot produce a card (a very
    thin roster, or a save with nothing booked yet). Keeping the fallback means a
    quick sim never dies because there are no feuds to build a story from.
    """
    try:
        import autobook                              # noqa: PLC0415 — avoid a cycle
        sug = autobook.suggest(con, brand_id, kind)
        if len(sug["matches"]) >= min(2, matches):
            out = sug["matches"][:matches]
            for m in out:
                m.pop("why", None)
                m.pop("slot", None)
            return out
    except (ValueError, KeyError):
        pass
    return _ladder_card(con, brand_id, matches)


def auto_promos(con: sqlite3.Connection, brand_id: str, count: int = 2,
                kind: str = "tv") -> list[dict]:
    """The talking half of an auto-booked show, in the same suggestion shape."""
    try:
        import autobook                              # noqa: PLC0415
        return autobook.suggest(con, brand_id, kind)["promos"][:count]
    except (ValueError, KeyError):
        return []


def _ladder_card(con: sqlite3.Connection, brand_id: str, matches: int = 4) -> list[dict]:
    """The original booker: pair by overall, best pairing last. The fallback."""
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

    ach = game.achievement_inputs(con)
    ranked = sorted(roster, reverse=True,
                    key=lambda w: game.effective_attributes(con, w, ach.get(w))["overall"])
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
