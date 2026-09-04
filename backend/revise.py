"""Overruling the simulation — the GM's final say on a result.

WHY THIS EXISTS. The sim decides who wins and how good the match was, and it is
deliberately deterministic so results are reproducible. But this is a GM game,
and the whole premise everywhere else in the save is that the engine SUGGESTS and
the GM DECIDES: ratings progression, turns, the pre-booked card, the contender
ladder. Match results were the one place that rule did not hold, which made them
the one place the game could hand you something you had to live with.

WHAT REVISING ACTUALLY HAS TO UNDO. A result is not a number in a row — it has
already paid out into half a dozen places. Changing the winner means putting
back:

    the participant flags        who is marked as having won
    win/loss/draw records        on both sides
    momentum                     the winner gained, the loser lost
    the title reign              if this match awarded a belt
    the storyline beat           "she beat her via pinfall" is now wrong
    the show rating              the night's average moves with the star rating
    the Power 25                 published from the results

Every one of those is reversed here rather than recomputed from scratch, because
recomputing would also undo everything that happened AFTER the match. That is the
one real limitation and it is stated in `LIMITS` so the UI can say it out loud:
revising a match from four shows ago cannot un-ring the bell on what its result
caused in between.

Every revision is written to `match_revision`, because the final say being hers
is a feature and a save should be able to show where she used it.
"""
from __future__ import annotations

import sqlite3

import game
import sim

# What a revision does NOT reach back and fix. Surfaced to the UI so the GM is
# told the truth about the edge of the feature rather than discovering it.
LIMITS = (
    "Revising a result puts back the records, momentum, the title and the "
    "storyline beat for THIS match. It does not re-simulate later shows that "
    "were booked off the old outcome."
)


def revisions(con: sqlite3.Connection, match_id: int) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT * FROM match_revision WHERE match_id=? ORDER BY id", (match_id,))]


def _log(con: sqlite3.Connection, match_id: int, field: str,
         frm, to, note: str | None = None) -> None:
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    con.execute(
        "INSERT INTO match_revision (match_id, on_date, field, from_value, to_value, note) "
        "VALUES (?,?,?,?,?,?)",
        (match_id, st["current_date"] if st else game.now_iso()[:10],
         field, str(frm), str(to), note))


def _sides(con: sqlite3.Connection, match_id: int) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for r in con.execute(
        "SELECT wrestler_id, team FROM sim_match_participant WHERE match_id=? "
        "ORDER BY team", (match_id,)):
        out.setdefault(r["team"], []).append(r["wrestler_id"])
    return out


def match_detail(con: sqlite3.Connection, match_id: int) -> dict:
    """One match, in the shape the revise UI needs: sides, result, what it did."""
    m = con.execute(
        """SELECT m.*, s.name show_name, s.held_on, s.brand_id, s.is_ppv
             FROM sim_match m JOIN show s ON s.id=m.show_id
            WHERE m.id=?""", (match_id,)).fetchone()
    if not m:
        raise game.SigningError("no such match")
    sides = _sides(con, match_id)
    winners = [r["wrestler_id"] for r in con.execute(
        "SELECT wrestler_id FROM sim_match_participant WHERE match_id=? AND is_winner=1",
        (match_id,))]
    winner_team = None
    for t, ids in sides.items():
        if ids and ids[0] in winners:
            winner_team = t
            break
    reign = con.execute(
        "SELECT * FROM game_title_reign WHERE won_at_match=?", (match_id,)).fetchone()
    return {
        "match_id": match_id, "show_id": m["show_id"], "show_name": m["show_name"],
        "held_on": m["held_on"], "brand_id": m["brand_id"], "is_ppv": m["is_ppv"],
        "slot": m["slot"], "quality": m["quality"],
        "stars": sim.stars_from_quality(m["quality"] or 0),
        "finish": m["finish"], "title_id": m["title_id"],
        "match_type": m["match_type"], "stipulation": m["stipulation"],
        "winner_team": winner_team,
        "sides": [{"team": t,
                   "wrestlers": [{"id": w, "name": game._wname(con, w)} for w in ids]}
                  for t, ids in sorted(sides.items())],
        "awarded_title": dict(reign) if reign else None,
        "revisions": revisions(con, match_id),
        "limits": LIMITS,
    }


