"""Feuds as STORIES rather than heat counters.

THE PROBLEM THIS FIXES. A feud was a number that went up every time you booked
the pair together. That makes a rivalry a series of matches, which is not how
wrestling works — the match is the payoff and everything before it is the build.
Worse, it had no memory: nothing in the save could say "she has beaten me twice
and I need the cage match", because nothing recorded that she had beaten her
twice.

So a feud now has:

  BEATS    every match, promo, run-in and turn between the two, written down in
           order with who won. This is the story so far, and it is what lets the
           booker and the GM both reason about what should happen NEXT.

  A STAGE  build → escalation → blow-off, derived from heat. The stage decides
           what kind of segment the pre-booker reaches for: talking early,
           physicality in the middle, a gimmick match at the end.

  A PLANNED BLOW-OFF  the GM can point a feud at a pay-per-view. Until that
           date the booker deliberately WITHHOLDS the singles match — it books
           promos, run-ins and multi-woman matches that keep them apart instead.
           That is the difference between a feud and four weeks of the same
           match, and it is the single most valuable thing a GM can decide.

WHY WITHHOLDING IS THE INTERESTING RULE. Anyone can book the blow-off tonight.
The skill is not booking it tonight — and a booker that always reached for the
hottest available pairing made that skill impossible to express.
"""
from __future__ import annotations

import sqlite3
from datetime import date

import game

# ---------------------------------------------------------------- kinds
#
# A rivalry is not the only story two people can be in, and treating every
# storyline as a feud meant the only tool the game had was "book them against
# each other". These four cover what a wrestling show actually runs:
#
#   rivalry      they want to fight. Heat is animosity, the payoff is a match.
#   romance      they are together. Heat is how invested the crowd is, the payoff
#                is a moment — and the best payoff of all is it going WRONG.
#   alliance     they are on the same side. The payoff is a tag match won
#                together; the interesting ending is a betrayal.
#   mentorship   a veteran and somebody coming up. The payoff is the student
#                arriving, and the sour version is the student surpassing her.
#
# WANTS_MATCH is the load-bearing field. For a rivalry, booking the two against
# each other builds the story. For a romance or an alliance it BREAKS it — which
# is why the pre-booker has to know the difference, and why booking a couple
# against each other is offered as a deliberate act (see `sour`) rather than
# happening by accident.
KINDS: dict[str, dict] = {
    "rivalry": {
        "label": "Rivalry", "icon": "⚔", "wants_match": True,
        "heat_word": "heat",
        "desc": "They want to fight. Build it with promos, pay it off with a match.",
        "sours_to": None,
    },
    "romance": {
        "label": "Romance", "icon": "❤", "wants_match": False,
        "heat_word": "investment",
        "desc": "A couple on screen. Promos and moments build it; a break-up is "
                "the biggest payoff in wrestling.",
        "sours_to": "rivalry",
        "sour_label": "Break-up",
        "sour_note": "The break-up turns it into a rivalry with the crowd already invested.",
    },
    "alliance": {
        "label": "Alliance", "icon": "🤝", "wants_match": False,
        "heat_word": "trust",
        "desc": "Two on the same side. Win tag matches together; the ending is a "
                "betrayal nobody saw coming.",
        "sours_to": "rivalry",
        "sour_label": "Betrayal",
        "sour_note": "The betrayal turns it into a rivalry, and the crowd remembers "
                     "every match they won together.",
    },
    "mentorship": {
        "label": "Mentorship", "icon": "🎓", "wants_match": False,
        "heat_word": "bond",
        "desc": "A veteran bringing somebody up. The student's Wrestling grows "
                "faster while it lasts.",
        "sours_to": "rivalry",
        "sour_label": "The student turns",
        "sour_note": "She has outgrown her teacher. A rivalry with real history behind it.",
    },
}

DEFAULT_KIND = "rivalry"

# A mentorship measurably helps the student: her season Wrestling progression is
# scaled by this while the bond holds. It is the only storyline kind with a
# mechanical effect on a RATING, which is why it is a modest number and why the
# progression reason line says it out loud.
MENTOR_GROWTH_BONUS = 0.35


def kind_of(row) -> str:
    """The kind of one storyline row, defaulting for saves written before kinds."""
    try:
        k = row["kind"]
    except (KeyError, IndexError, TypeError):
        k = None
    return k if k in KINDS else DEFAULT_KIND


