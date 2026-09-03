"""Contract negotiation.

Every signing — a draft pick or a free agent — is now a negotiation, not a
take-it-or-leave-it asking price. Each wrestler has a private **reservation
price** (the least she'll take) built from her star power, age, the role she's
being offered and, for draft picks, which round she went in. You make an offer
of salary + perks; she accepts, counters, or is insulted by a low-ball. The
bigger the star the harder she haggles and the shorter her patience for
low-balls; older or lower-card wrestlers sign cheap and happily.

The maths here is deterministic and explainable. Groq only writes the *reaction
line* on top (see ai.negotiation_line) — if it's down, canned lines are used and
nothing breaks.
"""

from __future__ import annotations

import sqlite3

import attributes as A
import game

# Perks trade money for goodwill. Each is worth a fraction of the reservation
# price, and some are worth much more to certain wrestlers — a veteran loves a
# lighter schedule, a rising star cares about the main-event spotlight ("the
# amount of chances they'll get"). label, base fraction.
PERKS = {
    "main_event":     ("Main-event push", 0.18),
    "title_shot":     ("Guaranteed title shot", 0.11),
    "creative":       ("Creative control", 0.08),
    "light_schedule": ("Reduced schedule", 0.07),
}

# Personality shapes how she negotiates. Four of them, each with ONE distinct,
# legible effect the UI spells out:
#   key: (label, description, demand_factor, effect)
#     demand_factor scales her reservation price directly.
#     effect is the one-line rule the UI shows so the choice is never a mystery.
#
#   money_hungry  wants top dollar and barely values perks — pay her in cash.
#   ambitious     will take a real pay cut for a push or a title shot.
#   loyal         signs cheap, stays patient, forgives a low-ball.
#   prima_donna   moody — her price swings hard with her morale.
PERSONALITIES = {
    "money_hungry": ("Money-hungry", "chases the biggest cheque", 1.35,
                     "Wants ~35% over market and perks barely sway her — pay cash. Short fuse on low-balls."),
    "ambitious":    ("Ambitious", "trades money for a push", 1.00,
                     "Market money, but a main-event push or guaranteed title shot is worth double — lean on perks."),
    "loyal":        ("Loyal", "happy to stay for less", 0.82,
                     "Signs ~18% under market, very patient, and shrugs off a low-ball rather than walking."),
    "prima_donna":  ("Prima donna", "moody — money tracks how she feels", 1.05,
                     "Her demand swings hardest with morale: fed-up she gouges you, happy she signs cheap."),
}

# Everything that used to be another personality collapses to this baseline.
DEFAULT_PERSONALITY = "ambitious"
_LEGACY_PERSONALITY = {"mercenary": "ambitious", "team_player": "loyal"}


def _persona(con: sqlite3.Connection, wid: int) -> tuple[str, int]:
    """Effective personality + current morale."""
    row = con.execute(
        """SELECT COALESCE(o.personality, a.personality) personality,
                  COALESCE(s.morale, 50) morale
           FROM attributes a
           LEFT JOIN attribute_override o ON o.wrestler_id = a.wrestler_id
           LEFT JOIN wrestler_state s ON s.wrestler_id = a.wrestler_id
           WHERE a.wrestler_id = ?""", (wid,)).fetchone()
    if not row:
        return DEFAULT_PERSONALITY, 50
    p = row["personality"]
    p = _LEGACY_PERSONALITY.get(p, p)
    if p not in PERSONALITIES:
        p = DEFAULT_PERSONALITY
    return p, row["morale"]

# In-memory patience per (wrestler, brand) negotiation. A low-ball burns it; at
# zero she walks. Wiped on backend restart and on a completed signing — fine for
# a local single-user game.
_PATIENCE: dict[str, int] = {}


def _key(wid: int, brand: str) -> str:
    return f"{wid}:{brand}"


def reset(wid: int, brand: str) -> None:
    _PATIENCE.pop(_key(wid, brand), None)


def perk_labels(perks: list[str]) -> list[str]:
    return [PERKS[p][0] for p in perks if p in PERKS]


