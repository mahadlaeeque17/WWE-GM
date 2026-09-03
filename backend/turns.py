"""Face and heel turns — proposed by the crowd, decided by the GM.

WHY NOTHING TURNS AUTOMATICALLY. A turn is the single biggest creative decision
in wrestling and it is exactly the kind of call a simulation should not make for
you. So this module never writes an alignment. It watches for the four things
that in practice force a turn, files a SUGGESTION with the evidence behind it,
and waits — the same contract rating progression follows, for the same reason:
the engine can see things you cannot, but it does not get to overrule you.

THE FOUR TRIGGERS, and what each one actually detects:

  crowd        The crowd is reacting to her the wrong way round — a heel they
               cheer anyway, a face they have stopped caring about. Measured
               from `segment_pop` over her last several segments, so one loud
               night is never enough. This is the famous one.

  betrayal     A face who laid out another face in a run-in beatdown. She has
               already acted like a heel; the alignment is just paperwork.

  frustration  A face on a long losing run. "Nice guy finishes last" is the
               oldest heel-turn motivation there is.

  stale        A wrestler who has been the same thing for a very long time while
               going nowhere. Not a crowd problem — a creative one.

Approving a turn writes `attribute_override.alignment`, which is the same layer
a hand edit uses, because an approved turn IS a user-decided value.
"""
from __future__ import annotations

import sqlite3

import crowd
import game

# How many recent segments the crowd trigger needs before it will speak up. One
# hot night is a hot night; five in a row is the crowd telling you something.
MIN_SAMPLES = 4

# A losing run long enough to read as a motivation rather than a slump.
FRUSTRATION_LOSSES = 5

# Stale: this many matches without a main event or a title shot, same alignment
# throughout. Deliberately large — "she needs freshening up" is a slow signal.
STALE_MATCHES = 22

TRIGGERS = {
    "crowd": "The crowd",
    "betrayal": "Betrayal",
    "frustration": "Frustration",
    "stale": "Gone stale",
}


def _pending(con: sqlite3.Connection, wid: int) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM turn_suggestion WHERE wrestler_id=? AND status='pending'",
        (wid,)).fetchone())


def _recently_rejected(con: sqlite3.Connection, wid: int, trigger: str) -> bool:
    """Do not re-file a turn the GM has already said no to.

    Without this the crowd trigger would re-propose the same turn every single
    week, which trains the GM to ignore the queue — the one thing an approval
    queue must never do.
    """
    return bool(con.execute(
        """SELECT 1 FROM turn_suggestion
           WHERE wrestler_id=? AND trigger=? AND status='rejected'""",
        (wid, trigger)).fetchone())


def _file(con: sqlite3.Connection, wid: int, to_align: str, trigger: str,
          reason: str, evidence: str, score: float) -> int | None:
    if _pending(con, wid) or _recently_rejected(con, wid, trigger):
        return None
    eff = game.effective_attributes(con, wid)
    frm = eff.get("alignment") or "face"
    if frm == to_align:
        return None
    cur = con.execute(
        """INSERT INTO turn_suggestion (wrestler_id, from_align, to_align, trigger,
             reason, evidence, score, status, created_on)
           VALUES (?,?,?,?,?,?,?, 'pending', ?)""",
        (wid, frm, to_align, trigger, reason, evidence, round(score, 1), game.now_iso()))
    game.log_event(con, "turn",
                   f"{game._wname(con, wid)} — {frm} → {to_align} suggested ({TRIGGERS[trigger]}).",
                   icon="🔄")
    return cur.lastrowid


def scan(con: sqlite3.Connection) -> dict:
    """Look for turns worth proposing across the whole signed roster."""
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if not st:
        return {"created": 0}
    season = st["season_year"]
    created = 0

    for r in con.execute(
        """SELECT wrestler_id FROM contract
           WHERE terminated_on IS NULL AND role<>'manager'
             AND start_year<=? AND end_year>=?""", (season, season)):
        wid = r["wrestler_id"]
        try:
            eff = game.effective_attributes(con, wid)
        except ValueError:
            continue
        align = eff.get("alignment") or "face"

        # ---- the crowd -------------------------------------------------
        rp = crowd.recent_pop(con, wid, limit=8)
        if rp["samples"] >= MIN_SAMPLES and rp["drifting"]:
            avg = rp["avg_pop"]
            if rp["drifting"] == "face":
                reason = ("The crowd cheers her anyway. She is too over to keep "
                          "booing — turn her before they turn her for you.")
            else:
                reason = ("The crowd has stopped getting behind her. She is being "
                          "rejected as a good guy.")
            ev = (f"Average crowd reaction {avg:+.0f} across her last "
                  f"{rp['samples']} segments, as a {align}.")
            if _file(con, wid, rp["drifting"], "crowd", reason, ev, abs(avg)):
                created += 1
                continue

        # ---- frustration -----------------------------------------------
        if align == "face":
            recent = [x for x in con.execute(
                """SELECT p.is_winner, m.finish FROM sim_match_participant p
                     JOIN sim_match m ON m.id=p.match_id
                     JOIN show s ON s.id=m.show_id
                    WHERE p.wrestler_id=? ORDER BY s.held_on DESC, m.slot DESC
                    LIMIT ?""", (wid, FRUSTRATION_LOSSES))]
            if (len(recent) >= FRUSTRATION_LOSSES
                    and all(not x["is_winner"] and x["finish"] != "draw" for x in recent)):
                if _file(con, wid, "heel", "frustration",
                         "She has done everything right and lost anyway. The obvious "
                         "story is that she stops playing fair.",
                         f"Beaten in her last {len(recent)} matches.",
                         float(len(recent) * 8)):
                    created += 1
                    continue

        # ---- gone stale ------------------------------------------------
        tot = con.execute(
            """SELECT COUNT(*) n,
                      SUM(CASE WHEN m.title_id IS NOT NULL THEN 1 ELSE 0 END) titles,
                      SUM(CASE WHEN m.slot=(SELECT MAX(mm.slot) FROM sim_match mm
                                            WHERE mm.show_id=m.show_id) THEN 1 ELSE 0 END) mains
                 FROM sim_match_participant p
                 JOIN sim_match m ON m.id=p.match_id
                WHERE p.wrestler_id=?""", (wid,)).fetchone()
        if (tot and (tot["n"] or 0) >= STALE_MATCHES
                and not (tot["titles"] or 0) and not (tot["mains"] or 0)):
            other = "heel" if align == "face" else "face"
            if _file(con, wid, other, "stale",
                     "Same character, same spot on the card, for a very long time. "
                     "A turn is the cheapest way to make her interesting again.",
                     f"{tot['n']} matches with no main event and no title shot.",
                     float(tot["n"])):
                created += 1
    con.commit()
    return {"created": created}


