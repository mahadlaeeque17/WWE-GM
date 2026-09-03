"""Promo segments — the half of a show that isn't a match.

WHY THESE EXIST AS A FIRST-CLASS SEGMENT. Rivalry heat used to come from one
place: booking two women against each other. That makes a feud a series of
matches, which is not how wrestling works — the match is the payoff and the
talking is the build. A promo is therefore the cheap way to build heat (no
fatigue to speak of, no injury risk) and a match is the expensive way to cash it
in. That trade-off is the whole reason a two-promo slot exists on every card.

WHAT DECIDES HOW A PROMO GOES. Mic work, then star power, then what she has
actually won — a champion talking means more than a rookie talking. Wrestling
ability barely registers, which is the point: the promo segment rewards a
different worker than the main event does, so a roster has two kinds of value.

HOW IT PAYS OFF. Each promo type has its own effects — a contract signing builds
a lot of heat, a run-in beatdown swings momentum hard in the aggressor's favour,
a title presentation adds prestige to the belt. Promos also count toward the show
rating (at a lower weight than matches) so two dead segments drag a night down.

Deterministic like everything else in the sim: the roll comes from the save seed,
the show id and the slot.
"""
from __future__ import annotations

import random
import sqlite3

import crowd
import game

SCHEMA = """
CREATE TABLE IF NOT EXISTS sim_promo (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    show_id  INTEGER NOT NULL REFERENCES show(id),
    slot     INTEGER NOT NULL,          -- position on the card, shares the run with matches
    kind     TEXT NOT NULL,             -- a PROMO_TYPES key
    quality  REAL,                      -- 0-100, same scale as a match
    feud_id  INTEGER REFERENCES feud(id),
    topic    TEXT,
    note     TEXT
);
CREATE TABLE IF NOT EXISTS sim_promo_participant (
    promo_id    INTEGER NOT NULL REFERENCES sim_promo(id),
    wrestler_id INTEGER NOT NULL REFERENCES wrestler(id),
    seat        INTEGER NOT NULL DEFAULT 0,   -- 0 = whoever has the mic / the aggressor
    PRIMARY KEY (promo_id, wrestler_id)
);
CREATE INDEX IF NOT EXISTS idx_promo_show ON sim_promo(show_id, slot);
CREATE INDEX IF NOT EXISTS idx_promo_part ON sim_promo_participant(wrestler_id);
"""


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    con.commit()


# ---------------------------------------------------------------- the types
#
# min/max      how many women are in the segment
# heat         rivalry heat added if the participants are feuding
# momentum     momentum for the woman holding the mic (seat 0)
# guest_mom    momentum for everyone else in it
# quality      a flat bonus/penalty in quality points — a contract signing is
#              inherently a bigger deal than a backstage word
# needs_feud   the segment makes no sense without a rivalry to build
# fatigue      talking is not wrestling; most of these cost almost nothing