def profile(con: sqlite3.Connection, wid: int, kind: str, tier_factor: float,
            morale_override: int | None = None,
            retention: float = 1.0) -> dict:
    """Her private negotiating position — driven by star power, age, personality
    and current morale.

    `morale_override` forces the morale term to a fixed value. That exists for
    `market_rate()`: comparing a salary against a price that itself moves with
    morale is circular — underpaid lowers morale, which raises her price, which
    makes her more underpaid — and the spiral has no bottom. The pay-satisfaction
    engine needs a benchmark that does NOT move with how she feels.

    `retention` scales the result for an EXTENSION. She is already here: staying
    is cheaper than being recruited, and the discount is bigger the happier she
    is (see extension_quote).
    """
    a = game.effective_attributes(con, wid)
    base = game.manager_price(con, wid) if kind == "manager" else a["value"]
    star = min(1.0, a["overall"] / 75.0)          # 0..1, ~75 overall = top of the card
    age = a.get("age") or 30
    personality, morale = _persona(con, wid)
    if morale_override is not None:
        morale = morale_override

    reservation = base * tier_factor * (0.60 + 0.55 * star)
    if age >= 38:
        reservation *= 0.85                       # veterans take less, fewer years left
    elif age <= 24:
        reservation *= 1.06                       # young upside holds out

    # Personality: money_hungry always wants more, a team_player signs cheap.
    reservation *= PERSONALITIES[personality][2]

    # Morale: a fed-up worker wants a lot more to stay; a happy one takes less.
    # A prima donna's mood swings hardest.
    swing = 85 if personality == "prima_donna" else 125
    morale_mult = max(0.55, min(1.6, 1 + (50 - morale) / swing))
    reservation *= morale_mult

    reservation *= retention
    reservation = max(A.MIN_VALUE, int(round(reservation / 5_000) * 5_000))

    # money_hungry and unhappy wrestlers also haggle harder (less patience).
    toughness = min(1.0, star + (0.2 if personality == "money_hungry" else 0)
                    + (0.15 if morale < 35 else 0))
    start_patience = 1 + round(2 * (1 - toughness))
    # The loyal are forgiving — they hear you out longer before walking.
    if personality == "loyal":
        start_patience += 2
    return {"base": base, "reservation": reservation, "toughness": toughness,
            "star": star, "age": age, "patience": start_patience,
            "personality": personality, "morale": morale, "retention": retention}


# ---------------------------------------------------------------- market rate

def market_rate(con: sqlite3.Connection, wid: int, kind: str = "wrestler") -> int:
    """What she is WORTH, independent of how she feels about you.

    This is the yardstick the whole pay-satisfaction system is measured against,
    so it deliberately pins morale at neutral. Being paid above it makes her
    happy and being paid under it makes her sour — and if the yardstick moved
    with her mood, that judgement would be measuring itself.
    """
    return profile(con, wid, kind, 1.0, morale_override=50)["reservation"]


def pay_position(con: sqlite3.Connection, wid: int) -> dict:
    """Where her actual salary sits against the market — the input to morale.

    `ratio` is salary ÷ market rate. Above 1 she is being looked after; below 1
    she is being taken advantage of, and she will eventually say so.
    """
    st = con.execute("SELECT season_year FROM game_state WHERE id=1").fetchone()
    if not st:
        return {"under_contract": False}
    c = game.active_contract(con, wid, st["season_year"])
    if not c:
        return {"under_contract": False}
    kind = "manager" if c["role"] == "manager" else "wrestler"
    market = market_rate(con, wid, kind)
    salary = c["annual_value"]
    ratio = salary / market if market else 1.0
    if ratio >= 1.30:
        verdict, label = "overpaid", "paid well over her worth"
    elif ratio >= 1.12:
        verdict, label = "generous", "paid above the market"
    elif ratio >= 0.92:
        verdict, label = "fair", "paid about right"
    elif ratio >= 0.78:
        verdict, label = "underpaid", "paid under the market"
    else:
        verdict, label = "insulted", "badly underpaid"
    return {"under_contract": True, "salary": salary, "market": market,
            "ratio": round(ratio, 3), "verdict": verdict, "label": label,
            "gap": salary - market, "contract_id": c["id"],
            "years_left": c["end_year"] - st["season_year"] + 1,
            "perks": [PERKS[p][0] for p in _contract_perks(c["perks"]) if p in PERKS]}


def _contract_perks(perks_json: str | None) -> list[str]:
    import json
    if not perks_json:
        return []
    try:
        return [p for p in json.loads(perks_json) if p]
    except Exception:                                        # noqa: BLE001
        return []


