"""Everything that has ever happened to one wrestler.

The sim already records enough to answer real questions — who she has beaten,
what she did in 2003, how she does against one specific opponent — but nothing
ever asked. Every match writes a `sim_match_participant` row with a team number
and a winner flag, and that is all a head-to-head needs.

THE ONE SUBTLETY, and it is the whole reason this is a module rather than a
query: "opponent" is not "everyone else in the match". A tag match has partners
on your own side, and counting a partner as someone you beat would make a tag
team look like a lifelong rivalry. Opponents are participants on a DIFFERENT
`team` number; partners are on the same one. Both are worth reporting, and they
are different facts.

Deliberately read-only. Nothing here writes, so it can be called from any screen
without wondering what it might change.
"""

from __future__ import annotations

import sqlite3

import game


def _name(con: sqlite3.Connection, wid: int) -> str:
    return game._wname(con, wid)


def _match_rows(con: sqlite3.Connection, wid: int) -> list[sqlite3.Row]:
    """Every match she has worked, with the show it was on."""
    return con.execute(
        """SELECT m.id AS match_id, m.slot, m.quality, m.finish, m.title_id,
                  m.stipulation, p.team, p.is_winner,
                  s.id AS show_id, s.name AS show_name, s.held_on, s.is_ppv,
                  s.ppv_name, s.brand_id,
                  CAST(substr(s.held_on, 1, 4) AS INTEGER) AS season,
                  t.name AS title_name, t.short_name AS title_short
             FROM sim_match_participant p
             JOIN sim_match m ON m.id = p.match_id
             JOIN show s      ON s.id = m.show_id
             LEFT JOIN game_title t ON t.id = m.title_id
            WHERE p.wrestler_id = ?
            ORDER BY s.held_on, m.slot""",
        (wid,)).fetchall()


def _others(con: sqlite3.Connection, match_ids: list[int]) -> dict[int, list[sqlite3.Row]]:
    """Everyone in those matches, grouped by match, in one query."""
    if not match_ids:
        return {}
    marks = ",".join("?" * len(match_ids))
    out: dict[int, list[sqlite3.Row]] = {}
    for r in con.execute(
            f"""SELECT match_id, wrestler_id, team, is_winner
                  FROM sim_match_participant WHERE match_id IN ({marks})""",
            match_ids):
        out.setdefault(r["match_id"], []).append(r)
    return out