def set_stars(con: sqlite3.Connection, match_id: int, stars: float) -> dict:
    """Overrule the star rating.

    Stored as QUALITY, because quality is what everything downstream reads —
    the show rating, prestige drift, the Power 25 and rating progression all
    read `sim_match.quality`, so writing stars anywhere else would leave the
    number on screen disagreeing with the number in the maths.
    """
    if not 0 <= stars <= 5:
        raise game.SigningError("a star rating is 0 to 5")
    # Half-star steps, matching what the sim itself produces.
    stars = round(stars * 2) / 2
    m = con.execute("SELECT quality, show_id FROM sim_match WHERE id=?",
                    (match_id,)).fetchone()
    if not m:
        raise game.SigningError("no such match")
    old_q = m["quality"]
    # The exact inverse of stars_from_quality, which is round(q/10)/2 — so
    # q = stars*20 and nothing else. An earlier version subtracted 5 to "land
    # mid-band" and put every half-star value on a rounding boundary instead,
    # where Python's round-half-to-even turned 0.5★ back into 0★.
    new_q = max(0.0, min(100.0, stars * 20.0))
    con.execute("UPDATE sim_match SET quality=? WHERE id=?", (new_q, match_id))
    _log(con, match_id, "stars",
         sim.stars_from_quality(old_q or 0), stars, "GM override")
    _rescore_show(con, m["show_id"])
    game.log_event(con, "revision",
                   f"Match rating overruled to {stars:g}★.", icon="✎")
    con.commit()
    return {"match_id": match_id, "stars": stars, "quality": new_q}


def set_winner(con: sqlite3.Connection, match_id: int,
               winner_team: int | None, finish: str | None = None) -> dict:
    """Overrule who won. `winner_team=None` makes it a draw.

    Reverses the old outcome's effects before applying the new one — see the
    module docstring for exactly what is put back and what is not.
    """
    d = match_detail(con, match_id)
    sides = {s["team"]: [w["id"] for w in s["wrestlers"]] for s in d["sides"]}
    if winner_team is not None and winner_team not in sides:
        raise game.SigningError(f"this match has no side {winner_team}")
    old_team = d["winner_team"]
    old_finish = d["finish"]
    finish = finish or ("draw" if winner_team is None
                        else (old_finish if old_finish != "draw" else "pinfall"))
    if winner_team == old_team and finish == old_finish:
        return {"match_id": match_id, "unchanged": True}

    # ---- put back the old result ----------------------------------------
    for team, ids in sides.items():
        won_before = (old_team == team) and old_finish != "draw"
        lost_before = (old_team is not None and old_team != team
                       and old_finish != "draw")
        drew_before = old_finish == "draw"
        for w in ids:
            con.execute(
                """UPDATE wrestler_state SET
                     sim_wins   = MAX(0, sim_wins   - ?),
                     sim_losses = MAX(0, sim_losses - ?),
                     sim_draws  = MAX(0, sim_draws  - ?),
                     momentum   = MAX(0, MIN(100, momentum - ?))
                   WHERE wrestler_id=?""",
                (1 if won_before else 0, 1 if lost_before else 0,
                 1 if drew_before else 0,
                 8 if won_before else (-6 if lost_before else 0), w))

    # ---- apply the new one ----------------------------------------------
    for team, ids in sides.items():
        wins_now = (winner_team == team) and finish != "draw"
        loses_now = (winner_team is not None and winner_team != team
                     and finish != "draw")
        draws_now = finish == "draw"
        for w in ids:
            con.execute(
                """UPDATE wrestler_state SET
                     sim_wins   = sim_wins   + ?,
                     sim_losses = sim_losses + ?,
                     sim_draws  = sim_draws  + ?,
                     momentum   = MAX(0, MIN(100, momentum + ?))
                   WHERE wrestler_id=?""",
                (1 if wins_now else 0, 1 if loses_now else 0,
                 1 if draws_now else 0,
                 8 if wins_now else (-6 if loses_now else 0), w))
        for w in ids:
            con.execute(
                "UPDATE sim_match_participant SET is_winner=? "
                "WHERE match_id=? AND wrestler_id=?",
                (1 if wins_now else 0, match_id, w))

    con.execute("UPDATE sim_match SET finish=? WHERE id=?", (finish, match_id))
    _retitle(con, match_id, d, winner_team, finish, sides)
    _rebeat(con, match_id, d, winner_team, finish, sides)

    _log(con, match_id, "winner", old_team, winner_team, "GM override")
    if finish != old_finish:
        _log(con, match_id, "finish", old_finish, finish, "GM override")
    who = ("a draw" if winner_team is None
           else " & ".join(game._wname(con, w) for w in sides[winner_team]))
    game.log_event(con, "revision",
                   f"Result overruled on {d['show_name']}: now {who}.", icon="✎")
    con.commit()
    _republish(con, d["held_on"])
    return {"match_id": match_id, "winner_team": winner_team, "finish": finish}


