"""How every wrestler feels about working here, and WHY.

WHY THIS IS ITS OWN MODULE. Morale already existed, but it only ever moved as a
side effect of a match: win, lose, get jobbed out, be left off the show. That
made it a scoreboard of last Monday rather than a picture of a career, and it
meant the two things a wrestler actually cares most about — what she is paid and
whether she is going anywhere — had no effect on her at all. So a woman could be
on half her market rate, buried in the opener for eight months, and still sit at
a contented 50.

The model here is a MONTHLY DRIFT built from standing conditions:

    pay          salary against her market rate. The biggest single factor,
                 because it is the one she can compare with everyone else's.
    booking      is she on television? Nothing sours a locker room like being
                 forgotten, and nothing sours it faster than being overworked.
    spotlight    main events and title shots — whether she is going anywhere.
    winning      her record. Losing constantly wears anybody down.
    promises     the perks written into her deal, checked against reality.
    stamina      worked into the ground with no rest.
    story        does she have a rivalry, i.e. a reason to be there?

Every factor returns a signed number of morale points per month and a line of
plain English. The lines are the point: a number with no explanation is not
information the GM can act on, and every one of these has a fix.

PAY IS MEASURED AGAINST A FIXED YARDSTICK. `negotiate.market_rate` pins morale
at neutral when it prices her, because a price that moved with her mood would be
measuring itself — underpaid lowers morale, which raises her price, which makes
her more underpaid, with no bottom to the spiral.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import game
import negotiate

# The bands, and what to call them. Deliberately more granular at the bottom:
# the difference between "unhappy" and "wants out" is the one the GM has to see
# coming, and 30 vs 20 is where a request turns into a demand.
BANDS = [
    (0,  "mutinous",  "She is done. She will force a move if you let this sit."),
    (12, "wants out", "Actively trying to leave."),
    (25, "unhappy",   "Sour, and starting to say so out loud."),
    (38, "restless",  "Not happy, not desperate. Fixable."),
    (52, "content",   "No complaints."),
    (66, "happy",     "Glad to be here."),
    (80, "delighted", "Would run through a wall for the brand."),
    (92, "ecstatic",  "As good as it gets."),
]

# Rock bottom. At or below this she stops asking and starts acting — see
# demands.force_moves(). It is a band of its own so the warning has somewhere to
# live before the consequence arrives.
ROCK_BOTTOM = 10

# A month's drift is capped so no single month can swing a career. Twelve months
# of neglect can still take a contented wrestler to mutinous, which is the point.
MAX_MONTHLY_DRIFT = 9

# Only a slide to HERE or below is worth a news line. A wrestler dropping from
# delighted to merely content is not a problem and does not need reporting; the
# feed is for things the GM should do something about.
ALERT_BELOW = 38


def _reads(band_label: str) -> str:
    """Fit a band label into a sentence.

    The labels are chosen to read well in a table ("wants out", "mutinous"),
    which means some are adjectives and some are verb phrases — so "X is wants
    out" came out ungrammatical. This picks the verb that fits.
    """
    return band_label if band_label.startswith("wants") else f"is {band_label}"


WINDOW_DAYS = 35        # what "lately" means, matching the Power 25's window

# Under this many matches in the window she feels forgotten; over the cap she
# feels used up. The light-schedule perk moves both, because she asked for it.
IDLE_MATCHES = 1
BUSY_MATCHES = 7


def band(m: int) -> tuple[str, str]:
    label, note = BANDS[0][1], BANDS[0][2]
    for lo, lab, n in BANDS:
        if m >= lo:
            label, note = lab, n
    return label, note


def _window(con: sqlite3.Connection) -> tuple[str, str]:
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if not st:
        raise game.SigningError("no active save")
    today = date.fromisoformat(st["current_date"])
    return (today - timedelta(days=WINDOW_DAYS)).isoformat(), st["current_date"]


def _recent(con: sqlite3.Connection, wid: int, since: str, until: str) -> dict:
    """What she has actually done lately — the evidence behind every factor."""
    r = con.execute(
        """SELECT COUNT(*) n,
                  SUM(CASE WHEN m.finish<>'draw' AND p.is_winner THEN 1 ELSE 0 END) wins,
                  SUM(CASE WHEN m.title_id IS NOT NULL THEN 1 ELSE 0 END) title_shots,
                  SUM(CASE WHEN m.slot = (SELECT MAX(mm.slot) FROM sim_match mm
                                          WHERE mm.show_id=m.show_id)
                           THEN 1 ELSE 0 END) main_events
             FROM sim_match_participant p
             JOIN sim_match m ON m.id=p.match_id
             JOIN show s ON s.id=m.show_id
            WHERE p.wrestler_id=? AND s.held_on BETWEEN ? AND ?""",
        (wid, since, until)).fetchone()
    promos = con.execute(
        """SELECT COUNT(*) n FROM sim_promo_participant pp
             JOIN sim_promo pr ON pr.id=pp.promo_id
             JOIN show s ON s.id=pr.show_id
            WHERE pp.wrestler_id=? AND s.held_on BETWEEN ? AND ?""",
        (wid, since, until)).fetchone()
    return {"matches": r["n"] or 0, "wins": r["wins"] or 0,
            "title_shots": r["title_shots"] or 0,
            "main_events": r["main_events"] or 0,
            "promos": promos["n"] or 0}


def _personality_scale(personality: str, factor: str) -> float:
    """The same slight felt differently depending on who she is.

    This is what makes the four personalities matter outside the negotiating
    table: money-hungry feels an underpayment twice as hard, ambitious cares
    about the spotlight and shrugs at the money, loyal absorbs almost anything,
    and a prima donna amplifies everything.
    """
    if personality == "money_hungry":
        return 1.9 if factor == "pay" else 0.7
    if personality == "ambitious":
        return 0.7 if factor == "pay" else (1.8 if factor == "spotlight" else 1.0)
    if personality == "loyal":
        return 0.5
    if personality == "prima_donna":
        return 1.5
    return 1.0


def factors(con: sqlite3.Connection, wid: int) -> list[dict]:
    """Every standing condition acting on her morale, with its monthly points.

    Each row is {key, label, delta, detail, fix} — `fix` is the lever the GM has,
    because a complaint with no available answer is just noise.
    """
    since, until = _window(con)
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    season = st["season_year"]
    c = game.active_contract(con, wid, season)
    if not c:
        return []

    personality, _ = negotiate._persona(con, wid)
    rec = _recent(con, wid, since, until)
    state = con.execute("SELECT * FROM wrestler_state WHERE wrestler_id=?", (wid,)).fetchone()
    fatigue = (state["fatigue"] if state else 0) or 0
    eff = game.effective_attributes(con, wid)
    perks = negotiate._contract_perks(c["perks"])
    light = "light_schedule" in perks
    out: list[dict] = []

    # ---- pay -------------------------------------------------------------
    pay = negotiate.pay_position(con, wid)
    if pay.get("under_contract"):
        # Centred on 1.0 and scaled so ±30% off market is worth roughly ±5 a
        # month before personality. Capped either side: a wrestler paid triple
        # is delighted, not infinitely delighted.
        raw = max(-0.45, min(0.45, pay["ratio"] - 1.0)) * 11.0
        delta = raw * _personality_scale(personality, "pay")
        gap = pay["gap"]
        detail = (f"On ${pay['salary']:,} against a market rate of ${pay['market']:,} — "
                  f"{'+' if gap >= 0 else '−'}${abs(gap):,}. {pay['label'].capitalize()}.")
        out.append({"key": "pay", "label": "Pay", "delta": round(delta, 1),
                    "detail": detail,
                    "fix": None if delta >= 0 else "Give her a raise, or expect a request."})

    # ---- booking ---------------------------------------------------------
    idle_cap = IDLE_MATCHES
    busy_cap = 4 if light else BUSY_MATCHES
    if rec["matches"] <= idle_cap and rec["promos"] == 0:
        d = -4.5
        detail = ("Not booked in a match or a segment in five weeks. "
                  "She is being forgotten.")
        fix = "Put her on the card — a promo counts."
    elif rec["matches"] <= idle_cap:
        d = -1.5
        detail = f"Only {rec['matches']} match in five weeks, though she has been on the mic."
        fix = "Get her in a match."
    elif rec["matches"] > busy_cap:
        d = -2.5 if not light else -5.0
        detail = (f"{rec['matches']} matches in five weeks"
                  + (" — and she negotiated a reduced schedule." if light else " — she is being run into the ground."))
        fix = "Give her a week off, or grant time off when she asks."
    else:
        d = 1.5
        detail = f"{rec['matches']} matches and {rec['promos']} segments in five weeks — a real role."
        fix = None
    out.append({"key": "booking", "label": "Booking", "delta": round(d, 1),
                "detail": detail, "fix": fix})

    # ---- spotlight -------------------------------------------------------
    spot = rec["main_events"] * 1.6 + rec["title_shots"] * 1.2
    # What she EXPECTS scales with how over she is: a headliner in the opener is
    # a problem, a rookie in the opener is Tuesday.
    expectation = max(0.0, (eff["popularity"] - 9) * 0.55)
    d = max(-5.0, min(4.5, spot - expectation)) * _personality_scale(personality, "spotlight")
    if spot == 0 and expectation > 1.5:
        detail = (f"No main events, no title shots, and she is over enough "
                  f"(popularity {eff['popularity']}/20) to expect both.")
        fix = "Book her in a main event or give her a title shot."
    elif spot > 0:
        bits = []
        if rec["main_events"]:
            bits.append(f"{rec['main_events']} main event{'s' if rec['main_events'] != 1 else ''}")
        if rec["title_shots"]:
            bits.append(f"{rec['title_shots']} title shot{'s' if rec['title_shots'] != 1 else ''}")
        detail = f"{' and '.join(bits)} in five weeks."
        fix = None
    else:
        detail = "Working where she expects to work."
        fix = None
    out.append({"key": "spotlight", "label": "Spotlight", "delta": round(d, 1),
                "detail": detail, "fix": fix})

    # ---- winning ---------------------------------------------------------
    if rec["matches"] >= 3:
        wr = rec["wins"] / rec["matches"]
        d = (wr - 0.45) * 7.0
        detail = f"{rec['wins']}-{rec['matches'] - rec['wins']} lately ({wr * 100:.0f}%)."
        out.append({"key": "winning", "label": "Results", "delta": round(d, 1),
                    "detail": detail,
                    "fix": None if d >= 0 else "She needs to win something."})

    # ---- promises --------------------------------------------------------
    ps = game.perk_status(con, wid, season)
    missed = [p for p in ps if not p["delivered"]]
    if ps:
        d = -3.0 * len(missed) if missed else 1.5
        detail = ("Promised " + ", ".join(p["label"].lower() for p in ps) + ". "
                  + ("Not delivering: " + ", ".join(p["label"].lower() for p in missed) + "."
                     if missed else "All being honoured."))
        out.append({"key": "promises", "label": "Promises", "delta": round(d, 1),
                    "detail": detail,
                    "fix": None if not missed else "Honour the perk she took less money for."})

    # ---- stamina ---------------------------------------------------------
    if fatigue >= 80:
        out.append({"key": "stamina", "label": "Stamina", "delta": -3.0,
                    "detail": f"Stamina down to {100 - fatigue}/100. She is running on empty.",
                    "fix": "Rest her for a week or two."})
    elif fatigue >= 60:
        out.append({"key": "stamina", "label": "Stamina", "delta": -1.0,
                    "detail": f"Stamina {100 - fatigue}/100 — tired.", "fix": "Ease her schedule."})

    # ---- story -----------------------------------------------------------
    feuds = [f for f in game.list_feuds(con, "active") if wid in (f["a_id"], f["b_id"])]
    if feuds:
        hottest = max(f["heat"] for f in feuds)
        out.append({"key": "story", "label": "Storyline", "delta": round(1.0 + hottest / 50.0, 1),
                    "detail": f"In a rivalry at {hottest} heat — she has something to do.",
                    "fix": None})
    elif eff["popularity"] >= 10:
        out.append({"key": "story", "label": "Storyline", "delta": -2.0,
                    "detail": "No rivalry. She is over and has nothing to be about.",
                    "fix": "Start a feud for her."})
    return out


def snapshot(con: sqlite3.Connection, wid: int) -> dict:
    """The whole picture for one wrestler: mood, pay, every factor, the drift."""
    state = con.execute("SELECT morale, fatigue, rested_until, injured_until "
                        "FROM wrestler_state WHERE wrestler_id=?", (wid,)).fetchone()
    m = (state["morale"] if state else 50) or 50
    fs = factors(con, wid)
    drift = sum(f["delta"] for f in fs)
    drift = max(-MAX_MONTHLY_DRIFT, min(MAX_MONTHLY_DRIFT, drift))
    label, note = band(m)
    personality, _ = negotiate._persona(con, wid)
    return {
        "wrestler_id": wid, "name": game._wname(con, wid),
        "morale": m, "band": label, "band_note": note,
        "rock_bottom": m <= ROCK_BOTTOM,
        "personality": personality,
        "personality_label": negotiate.PERSONALITIES[personality][0],
        "pay": negotiate.pay_position(con, wid),
        "factors": sorted(fs, key=lambda f: f["delta"]),
        "monthly_drift": round(drift, 1),
        "stamina": max(0, 100 - ((state["fatigue"] if state else 0) or 0)),
        "rested_until": state["rested_until"] if state else None,
        "injured_until": state["injured_until"] if state else None,
    }


def locker_room(con: sqlite3.Connection, brand_id: str | None = None) -> list[dict]:
    """Everyone under contract, unhappiest first — the room at a glance."""
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if not st:
        return []
    season = st["season_year"]
    sql = """SELECT c.wrestler_id, c.brand_id FROM contract c
             WHERE c.terminated_on IS NULL AND c.start_year<=? AND c.end_year>=?"""
    args: list = [season, season]
    if brand_id:
        sql += " AND c.brand_id=?"
        args.append(brand_id)
    out = []
    for r in con.execute(sql, tuple(args)):
        try:
            s = snapshot(con, r["wrestler_id"])
        except (ValueError, game.SigningError):
            continue
        s["brand_id"] = r["brand_id"]
        # The worst thing acting on her, for the one-line summary in a table.
        worst = s["factors"][0] if s["factors"] and s["factors"][0]["delta"] < 0 else None
        s["headline"] = worst["detail"] if worst else (s["factors"][-1]["detail"]
                                                       if s["factors"] else "Nothing to report.")
        out.append(s)
    return sorted(out, key=lambda s: (s["morale"], -abs(s["monthly_drift"])))


def apply_monthly_drift(con: sqlite3.Connection) -> dict:
    """Move every signed wrestler's morale by her standing conditions.

    Called when the calendar advances a month. This is the loop that makes pay
    and booking matter over a season rather than only in the week they happen.
    """
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if not st:
        return {"moved": 0}
    season = st["season_year"]
    moved, notable = 0, []
    for r in con.execute(
        """SELECT wrestler_id FROM contract
           WHERE terminated_on IS NULL AND start_year<=? AND end_year>=?""",
        (season, season)):
        wid = r["wrestler_id"]
        try:
            fs = factors(con, wid)
        except (ValueError, game.SigningError):
            continue
        drift = sum(f["delta"] for f in fs)
        drift = int(round(max(-MAX_MONTHLY_DRIFT, min(MAX_MONTHLY_DRIFT, drift))))
        if drift == 0:
            continue
        before = con.execute("SELECT morale FROM wrestler_state WHERE wrestler_id=?",
                             (wid,)).fetchone()
        b = (before["morale"] if before else 50) or 50
        con.execute("UPDATE wrestler_state SET morale = MAX(0, MIN(100, morale + ?)) "
                    "WHERE wrestler_id=?", (drift, wid))
        after = max(0, min(100, b + drift))
        moved += 1
        # Only log a crossing INTO a band worth acting on. An alert is only
        # useful if it is rare: "everyone's morale moved by one" is not news, and
        # neither is a happy wrestler becoming merely content — nothing is wrong
        # yet and nothing needs doing.
        if band(after)[0] != band(b)[0] and after <= ALERT_BELOW < b:
            notable.append({"wrestler_id": wid, "name": game._wname(con, wid),
                            "from": b, "to": after, "band": band(after)[0]})
    for n in notable:
        game.log_event(con, "morale",
                       f"{n['name']} {_reads(n['band'])} — morale {n['from']} → {n['to']}.",
                       icon="😖")
    con.commit()
    return {"moved": moved, "notable": notable}