PROMO_TYPES: dict[str, dict] = {
    "callout": {
        "label": "Callout", "min": 1, "max": 2, "heat": 8, "momentum": 4,
        "guest_mom": 0, "quality": 0, "fatigue": 1, "needs_feud": False,
        "desc": "One woman in the ring names her rival and demands the match.",
    },
    "backstage_interview": {
        "label": "Backstage Interview", "min": 1, "max": 2, "heat": 5, "momentum": 3,
        "guest_mom": 1, "quality": -2, "fatigue": 0, "needs_feud": False,
        "desc": "A word with the interviewer by the production trucks. Cheap and quiet.",
    },
    "open_challenge": {
        "label": "Open Challenge", "min": 1, "max": 2, "heat": 6, "momentum": 5,
        "guest_mom": 2, "quality": 2, "fatigue": 1, "needs_feud": False,
        "desc": "A champion opens the floor to anybody in the back.",
    },
    "face_to_face": {
        "label": "Face-to-Face", "min": 2, "max": 2, "heat": 12, "momentum": 3,
        "guest_mom": 3, "quality": 3, "fatigue": 1, "needs_feud": True,
        "desc": "Both women, one ring, nose to nose. Nothing sells a match faster.",
    },
    "contract_signing": {
        "label": "Contract Signing", "min": 2, "max": 2, "heat": 16, "momentum": 2,
        "guest_mom": 2, "quality": 5, "fatigue": 1, "needs_feud": True,
        "desc": "A table, two pens and a brawl. The formal build to a big match.",
    },
    "run_in_beatdown": {
        "label": "Run-In Beatdown", "min": 2, "max": 4, "heat": 18, "momentum": 8,
        "guest_mom": -6, "quality": 4, "fatigue": 4, "needs_feud": True,
        "desc": "The aggressor jumps her rival from behind. Heat, and a momentum swing.",
    },
    "title_presentation": {
        "label": "Title Presentation", "min": 1, "max": 2, "heat": 3, "momentum": 5,
        "guest_mom": 1, "quality": 2, "fatigue": 0, "needs_feud": False,
        "prestige": 2,
        "desc": "The champion holds the belt up and reminds everybody why it matters.",
    },
    "stable_announcement": {
        "label": "Stable Announcement", "min": 2, "max": 5, "heat": 6, "momentum": 5,
        "guest_mom": 4, "quality": 3, "fatigue": 1, "needs_feud": False,
        "desc": "A faction forms, adds a member, or turns on one. Lifts everybody in it.",
    },
    "in_ring_apology": {
        "label": "In-Ring Apology", "min": 1, "max": 2, "heat": 7, "momentum": -3,
        "guest_mom": 2, "quality": 1, "fatigue": 0, "needs_feud": False,
        "desc": "Made to say sorry. Humbling — it costs her momentum and earns sympathy.",
    },
    "gm_address": {
        "label": "GM Address", "min": 1, "max": 3, "heat": 4, "momentum": 2,
        "guest_mom": 1, "quality": 0, "fatigue": 0, "needs_feud": False,
        "desc": "Authority sets the stakes: a stipulation, a #1 contender, a warning.",
    },
}

DEFAULT = "callout"

# What a promo is scored on. Mic first, then how over she is, then what she has
# won. Wrestling barely counts — that is the point of the segment existing.
MIC_WEIGHTS = {"mic": 0.42, "popularity": 0.26, "achievements": 0.14,
               "looks": 0.09, "personal": 0.06, "wrestling": 0.03}

# Promos come in below matches on the 0-100 scale on purpose: a great segment is
# a great segment, but the main event is what a night is remembered for.
PROMO_SHOW_WEIGHT = 0.5

# CALIBRATION — why these two numbers exist.
#
# A mic score and a match's quality base are both built from 0-20 categories, so
# both land in roughly 5-16. But a MATCH then collects about twenty-five points
# of additive bonuses a promo has no equivalent of: the slot bonus, the title
# bonus, style chemistry, the stipulation and the production. Scored raw, the
# same calibre of performer read 5-19 on the mic against 13-41 in the ring — so
# booking a promo at all dragged the show rating down, which is exactly backwards
# from the intent.
#
# The fix is to put the promo's own spread on the match's footing rather than to
# invent bonuses for it. SPREAD stretches the mic score across a comparable
# range and FLOOR is the promo's answer to the slot bonus — the segment is on
# television and the building is full. With these, an average talker lands near
# an average match and an exceptional one beats it, which is the point of the
# segment existing.
PROMO_SPREAD = 2.4
PROMO_FLOOR = 8.0


def catalogue() -> list[dict]:
    return [{"key": k, **v} for k, v in PROMO_TYPES.items()]


def get(key: str | None) -> dict:
    return PROMO_TYPES.get(key or DEFAULT, PROMO_TYPES[DEFAULT])


def validate(kind: str | None, wrestler_ids: list[int]) -> None:
    p = get(kind)
    ids = [w for w in wrestler_ids if w]
    if len(ids) != len(set(ids)):
        raise ValueError(f"The same woman is in the {p['label']} segment twice.")
    if len(ids) < p["min"]:
        raise ValueError(f"A {p['label']} needs at least {p['min']} "
                         f"{'woman' if p['min'] == 1 else 'women'}.")
    if len(ids) > p["max"]:
        raise ValueError(f"A {p['label']} holds at most {p['max']} women.")


def _rng(seed: int, show_id: int, slot: int) -> random.Random:
    """A stream of its own, offset from the match streams so a promo in slot 3
    and a match in slot 3 do not share rolls."""
    return random.Random((seed * 2_000_003) ^ (show_id * 4_513) ^ (slot * 97))