def note_betrayal(con: sqlite3.Connection, aggressor: int, victim: int,
                  detail: str) -> int | None:
    """A face laid out another face. She has already turned; file the paperwork.

    Called from the promo layer when a run-in beatdown has a face on both ends —
    the one turn trigger that comes from a single deliberate booking decision
    rather than from accumulated evidence.
    """
    try:
        a = game.effective_attributes(con, aggressor)
        v = game.effective_attributes(con, victim)
    except ValueError:
        return None
    if (a.get("alignment") or "face") != "face" or (v.get("alignment") or "face") != "face":
        return None
    return _file(con, aggressor, "heel", "betrayal",
                 "She attacked another good guy from behind. The crowd will not "
                 "forgive that, and it does not need to.",
                 detail, 70.0)


def list_suggestions(con: sqlite3.Connection, status: str = "pending") -> list[dict]:
    sql = """SELECT t.*, COALESCE(o.display_name, w.name) name
               FROM turn_suggestion t
               JOIN wrestler w ON w.id=t.wrestler_id
               LEFT JOIN attribute_override o ON o.wrestler_id=t.wrestler_id"""
    args: tuple = ()
    if status and status != "all":
        sql += " WHERE t.status=?"
        args = (status,)
    sql += " ORDER BY t.score DESC, t.id DESC"
    out = []
    for r in con.execute(sql, args):
        d = dict(r)
        d["trigger_label"] = TRIGGERS.get(d["trigger"], d["trigger"])
        out.append(d)
    return out


def resolve(con: sqlite3.Connection, sid: int, approve: bool) -> dict:
    """Approve a turn (writing the alignment) or reject it.

    Approving is the ONLY path that changes an alignment from this module, and it
    writes to `attribute_override` — the layer a re-harvest never overwrites.
    """
    s = con.execute("SELECT * FROM turn_suggestion WHERE id=?", (sid,)).fetchone()
    if not s:
        raise game.SigningError("no such turn suggestion")
    if s["status"] != "pending":
        raise game.SigningError(f"already {s['status']}")
    if not approve:
        con.execute("UPDATE turn_suggestion SET status='rejected', resolved_on=? WHERE id=?",
                    (game.now_iso(), sid))
        con.commit()
        return {"id": sid, "status": "rejected"}

    wid = s["wrestler_id"]
    con.execute(
        """INSERT INTO attribute_override (wrestler_id, alignment, updated_at)
           VALUES (?,?,?)
           ON CONFLICT(wrestler_id) DO UPDATE SET alignment=excluded.alignment,
             updated_at=excluded.updated_at""",
        (wid, s["to_align"], game.now_iso()))
    # A turn is a fresh start: it wipes the slate she had gone stale on and the
    # crowd re-evaluates her from scratch, so old pops must not keep firing the
    # same suggestion.
    con.execute("DELETE FROM segment_pop WHERE wrestler_id=?", (wid,))
    con.execute("UPDATE wrestler_state SET momentum = MIN(100, momentum + 12), "
                "morale = MAX(0, MIN(100, morale + 6)) WHERE wrestler_id=?", (wid,))
    con.execute("UPDATE turn_suggestion SET status='approved', resolved_on=? WHERE id=?",
                (game.now_iso(), sid))
    name = game._wname(con, wid)
    game.log_event(con, "turn",
                   f"{name} turns {s['to_align']}! " +
                   ("The crowd got what it wanted." if s["trigger"] == "crowd"
                    else "A new direction."),
                   icon="🔄")
    con.commit()
    return {"id": sid, "status": "approved", "wrestler_id": wid,
            "alignment": s["to_align"], "name": name}
