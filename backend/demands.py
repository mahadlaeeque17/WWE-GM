"""Wrestlers coming to the GM with things they want — and acting if ignored.

THE DESIGN RULE THAT MATTERS. A wrestler asks BEFORE she acts, always. Every
consequence in this module is preceded by a request the GM saw, and by an
escalation that says in plain words what happens if it keeps being ignored. That
is what makes a forced trade fair rather than a random punishment: by the time
she walks out you have turned her down three times and been told twice that she
was going to do it.

The escalation ladder is the same for every request kind:

    ask    → the first time. Polite, costs nothing to refuse.
    firm   → asked again after being denied or ignored. Refusing hurts.
    final  → the last time she asks. The text says what she will do instead.

At morale ROCK BOTTOM (see morale.ROCK_BOTTOM) a wrestler with a `final` trade
or release demand stops asking and FORCES it — she is traded to the other brand,
or she walks out of the company. Both are logged loudly and recorded in
`forced_move`, because the GM should be able to look back and see exactly when
she lost her.

WHY GRANTING SOMETHING ISN'T FREE. Every grant does something real: a raise
rewrites the contract and eats cap space, time off makes her unbookable for two
weeks, a title shot pins the contender ladder, a push is a PROMISE that gets
checked. A request you can grant with no cost is not a decision.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

import game
import morale
import negotiate

# How long a request sits before she gives up waiting and escalates. Four weeks
# is one booking cycle — long enough that the GM has genuinely had a chance.
EXPIRY_DAYS = 28

SEVERITY_ORDER = ["ask", "firm", "final"]

# How far back a grudge counts when working out how insistent she is. Escalation
# is about HER PATIENCE, not about one topic: being turned down over a raise and
# then over time off is two refusals, and she is entitled to be firmer the second
# time. Scoping it per-KIND (which is what this used to do) let a wrestler rotate
# grievances forever and never reach `final`, which meant a trade demand could
# never actually be carried out. Windowed so a refusal from last spring is not
# still being held against you in December.
GRIEVANCE_WINDOW_DAYS = 120

# Morale paid or docked when the GM says yes or no. Denying gets steadily worse
# as she escalates, which is the whole pressure of the system.
GRANT_MORALE = {"ask": 8, "firm": 12, "final": 18}
DENY_MORALE = {"ask": -4, "firm": -9, "final": -16}

# Time off is two weeks. Long enough to matter to the card, short enough to be
# worth granting.
REST_WEEKS = 2

# A granted push or title shot is a promise with a deadline, checked the same way
# a contract perk is.
PROMISE_DAYS = 35

# How many NEW requests a month can bring. Without a cap, the first month of a
# save filed one for nearly every wrestler on the roster — an in-tray of
# eighteen is a wall, and a wall gets ignored, which defeats the entire point of
# her asking before she acts. Five is a page somebody actually reads. The rest
# wait their turn, and the queue is drained in order of urgency so a final
# warning can never be the thing that gets crowded out.
MAX_NEW_PER_MONTH = 5

# A deal she signed this season is a deal she AGREED to, so she does not get to
# call it an insult yet. Without this every draft pick demanded a raise
# immediately: a rookie contract is written at a tier discount, so measured
# against the open market she is "underpaid" from the moment she signs. That is
# a real and intended dynamic — it just should not become a grievance until she
# has served some of the deal.
RAISE_GRACE_SEASONS = 1


# ---------------------------------------------------------------- definitions
#
# Each kind knows how to describe itself, how bad it is to refuse, and what
# granting it actually does. `escalates_to` is what she asks for next when this
# has been refused at `final` — the path from "pay me" to "trade me" to "release
# me" is the arc of somebody giving up on you.
KINDS: dict[str, dict] = {
    "raise": {
        "label": "A raise", "icon": "💰",
        "desc": "She is being paid under the market and knows it.",
        "escalates_to": "trade",
    },
    "title_shot": {
        "label": "A title shot", "icon": "🏆",
        "desc": "She has earned a shot and has not been given one.",
        "escalates_to": "push",
    },
    "push": {
        "label": "A push", "icon": "📈",
        "desc": "She wants the top of the card.",
        "escalates_to": "trade",
    },
    "time_off": {
        "label": "Time off", "icon": "🛌",
        "desc": "She is worked into the ground and needs a fortnight.",
        "escalates_to": "release",
    },
    "storyline": {
        "label": "A storyline", "icon": "🎬",
        "desc": "She is over and has nothing to be about.",
        "escalates_to": "trade",
    },
    "turn": {
        "label": "A character change", "icon": "🔄",
        "desc": "The crowd is reacting to her the wrong way round.",
        "escalates_to": "storyline",
    },
    "trade": {
        "label": "A trade", "icon": "⇄",
        "desc": "She wants off this brand.",
        "escalates_to": "release",
    },
    "release": {
        "label": "Her release", "icon": "🚪",
        "desc": "She wants out of the company altogether.",
        "escalates_to": None,
    },
}


def _today(con: sqlite3.Connection) -> str:
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if not st:
        raise game.SigningError("no active save")
    return st["current_date"]


def _open_for(con: sqlite3.Connection, wid: int):
    return con.execute(
        "SELECT * FROM wrestler_request WHERE wrestler_id=? AND status='open'",
        (wid,)).fetchone()


def _history(con: sqlite3.Connection, wid: int, kind: str) -> list[sqlite3.Row]:
    return list(con.execute(
        "SELECT * FROM wrestler_request WHERE wrestler_id=? AND kind=? "
        "ORDER BY id DESC", (wid, kind)))


def _grievances(con: sqlite3.Connection, wid: int, today: str) -> int:
    """How many times she has recently been refused or ignored, across the board.

    This is what sets severity — see GRIEVANCE_WINDOW_DAYS for why it is not
    counted per request kind.
    """
    since = (date.fromisoformat(today)
             - timedelta(days=GRIEVANCE_WINDOW_DAYS)).isoformat()
    return con.execute(
        """SELECT COUNT(*) FROM wrestler_request
            WHERE wrestler_id=? AND status IN ('denied','expired')
              AND COALESCE(resolved_on, created_on) >= ?""",
        (wid, since)).fetchone()[0]


# ---------------------------------------------------------------- generation

def _wants(con: sqlite3.Connection, wid: int, snap: dict) -> list[tuple[str, dict]]:
    """Everything this wrestler has a legitimate reason to ask for, best first.

    Returns (kind, extras) pairs. Only the top one is ever filed — a wrestler
    who turned up with a list of six grievances would be noise, not character.
    """
    m = snap["morale"]
    eff = game.effective_attributes(con, wid)
    pay = snap["pay"]
    fs = {f["key"]: f for f in snap["factors"]}
    out: list[tuple[str, dict]] = []

    # Rock bottom overrides everything: she is not asking for a raise any more.
    if m <= morale.ROCK_BOTTOM:
        out.append(("release", {}))
        out.append(("trade", {}))
    elif m <= 22:
        out.append(("trade", {}))

    if pay.get("under_contract") and pay["ratio"] < 0.86 and _served_enough(con, wid):
        want = int(round(pay["market"] * 1.05 / 5_000) * 5_000)
        out.append(("raise", {"ask_value": want}))

    if fs.get("stamina", {}).get("delta", 0) <= -3 or snap["stamina"] <= 22:
        out.append(("time_off", {"ask_value": REST_WEEKS}))

    # A title shot is only a legitimate ask if the ladder actually agrees.
    try:
        import rankings
        for t in con.execute(
            """SELECT id, name, short_name FROM game_title
               WHERE active=1 AND tier<>'manager'"""):
            ladder = rankings.ladder_for(con, t["id"])
            top = [x["wrestler_id"] for x in ladder[:3]]
            if wid in top:
                held = con.execute(
                    "SELECT 1 FROM game_title_reign WHERE title_id=? AND wrestler_id=? "
                    "AND lost_on IS NULL", (t["id"], wid)).fetchone()
                if not held:
                    out.append(("title_shot", {"ask_value": t["id"],
                                               "title_name": t["short_name"] or t["name"]}))
                    break
    except Exception:                                        # noqa: BLE001
        pass

    if fs.get("spotlight", {}).get("delta", 0) <= -2.5 and eff["popularity"] >= 11:
        out.append(("push", {}))

    if fs.get("story", {}).get("delta", 0) < 0:
        opp = _suggest_opponent(con, wid)
        if opp:
            out.append(("storyline", {"ask_target": opp}))

    import crowd
    rp = crowd.recent_pop(con, wid, limit=8)
    if rp["samples"] >= 4 and rp["drifting"]:
        out.append(("turn", {"detail_extra": rp["drifting"]}))

    return out


def _served_enough(con: sqlite3.Connection, wid: int) -> bool:
    """Has she been on this deal long enough to complain about what it pays?

    See RAISE_GRACE_SEASONS. A wrestler who is ALREADY sour is exempt: at that
    point the money is a symptom of the mood rather than the cause of it, and
    making her wait a season to mention it would just hide the problem.
    """
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if not st:
        return True
    season = st["season_year"]
    c = game.active_contract(con, wid, season)
    if not c:
        return False
    m = con.execute("SELECT morale FROM wrestler_state WHERE wrestler_id=?",
                    (wid,)).fetchone()
    if m and (m["morale"] or 50) <= 30:
        return True
    return season - c["start_year"] >= RAISE_GRACE_SEASONS


def _suggest_opponent(con: sqlite3.Connection, wid: int) -> int | None:
    """Somebody on her brand, opposite alignment, closest in standing.

    She is not asking for a random feud — she has somebody in mind, which is
    what makes granting it a one-click action rather than a research task.
    """
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    season = st["season_year"]
    c = game.active_contract(con, wid, season)
    if not c:
        return None
    try:
        me = game.effective_attributes(con, wid)
    except ValueError:
        return None
    best, gap = None, 1e9
    for r in con.execute(
        """SELECT wrestler_id FROM contract
           WHERE brand_id=? AND terminated_on IS NULL AND role<>'manager'
             AND start_year<=? AND end_year>=? AND wrestler_id<>?""",
        (c["brand_id"], season, season, wid)):
        other = r["wrestler_id"]
        if game.feud_between(con, wid, other):
            continue
        try:
            o = game.effective_attributes(con, other)
        except ValueError:
            continue
        if (o.get("alignment") or "face") == (me.get("alignment") or "face"):
            continue
        d = abs(o["overall"] - me["overall"])
        if d < gap:
            best, gap = other, d
    return best


def _text_for(con: sqlite3.Connection, wid: int, kind: str, severity: str,
              snap: dict, extras: dict) -> tuple[str, str]:
    """Her reason, and the detail line that says what happens if you say no.

    The detail on a `final` request is the single most important string in this
    module: it is the warning that makes the consequence fair.
    """
    name = snap["name"]
    k = KINDS[kind]
    pay = snap["pay"]
    if kind == "raise":
        reason = (f"{name} is on ${pay.get('salary', 0):,} against a market rate of "
                  f"${pay.get('market', 0):,}. She wants ${extras.get('ask_value', 0):,}.")
    elif kind == "title_shot":
        reason = (f"{name} is in the top three of the {extras.get('title_name', 'title')} "
                  f"ladder and has not been given a shot.")
    elif kind == "push":
        reason = f"{name} wants a run at the top of the card — no main events lately."
    elif kind == "time_off":
        reason = (f"{name} is down to {snap['stamina']}/100 stamina and wants "
                  f"{extras.get('ask_value', REST_WEEKS)} weeks off.")
    elif kind == "storyline":
        tgt = extras.get("ask_target")
        reason = (f"{name} has nothing going on and wants a rivalry"
                  + (f" with {game._wname(con, tgt)}." if tgt else "."))
    elif kind == "turn":
        to = extras.get("detail_extra") or "the other way"
        reason = (f"{name} says the crowd is treating her like a {to} and wants "
                  f"to lean into it.")
    elif kind == "trade":
        reason = (f"{name} has asked to be moved to the other brand. Morale "
                  f"{snap['morale']} — {snap['band']}.")
    else:
        reason = (f"{name} has asked for her release. Morale {snap['morale']} — "
                  f"{snap['band']}.")

    if severity == "ask":
        detail = k["desc"]
    elif severity == "firm":
        nxt = KINDS[kind]["escalates_to"]
        detail = ("She has asked before and been turned down. Refusing again will "
                  "cost real morale"
                  + (f", and she will start asking for {KINDS[nxt]['label'].lower()}."
                     if nxt else "."))
    else:
        if kind == "trade":
            detail = ("LAST TIME SHE ASKS. If her morale stays at rock bottom she "
                      "will force the move herself and you will not get to pick "
                      "what comes back.")
        elif kind == "release":
            detail = ("LAST TIME SHE ASKS. If her morale stays at rock bottom she "
                      "will walk out and you lose her for nothing.")
        else:
            nxt = KINDS[kind]["escalates_to"]
            detail = ("Final time she asks nicely. After this she starts asking for "
                      + (KINDS[nxt]["label"].lower() if nxt else "her release") + ".")
    return reason, detail


def generate(con: sqlite3.Connection) -> dict:
    """File the requests the roster has earned the right to make.

    One open request per wrestler at a time, ever. A locker room that files nine
    grievances at once is a spreadsheet; one at a time is a person.
    """
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if not st:
        return {"created": 0}
    today = _today(con)
    season = st["season_year"]

    # Work out everyone's case FIRST, then file only the most urgent few — see
    # MAX_NEW_PER_MONTH. Urgency is how insistent she already is, then how
    # unhappy she is, so a final warning can never be crowded out by a contented
    # wrestler angling for a slightly better deal.
    candidates: list[tuple[int, int, dict]] = []
    for r in con.execute(
        """SELECT wrestler_id, brand_id FROM contract
           WHERE terminated_on IS NULL AND start_year<=? AND end_year>=?""",
        (season, season)):
        wid, brand = r["wrestler_id"], r["brand_id"]
        if _open_for(con, wid):
            continue
        try:
            snap = morale.snapshot(con, wid)
        except (ValueError, game.SigningError):
            continue
        wants = _wants(con, wid, snap)
        if not wants:
            continue
        kind, extras = wants[0]
        # Severity comes from how many times she has recently been refused or
        # ignored AT ALL — her patience, not her topic. See _grievances().
        prior = _grievances(con, wid, today)
        severity = SEVERITY_ORDER[min(prior, len(SEVERITY_ORDER) - 1)]
        candidates.append((
            -SEVERITY_ORDER.index(severity), snap["morale"],
            {"wid": wid, "brand": brand, "kind": kind, "extras": extras,
             "severity": severity, "prior": prior, "snap": snap}))

    candidates.sort(key=lambda c: (c[0], c[1]))
    created = 0
    for _, _, c in candidates[:MAX_NEW_PER_MONTH]:
        wid, brand, kind = c["wid"], c["brand"], c["kind"]
        severity, snap = c["severity"], c["snap"]
        reason, detail = _text_for(con, wid, kind, severity, snap, c["extras"])
        expires = (date.fromisoformat(today) + timedelta(days=EXPIRY_DAYS)).isoformat()
        con.execute(
            """INSERT INTO wrestler_request (wrestler_id, brand_id, kind, severity,
                 ask_value, ask_target, reason, detail, status, created_on, expires_on,
                 times_asked)
               VALUES (?,?,?,?,?,?,?,?, 'open', ?,?,?)""",
            (wid, brand, kind, severity, c["extras"].get("ask_value"),
             c["extras"].get("ask_target"), reason, detail, today, expires,
             c["prior"] + 1))
        created += 1
        if severity == "final":
            game.log_event(con, "request",
                           f"{snap['name']} is asking for {KINDS[kind]['label'].lower()} "
                           f"for the last time.", brand, KINDS[kind]["icon"])
    waiting = max(0, len(candidates) - created)
    con.commit()
    if created:
        game.log_event(con, "request",
                       f"{created} wrestler{'s' if created != 1 else ''} "
                       f"{'have' if created != 1 else 'has'} come to you with something."
                       + (f" {waiting} more are waiting their turn." if waiting else ""),
                       icon="🗣")
        con.commit()
    return {"created": created, "waiting": waiting}


def expire_stale(con: sqlite3.Connection) -> dict:
    """Requests the GM never answered. Ignoring is a decision and it costs.

    Deliberately harsher than a straight denial: she would rather have been told
    no than not been answered at all.
    """
    today = _today(con)
    n = 0
    for r in con.execute(
        "SELECT * FROM wrestler_request WHERE status='open' AND expires_on < ?", (today,)):
        con.execute("UPDATE wrestler_request SET status='expired', resolved_on=? WHERE id=?",
                    (today, r["id"]))
        hit = DENY_MORALE[r["severity"]] - 2
        con.execute("UPDATE wrestler_state SET morale = MAX(0, MIN(100, morale + ?)) "
                    "WHERE wrestler_id=?", (hit, r["wrestler_id"]))
        n += 1
    if n:
        game.log_event(con, "request",
                       f"{n} request{'s' if n != 1 else ''} went unanswered.", icon="🙉")
    con.commit()
    return {"expired": n}


# ---------------------------------------------------------------- resolution

def _grant(con: sqlite3.Connection, r: sqlite3.Row) -> dict:
    """Actually do the thing she asked for. Every branch has a real cost."""
    wid, kind = r["wrestler_id"], r["kind"]
    today = _today(con)
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    season = st["season_year"]
    name = game._wname(con, wid)
    out: dict = {"kind": kind}

    if kind == "raise":
        c = game.active_contract(con, wid, season)
        if not c:
            raise game.SigningError("she is not under contract")
        new = int(r["ask_value"] or negotiate.market_rate(con, wid))
        rise = new - c["annual_value"]
        fin = {f["brand_id"]: f for f in game.brand_finances(con, season)}[c["brand_id"]]
        if rise > fin["available"]:
            raise game.SigningError(
                f"{fin['name']} has ${fin['available']:,} of cap space and this raise "
                f"costs ${rise:,}. Free up money or turn her down.")
        con.execute("UPDATE contract SET annual_value=? WHERE id=?", (new, c["id"]))
        game.log_event(con, "contract",
                       f"{name} gets a raise — ${c['annual_value']:,} → ${new:,}.",
                       c["brand_id"], "💰")
        out.update({"from": c["annual_value"], "to": new})

    elif kind == "title_shot":
        import rankings
        tid = int(r["ask_value"] or 0)
        if not tid:
            raise game.SigningError("no title recorded on this request")
        rankings.lock_contender(con, tid, wid)
        t = con.execute("SELECT name FROM game_title WHERE id=?", (tid,)).fetchone()
        game.log_event(con, "title",
                       f"{name} is granted a shot at the {t['name'] if t else 'title'} "
                       f"— pinned as #1 contender.", r["brand_id"], "🏆")
        out.update({"title_id": tid})

    elif kind == "push":
        # A push is a PROMISE, not a switch: she is told she is going to the top
        # of the card, and the engine checks whether she got there.
        game.set_setting(con, f"promise:push:{wid}",
                         json.dumps({"until": (date.fromisoformat(today)
                                               + timedelta(days=PROMISE_DAYS)).isoformat()}))
        game.log_event(con, "request", f"{name} is promised a run at the top of the card.",
                       r["brand_id"], "📈")
        out.update({"promise_days": PROMISE_DAYS})

    elif kind == "time_off":
        weeks = int(r["ask_value"] or REST_WEEKS)
        until = (date.fromisoformat(today) + timedelta(weeks=weeks)).isoformat()
        con.execute("UPDATE wrestler_state SET rested_until=? WHERE wrestler_id=?",
                    (until, wid))
        game.log_event(con, "request", f"{name} is given {weeks} weeks off.",
                       r["brand_id"], "🛌")
        out.update({"rested_until": until})

    elif kind == "storyline":
        tgt = r["ask_target"]
        if not tgt:
            tgt = _suggest_opponent(con, wid)
        if not tgt:
            raise game.SigningError("nobody suitable on her brand to feud with")
        if not game.feud_between(con, wid, tgt):
            game.create_feud(con, wid, tgt, r["brand_id"], "She asked for this one.")
        out.update({"opponent": tgt, "opponent_name": game._wname(con, tgt)})

    elif kind == "turn":
        import crowd
        rp = crowd.recent_pop(con, wid, limit=8)
        to = rp["drifting"] or ("heel" if (game.effective_attributes(con, wid)
                                           .get("alignment") == "face") else "face")
        con.execute(
            """INSERT INTO attribute_override (wrestler_id, alignment, updated_at)
               VALUES (?,?,?) ON CONFLICT(wrestler_id) DO UPDATE SET
                 alignment=excluded.alignment, updated_at=excluded.updated_at""",
            (wid, to, game.now_iso()))
        con.execute("DELETE FROM segment_pop WHERE wrestler_id=?", (wid,))
        con.execute("UPDATE turn_suggestion SET status='approved', resolved_on=? "
                    "WHERE wrestler_id=? AND status='pending'", (game.now_iso(), wid))
        game.log_event(con, "turn", f"{name} turns {to} — she asked for it.",
                       r["brand_id"], "🔄")
        out.update({"alignment": to})

    elif kind == "trade":
        out.update(_move_brands(con, wid, "granted at her request"))

    elif kind == "release":
        game.release(con, wid)
        game.log_event(con, "contract", f"{name} is released at her own request.",
                       r["brand_id"], "🚪")
        out.update({"released": True})

    return out


def _move_brands(con: sqlite3.Connection, wid: int, why: str) -> dict:
    """Send her to the other brand, carrying her contract.

    Uses a direct brand switch rather than `game.trade`, which needs wrestlers
    from BOTH sides — a one-way move is exactly what a trade demand is, and the
    receiving brand still has to fit her under its cap.
    """
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    season = st["season_year"]
    c = game.active_contract(con, wid, season)
    if not c:
        raise game.SigningError("she is not under contract")
    dest = next((b[0] for b in game.BRANDS if b[0] != c["brand_id"]), None)
    if not dest:
        raise game.SigningError("there is nowhere to move her to")
    fin = {f["brand_id"]: f for f in game.brand_finances(con, season)}
    if c["annual_value"] > fin[dest]["available"]:
        raise game.SigningError(
            f"{fin[dest]['name']} has ${fin[dest]['available']:,} free and her deal is "
            f"${c['annual_value']:,}. Clear space or she cannot be moved.")
    con.execute("UPDATE contract SET brand_id=? WHERE id=?", (dest, c["id"]))
    # A fresh start is worth something: the move itself lifts her mood.
    con.execute("UPDATE wrestler_state SET morale = MAX(0, MIN(100, morale + 15)) "
                "WHERE wrestler_id=?", (wid,))
    game.log_event(con, "trade",
                   f"{game._wname(con, wid)} moves from {c['brand_id']} to {dest} — {why}.",
                   dest, "⇄")
    return {"from_brand": c["brand_id"], "to_brand": dest, "moved": True}


def resolve(con: sqlite3.Connection, rid: int, grant: bool,
            counter_value: int | None = None) -> dict:
    """Say yes or no. `counter_value` part-grants a raise at a number you pick.

    A part-granted raise is scored on how close it came: meeting her most of the
    way still buys most of the goodwill, which is the honest middle ground
    between "yes" and "no".
    """
    r = con.execute("SELECT * FROM wrestler_request WHERE id=?", (rid,)).fetchone()
    if not r:
        raise game.SigningError("no such request")
    if r["status"] != "open":
        raise game.SigningError(f"already {r['status']}")
    wid = r["wrestler_id"]
    today = _today(con)
    name = game._wname(con, wid)

    if not grant:
        con.execute("UPDATE wrestler_request SET status='denied', resolved_on=? WHERE id=?",
                    (today, rid))
        hit = DENY_MORALE[r["severity"]]
        con.execute("UPDATE wrestler_state SET morale = MAX(0, MIN(100, morale + ?)) "
                    "WHERE wrestler_id=?", (hit, wid))
        game.log_event(con, "request",
                       f"{name} is turned down over {KINDS[r['kind']]['label'].lower()}.",
                       r["brand_id"], "✋")
        con.commit()
        return {"id": rid, "status": "denied", "morale_change": hit}

    # A raise can be met part-way; everything else is yes or no.
    if r["kind"] == "raise" and counter_value is not None:
        asked = r["ask_value"] or 0
        c = game.active_contract(
            con, wid, con.execute("SELECT season_year FROM game_state WHERE id=1").fetchone()[0])
        current = c["annual_value"] if c else 0
        if counter_value <= current:
            raise game.SigningError("a counter has to be more than she is on now")
        con.execute("UPDATE wrestler_request SET ask_value=? WHERE id=?", (counter_value, rid))
        r = con.execute("SELECT * FROM wrestler_request WHERE id=?", (rid,)).fetchone()
        share = (counter_value - current) / max(1, asked - current)
        gain = int(round(GRANT_MORALE[r["severity"]] * max(0.25, min(1.0, share))))
    else:
        gain = GRANT_MORALE[r["severity"]]

    detail = _grant(con, r)
    con.execute("UPDATE wrestler_request SET status='granted', resolved_on=? WHERE id=?",
                (today, rid))
    con.execute("UPDATE wrestler_state SET morale = MAX(0, MIN(100, morale + ?)) "
                "WHERE wrestler_id=?", (gain, wid))
    con.commit()
    return {"id": rid, "status": "granted", "morale_change": gain, "detail": detail}


# ---------------------------------------------------------------- forcing

def force_moves(con: sqlite3.Connection) -> list[dict]:
    """Wrestlers at rock bottom who have run out of patience, acting on it.

    The one place in the game where something happens to the roster that the GM
    did not approve — and it is only reachable after she has asked at `final`
    severity and been refused or ignored. The request text warned, in words, that
    this was coming.

    A trade demand moves her. A release demand walks her out. If the other brand
    cannot fit her contract she walks out instead, because a wrestler at rock
    bottom does not stay for the cap's convenience.
    """
    today = _today(con)
    forced = []
    for r in con.execute(
        """SELECT wr.* FROM wrestler_request wr
             JOIN wrestler_state s ON s.wrestler_id = wr.wrestler_id
            WHERE wr.severity='final' AND wr.kind IN ('trade','release')
              AND wr.status IN ('denied','expired')
              AND COALESCE(s.morale, 50) <= ?
              AND NOT EXISTS (SELECT 1 FROM forced_move fm
                              WHERE fm.wrestler_id = wr.wrestler_id
                                AND fm.on_date >= wr.created_on)""",
        (morale.ROCK_BOTTOM,)):
        wid = r["wrestler_id"]
        name = game._wname(con, wid)
        st = con.execute("SELECT season_year FROM game_state WHERE id=1").fetchone()
        c = game.active_contract(con, wid, st["season_year"])
        if not c:
            continue
        kind, note = "trade", ""
        if r["kind"] == "trade":
            try:
                mv = _move_brands(con, wid, "she forced the move")
                dest = mv["to_brand"]
            except game.SigningError as e:
                kind, dest, note = "walkout", None, f" ({e})"
        else:
            kind, dest = "walkout", None

        if kind == "walkout":
            game.release(con, wid)
            con.execute(
                "INSERT INTO forced_move (wrestler_id, kind, from_brand, to_brand, "
                "on_date, reason) VALUES (?,?,?,?,?,?)",
                (wid, "walkout", c["brand_id"], None, today,
                 f"Morale at rock bottom; her demand was refused{note}."))
            game.log_event(con, "walkout",
                           f"{name} has WALKED OUT of {c['brand_id']}. She asked to leave "
                           f"three times.", c["brand_id"], "🚪")
            forced.append({"wrestler_id": wid, "name": name, "kind": "walkout",
                           "from_brand": c["brand_id"]})
        else:
            con.execute(
                "INSERT INTO forced_move (wrestler_id, kind, from_brand, to_brand, "
                "on_date, reason) VALUES (?,?,?,?,?,?)",
                (wid, "trade", c["brand_id"], dest, today,
                 "Morale at rock bottom; her trade demand was refused."))
            game.log_event(con, "trade",
                           f"{name} has FORCED her way off {c['brand_id']}. "
                           f"She asked three times.", dest, "⇄")
            forced.append({"wrestler_id": wid, "name": name, "kind": "trade",
                           "from_brand": c["brand_id"], "to_brand": dest})
    con.commit()
    return forced


# ---------------------------------------------------------------- reading

def open_requests(con: sqlite3.Connection, brand_id: str | None = None) -> list[dict]:
    """The GM's in-tray, most urgent first."""
    sql = """SELECT r.*, COALESCE(o.display_name, w.name) name,
                    COALESCE(s.morale, 50) morale, COALESCE(s.fatigue, 0) fatigue,
                    COALESCE(ot.display_name, wt.name) target_name
               FROM wrestler_request r
               JOIN wrestler w ON w.id=r.wrestler_id
               LEFT JOIN attribute_override o ON o.wrestler_id=r.wrestler_id
               LEFT JOIN wrestler_state s ON s.wrestler_id=r.wrestler_id
               LEFT JOIN wrestler wt ON wt.id=r.ask_target
               LEFT JOIN attribute_override ot ON ot.wrestler_id=r.ask_target
              WHERE r.status='open'"""
    args: list = []
    if brand_id:
        sql += " AND r.brand_id=?"
        args.append(brand_id)
    # ORDER BY uses the OUTPUT alias `morale` — the column comes from the joined
    # wrestler_state, so `r.morale` would not resolve.
    sql += """ ORDER BY CASE r.severity WHEN 'final' THEN 0 WHEN 'firm' THEN 1 ELSE 2 END,
                        morale ASC, r.id"""
    out = []
    for r in con.execute(sql, tuple(args)):
        d = dict(r)
        k = KINDS.get(d["kind"], {})
        d["label"] = k.get("label", d["kind"])
        d["icon"] = k.get("icon", "🗣")
        d["band"] = morale.band(d["morale"])[0]
        d["stamina"] = max(0, 100 - (d["fatigue"] or 0))
        d["can_force"] = (d["severity"] == "final" and d["kind"] in ("trade", "release"))
        out.append(d)
    return out


def history(con: sqlite3.Connection, limit: int = 60) -> list[dict]:
    return [dict(r) for r in con.execute(
        """SELECT r.*, COALESCE(o.display_name, w.name) name
             FROM wrestler_request r
             JOIN wrestler w ON w.id=r.wrestler_id
             LEFT JOIN attribute_override o ON o.wrestler_id=r.wrestler_id
            WHERE r.status<>'open'
            ORDER BY r.resolved_on DESC, r.id DESC LIMIT ?""", (limit,))]


def forced(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute(
        """SELECT f.*, COALESCE(o.display_name, w.name) name
             FROM forced_move f
             JOIN wrestler w ON w.id=f.wrestler_id
             LEFT JOIN attribute_override o ON o.wrestler_id=f.wrestler_id
            ORDER BY f.on_date DESC, f.id DESC""")]