def simulate_promo(
    con: sqlite3.Connection,
    show_id: int,
    slot: int,
    kind: str,
    wrestler_ids: list[int],
    seed: int,
    topic: str | None = None,
    is_ppv: bool = False,
) -> dict:
    """Resolve one promo segment WITHOUT writing it — same contract as
    `sim.simulate_match`, so a whole show can be built then committed."""
    validate(kind, wrestler_ids)
    p = get(kind)
    ids = [w for w in wrestler_ids if w]
    rng = _rng(seed, show_id, slot)

    ach = game.achievement_inputs(con)
    attrs = {w: game.effective_attributes(con, w, ach.get(w)) for w in ids}

    def mic_score(w: int) -> float:
        a = attrs[w]
        return sum(a.get(k, 0) * v for k, v in MIC_WEIGHTS.items())

    scores = [mic_score(w) for w in ids]
    # The woman on the mic carries the segment; the others are there to react.
    base = scores[0] * 0.6 + (sum(scores) / len(scores)) * 0.4

    state = {w: con.execute("SELECT momentum, morale FROM wrestler_state WHERE wrestler_id=?",
                            (w,)).fetchone() for w in ids}
    avg_mom = sum((state[w]["momentum"] if state[w] else 50) for w in ids) / len(ids)
    avg_morale = sum((state[w]["morale"] if state[w] else 50) for w in ids) / len(ids)

    # A rivalry gives the segment something to be ABOUT. Without one a promo is
    # just talking, and it lands flatter.
    feud, feud_heat = None, 0
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            f = game.feud_between(con, ids[i], ids[j])
            if f and f["heat"] > feud_heat:
                feud, feud_heat = f, f["heat"]
    feud_bonus = feud_heat * 0.12 if feud else (-4 if p["needs_feud"] else 0)

    # Good vs evil: a heel and a face in the same segment has a natural argument.
    aligns = {attrs[w].get("alignment") or "face" for w in ids}
    align_bonus = 5 if ("face" in aligns and "heel" in aligns) else (0 if len(ids) == 1 else -3)

    quality = base * PROMO_SPREAD + PROMO_FLOOR \
        + (avg_mom - 50) * 0.10 + (avg_morale - 50) * 0.06 \
        + feud_bonus + align_bonus + p["quality"] + (4 if is_ppv else 0) \
        + rng.gauss(0, 5)
    quality = max(0.0, min(100.0, quality))

    # A promo has a crowd reaction like a match does, and each woman in it gets
    # her own read — a heel cutting a great promo SHOULD be booed harder, and
    # the one who is cheered anyway is the one who wants turning.
    react = crowd.segment_reaction(quality, base, feud_heat, aligns, is_ppv, False)
    pops: dict[int, tuple[float, str]] = {}
    for seat, wid in enumerate(ids):
        al = attrs[wid].get("alignment") or "face"
        pops[wid] = (crowd.wrestler_pop(
            al, attrs[wid]["popularity"],
            (state[wid]["momentum"] if state[wid] else 50),
            quality,
            # Holding the mic is the promo equivalent of winning: she controlled
            # the segment. The victim of a beatdown is the one taking the fall.
            won=(seat == 0 and kind != "in_ring_apology"),
            beaten_clean=(kind == "run_in_beatdown" and seat > 0),
            cheap_finish=False, feud_heat=feud_heat), al)

    return {
        "slot": slot, "kind": kind, "label": p["label"], "wrestler_ids": ids,
        "quality": round(quality, 1), "feud_id": feud["id"] if feud else None,
        "feud_heat": feud_heat, "topic": topic,
        "alignment_bonus": align_bonus, "is_promo": True,
        "pops": pops, **react,
    }