def _retitle(con, match_id, d, winner_team, finish, sides) -> None:
    """Move the belt if this match awarded one and the winner changed.

    Only touches a reign this match CREATED (`won_at_match`). A belt that was
    already held going in and successfully defended does not move, which is
    correct: the reign it belongs to was not created here.
    """
    if not d["title_id"]:
        return
    reign = con.execute(
        "SELECT * FROM game_title_reign WHERE won_at_match=?", (match_id,)).fetchone()
    clean = finish in ("pinfall", "submission")
    new_champ = (sides[winner_team][0]
                 if winner_team is not None and clean and sides.get(winner_team)
                 else None)

    if reign and new_champ is None:
        # The title change is undone: hand the belt back to whoever held it.
        con.execute("DELETE FROM game_title_reign WHERE id=?", (reign["id"],))
        con.execute(
            """UPDATE game_title_reign SET lost_on=NULL
                WHERE title_id=? AND lost_on=?""",
            (d["title_id"], reign["won_on"]))
        _log(con, match_id, "title", "changed hands", "no change",
             "reverted by a result override")
    elif reign and new_champ != reign["wrestler_id"]:
        con.execute("UPDATE game_title_reign SET wrestler_id=? WHERE id=?",
                    (new_champ, reign["id"]))
        _log(con, match_id, "title", reign["wrestler_id"], new_champ,
             "reverted by a result override")
    elif not reign and new_champ is not None:
        # It did not change hands before and now it should — unless the new
        # winner is the sitting champion, in which case she just retained.
        champ = con.execute(
            "SELECT * FROM game_title_reign WHERE title_id=? AND lost_on IS NULL",
            (d["title_id"],)).fetchone()
        if champ and champ["wrestler_id"] != new_champ:
            con.execute("UPDATE game_title_reign SET lost_on=? WHERE id=?",
                        (d["held_on"], champ["id"]))
            con.execute(
                """INSERT INTO game_title_reign (title_id, wrestler_id, won_on, won_at_match)
                   VALUES (?,?,?,?)""",
                (d["title_id"], new_champ, d["held_on"], match_id))
            _log(con, match_id, "title", champ["wrestler_id"], new_champ,
                 "belt moved by a result override")


def _rebeat(con, match_id, d, winner_team, finish, sides) -> None:
    """Rewrite the storyline beat this match wrote, so the story is not lying."""
    import storylines
    beat = con.execute(
        "SELECT * FROM feud_beat WHERE show_id=? AND kind='match' "
        "ORDER BY id DESC", (d["show_id"],)).fetchall()
    if not beat:
        return
    in_ring = {w for ids in sides.values() for w in ids}
    winner = (sides[winner_team][0] if winner_team is not None
              and finish != "draw" and sides.get(winner_team) else None)
    for b in beat:
        f = con.execute("SELECT * FROM feud WHERE id=?", (b["feud_id"],)).fetchone()
        if not f or f["a_id"] not in in_ring or f["b_id"] not in in_ring:
            continue
        loser = (f["b_id"] if winner == f["a_id"] else f["a_id"]) if winner else None
        txt = (f"{game._wname(con, winner)} beat {game._wname(con, loser)} "
               f"via {finish} — {d['quality']:.0f}/100 (GM overruled)"
               if winner else
               f"{game._wname(con, f['a_id'])} and {game._wname(con, f['b_id'])} "
               f"went to a draw (GM overruled)")
        con.execute("UPDATE feud_beat SET text=?, winner_id=? WHERE id=?",
                    (txt, winner, b["id"]))
        storylines.sync_stage(con, b["feud_id"])
        break


