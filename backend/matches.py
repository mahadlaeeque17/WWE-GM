"""Match STRUCTURES — how many sides and how many bodies on each.

This is deliberately a separate axis from `booking.STIPULATIONS`, which is the
RULES (steel cage, tables, no-DQ). The two compose: a Fatal 4-Way inside a Steel
Cage is a structure and a stipulation, not a thirty-entry list of every possible
combination. Keeping them apart is also what lets the auto-booker choose a shape
from who is available and a stipulation from how hot the feud is, independently.

WHY A STRUCTURE CHANGES QUALITY AND FATIGUE. A triple threat has no rest holds
and three people looking for a pin — more spots, more chaos, a shade better on
average and harder on the body. A six-woman tag is the opposite: everyone gets a
breather on the apron, so it goes over well and costs less stamina per worker.
Those two numbers are the whole mechanical difference; the sim's existing team
strength maths already handles "more people on a side" correctly.

`sides` is how many corners the match has, `sizes` how many workers per corner.
Either may be a (min, max) range — a battle royal is any number of one-woman
sides, a handicap is 1 against 2..3.
"""
from __future__ import annotations

# key -> label, shape, and what the shape does to the match
MATCH_TYPES: dict[str, dict] = {
    "singles": {
        "label": "Singles", "short": "1 v 1", "sides": 2, "sizes": 1,
        "quality": 0, "fatigue": 1.0,
        "desc": "One on one. The baseline — nothing helps or hurts it.",
    },
    "tag": {
        "label": "Tag Team", "short": "2 v 2", "sides": 2, "sizes": 2,
        "quality": 2, "fatigue": 0.85,
        "desc": "Two on two. Hot tags and a breather on the apron — easy to get right.",
    },
    "six_woman": {
        "label": "Six-Woman Tag", "short": "3 v 3", "sides": 2, "sizes": 3,
        "quality": 3, "fatigue": 0.72,
        "desc": "Three on three. Plenty of bodies, plenty of rest — kind on stamina.",
    },
    "triple_threat": {
        "label": "Triple Threat", "short": "3-way", "sides": 3, "sizes": 1,
        "quality": 4, "fatigue": 1.15,
        "desc": "Three corners, no tags, no rest. Anyone can steal it.",
    },
    "fatal_four_way": {
        "label": "Fatal 4-Way", "short": "4-way", "sides": 4, "sizes": 1,
        "quality": 5, "fatigue": 1.22,
        "desc": "Four corners. Chaos — the strongest woman in it can lose without being beaten.",
    },
    "tag_triple_threat": {
        "label": "Triple Threat Tag", "short": "3-way tag", "sides": 3, "sizes": 2,
        "quality": 5, "fatigue": 1.0,
        "desc": "Three teams, one fall. A tag division's blow-off match.",
    },
    "handicap": {
        "label": "Handicap", "short": "1 v 2", "sides": 2, "sizes": (1, 3),
        "quality": 1, "fatigue": 1.1, "uneven": True,
        "desc": "Outnumbered. A storyline match — the odds are the story.",
    },
    "gauntlet": {
        "label": "Gauntlet", "short": "gauntlet", "sides": (3, 6), "sizes": 1,
        "quality": 4, "fatigue": 1.3,
        "desc": "One after another until nobody is left standing.",
    },
    "battle_royal": {
        "label": "Battle Royal", "short": "royal", "sides": (6, 16), "sizes": 1,
        "quality": 3, "fatigue": 1.25,
        "desc": "Over the top rope. A whole division in one match.",
    },
}

DEFAULT = "singles"


def catalogue() -> list[dict]:
    """The list the booking screen renders, with the shape flattened for the UI."""
    out = []
    for key, m in MATCH_TYPES.items():
        lo_s, hi_s = _range(m["sides"])
        lo_p, hi_p = _range(m["sizes"])
        out.append({
            "key": key, "label": m["label"], "short": m["short"], "desc": m["desc"],
            "min_sides": lo_s, "max_sides": hi_s,
            "min_per_side": lo_p, "max_per_side": hi_p,
            "quality": m["quality"], "fatigue": m["fatigue"],
            "uneven": bool(m.get("uneven")),
            "wrestlers": lo_s * lo_p,
        })
    return out