def wants_match(kind: str) -> bool:
    return KINDS.get(kind, KINDS[DEFAULT_KIND])["wants_match"]


# Heat thresholds for the three stages. The top one is game.FEUD_BLOWOFF_HEAT so
# there is exactly one definition of "ready to pay off" in the codebase.
STAGE_ESCALATION = 45
STAGES = {
    "build": ("Build", "Early. Talking, not fighting — save the match."),
    "escalation": ("Escalation", "It has turned physical. Keep it away from a clean finish."),
    "blowoff": ("Ready to blow off", "The crowd wants the match. Give it a gimmick and pay it off."),
    "settled": ("Settled", "Over."),
}


def stage_for(heat: int, status: str = "active") -> str:
    if status != "active":
        return "settled"
    if heat >= game.FEUD_BLOWOFF_HEAT:
        return "blowoff"
    if heat >= STAGE_ESCALATION:
        return "escalation"
    return "build"


def add_beat(con: sqlite3.Connection, feud_id: int, on_date: str, kind: str, text: str,
             show_id: int | None = None, winner_id: int | None = None) -> int:
    """Write one moment into a rivalry's history."""
    heat = con.execute("SELECT heat FROM feud WHERE id=?", (feud_id,)).fetchone()
    cur = con.execute(
        "INSERT INTO feud_beat (feud_id, on_date, show_id, kind, text, heat_after, winner_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (feud_id, on_date, show_id, kind, text, heat["heat"] if heat else None, winner_id))
    return cur.lastrowid


def beats(con: sqlite3.Connection, feud_id: int) -> list[dict]:
    return [dict(r) for r in con.execute(
        """SELECT b.*, COALESCE(o.display_name, w.name) winner_name
             FROM feud_beat b
             LEFT JOIN wrestler w ON w.id=b.winner_id
             LEFT JOIN attribute_override o ON o.wrestler_id=b.winner_id
            WHERE b.feud_id=? ORDER BY b.on_date, b.id""", (feud_id,))]


def _series(bts: list[dict], a_id: int, b_id: int) -> dict:
    """Who is winning the rivalry. The reason beats are stored at all."""
    a = sum(1 for x in bts if x["kind"] == "match" and x["winner_id"] == a_id)
    b = sum(1 for x in bts if x["kind"] == "match" and x["winner_id"] == b_id)
    drawn = sum(1 for x in bts if x["kind"] == "match" and x["winner_id"] is None)
    return {"a_wins": a, "b_wins": b, "draws": drawn, "matches": a + b + drawn,
            "leader": None if a == b else (a_id if a > b else b_id)}


def sync_stage(con: sqlite3.Connection, feud_id: int) -> str:
    f = con.execute("SELECT heat, status FROM feud WHERE id=?", (feud_id,)).fetchone()
    if not f:
        return "settled"
    s = stage_for(f["heat"], f["status"])
    con.execute("UPDATE feud SET stage=? WHERE id=?", (s, feud_id))
    return s


def plan_blowoff(con: sqlite3.Connection, feud_id: int, on_date: str | None,
                 label: str | None = None) -> dict:
    """Point a feud at a date — or clear the plan.

    Setting this is what tells the booker to protect the pairing until then.
    """
    f = con.execute("SELECT * FROM feud WHERE id=?", (feud_id,)).fetchone()
    if not f:
        raise game.SigningError("no such feud")
    con.execute("UPDATE feud SET planned_blowoff=?, blowoff_label=? WHERE id=?",
                (on_date, label, feud_id))
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    today = st["current_date"] if st else on_date
    if on_date:
        add_beat(con, feud_id, today, "planned",
                 f"Blow-off set for {label or on_date}. Keep them apart until then.")
        game.log_event(con, "feud",
                       f"{game._wname(con, f['a_id'])} vs {game._wname(con, f['b_id'])} "
                       f"is being built to {label or on_date}.", f["brand_id"], "📌")
    con.commit()
    return {"feud_id": feud_id, "planned_blowoff": on_date, "label": label}


def is_protected(con: sqlite3.Connection, feud_id: int, on_date: str) -> bool:
    """Should the booker keep these two OUT of a singles match tonight?

    True while a planned blow-off is still in the future. This is the whole
    mechanism behind "don't give away the match" — everything else about
    storylines is bookkeeping in service of this one boolean.
    """
    f = con.execute("SELECT planned_blowoff FROM feud WHERE id=?", (feud_id,)).fetchone()
    if not f or not f["planned_blowoff"]:
        return False
    return f["planned_blowoff"] > on_date


def next_beat(con: sqlite3.Connection, feud: dict, on_date: str) -> dict:
    """What should happen next in this story, and why.

    Read by the pre-booker to choose a segment and shown verbatim in the UI, so
    the advice the GM reads is the advice the booker actually followed.

    The KIND comes first, because it changes what "building it" even means. For a
    rivalry the match is the payoff; for a romance, an alliance or a mentorship
    the match is the thing that BREAKS it, so the advice never asks for one.
    """
    kind = kind_of(feud)
    if kind != "rivalry":
        return _non_rivalry_beat(con, feud, kind)
    stage = stage_for(feud["heat"], feud["status"])
    protected = bool(feud.get("planned_blowoff")) and feud["planned_blowoff"] > on_date
    bts = beats(con, feud["id"])
    series = _series(bts, feud["a_id"], feud["b_id"])
    a, b = game._wname(con, feud["a_id"]), game._wname(con, feud["b_id"])

    if protected:
        label = feud.get("blowoff_label") or feud["planned_blowoff"]
        return {"want": "keep_apart", "segment": "promo",
                "advice": f"Blow-off booked for {label}. Build it — promos, a run-in, "
                          f"or put them on opposite sides of a tag. Do NOT give away "
                          f"the singles match.",
                "stage": stage, "series": series, "protected": True}
    if stage == "build":
        return {"want": "talk", "segment": "promo",
                "advice": f"Early days at {feud['heat']} heat. A callout or a "
                          f"face-to-face is worth more than a match right now.",
                "stage": stage, "series": series, "protected": False}
    if stage == "escalation":
        if series["matches"] >= 2 and series["leader"]:
            led = game._wname(con, series["leader"])
            other = b if series["leader"] == feud["a_id"] else a
            return {"want": "physical", "segment": "match",
                    "advice": f"{led} leads the series {max(series['a_wins'], series['b_wins'])}"
                              f"-{min(series['a_wins'], series['b_wins'])}. "
                              f"{other} needs a win back, or a run-in — do not let this "
                              f"become one-sided before the blow-off.",
                    "stage": stage, "series": series, "protected": False}
        return {"want": "physical", "segment": "match",
                "advice": f"It has turned physical at {feud['heat']} heat. A run-in "
                          f"beatdown or a no-DQ match keeps it climbing without "
                          f"settling it.",
                "stage": stage, "series": series, "protected": False}
    return {"want": "blowoff", "segment": "match",
            "advice": f"{feud['heat']} heat — the crowd wants this. Pay it off with a "
                      f"gimmick match; a clean finish now settles the feud.",
            "stage": stage, "series": series, "protected": False}


def _non_rivalry_beat(con: sqlite3.Connection, feud: dict, kind: str) -> dict:
    """Advice for a story that is not about wanting to fight.

    These share a shape: build with segments, and the interesting ending is the
    one where it goes wrong. So the advice escalates toward the SOUR turn rather
    than toward a match, and names it — the GM should be able to see the good
    version of the ending coming.
    """
    k = KINDS[kind]
    heat = feud["heat"]
    bts = beats(con, feud["id"])
    series = _series(bts, feud["a_id"], feud["b_id"])
    a, b = game._wname(con, feud["a_id"]), game._wname(con, feud["b_id"])
    common = {"stage": "build" if heat < STAGE_ESCALATION
              else "escalation" if heat < game.FEUD_BLOWOFF_HEAT else "blowoff",
              "series": series, "protected": False, "kind": kind}

    if kind == "romance":
        if heat >= game.FEUD_BLOWOFF_HEAT:
            return {**common, "want": "sour", "segment": "promo",
                    "advice": f"The crowd is fully invested at {heat}. This is the "
                              f"moment to break them up — the rivalry that comes out "
                              f"of it starts hot instead of cold."}
        if heat >= STAGE_ESCALATION:
            return {**common, "want": "talk", "segment": "promo",
                    "advice": f"{heat} investment. Put them out there together — a "
                              f"segment they share is worth more than either alone."}
        return {**common, "want": "talk", "segment": "promo",
                "advice": f"Early days. Backstage segments and a shared promo get "
                          f"{a} and {b} over as a couple."}

    if kind == "alliance":
        if heat >= game.FEUD_BLOWOFF_HEAT:
            return {**common, "want": "sour", "segment": "promo",
                    "advice": f"They have banked enough trust at {heat} for a betrayal "
                              f"to actually hurt. Turn one on the other."}
        return {**common, "want": "team", "segment": "match",
                "advice": f"Book {a} and {b} on the SAME side of a tag and let them "
                          f"win. Every win together is credit you can spend on the "
                          f"betrayal later."}

    # mentorship
    if heat >= game.FEUD_BLOWOFF_HEAT:
        return {**common, "want": "sour", "segment": "promo",
                "advice": f"The student has arrived. Turning her on her teacher now "
                          f"is a rivalry with real history behind it."}
    return {**common, "want": "team", "segment": "match",
            "advice": f"Keep them together — a shared tag match, or {a} at ringside "
                      f"for {b}. The bond is worth Wrestling growth to the student "
                      f"while it lasts."}


def student_of(con: sqlite3.Connection, wid: int) -> int | None:
    """Her mentor, if a mentorship is running and she is the junior half.

    The junior is whoever is YOUNGER — the storyline does not record which is
    which, and age is the honest read rather than asking the GM to declare it.
    """
    for f in con.execute(
        """SELECT * FROM feud WHERE status='active'
            AND (a_id=? OR b_id=?)""", (wid, wid)):
        if kind_of(f) != "mentorship":
            continue
        other = f["b_id"] if f["a_id"] == wid else f["a_id"]
        try:
            me = game.effective_attributes(con, wid).get("age") or 30
            them = game.effective_attributes(con, other).get("age") or 30
        except ValueError:
            continue
        if me < them:
            return other
    return None


def sour(con: sqlite3.Connection, feud_id: int, note: str | None = None) -> dict:
    """Turn a romance, alliance or mentorship into a rivalry.

    THIS IS THE PAYOFF, not a failure state. A break-up or a betrayal converts a
    story the crowd is already invested in into a feud that starts hot, which is
    strictly better than opening a cold rivalry between the same two people —
    and it is the single most valuable thing the non-rivalry kinds are for.

    The heat carries over (that investment is the whole point) and the previous
    kind is remembered in `was_kind`, so the new rivalry can say where it came
    from.
    """
    f = con.execute("SELECT * FROM feud WHERE id=?", (feud_id,)).fetchone()
    if not f:
        raise game.SigningError("no such storyline")
    kind = kind_of(f)
    k = KINDS[kind]
    if not k.get("sours_to"):
        raise game.SigningError("a rivalry has nowhere to turn — settle it instead.")
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    on = st["current_date"] if st else game.now_iso()[:10]
    # A turn is a shock: it adds heat on top of what was already banked.
    new_heat = min(100, (f["heat"] or 25) + 18)
    con.execute(
        "UPDATE feud SET kind=?, was_kind=?, heat=?, planned_blowoff=NULL, "
        "blowoff_label=NULL WHERE id=?",
        (k["sours_to"], kind, new_heat, feud_id))
    a, b = game._wname(con, f["a_id"]), game._wname(con, f["b_id"])
    add_beat(con, feud_id, on, "turn",
             note or f"{k['sour_label']} — {a} and {b} are done. {k['sour_note']}")
    sync_stage(con, feud_id)
    game.log_event(con, "feud", f"{k['sour_label']}: {a} and {b}. It is a rivalry now.",
                   f["brand_id"], "💔" if kind == "romance" else "🗡")
    con.commit()
    return {"feud_id": feud_id, "kind": k["sours_to"], "was_kind": kind,
            "heat": new_heat}


def arc(con: sqlite3.Connection, feud_id: int) -> dict:
    """One rivalry's whole story — for the Rivalries screen."""
    f = con.execute("SELECT * FROM feud WHERE id=?", (feud_id,)).fetchone()
    if not f:
        raise game.SigningError("no such feud")
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    today = st["current_date"] if st else date.today().isoformat()
    d = dict(f)
    d["a_name"] = game._wname(con, f["a_id"])
    d["b_name"] = game._wname(con, f["b_id"])
    kind = kind_of(f)
    k = KINDS[kind]
    d["kind"] = kind
    d["kind_label"] = k["label"]
    d["kind_icon"] = k["icon"]
    d["kind_desc"] = k["desc"]
    d["heat_word"] = k["heat_word"]
    d["wants_match"] = k["wants_match"]
    d["sours_to"] = k.get("sours_to")
    d["sour_label"] = k.get("sour_label")
    stage = stage_for(f["heat"], f["status"])
    d["stage"] = stage
    d["stage_label"], d["stage_note"] = STAGES[stage]
    # A non-rivalry has no "blow-off" to be ready for; its stage label should
    # describe what it actually is.
    if kind != "rivalry":
        d["stage_label"] = k["label"]
        d["stage_note"] = k["desc"]
    d["beats"] = beats(con, feud_id)
    d["next"] = next_beat(con, d, today)
    d["series"] = d["next"]["series"]
    return d


def arcs(con: sqlite3.Connection, status: str | None = "active") -> list[dict]:
    ids = [r["id"] for r in con.execute(
        "SELECT id FROM feud" + (" WHERE status=?" if status else "") + " ORDER BY heat DESC",
        (status,) if status else ())]
    return [arc(con, i) for i in ids]


def settle_stale(con: sqlite3.Connection) -> list[dict]:
    """Close feuds that have been paid off and gone quiet.

    A rivalry that blew off cleanly and has not been touched since is over,
    whatever the heat number says — and leaving it open means the booker keeps
    trying to book a story that already ended.
    """
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if not st:
        return []
    today = date.fromisoformat(st["current_date"])
    closed = []
    for f in con.execute("SELECT * FROM feud WHERE status='active'"):
        bts = beats(con, f["id"])
        if not bts:
            continue
        # A romance or an alliance is a STANDING relationship, not a story
        # heading for a finish. Closing one for being quiet would keep quietly
        # dissolving couples the GM never broke up — they end when she sours
        # them or settles them, and not otherwise.
        if kind_of(f) != "rivalry":
            continue
        last = date.fromisoformat(bts[-1]["on_date"])
        quiet_days = (today - last).days
        series = _series(bts, f["a_id"], f["b_id"])
        # Paid off: a decisive series and a clean finish, then five quiet weeks.
        if quiet_days >= 35 and series["matches"] >= 2 and series["leader"] is not None:
            game.settle_feud(con, f["id"])
            add_beat(con, f["id"], st["current_date"], "settled",
                     f"{game._wname(con, series['leader'])} won the rivalry.")
            closed.append({"feud_id": f["id"],
                           "winner": game._wname(con, series["leader"])})
        # Or simply abandoned: nothing at all for ten weeks.
        elif quiet_days >= 70:
            game.settle_feud(con, f["id"])
            add_beat(con, f["id"], st["current_date"], "settled",
                     "Quietly dropped — nobody mentioned it again.")
            closed.append({"feud_id": f["id"], "winner": None})
    con.commit()
    return closed


# ---------------------------------------------------------------- suggestions
#
# WHAT WAS MISSING. The locker room proposes requests and the crowd proposes
# turns, but nothing proposed STORIES — so a roster could sit there with fifteen
# unbooked women and no rivalries, and the game would never once say "these two
# should be feuding". Which is the single most useful thing it could say, because
# a rivalry is the best reason to put two people in a ring and everything
# downstream (the pre-booked card, heat, the ratings war) runs on having one.
#
# Suggestions only, like everything else: this returns pairings with reasons and
# the GM opens whichever she likes.

# Nobody needs a fourth storyline. Above this she is spread too thin for another
# one to mean anything.
MAX_STORIES_EACH = 2

# How close in standing two people should be for a rivalry to look competitive.
# Wide enough to allow an upset story, tight enough to avoid a squash.
RIVAL_GAP = 14


def suggestions(con: sqlite3.Connection, brand_id: str | None = None,
                limit: int = 6) -> list[dict]:
    """Pairings worth a story, with the reason and the kind that fits.

    Ranked so the most valuable suggestion is first: two over women with nothing
    to do is a bigger miss than two enhancement talents with nothing to do.
    """
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if not st:
        return []
    season = st["season_year"]
    sql = """SELECT c.wrestler_id, c.brand_id, c.role FROM contract c
             WHERE c.terminated_on IS NULL AND c.start_year<=? AND c.end_year>=?"""
    args: list = [season, season]
    if brand_id:
        sql += " AND c.brand_id=?"
        args.append(brand_id)

    ach = game.achievement_inputs(con)
    people: list[dict] = []
    for r in con.execute(sql, tuple(args)):
        try:
            eff = game.effective_attributes(con, r["wrestler_id"], ach.get(r["wrestler_id"]))
        except ValueError:
            continue
        people.append({
            "id": r["wrestler_id"], "brand_id": r["brand_id"],
            "name": game._wname(con, r["wrestler_id"]),
            "overall": eff["overall"], "popularity": eff["popularity"],
            "alignment": eff.get("alignment") or "face",
            "age": eff.get("age") or 30,
            "working_role": eff.get("working_role", "wrestler"),
        })

    # How many stories each is already in — the cap that stops a suggestion
    # engine from proposing a fifth feud for the same woman.
    running: dict[int, int] = {}
    existing: set[frozenset] = set()
    for f in con.execute("SELECT * FROM feud WHERE status='active'"):
        existing.add(frozenset({f["a_id"], f["b_id"]}))
        for w in (f["a_id"], f["b_id"]):
            running[w] = running.get(w, 0) + 1

    out: list[dict] = []
    for i, a in enumerate(people):
        if running.get(a["id"], 0) >= MAX_STORIES_EACH:
            continue
        for b in people[i + 1:]:
            if running.get(b["id"], 0) >= MAX_STORIES_EACH:
                continue
            if frozenset({a["id"], b["id"]}) in existing:
                continue
            if a["brand_id"] != b["brand_id"]:
                continue          # a story needs them on the same show
            s = _score_pair(a, b)
            if s:
                out.append(s)

    out.sort(key=lambda x: -x["score"])
    return out[:limit]


def _score_pair(a: dict, b: dict) -> dict | None:
    """Why these two, and what kind of story. None if there is no case."""
    gap = abs(a["overall"] - b["overall"])
    pop = (a["popularity"] + b["popularity"]) / 2
    opposed = a["alignment"] != b["alignment"]
    mgr = "manager" in (a["working_role"], b["working_role"])
    both_mgr = a["working_role"] == b["working_role"] == "manager"

    # A manager and a wrestler is a ROMANCE waiting to happen — it is the pairing
    # the kind exists for, and it needs no ring time from her at all.
    if mgr and not both_mgr:
        return {"a_id": a["id"], "b_id": b["id"], "a_name": a["name"],
                "b_name": b["name"], "kind": "romance",
                "score": 40 + pop * 2.0,
                "reason": f"{a['name']} and {b['name']} — a manager and the woman she "
                          f"stands beside. A romance builds both of them without "
                          f"needing a single match.",
                "brand_id": a["brand_id"]}
    if both_mgr:
        return None               # two managers with no wrestlers is not a story

    # A big age gap with a real ability gap is a MENTORSHIP: the veteran has
    # something to teach and the student measurably gains from it.
    if abs(a["age"] - b["age"]) >= 9 and gap >= 8:
        vet, kid = (a, b) if a["age"] > b["age"] else (b, a)
        return {"a_id": vet["id"], "b_id": kid["id"], "a_name": vet["name"],
                "b_name": kid["name"], "kind": "mentorship",
                "score": 30 + kid["popularity"] * 1.2,
                "reason": f"{vet['name']} is {vet['age']} and {kid['name']} is "
                          f"{kid['age']}. A mentorship grows the student's Wrestling "
                          f"faster while it lasts — and the turn on the teacher later "
                          f"writes itself.",
                "brand_id": a["brand_id"]}

    # Same alignment and similar level: they belong on the SAME side.
    if not opposed and gap <= RIVAL_GAP:
        return {"a_id": a["id"], "b_id": b["id"], "a_name": a["name"],
                "b_name": b["name"], "kind": "alliance",
                "score": 20 + pop * 1.4,
                "reason": f"{a['name']} and {b['name']} are both "
                          f"{a['alignment']}s at a similar level. An alliance gives "
                          f"you tag matches now and a betrayal to spend later.",
                "brand_id": a["brand_id"]}

    # Opposite alignments, close in level: the classic rivalry.
    if opposed and gap <= RIVAL_GAP:
        return {"a_id": a["id"], "b_id": b["id"], "a_name": a["name"],
                "b_name": b["name"], "kind": "rivalry",
                "score": 45 + pop * 2.6 - gap * 0.5,
                "reason": f"{a['name']} ({a['alignment']}) against {b['name']} "
                          f"({b['alignment']}), and only {gap} points between them. "
                          f"Good against evil at an even level is the easiest story "
                          f"there is.",
                "brand_id": a["brand_id"]}
    return None