# ---------------------------------------------------------------- extensions

# Staying is cheaper than being recruited — but only if she is happy. A content
# wrestler re-signs at a discount; a fed-up one wants MORE to stay than she
# would to arrive, because leaving is the thing she actually wants.
RETENTION_HAPPY = 0.84
RETENTION_NEUTRAL = 0.95
RETENTION_SOUR = 1.22

# Extra patience at the table when re-signing somebody already on the roster.
#
# WHY IT IS NEEDED. Patience starts at 1 for a genuine star, which is right for
# a free agent: insult her once and she is gone. Applied to an EXTENSION it made
# a top wrestler walk out of her own employer's office over a single opening
# number, before the GM had had one exchange — and it locked the negotiation for
# the rest of the season. She is already here; hearing a bad first offer from
# the brand she works for is worth a couple of exchanges, not an instant exit.
EXTENSION_PATIENCE_BONUS = 2


def retention_factor(morale: int) -> float:
    if morale >= 70:
        return RETENTION_HAPPY
    if morale >= 40:
        return RETENTION_NEUTRAL
    return RETENTION_SOUR


def extension_profile(con: sqlite3.Connection, wid: int, kind: str = "wrestler") -> dict:
    """Her negotiating position on an EXTENSION, discount and all."""
    _, morale = _persona(con, wid)
    p = profile(con, wid, kind, 1.0, retention=retention_factor(morale))
    p["patience"] += EXTENSION_PATIENCE_BONUS
    return p


def extension_quote(con: sqlite3.Connection, wid: int, kind: str = "wrestler") -> dict:
    """The public ballpark for re-signing her, and why it is that number.

    Extensions used to be a button: type her asking price, press extend. That
    made the one decision with a real cost — what keeping somebody is worth —
    into data entry, and it meant morale had no consequence at the only moment
    morale should bite hardest.
    """
    p = extension_profile(con, wid, kind)
    _, morale = _persona(con, wid)
    rf = retention_factor(morale)
    asking = int(round(p["reservation"] * (1.04 + 0.14 * p["star"]) / 10_000) * 10_000)
    if rf <= RETENTION_HAPPY:
        stance = ("She is happy here and will re-sign at a discount — "
                  "roughly 16% under what it would cost to sign her cold.")
    elif rf <= RETENTION_NEUTRAL:
        stance = "She has no strong feelings either way. A small loyalty discount."
    else:
        stance = ("She is unhappy and wants MORE to stay than to arrive — "
                  "about 22% over market. Fix the mood or pay the premium.")
    return {"asking": asking, "market": market_rate(con, wid, kind),
            "base": p["base"], "morale": morale,
            "retention_factor": round(rf, 2), "stance": stance,
            "toughness": round(p["toughness"], 2),
            "personality": p["personality"],
            "personality_label": PERSONALITIES[p["personality"]][0],
            "personality_desc": PERSONALITIES[p["personality"]][1],
            "personality_effect": PERSONALITIES[p["personality"]][3]}


def _goodwill(perks: list[str], reservation: int, age: int, star: float,
              personality: str = "mercenary") -> int:
    g = 0.0
    for p in perks:
        if p not in PERKS:
            continue
        frac = PERKS[p][1]
        m = 1.0
        if p == "light_schedule" and age >= 36:
            m = 1.8
        if p == "main_event" and star >= 0.5:
            m = 1.5                                 # stars value the spotlight
        if p == "title_shot" and star >= 0.5:
            m = 1.3
        # The ambitious will trade real cash for a push and a title picture.
        if personality == "ambitious" and p in ("main_event", "title_shot"):
            m *= 2.0
        # The money-hungry only really hear the number — perks barely move them.
        if personality == "money_hungry":
            m *= 0.4
        g += reservation * frac * m
    return int(g)