def apply_promo(con: sqlite3.Connection, show_id: int, res: dict) -> int:
    """Commit one promo: the row, the participants, and everything it moved."""
    p = get(res["kind"])
    cur = con.execute(
        "INSERT INTO sim_promo (show_id, slot, kind, quality, feud_id, topic, "
        "reaction, reaction_score) VALUES (?,?,?,?,?,?,?,?)",
        (show_id, res["slot"], res["kind"], res["quality"], res.get("feud_id"),
         res.get("topic"), res.get("reaction"), res.get("reaction_score")))
    promo_id = cur.lastrowid
    if res.get("pops"):
        crowd.record_pops(con, "promo", promo_id, res["pops"])

    ids = res["wrestler_ids"]
    for seat, wid in enumerate(ids):
        con.execute("INSERT INTO sim_promo_participant (promo_id, wrestler_id, seat) "
                    "VALUES (?,?,?)", (promo_id, wid, seat))

    # A segment that went well lifts everybody in it; a stinker does not.
    lift = 1.0 if res["quality"] >= 55 else 0.4
    for seat, wid in enumerate(ids):
        delta = p["momentum"] if seat == 0 else p["guest_mom"]
        con.execute(
            """UPDATE wrestler_state SET
                 momentum = MAX(0, MIN(100, momentum + ?)),
                 morale   = MAX(0, MIN(100, morale + ?)),
                 fatigue  = MIN(100, fatigue + ?)
               WHERE wrestler_id=?""",
            (int(round(delta * lift)), 1 if res["quality"] >= 55 else 0,
             p["fatigue"], wid))

    # Heat: this is the cheap way to build a feud, and the reason to book one.
    if res.get("feud_id"):
        con.execute("UPDATE feud SET heat = MAX(0, MIN(100, heat + ?)) WHERE id=?",
                    (int(p["heat"] * lift), res["feud_id"]))
        import storylines                                    # noqa: PLC0415 — cycle
        st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
        on = st["current_date"] if st else None
        who = " & ".join(game._wname(con, w) for w in ids)
        storylines.add_beat(
            con, res["feud_id"], on or "", "run_in" if res["kind"] == "run_in_beatdown"
            else "promo",
            f"{p['label']}: {who} — {res['quality']:.0f}/100",
            show_id=show_id)
        storylines.sync_stage(con, res["feud_id"])

    # A run-in beatdown where a face lays out another face IS a heel turn. The
    # booking already happened; turns.py only files the paperwork for approval.
    if res["kind"] == "run_in_beatdown" and len(ids) >= 2:
        import turns                                         # noqa: PLC0415 — cycle
        turns.note_betrayal(con, ids[0], ids[1],
                            f"Attacked {game._wname(con, ids[1])} from behind in a "
                            f"run-in beatdown.")

    # A title presentation is the champion reminding everyone what the belt is.
    if p.get("prestige"):
        held = con.execute(
            """SELECT t.id FROM game_title t
               JOIN game_title_reign r ON r.title_id=t.id AND r.lost_on IS NULL
               WHERE r.wrestler_id=?""", (ids[0],)).fetchone()
        if held:
            con.execute("UPDATE game_title SET prestige = MIN(100, prestige + ?) WHERE id=?",
                        (p["prestige"], held["id"]))

    names = " & ".join(game._wname(con, w) for w in ids)
    game.log_event(con, "promo", f"{p['label']}: {names} — {res['quality']:.0f}/100",
                   icon="🎤")
    return promo_id


def for_show(con: sqlite3.Connection, show_id: int) -> list[dict]:
    """Every promo on a show, with its participants — for the show detail view."""
    ensure_schema(con)
    out = []
    for r in con.execute("SELECT * FROM sim_promo WHERE show_id=? ORDER BY slot", (show_id,)):
        d = dict(r)
        d["label"] = get(d["kind"])["label"]
        d["participants"] = [dict(x) for x in con.execute(
            """SELECT p.wrestler_id, p.seat, COALESCE(o.display_name, w.name) name,
                      (SELECT id FROM wrestler_image i WHERE i.wrestler_id=p.wrestler_id
                         AND i.is_profile=1 LIMIT 1) profile_image_id
               FROM sim_promo_participant p
               JOIN wrestler w ON w.id=p.wrestler_id
               LEFT JOIN attribute_override o ON o.wrestler_id=p.wrestler_id
               WHERE p.promo_id=? ORDER BY p.seat""", (d["id"],))]
        out.append(d)
    return out


def season_counts(con: sqlite3.Connection, season: int) -> dict[int, dict]:
    """Promo volume and average quality per wrestler for a season.

    Feeds rating progression: a woman who carried the talking half of the show
    all year has earned Popularity even if she never headlined.
    """
    ensure_schema(con)
    out: dict[int, dict] = {}
    for r in con.execute(
        """SELECT pp.wrestler_id wid, COUNT(*) n, AVG(p.quality) q
             FROM sim_promo_participant pp
             JOIN sim_promo p ON p.id = pp.promo_id
             JOIN show s ON s.id = p.show_id
            WHERE s.held_on BETWEEN ? AND ?
            GROUP BY pp.wrestler_id""", (f"{season}-01-01", f"{season}-12-31")):
        out[r["wid"]] = {"promos": r["n"], "avg_promo": round(r["q"] or 0, 1)}
    return out