def undo(con: sqlite3.Connection, match_id: int) -> dict:
    """Put a match back exactly as the simulation left it.

    Reads the revision log backwards and replays each entry in reverse, which is
    why every override records its FROM value rather than only its TO. That log
    was already there for the record; making it the undo source means there is
    one history rather than a history plus a separate snapshot that could
    disagree with it.

    Only the winner and the stars are reversible, and that is not a shortcut: a
    title move and a storyline beat are both DERIVED from those two, so putting
    the winner back re-derives them through the same code path that set them.
    """
    revs = revisions(con, match_id)
    if not revs:
        raise game.SigningError("this result has not been overruled")
    # Oldest FROM value is what the sim originally produced; anything in between
    # was the GM changing her mind, and undo means all the way back.
    first_winner = next((r for r in revs if r["field"] == "winner"), None)
    first_stars = next((r for r in revs if r["field"] == "stars"), None)
    out: dict = {"match_id": match_id, "reverted": []}

    if first_stars is not None:
        set_stars(con, match_id, float(first_stars["from_value"]))
        out["reverted"].append(f"stars back to {first_stars['from_value']}")
    if first_winner is not None:
        team = (None if first_winner["from_value"] in ("None", "", None)
                else int(first_winner["from_value"]))
        first_finish = next((r for r in revs if r["field"] == "finish"), None)
        set_winner(con, match_id, team,
                   first_finish["from_value"] if first_finish else None)
        out["reverted"].append("winner back to the simulated result")

    # The log is cleared: the match is as the sim left it, so claiming it was
    # overruled would be false, and the ✎ marker would be lying.
    con.execute("DELETE FROM match_revision WHERE match_id=?", (match_id,))
    game.log_event(con, "revision",
                   f"Override undone — the simulated result stands.", icon="↩")
    con.commit()
    return out


def _rescore_show(con: sqlite3.Connection, show_id: int) -> None:
    """Recompute the night's rating from its segments.

    Mirrors run_show's weighting — main event double, promos half — because the
    two must agree or the same card would rate differently depending on whether
    a result was ever revised.
    """
    import promos as PR
    ms = [r["quality"] for r in con.execute(
        "SELECT quality FROM sim_match WHERE show_id=? AND quality IS NOT NULL "
        "ORDER BY slot", (show_id,))]
    if not ms:
        return
    ps = [r["quality"] for r in con.execute(
        "SELECT quality FROM sim_promo WHERE show_id=? AND quality IS NOT NULL",
        (show_id,))]
    weights = [1.0] * (len(ms) - 1) + [2.0]
    qualities = ms + ps
    weights += [PR.PROMO_SHOW_WEIGHT] * len(ps)
    rating = sum(q * w for q, w in zip(qualities, weights)) / sum(weights)
    con.execute("UPDATE show SET rating=? WHERE id=?", (round(rating, 1), show_id))
    # The TV rating is built from the show rating, so it moves too.
    try:
        import brandwar
        brandwar.rate_show(con, show_id)
    except Exception:                                        # noqa: BLE001
        pass


def _republish(con: sqlite3.Connection, held_on: str) -> None:
    """Rebuild the Power 25 for the week the match was in.

    Wrapped: a ranking failure must never lose a revision that is already
    committed, exactly as run_show treats it.
    """
    try:
        import rankings
        rankings.generate_issue(con, held_on)
        con.commit()
    except Exception:                                        # noqa: BLE001
        pass