def offer(con: sqlite3.Connection, wid: int, brand: str, salary: int,
          perks: list[str] | None = None, kind: str = "wrestler",
          tier_factor: float = 1.0, signing_bonus: int = 0,
          context: str = "free_agent", years: int = 1) -> dict:
    """Evaluate an offer. Returns verdict + counter + mood + patience left.

    `context="extension"` re-signs somebody already on the roster: the same
    haggling, but priced off her retention factor instead of a draft tier, so
    how she FEELS about the brand decides whether keeping her is cheap or
    expensive. `years` only matters for an extension — see the length note below.
    """
    perks = perks or []
    if context == "extension":
        p = extension_profile(con, wid, kind)
    else:
        p = profile(con, wid, kind, tier_factor)
    res = p["reservation"]
    # Contract LENGTH is a term she has an opinion about. A veteran wants the
    # security of a long deal and will take less for it; somebody young and
    # rising wants to get back to the table while her stock is climbing, and
    # charges for being locked down.
    if context == "extension":
        if p["age"] >= 36:
            res *= 1.0 - min(0.10, 0.025 * max(0, years - 1))
        elif p["age"] <= 26:
            res *= 1.0 + min(0.14, 0.035 * max(0, years - 1))
        res = max(A.MIN_VALUE, int(round(res / 5_000) * 5_000))
    goodwill = _goodwill(perks, res, p["age"], p["star"], p["personality"])
    # A signing bonus is one-time money; count a share of it as sweetener.
    value = salary + goodwill + signing_bonus * 0.5
    ratio = value / res if res else 1.0

    key = _key(wid, brand)
    patience = _PATIENCE.get(key, p["patience"])

    if ratio >= 1.15:
        verdict, mood = "accept", "thrilled"
    elif ratio >= 1.0:
        verdict, mood = "accept", "satisfied"
    elif ratio >= 0.80:
        verdict, mood = "counter", "negotiating"
    elif ratio >= 0.62:
        verdict, mood = "counter", "unimpressed"
    else:
        verdict, mood = "offended", "insulted"

    counter = None
    if verdict == "counter":
        bump = 1.03 + 0.05 * p["toughness"] if mood == "negotiating" else 1.0
        counter = int(round(res * bump / 5_000) * 5_000)
    elif verdict == "offended":
        counter = int(round(res / 5_000) * 5_000)
        # A loyal wrestler shrugs off an insult and keeps talking; others burn
        # patience and edge toward walking.
        if p["personality"] != "loyal":
            patience -= 1
        else:
            verdict, mood = "counter", "unimpressed"

    if verdict == "accept":
        _PATIENCE.pop(key, None)
    else:
        _PATIENCE[key] = patience
        if patience <= 0:
            verdict, mood, counter = "walked", "done", None
            _PATIENCE.pop(key, None)
            if context == "extension":
                # She is ALREADY under contract, so walking out of an extension
                # is not a holdout — it is "we are done talking, I will see out
                # my deal". Recording a holdout here would wrongly drop her from
                # the brand she is currently signed to.
                con.execute(
                    "UPDATE wrestler_state SET morale = MAX(0, MIN(100, morale - 6)) "
                    "WHERE wrestler_id=?", (wid,))
                con.commit()
            else:
                # She sits out the year for THIS brand — recorded so she drops out
                # of its pool until the GM clears it or the season rolls over.
                game.record_holdout(con, wid, brand)

    return {
        "wrestler_id": wid, "brand_id": brand, "verdict": verdict, "mood": mood,
        "offer": salary, "perks": perks, "signing_bonus": signing_bonus,
        "counter": counter, "reservation_hint": counter,   # never expose exact reservation
        "patience": max(0, patience), "kind": kind, "context": context,
        "years": years,
        "personality": p["personality"], "morale": p["morale"],
    }


def opening_quote(con: sqlite3.Connection, wid: int, kind: str, tier_factor: float) -> dict:
    """A public starting point for the UI — the ballpark she's expecting, rounded
    so it reads as a guide, not her exact floor."""
    p = profile(con, wid, kind, tier_factor)
    asking = int(round(p["reservation"] * (1.05 + 0.15 * p["star"]) / 10_000) * 10_000)
    return {"asking": asking, "base": p["base"],
            "toughness": round(p["toughness"], 2),
            "personality": p["personality"],
            "personality_label": PERSONALITIES[p["personality"]][0],
            "personality_desc": PERSONALITIES[p["personality"]][1],
            "personality_effect": PERSONALITIES[p["personality"]][3],
            "morale": p["morale"],
            "note": "tough negotiator" if p["toughness"] >= 0.6
                    else "flexible" if p["toughness"] <= 0.35 else "reasonable"}
