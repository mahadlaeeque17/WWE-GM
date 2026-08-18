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


def profile(con: sqlite3.Connection, wid: int, kind: str, tier_factor: float) -> dict:
    """Her private negotiating position — driven by star power, age, personality
    and current morale."""
    a = game.effective_attributes(con, wid)
    base = game.manager_price(con, wid) if kind == "manager" else a["value"]
    star = min(1.0, a["overall"] / 75.0)          # 0..1, ~75 overall = top of the card
    age = a.get("age") or 30
    personality, morale = _persona(con, wid)

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
            "personality": personality, "morale": morale}


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
          tier_factor: float = 1.0, signing_bonus: int = 0) -> dict:
    """Evaluate an offer. Returns verdict + counter + mood + patience left."""
    perks = perks or []
    p = profile(con, wid, kind, tier_factor)
    res = p["reservation"]
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
            # She sits out the year for THIS brand — recorded so she drops out of
            # its pool until the GM clears it or the season rolls over.
            game.record_holdout(con, wid, brand)

    return {
        "wrestler_id": wid, "brand_id": brand, "verdict": verdict, "mood": mood,
        "offer": salary, "perks": perks, "signing_bonus": signing_bonus,
        "counter": counter, "reservation_hint": counter,   # never expose exact reservation
        "patience": max(0, patience), "kind": kind,
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
