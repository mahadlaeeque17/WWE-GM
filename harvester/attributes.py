"""Derive game attributes from harvested cagematch data.

The rating system is FOUR categories:

    Experience   earned in the sim, not from real life. Everyone starts at 0
                 (unless SEED_EXPERIENCE_FROM_CAREER is on). Lives in
                 wrestler_state, not here — it is game state.
    Charisma     promo skill / likeability, from cagematch rating + reach.
    Popularity   star power, from cagematch vote count.
    Looks        cagematch has NO looks data. Seeded as a placeholder and
                 expected to be hand-edited.

All four are user-overridable. Overrides live in `attribute_override` and are
never touched by normalize.py — see schema.sql.

Bump FORMULA_VERSION when a formula changes; it is recorded per row so you can
tell which saves were seeded under which rules.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date

FORMULA_VERSION = 3

RESET_DATE = date(2000, 1, 1)
RESET_YEAR = 2000

# Each category is scored out of 25, so the four sum to a 0-100 overall.
# Overall is a plain SUM, not a weighted average — that is what "totalling up
# to 100" means, and it keeps the maths legible when hand-editing.
CAT_MAX = 25
OVERALL_MAX = CAT_MAX * 4

# Rating shrinkage. Without it a 3-vote 9.0 outranks a 400-vote 7.5.
VOTE_PRIOR = 25
SITE_MEAN = 6.0

# Flip to True to start wrestlers with experience reflecting their real career
# instead of a clean slate. Off by default: the design is that experience is
# earned in YOUR sim, so the roster starts undifferentiated in the ring.
SEED_EXPERIENCE_FROM_CAREER = False

# Age curve. Value peaks in the late 20s and decays either side.
PEAK_AGE = 28
YOUTH_BONUS_PER_YEAR = 0.020   # under peak, each year younger is worth more
VETERAN_DECAY_PER_YEAR = 0.028  # over peak, each year older costs more
AGE_MULT_FLOOR = 0.35
AGE_MULT_CEIL = 1.25


def _clamp(v: float, lo: int = 0, hi: int = CAT_MAX) -> int:
    """Clamp a single category to 0-25."""
    return int(max(lo, min(hi, round(v))))


def adjusted_rating(rating: float | None, votes: int | None) -> float:
    if not rating or not votes:
        return SITE_MEAN
    return (votes * rating + VOTE_PRIOR * SITE_MEAN) / (votes + VOTE_PRIOR)


# ---------------------------------------------------------------- age

def parse_age_at_reset(birthday: str | None) -> tuple[int | None, str]:
    """Exact age on 1 January 2000.

    Cagematch birthdays come in three shapes and only one of them supports a
    real age, so the precision is returned alongside — the UI must not render
    a guess as though it were exact.

        '18.12.1975' -> (24, 'exact')
        '1959'       -> (41, 'year_only')     approximate, no day/month
        '13.04.'     -> (None, 'unknown')     no year at all
        None         -> (None, 'unknown')
    """
    if not birthday:
        return None, "unknown"

    b = birthday.strip()

    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", b)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            dob = date(year, month, day)
        except ValueError:
            return RESET_YEAR - year, "year_only"
        age = RESET_DATE.year - dob.year
        # birthday not yet reached in the reset year
        if (RESET_DATE.month, RESET_DATE.day) < (dob.month, dob.day):
            age -= 1
        return age, "exact"

    m = re.match(r"^(\d{4})$", b)
    if m:
        return RESET_YEAR - int(m.group(1)), "year_only"

    return None, "unknown"


def age_multiplier(age: int | None) -> float:
    """How age scales contract value. Younger is worth more.

    A 22-year-old carries a premium on upside; a 45-year-old is discounted hard.
    Unknown ages get 1.0 rather than a penalty — we should not punish a wrestler
    for a gap in cagematch's records.
    """
    if age is None:
        return 1.0
    if age <= PEAK_AGE:
        mult = 1.0 + (PEAK_AGE - age) * YOUTH_BONUS_PER_YEAR
    else:
        mult = 1.0 - (age - PEAK_AGE) * VETERAN_DECAY_PER_YEAR
    return max(AGE_MULT_FLOOR, min(AGE_MULT_CEIL, mult))


# ---------------------------------------------------------------- source

@dataclass
class Source:
    roles: str | None
    rating: float | None
    votes: int | None
    wins: int
    losses: int
    draws: int
    matches: int
    promos: dict
    reigns_pre_reset: int
    title_days_pre_reset: int
    style: str | None


# ---------------------------------------------------------------- categories

def charisma(s: Source) -> int:
    """Promo skill and likeability, out of 25.

    Cagematch does not grade promos, so this blends how highly she is rated
    (quality) with how widely she is known (reach). Someone well-rated by many
    people was almost certainly connecting with a crowd.
    """
    quality = adjusted_rating(s.rating, s.votes) * 1.875    # 0-18.75
    reach = min(6.25, 2.25 * math.log10((s.votes or 0) + 1))
    return _clamp(quality + reach)


def popularity(s: Source) -> int:
    """Star power, out of 25. Vote COUNT is the honest proxy — it measures how
    many people cared enough to rate her at all — lifted by championship
    pedigree earned before the reset."""
    fame = 5.5 * math.log10((s.votes or 0) + 1)
    pedigree = min(5.5, s.reigns_pre_reset * 1.25 + s.title_days_pre_reset / 600)
    return _clamp(fame + pedigree)


def looks(s: Source) -> int:
    """PLACEHOLDER, out of 25 — cagematch has no looks field and no review
    category for it.

    Seeded mid-scale with a mild pull toward the overall rating so the roster is
    not perfectly flat, then expected to be hand-edited. Do not read anything
    into this value; it is a starting point, not a measurement.
    """
    return _clamp(12.5 + (adjusted_rating(s.rating, s.votes) - SITE_MEAN))


def seeded_experience(s: Source) -> int:
    """Only used when SEED_EXPERIENCE_FROM_CAREER is on."""
    if not SEED_EXPERIENCE_FROM_CAREER:
        return 0
    return _clamp(6.4 * math.log10(s.matches + 1))


def experience_from_sim(sim_matches: int) -> int:
    """The live formula: experience grows with matches worked IN THE SIM.

    Logarithmic and out of 25, so the first twenty matches teach far more than
    the next twenty. Reaches the cap around 1,500 matches — a full career.
    """
    if sim_matches <= 0:
        return 0
    return _clamp(7.9 * math.log10(sim_matches + 1))


# ---------------------------------------------------------------- roles

# Cagematch concatenates roles with no separator — "Singles WrestlerTag Team
# Wrestler" — so the string cannot be split. Searching for known tokens works
# regardless, and the optional "(1997 - 2000)" year range that follows a role
# tells us WHEN she held it.
IN_RING_ROLES = ("Singles Wrestler", "Tag Team Wrestler")
MANAGER_ROLES = ("Manager", "Valet")

# Non-performing roles. Present in the data but irrelevant to the draft.
OTHER_ROLES = (
    "Trainer", "Promoter", "Booker", "Referee", "Interviewer",
    "Color Commentator", "Play-by-Play Commentator", "On-Air Official",
    "Road Agent", "Writer", "Backstage Helper",
)


def role_years(roles: str, role: str) -> tuple[int | None, int | None]:
    """The year range attached to a role, if cagematch recorded one."""
    m = re.search(re.escape(role) + r"\s*\((\d{4})(?:\s*-\s*(\d{4}))?\)", roles or "")
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2)) if m.group(2) else None


# A wrestler with this many recorded matches was clearly working in the ring,
# whatever the Roles string does or does not say.
WRESTLER_MATCH_FLOOR = 10


def classify_role(roles: str | None, matches: int = 0) -> str:
    """wrestler | manager | both.

    The Roles string is the first signal but it is INCOMPLETE for a chunk of the
    roster — the harvest captured only a fragment for some, so Meiko Satomura
    reads as just "Promoter" and Molly Holly as just "Road Agent". Trusting it
    alone turns real wrestlers into managers.

    Recorded match count is the trustworthy cross-check, so it wins: anyone with
    a real body of in-ring work is a wrestler regardless of the string. And when
    nothing is conclusive the default is WRESTLER, because this is a wrestling
    roster and missing data should not demote someone.

    "both" means she can be drafted into either pool — Sherri, Jacqueline,
    Beulah. A pure manager (Sunny, Miss Elizabeth) never wrestled enough to
    qualify and is explicitly tagged Manager or Valet.
    """
    roles = roles or ""
    wrestles = any(r in roles for r in IN_RING_ROLES) or matches >= WRESTLER_MATCH_FLOOR
    manages = any(r in roles for r in MANAGER_ROLES)

    if wrestles and manages:
        return "both"
    if wrestles:
        return "wrestler"
    if manages:
        return "manager"
    return "wrestler"


# Negotiating personality, seeded from her real profile so the roster is not a
# flat wall of one type. Deterministic — same source always yields the same
# personality — and, like every derived field, overridable per wrestler.
#   money_hungry  the biggest draws know their worth
#   prima_donna   established stars with title pedigree and an ego
#   ambitious     the young/less-proven, hungry for a push (the default)
#   loyal         the dependable hands who just want to work
def personality(s: Source) -> str:
    pop = popularity(s)
    cha = charisma(s)
    if pop >= 15:            # the biggest draws know their worth
        return "money_hungry"
    if pop <= 9:             # lower-card hands, just glad of the work
        return "loyal"
    # The crowded mid-card splits deterministically into egos and up-and-comers.
    return "prima_donna" if (cha + pop) % 2 == 0 else "ambitious"


def availability(s: Source) -> str:
    active = any(p["y1"] >= RESET_YEAR - 1 for p in s.promos.values())
    light_intl = all(p["m"] <= 5 for p in s.promos.values()) and s.matches <= 10
    if active:
        return "active_2000"
    if light_intl and adjusted_rating(s.rating, s.votes) >= 7.5:
        return "import"
    return "legend"


def derive(s: Source) -> dict:
    return {
        "charisma": charisma(s),
        "popularity": popularity(s),
        "looks": looks(s),
        "availability": availability(s),
        "role": classify_role(s.roles, s.matches),
        "role_source": s.roles,
        "personality": personality(s),
        "formula_ver": FORMULA_VERSION,
    }


# ---------------------------------------------------------------- valuation

# Money is calibrated against real WWE 2006 payrolls, scaled down to a top-flight
# women's promotion in the year 2000. On that sheet the marquee draws sat around
# $0.7M–$2M, a broad mid-card ran $200k–$500k, and a long tail sat at $40k–$190k.
# Our roster tops out near a 70 overall on day one (Trish, Lita) and climbs as
# experience is earned, so the curve is anchored so that:
#
#     overall 70  ->  ~$1.1M    (a genuine top draw)
#     overall 55  ->  ~$0.53M   (upper card)
#     overall 44  ->  ~$0.28M   (solid mid-card, the roster median)
#     overall 35  ->  ~$0.14M   (lower card)
#     overall 23  ->   $40k     (floor — enhancement talent)
#
# The exponent is steep (≈3) on purpose: in wrestling one draw earns more than
# the six hands below her combined, and it is what makes a first-round draft pick
# cost "way more" than a second-rounder without any artificial thumb on the scale.
BASE_VALUE = 3_100_000   # what a hypothetical 100 overall at age 28 commands
VALUE_EXPONENT = 2.95
MIN_VALUE = 40_000


def overall(experience: int, charisma_: int, popularity_: int, looks_: int) -> int:
    """0-100 overall: the plain SUM of four categories each capped at 25.

    Deliberately unweighted. Every category is worth the same 25 points, so the
    number on screen is always the four numbers next to it added up.
    """
    return int(max(0, min(OVERALL_MAX, experience + charisma_ + popularity_ + looks_)))


def contract_value(
    experience: int, charisma_: int, popularity_: int, looks_: int,
    age: int | None,
) -> int:
    """Annual contract value in game dollars.

    Superlinear in the composite rating (exponent ≈3) so the top of the roster
    separates sharply from the middle — the way real wrestling money works, where
    one draw earns more than the six people below her combined. See BASE_VALUE
    for the 2006-grounded anchor points.
    """
    score = overall(experience, charisma_, popularity_, looks_) / 100.0
    raw = BASE_VALUE * (score ** VALUE_EXPONENT) * age_multiplier(age)
    return max(MIN_VALUE, int(round(raw / 10_000) * 10_000))