def career(con: sqlite3.Connection, wid: int) -> dict:
    """Her whole record: by season, by opponent, by title, by partner.

    One pass over her matches builds all of it, so the cost is the same whether
    the panel shows one section or every one.
    """
    if not con.execute("SELECT 1 FROM wrestler WHERE id=?", (wid,)).fetchone():
        raise ValueError(f"no such wrestler: {wid}")

    rows = _match_rows(con, wid)
    others = _others(con, [r["match_id"] for r in rows])

    seasons: dict[int, dict] = {}
    versus: dict[int, dict] = {}
    partners: dict[int, dict] = {}
    best: list[dict] = []

    for r in rows:
        drew = r["finish"] == "draw"
        won = bool(r["is_winner"]) and not drew

        st = seasons.setdefault(r["season"], {
            "season": r["season"], "matches": 0, "wins": 0, "losses": 0,
            "draws": 0, "ppv": 0, "titles_won": 0, "quality_sum": 0.0,
            "main_events": 0,
        })
        st["matches"] += 1
        st["wins"] += 1 if won else 0
        st["losses"] += 0 if (won or drew) else 1
        st["draws"] += 1 if drew else 0
        st["ppv"] += 1 if r["is_ppv"] else 0
        st["quality_sum"] += r["quality"] or 0.0

        if r["quality"] is not None:
            best.append({
                "match_id": r["match_id"], "quality": round(r["quality"], 1),
                "held_on": r["held_on"], "show": r["show_name"],
                "title": r["title_name"], "stipulation": r["stipulation"],
                "won": won,
            })

        for o in others.get(r["match_id"], []):
            if o["wrestler_id"] == wid:
                continue
            # Same team = partner, different team = opponent. Counting a tag
            # partner as someone you beat is the classic way to get this wrong.
            bucket = partners if o["team"] == r["team"] else versus
            rec = bucket.setdefault(o["wrestler_id"], {
                "wrestler_id": o["wrestler_id"], "matches": 0,
                "wins": 0, "losses": 0, "draws": 0, "last_met": None,
            })
            rec["matches"] += 1
            rec["last_met"] = r["held_on"]
            if drew:
                rec["draws"] += 1
            elif bucket is versus:
                rec["wins"] += 1 if won else 0
                rec["losses"] += 0 if won else 1
            else:
                # As a PARTNER, a win is the team's win — there is no losing to
                # your own partner, so this counts shared results.
                rec["wins"] += 1 if won else 0
                rec["losses"] += 0 if won else 1

    for st in seasons.values():
        st["avg_quality"] = (round(st["quality_sum"] / st["matches"], 1)
                             if st["matches"] else None)
        st.pop("quality_sum")

    # Title reigns won in a season belong to that season's line.
    reigns = []
    for r in con.execute(
            """SELECT r.id, r.won_on, r.lost_on, t.name, t.short_name, t.tier,
                      julianday(COALESCE(r.lost_on,
                        (SELECT game_state.current_date FROM game_state WHERE id=1)))
                        - julianday(r.won_on) AS days
                 FROM game_title_reign r JOIN game_title t ON t.id = r.title_id
                WHERE r.wrestler_id = ?
                ORDER BY r.won_on""", (wid,)):
        d = dict(r)
        d["days"] = int(max(0, d["days"] or 0))
        d["ongoing"] = d["lost_on"] is None
        reigns.append(d)
        yr = int(str(d["won_on"])[:4])
        if yr in seasons:
            seasons[yr]["titles_won"] += 1

    accolades = [dict(r) | {"label": game.ACCOLADES.get(r["kind"], (r["kind"],))[0]}
                 for r in con.execute(
                     """SELECT kind, season_year, detail, awarded_on
                          FROM accomplishment WHERE wrestler_id=?
                          ORDER BY awarded_on""", (wid,))]

    spells = [dict(r) for r in con.execute(
        """SELECT brand_id, annual_value, years, start_year, end_year,
                  signed_on, terminated_on, origin, role
             FROM contract WHERE wrestler_id=? ORDER BY start_year, signed_on""",
        (wid,))]

    def named(bucket: dict) -> list[dict]:
        out = []
        for rec in bucket.values():
            out.append({**rec, "name": _name(con, rec["wrestler_id"]),
                        "win_pct": round(rec["wins"] / rec["matches"] * 100)
                        if rec["matches"] else 0})
        out.sort(key=lambda x: (-x["matches"], x["name"]))
        return out

    total = {
        "matches": sum(s["matches"] for s in seasons.values()),
        "wins": sum(s["wins"] for s in seasons.values()),
        "losses": sum(s["losses"] for s in seasons.values()),
        "draws": sum(s["draws"] for s in seasons.values()),
        "ppv": sum(s["ppv"] for s in seasons.values()),
        "reigns": len(reigns),
        "title_days": sum(r["days"] for r in reigns),
        "accolades": len(accolades),
    }
    total["win_pct"] = (round(total["wins"] / total["matches"] * 100)
                        if total["matches"] else 0)

    best.sort(key=lambda m: -m["quality"])

    return {
        "wrestler_id": wid,
        "name": _name(con, wid),
        "total": total,
        "seasons": sorted(seasons.values(), key=lambda s: s["season"]),
        "versus": named(versus),
        "partners": named(partners),
        "reigns": reigns,
        "accolades": accolades,
        "contracts": spells,
        "best_matches": best[:8],
    }


def head_to_head(con: sqlite3.Connection, a: int, b: int) -> dict:
    """Every match these two have had against each other, in order.

    Separate from `career` because the interesting thing here is the SEQUENCE —
    who won which one, on what show — and folding that into the career payload
    would mean carrying it for all 370 possible opponents.
    """
    rows = con.execute(
        """SELECT m.id AS match_id, s.held_on, s.name AS show_name, s.is_ppv,
                  m.quality, m.finish, m.stipulation,
                  t.name AS title_name,
                  pa.team AS a_team, pa.is_winner AS a_won,
                  pb.team AS b_team, pb.is_winner AS b_won
             FROM sim_match m
             JOIN sim_match_participant pa ON pa.match_id = m.id AND pa.wrestler_id = ?
             JOIN sim_match_participant pb ON pb.match_id = m.id AND pb.wrestler_id = ?
             JOIN show s ON s.id = m.show_id
             LEFT JOIN game_title t ON t.id = m.title_id
            WHERE pa.team <> pb.team
            ORDER BY s.held_on, m.slot""",
        (a, b)).fetchall()

    meetings, aw, bw, dr = [], 0, 0, 0
    for r in rows:
        drew = r["finish"] == "draw"
        if drew:
            dr += 1
            winner = None
        elif r["a_won"]:
            aw += 1
            winner = a
        else:
            bw += 1
            winner = b
        meetings.append({
            "match_id": r["match_id"], "held_on": r["held_on"],
            "show": r["show_name"], "is_ppv": bool(r["is_ppv"]),
            "quality": round(r["quality"], 1) if r["quality"] is not None else None,
            "finish": r["finish"], "stipulation": r["stipulation"],
            "title": r["title_name"], "winner_id": winner,
        })

    return {
        "a": {"wrestler_id": a, "name": _name(con, a), "wins": aw},
        "b": {"wrestler_id": b, "name": _name(con, b), "wins": bw},
        "draws": dr,
        "meetings": meetings,
    }
