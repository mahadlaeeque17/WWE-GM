"""Derive game attributes from harvested cagematch data.

The rating system is FIVE categories, each out of 20, summing to a 0-100 overall:

    Wrestling     in-ring ability. A stored base seeded from cagematch, PLUS a
                  live swing from her win/loss record in YOUR save.
    Achievements  what she has won IN THIS SAVE — championships, Rumbles,
                  Playboy covers, awards. Nothing real-life counts. Everyone
                  starts at 0 and earns every point of it.
    Popularity    star power: her cagematch score, how many people cared enough
                  to rate her, and promo skill. Stored, editable, and moved by
                  the season-end progression engine.
    Looks         yours. Cagematch has no such data and never will.
    Personal      yours, and only yours. Nothing derives it, nothing suggests a
                  change to it, and the sim reads it but never writes it.

WHICH ARE LIVE AND WHICH ARE STORED matters, so it is stated once here:

    stored + editable    Wrestling (the base), Popularity, Looks, Personal
    computed every read  Achievements (from save records), and the record swing
                         on top of the Wrestling base

That split is the whole design. A stored value is a judgement — yours or the
harvest's — and survives untouched. A computed value is a fact about the save and
must never be stored, because a stored copy goes stale the moment she wins
something and then quietly contradicts the trophy cabinet next to it.

Overrides live in `attribute_override` and are never touched by normalize.py —
see schema.sql. Bump FORMULA_VERSION when a formula changes; it is recorded per
row so you can tell which saves were seeded under which rules.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date

FORMULA_VERSION = 4

RESET_DATE = date(2000, 1, 1)
RESET_YEAR = 2000

# Five categories, 20 each, so the five sum to a 0-100 overall. Overall is a
# plain SUM, not a weighted average — that is what "totalling up to 100" means,
# and it keeps the maths legible when hand-editing: the number on screen is
# always the five numbers next to it added up.
CAT_MAX = 20
CATEGORIES = ("wrestling", "achievements", "popularity", "looks", "personal")
OVERALL_MAX = CAT_MAX * len(CATEGORIES)

# The two the GM owns outright. Listed rather than assumed, because the
# progression engine has to know what it is not allowed to touch.
GM_OWNED = ("looks", "personal")

# Where a brand-new wrestler's Personal starts. Neutral on purpose: it is a
# placeholder for a judgement not yet made, so it must not flatter or punish.
PERSONAL_DEFAULT = 10

# Rating shrinkage. Without it a 3-vote 9.0 outranks a 400-vote 7.5.
VOTE_PRIOR = 25
SITE_MEAN = 6.0

# Age curve. Value peaks in the late 20s and decays either side.
PEAK_AGE = 28
YOUTH_BONUS_PER_YEAR = 0.020   # under peak, each year younger is worth more
VETERAN_DECAY_PER_YEAR = 0.028  # over peak, each year older costs more
AGE_MULT_FLOOR = 0.35
AGE_MULT_CEIL = 1.25


def _clamp(v: float, lo: int = 0, hi: int = CAT_MAX) -> int:
    """Clamp a single category to 0-20."""
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


# ------------------------------------------------------------ stored categories

# Wrestling is a straight line off the vote-shrunk cagematch rating, anchored at
# the two ends of the roster's actual spread:
#
#     adj 9.48  (Manami Toyota, the best-rated worker in the data)  ->  20
#     adj 6.64  (the roster median)                                 ->  11
#     adj 3.20  (the floor)                                         ->   0
#
# NO career-volume term, though there is an obvious argument for one. The
# harvest's match counts are far too sparse to carry weight: the median wrestler
# has 0 recorded matches, and Manami Toyota — 25 years and thousands of matches —
# has exactly 1. A volume term built on that would not be measuring ring time, it
# would be measuring how completely cagematch happened to scrape her profile, and
# it demoted the best workers in the game. Better no signal than a false one.
WRESTLING_RATING_FLOOR = 3.2
WRESTLING_RATING_SLOPE = 3.15


def wrestling(s: Source) -> int:
    """In-ring ability, out of 20 — the BASE only, before her save record.

    Cagematch grades matches, not wrestlers, so the vote-shrunk rating is the
    best available read on how good she is between the ropes: it is an average of
    how her work was received, by the people who watched it.

    Deliberately NOT the same thing as the old `experience`. Experience started
    everyone at zero and grew with sim matches, which meant a debuting roster was
    perfectly flat in the ring — Manami Toyota and a valet opened identical. This
    starts from what she could actually do, and the save's win/loss record moves
    it from there (see `record_swing`).

    ONLY 50 OF THE 270 WRESTLERS HAVE A RATING AT ALL. For the rest this function
    would return the same floor value off the site mean, which is why seeding
    them is migrate_ratings.py's problem and not this one — it has the old
    hand-set numbers to work from, and this does not.
    """
    return _clamp((adjusted_rating(s.rating, s.votes) - WRESTLING_RATING_FLOOR)
                  * WRESTLING_RATING_SLOPE)


def popularity(s: Source) -> int:
    """Star power, out of 20 — cagematch score plus reach plus promo skill.

    Three named parts with stated caps, so the number can be argued with:

        score   how highly her work is rated          up to  8
        fame    how many people cared enough to vote   up to  6
        promo   mic work and likeability              up to  6

    `fame` is vote COUNT, not rating: it measures whether anyone was watching,
    which is exactly what star power is. `promo` is what used to be its own
    Charisma category — folded in here because "popularity" in wrestling has
    never been separable from being able to talk.

    Championship pedigree used to lift this and no longer does. Everything she
    has won now lives in Achievements, and counting a pre-2000 reign here as
    well as there would be paying her twice for it.
    """
    return _clamp(_pop_score(s) + _pop_fame(s) + _pop_promo(s))


def _pop_score(s: Source) -> float:
    return max(0.0, min(8.0, (adjusted_rating(s.rating, s.votes) - 4.25) * 1.85))


def _pop_fame(s: Source) -> float:
    return min(6.0, 2.6 * math.log10((s.votes or 0) + 1))


def _pop_promo(s: Source) -> float:
    """Promo skill, out of 6.

    Cagematch does not grade promos, so this is the same blend of quality and
    reach the old Charisma category used, scaled down to the share of Popularity
    it is worth. It is the weakest-grounded input here, which is the argument
    for it being a component rather than a category of its own.
    """
    quality = adjusted_rating(s.rating, s.votes) * 0.42
    reach = min(1.5, 0.55 * math.log10((s.votes or 0) + 1))
    return max(0.0, min(6.0, quality + reach - 2.4))


def looks(s: Source) -> int:
    """PLACEHOLDER, out of 20 — cagematch has no looks field and no review
    category for it.

    Seeded mid-scale with a mild pull toward the overall rating so the roster is
    not perfectly flat, then expected to be hand-edited. Do not read anything
    into this value; it is a starting point, not a measurement.
    """
    return _clamp(10.0 + (adjusted_rating(s.rating, s.votes) - SITE_MEAN) * 0.8)


def personal(s: Source) -> int:
    """Yours. Nothing about the harvest has an opinion, so it starts neutral.

    `s` is unused and stays in the signature on purpose: it makes the fact that
    no source data feeds this visible at the call site rather than buried in a
    docstring.
    """
    return PERSONAL_DEFAULT


# ------------------------------------------------------- live: wrestling record

# How far a win/loss record can move the Wrestling base, in either direction.
# Bounded on purpose: a hot streak is form, not a different wrestler, and letting
# the record swing the number freely would make a booked squash run indistinguish-
# able from genuine ability. Permanent growth is the progression engine's job.
RECORD_SWING_MAX = 3.0

# Shrinkage toward .500. Without it a 1-0 record reads as a perfect win rate and
# earns the full bonus off a single match.
RECORD_PRIOR_MATCHES = 6.0


def record_swing(sim_wins: int, sim_matches: int) -> float:
    """How her save record moves the Wrestling base, in [-3, +3].

    Shrunk toward .500 by a six-match prior, so the swing earns its way in: an
    undefeated debutant sits near +1 after three matches and only approaches +3
    once the sample is real.
    """
    if sim_matches <= 0:
        return 0.0
    rate = (sim_wins + RECORD_PRIOR_MATCHES * 0.5) / (sim_matches + RECORD_PRIOR_MATCHES)
    return max(-RECORD_SWING_MAX,
               min(RECORD_SWING_MAX, (rate - 0.5) * 2 * RECORD_SWING_MAX * 1.15))


def wrestling_live(base: int, sim_wins: int, sim_matches: int) -> int:
    """The Wrestling number actually shown: base ability plus current form."""
    return _clamp(base + record_swing(sim_wins, sim_matches))


# ---------------------------------------------------- live: achievements
#
# Everything here is earned INSIDE the save. A real-life twelve-time champion
# starts on zero, exactly like the woman she is about to wrestle, and the trophy
# cabinet fills up from the shows you book. That is the point of the category:
# it is the one rating that is a record of your own game rather than an opinion
# about wrestling history.
#
# Points are calibrated so that 20/20 is a genuine all-time save career — several
# world reigns, a Rumble, and the marquee awards — and so that one secondary
# title run reads as the modest thing it is.

TITLE_POINTS = {
    "world": 4.0,
    "secondary": 2.0,
    "tag": 1.5,
    "cruiserweight": 1.4,
    "hardcore": 1.2,
    "manager": 1.6,
}

# A long reign is worth more than a hot-potato one, so days held count too —
# but weakly, and capped, so that a decade with one belt cannot be the whole
# category on its own.
TITLE_DAYS_DIVISOR = 240.0
TITLE_DAYS_CAP = 5.0

ACHIEVEMENT_POINTS = {
    # sim-awarded
    "royal_rumble": 3.0,
    "money_in_the_bank": 2.0,
    "kotr": 2.0,
    "mania_main_event": 2.5,
    "wrestlemania": 0.8,
    "survivor_sole": 1.2,
    "iron_woman": 1.5,
    "grand_slam": 3.0,
    # manual
    "playboy_cover": 1.5,
    "babe_of_year": 1.5,
    "woman_of_year": 3.0,
    "match_of_year": 1.5,
    "feud_of_year": 1.2,
    "most_improved": 1.0,
    "rookie_of_year": 1.0,
    "hall_of_fame": 4.0,
    "slammy": 0.8,
}


def achievements(reigns_by_tier: dict[str, int], title_days: int,
                 accolades: dict[str, int]) -> int:
    """What she has won in this save, out of 20.

    Pure function of counts so it can be unit-tested and so the UI can show the
    working — "3 world reigns, 412 days, a Rumble" — next to the number.
    """
    pts = sum(TITLE_POINTS.get(tier, 1.0) * n for tier, n in reigns_by_tier.items())
    pts += min(TITLE_DAYS_CAP, max(0, title_days) / TITLE_DAYS_DIVISOR)
    pts += sum(ACHIEVEMENT_POINTS.get(kind, 0.5) * n for kind, n in accolades.items())
    return _clamp(pts)


def achievement_breakdown(reigns_by_tier: dict[str, int], title_days: int,
                          accolades: dict[str, int]) -> list[str]:
    """Human-readable reasons behind an Achievements score, biggest first.

    Exists so the rating is never a bare number the GM has to take on trust —
    the same reason the progression engine ships a reason with every suggestion.
    """
    parts: list[tuple[float, str]] = []
    for tier, n in reigns_by_tier.items():
        if n:
            pts = TITLE_POINTS.get(tier, 1.0) * n
            parts.append((pts, f"{n}× {tier} title" + ("s" if n > 1 else "")))
    if title_days > 0:
        parts.append((min(TITLE_DAYS_CAP, title_days / TITLE_DAYS_DIVISOR),
                      f"{title_days:,} days as champion"))
    for kind, n in accolades.items():
        if n:
            pts = ACHIEVEMENT_POINTS.get(kind, 0.5) * n
            label = kind.replace("_", " ")
            parts.append((pts, f"{n}× {label}" if n > 1 else label))
    parts.sort(key=lambda p: -p[0])
    return [label for _, label in parts]


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
    wrs = wrestling(s)
    if pop >= 13:            # the biggest draws know their worth
        return "money_hungry"
    if pop <= 7:             # lower-card hands, just glad of the work
        return "loyal"
    # The crowded mid-card splits deterministically into egos and up-and-comers.
    return "prima_donna" if (wrs + pop) % 2 == 0 else "ambitious"


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
        "wrestling": wrestling(s),
        "popularity": popularity(s),
        "looks": looks(s),
        "personal": personal(s),
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
#
# RE-ANCHORED FOR THE FIVE-CATEGORY SCALE, by solving rather than by taste.
#
# Achievements now starts at 0 for absolutely everyone, so the day-one spread is
# COMPRESSED against the old four-category one — 18-65 where it used to be 23-70.
# Left alone, the old curve made the best wrestler alive cost upper-mid money in
# the first draft. Two anchors are the ones worth holding, so the exponent and
# the base were solved for both at once off the real roster distribution:
#
#     top      overall 65  ->  $1.24M   a genuine headline draw, day one
#     median   overall 44  ->  $0.31M   unchanged from the old system, so the
#                                       total payroll stays in the same place
#
# and the rest of the curve falls out of those:
#
#     overall 62  ->  ~$0.97M   (upper card)
#     overall 50  ->  ~$0.44M
#     overall 40  ->  ~$0.20M   (lower-mid)
#     overall 32  ->  ~$0.09M
#     overall 22  ->   $40k     (floor — enhancement talent)
#
# The exponent came out STEEPER than the old 2.95, and that is a move toward the
# 2006 payroll sheet rather than away from it: on the real thing the top earner
# made roughly seven times the median, which needs an exponent near 4, not 3. It
# also does the job the old comment claimed — one draw now genuinely earns more
# than the six hands below her combined.
#
# THE CONSEQUENCE, stated plainly: Achievements only ever goes up, so a wrestler
# who wins things gets more expensive every season. A champion who accumulates a
# full 20 points across a long save more than doubles her price on that alone.
# That is deliberate — winning should cost you — and it is why STARTING_BUDGET
# and BUDGET_GROWTH in game.py were lifted alongside this. If re-signing your own
# champions ever feels impossible rather than merely painful, the growth rate is
# the dial to turn, not this exponent.
BASE_VALUE = 5_470_000   # what a hypothetical 100 overall at age 28 commands
VALUE_EXPONENT = 3.62
MIN_VALUE = 40_000


def overall(wrestling_: int, achievements_: int, popularity_: int,
            looks_: int, personal_: int) -> int:
    """0-100 overall: the plain SUM of five categories each capped at 20.

    Deliberately unweighted. Every category is worth the same 20 points, so the
    number on screen is always the five numbers next to it added up.
    """
    total = wrestling_ + achievements_ + popularity_ + looks_ + personal_
    return int(max(0, min(OVERALL_MAX, total)))


def contract_value(wrestling_: int, achievements_: int, popularity_: int,
                   looks_: int, personal_: int, age: int | None) -> int:
    """Annual contract value in game dollars.

    Superlinear in the composite rating (exponent ~3) so the top of the roster
    separates sharply from the middle — the way real wrestling money works, where
    one draw earns more than the six people below her combined. See BASE_VALUE
    for the 2006-grounded anchor points and for why winning gets expensive.
    """
    score = overall(wrestling_, achievements_, popularity_, looks_, personal_) / 100.0
    raw = BASE_VALUE * (score ** VALUE_EXPONENT) * age_multiplier(age)
    return max(MIN_VALUE, int(round(raw / 10_000) * 10_000))
