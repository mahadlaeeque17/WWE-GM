"""What is wrong with this card, before you run it.

WHY THIS IS SEPARATE FROM VALIDATION. `sim.run_show` already REFUSES an illegal
card: a half-filled Fatal 4-Way, somebody booked twice, a woman on the injury
shelf. Those are errors and stopping them is correct. But the far more common
problem is a card that is perfectly legal and simply bad — the same two women
for the third week running, a title match nobody has been built for, four
matches with no heel in any of them, a main event weaker than the opener. The
sim will happily run all of that, and you find out afterwards from a rating.

So this is ADVISORY, never blocking. Every finding has a level, a sentence that
says what is wrong, and a fix — and the GM confirms anyway if she disagrees,
because she is the one booking the show. The whole point is to move the feedback
from after the show to before it.

Each check reads something the save already knows, so nothing here is a guess:
recent cards, storyline heat, alignments, stamina, the contender ladder.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import game
import medical
import storylines

# How far back "recently" looks when judging repetition. Three shows is roughly
# a fortnight of television, which is where the same match starts to feel stale.
RECENT_SHOWS = 3

# Levels, in the order they are shown. `problem` is something that will visibly
# hurt the show; `note` is a missed opportunity.
LEVELS = ("problem", "note")


def _recent_shows(con: sqlite3.Connection, brand_id: str, n: int) -> list[int]:
    return [r["id"] for r in con.execute(
        """SELECT id FROM show WHERE brand_id=? ORDER BY held_on DESC, id DESC LIMIT ?""",
        (brand_id, n))]


def _recent_pairings(con: sqlite3.Connection, shows: list[int]) -> dict[frozenset, int]:
    """How often each pairing has already happened lately."""
    if not shows:
        return {}
    marks = ",".join("?" * len(shows))
    seen: dict[frozenset, int] = {}
    for m in con.execute(
        f"SELECT id FROM sim_match WHERE show_id IN ({marks})", shows):
        sides: dict[int, list[int]] = {}
        for p in con.execute(
            "SELECT wrestler_id, team FROM sim_match_participant WHERE match_id=?",
            (m["id"],)):
            sides.setdefault(p["team"], []).append(p["wrestler_id"])
        keys = list(sides)
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                for a in sides[keys[i]]:
                    for b in sides[keys[j]]:
                        k = frozenset({a, b})
                        seen[k] = seen.get(k, 0) + 1
    return seen


def _worked_count(con: sqlite3.Connection, shows: list[int]) -> dict[int, int]:
    if not shows:
        return {}
    marks = ",".join("?" * len(shows))
    return {r["wrestler_id"]: r["n"] for r in con.execute(
        f"""SELECT p.wrestler_id, COUNT(*) n FROM sim_match_participant p
              JOIN sim_match m ON m.id=p.match_id
             WHERE m.show_id IN ({marks}) GROUP BY p.wrestler_id""", shows)}


def review(con: sqlite3.Connection, brand_id: str, card: list[dict],
           promos: list[dict] | None = None, kind: str = "tv") -> dict:
    """Read a card the way somebody who has booked before would read it.

    Returns {findings: [...], counts: {...}}. Advisory only — nothing here can
    stop a show being run.
    """
    promos = promos or []
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if not st:
        return {"findings": [], "counts": {}}
    today, season = st["current_date"], st["season_year"]
    findings: list[dict] = []

    def add(level: str, key: str, text: str, fix: str | None = None) -> None:
        findings.append({"level": level, "key": key, "text": text, "fix": fix})

    if not card:
        return {"findings": [], "counts": {"problem": 0, "note": 0}}

    ach = game.achievement_inputs(con)
    attrs: dict[int, dict] = {}

    def A(wid: int) -> dict:
        if wid not in attrs:
            try:
                attrs[wid] = game.effective_attributes(con, wid, ach.get(wid))
            except ValueError:
                attrs[wid] = {}
        return attrs[wid]

    booked = [w for m in card for t in m["teams"] for w in t if w]
    shows = _recent_shows(con, brand_id, RECENT_SHOWS)
    pairings = _recent_pairings(con, shows)
    worked = _worked_count(con, shows)
    feuds = game.list_feuds(con, "active")
    feud_of = {frozenset({f["a_id"], f["b_id"]}): f for f in feuds}

    # ---- repetition ------------------------------------------------------
    for m in card:
        sides = m["teams"]
        for i in range(len(sides)):
            for j in range(i + 1, len(sides)):
                for a in sides[i]:
                    for b in sides[j]:
                        n = pairings.get(frozenset({a, b}), 0)
                        if n >= 2:
                            add("problem", "repeat",
                                f"{game._wname(con, a)} vs {game._wname(con, b)} has "
                                f"already happened {n} times in the last "
                                f"{len(shows)} shows.",
                                "Give it a gimmick, add a third woman, or book "
                                "something else and come back to it.")

    # ---- overwork --------------------------------------------------------
    for wid in set(booked):
        n = worked.get(wid, 0)
        if n >= RECENT_SHOWS:
            add("note", "overworked",
                f"{game._wname(con, wid)} has worked every one of the last {n} shows.",
                "Rest her, or leave her off this one.")
        r = medical.risk(con, wid, today)
        if r["level"] in ("risky", "reckless"):
            add("problem", "risk",
                f"{game._wname(con, wid)} is {r['level']} to book — "
                f"{', '.join(r['reasons'])}.",
                "Rest her before she gets hurt.")

    # ---- conflict --------------------------------------------------------
    flat_matches = 0
    for m in card:
        aligns = {(A(w).get("alignment") or "face") for t in m["teams"] for w in t if w}
        if len(aligns) == 1:
            flat_matches += 1
    if flat_matches and flat_matches == len(card):
        add("problem", "no_conflict",
            "Not one match on this card has a face against a heel.",
            "Good against evil is what the crowd buys — swap somebody in.")
    elif flat_matches >= 2:
        add("note", "some_flat",
            f"{flat_matches} matches have no face-vs-heel conflict.",
            "The sim rewards a clear story; these will rate lower.")

    # ---- the main event --------------------------------------------------
    def wattage(m: dict) -> float:
        ws = [w for t in m["teams"] for w in t if w]
        if not ws:
            return 0.0
        return sum((A(w).get("popularity") or 0) for w in ws) / len(ws)

    if len(card) >= 2:
        me, opener = wattage(card[-1]), wattage(card[0])
        if me < opener - 1.5:
            add("problem", "backwards",
                "The opener has more star power than the main event.",
                "Move the biggest match last — it counts double toward the rating.")
        if not card[-1].get("title_id") and not any(
                feud_of.get(frozenset({a, b})) and
                feud_of[frozenset({a, b})]["heat"] >= game.FEUD_BLOWOFF_HEAT
                for i in range(len(card[-1]["teams"]))
                for j in range(i + 1, len(card[-1]["teams"]))
                for a in card[-1]["teams"][i] for b in card[-1]["teams"][j]):
            add("note", "cold_main",
                "The main event has no belt on it and no hot rivalry behind it.",
                "A title or a blow-off is what makes a match feel like a main event.")

    # ---- titles without a story -----------------------------------------
    for m in card:
        if not m.get("title_id"):
            continue
        ws = [w for t in m["teams"] for w in t if w]
        has_story = any(feud_of.get(frozenset({a, b}))
                        for i, a in enumerate(ws) for b in ws[i + 1:])
        if not has_story:
            t = con.execute("SELECT short_name, name FROM game_title WHERE id=?",
                            (m["title_id"],)).fetchone()
            add("note", "cold_title",
                f"The {t['short_name'] or t['name']} match has no rivalry behind it.",
                "Start a storyline between them, or build it with a promo first.")

    # ---- wasted heat -----------------------------------------------------
    on_card = set(booked) | {w for p in promos for w in (p.get("wrestler_ids") or [])}
    signed = {r["wrestler_id"] for r in con.execute(
        """SELECT wrestler_id FROM contract WHERE brand_id=? AND terminated_on IS NULL
             AND start_year<=? AND end_year>=?""", (brand_id, season, season))}
    for f in feuds:
        if storylines.kind_of(f) != "rivalry":
            continue
        if f["heat"] < game.FEUD_BLOWOFF_HEAT:
            continue
        pair = {f["a_id"], f["b_id"]}
        if not (pair & signed):
            continue
        if pair & on_card:
            continue
        if f["planned_blowoff"] and f["planned_blowoff"] > today:
            continue          # deliberately being held back, which is correct
        add("note", "wasted_heat",
            f"{game._wname(con, f['a_id'])} and {game._wname(con, f['b_id'])} are at "
            f"{f['heat']} heat and are not on this card at all.",
            "Heat decays if you ignore it — book the blow-off or at least a promo.")

    # ---- protected feuds being given away -------------------------------
    for m in card:
        sides = m["teams"]
        if len(sides) != 2 or any(len(t) != 1 for t in sides):
            continue          # only a straight singles gives a blow-off away
        a, b = sides[0][0], sides[1][0]
        f = feud_of.get(frozenset({a, b}))
        if f and f["planned_blowoff"] and f["planned_blowoff"] > today:
            add("problem", "gave_it_away",
                f"{game._wname(con, a)} vs {game._wname(con, b)} is being built to "
                f"{f['blowoff_label'] or f['planned_blowoff']} — this gives the match "
                f"away early.",
                "Put them on opposite sides of a tag instead, or clear the plan.")

    # ---- romances booked as matches -------------------------------------
    for m in card:
        ws = [w for t in m["teams"] for w in t if w]
        for i, a in enumerate(ws):
            for b in ws[i + 1:]:
                f = feud_of.get(frozenset({a, b}))
                if not f:
                    continue
                k = storylines.kind_of(f)
                if k == "rivalry":
                    continue
                # Same side is fine for an alliance; opposite sides is not.
                same = any(a in t and b in t for t in m["teams"])
                if not same and not storylines.wants_match(k):
                    label = storylines.KINDS[k]["label"].lower()
                    add("problem", "wrong_kind",
                        f"{game._wname(con, a)} and {game._wname(con, b)} are in a "
                        f"{label} and this books them against each other.",
                        f"Break it up first if that is what you want — that turns the "
                        f"{label} into a rivalry that starts hot.")

    # ---- promo slots ------------------------------------------------------
    if not promos:
        add("note", "no_promos",
            "No promo segments on this card.",
            "Talking is the cheap way to build a rivalry — a match is the "
            "expensive way to cash it in.")

    counts = {lv: sum(1 for f in findings if f["level"] == lv) for lv in LEVELS}
    return {"findings": findings, "counts": counts,
            "verdict": _verdict(counts, len(card))}


def _verdict(counts: dict, n: int) -> str:
    if counts.get("problem"):
        return (f"{counts['problem']} thing{'s' if counts['problem'] != 1 else ''} "
                f"here will hurt the show.")
    if counts.get("note"):
        return f"{counts['note']} missed opportunit{'ies' if counts['note'] != 1 else 'y'}."
    return "Nothing wrong with this card."