def _range(v) -> tuple[int, int]:
    return (v[0], v[1]) if isinstance(v, (tuple, list)) else (v, v)


def get(key: str | None) -> dict:
    return MATCH_TYPES.get(key or DEFAULT, MATCH_TYPES[DEFAULT])


def quality_bonus(key: str | None) -> float:
    return float(get(key)["quality"])


def fatigue_factor(key: str | None) -> float:
    return float(get(key)["fatigue"])


def default_teams(key: str | None) -> list[list[int]]:
    """An empty skeleton of the right shape — what the UI opens a new row with."""
    m = get(key)
    sides, _ = _range(m["sides"])
    per, _ = _range(m["sizes"])
    if m.get("uneven"):
        return [[0], [0, 0]]
    return [[0] * per for _ in range(sides)]


def infer(teams: list[list[int]]) -> str:
    """Name the shape of a card row that carries no match_type.

    Saves written before match types existed, and the AI/auto card, are all
    plain lists of sides — they still have to display as something.
    """
    sides = len(teams)
    sizes = sorted({len(t) for t in teams})
    if sides == 2 and sizes == [1]:
        return "singles"
    if sides == 2 and sizes == [2]:
        return "tag"
    if sides == 2 and sizes == [3]:
        return "six_woman"
    if sides == 2 and len(sizes) > 1:
        return "handicap"
    if sides == 3 and sizes == [1]:
        return "triple_threat"
    if sides == 3 and sizes == [2]:
        return "tag_triple_threat"
    if sides == 4 and sizes == [1]:
        return "fatal_four_way"
    if sides >= 6 and sizes == [1]:
        return "battle_royal"
    if sides >= 3 and sizes == [1]:
        return "gauntlet"
    return "singles"


def validate(key: str | None, teams: list[list[int]]) -> None:
    """Raise ValueError unless `teams` is a legal shape for this match type.

    Called before anything is simulated, so a half-filled Fatal 4-Way never
    reaches the sim and silently resolves as a triple threat.
    """
    m = get(key)
    label = m["label"]
    lo_s, hi_s = _range(m["sides"])
    lo_p, hi_p = _range(m["sizes"])
    if not lo_s <= len(teams) <= hi_s:
        want = f"{lo_s}" if lo_s == hi_s else f"{lo_s}–{hi_s}"
        raise ValueError(f"A {label} match needs {want} sides, not {len(teams)}.")
    for i, t in enumerate(teams, start=1):
        if not lo_p <= len(t) <= hi_p:
            want = f"{lo_p}" if lo_p == hi_p else f"{lo_p}–{hi_p}"
            raise ValueError(f"A {label} match needs {want} wrestler(s) on each side "
                             f"— side {i} has {len(t)}.")
        if any(not w for w in t):
            raise ValueError(f"The {label} match has an empty slot — fill every spot or "
                             f"change the match type.")
    if m.get("uneven") and len({len(t) for t in teams}) == 1:
        raise ValueError(f"A {label} match has to be uneven — one side needs more bodies.")
    flat = [w for t in teams for w in t]
    if len(flat) != len(set(flat)):
        raise ValueError(f"Someone is booked twice in the same {label} match.")


def describe(key: str | None, teams: list[list[int]], names: dict[int, str]) -> str:
    """"Alundra Blayze & Bull Nakano vs …" — used in logs and the AI prompt."""
    def side(t):
        return " & ".join(names.get(w, str(w)) for w in t)
    joined = " vs ".join(side(t) for t in teams)
    m = get(key)
    return joined if key in (None, "singles") else f"{joined} ({m['label']})"
