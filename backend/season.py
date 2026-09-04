"""What the year was — one page that says it.

WHY THIS EXISTS. The save records everything and summarises nothing. Year-end
awards crown individuals, the Power 25 says who is hot this week, the ratings war
says who is winning — but nothing answers "what happened in 2003?", which is the
question you actually ask about a season three years later.

Everything here is READ-ONLY and derived. It writes nothing, decides nothing,
and adds no state: it is the save's own records, sorted and given headlines. That
is deliberate — a summary that could disagree with the data it summarises would
be worse than no summary.

The one judgement call is BREAKOUT, and it is stated in the code rather than
hidden: the biggest riser is measured on approved rating progression plus how
often she got onto the Power 10, because "she got better and people noticed" is
what breaking out actually is.
"""
from __future__ import annotations

import sqlite3

import game
import sim
import storylines


def _rows(con: sqlite3.Connection, sql: str, args: tuple = ()) -> list[dict]:
    return [dict(r) for r in con.execute(sql, args)]


def seasons(con: sqlite3.Connection) -> list[int]:
    """Every season that actually had a show on it."""
    return [r["y"] for r in con.execute(
        "SELECT DISTINCT CAST(substr(held_on,1,4) AS INTEGER) y FROM show ORDER BY y DESC")]


def summary(con: sqlite3.Connection, season: int) -> dict:
    lo, hi = f"{season}-01-01", f"{season}-12-31"

    shows = con.execute(
        """SELECT COUNT(*) n, SUM(is_ppv) ppvs, AVG(rating) avg_rating,
                  SUM(attendance) att
             FROM show WHERE held_on BETWEEN ? AND ?""", (lo, hi)).fetchone()
    if not shows or not shows["n"]:
        return {"season_year": season, "ran": False,
                "headline": f"Nothing was booked in {season}."}

    matches = con.execute(
        """SELECT COUNT(*) n, AVG(m.quality) avg_q
             FROM sim_match m JOIN show s ON s.id=m.show_id
            WHERE s.held_on BETWEEN ? AND ?""", (lo, hi)).fetchone()

    # ---- the best match --------------------------------------------------
    best = con.execute(
        """SELECT m.id, m.quality, m.match_type, m.stipulation, s.name show_name,
                  s.held_on, s.is_ppv
             FROM sim_match m JOIN show s ON s.id=m.show_id
            WHERE s.held_on BETWEEN ? AND ? AND m.quality IS NOT NULL
            ORDER BY m.quality DESC LIMIT 1""", (lo, hi)).fetchone()
    best_match = None
    if best:
        who = [game._wname(con, r["wrestler_id"]) for r in con.execute(
            "SELECT wrestler_id FROM sim_match_participant WHERE match_id=? "
            "ORDER BY team", (best["id"],))]
        best_match = {**dict(best), "stars": sim.stars_from_quality(best["quality"]),
                      "wrestlers": who}

    # ---- the best night --------------------------------------------------
    best_show = con.execute(
        """SELECT id, name, held_on, rating, tv_rating, buyrate, is_ppv, attendance
             FROM show WHERE held_on BETWEEN ? AND ? AND rating IS NOT NULL
            ORDER BY rating DESC LIMIT 1""", (lo, hi)).fetchone()
    biggest_tv = con.execute(
        """SELECT id, name, held_on, tv_rating FROM show
            WHERE held_on BETWEEN ? AND ? AND tv_rating IS NOT NULL
            ORDER BY tv_rating DESC LIMIT 1""", (lo, hi)).fetchone()
    biggest_ppv = con.execute(
        """SELECT id, name, held_on, buyrate FROM show
            WHERE held_on BETWEEN ? AND ? AND buyrate IS NOT NULL
            ORDER BY buyrate DESC LIMIT 1""", (lo, hi)).fetchone()

    # ---- the feud of the year -------------------------------------------
    # Scored on heat AND on how much of it actually happened on screen, so a
    # rivalry nobody booked cannot win it on a heat number alone.
    feud_row = con.execute(
        """SELECT f.id, f.a_id, f.b_id, f.heat, f.kind, f.was_kind,
                  COUNT(b.id) beats,
                  SUM(CASE WHEN b.kind='match' THEN 1 ELSE 0 END) matches
             FROM feud f LEFT JOIN feud_beat b
               ON b.feud_id=f.id AND b.on_date BETWEEN ? AND ?
            GROUP BY f.id
            HAVING beats > 0
            ORDER BY (f.heat * 0.6 + COUNT(b.id) * 6) DESC LIMIT 1""",
        (lo, hi)).fetchone()
    feud = None
    if feud_row:
        arc = storylines.arc(con, feud_row["id"])
        feud = {"id": feud_row["id"], "a_name": arc["a_name"], "b_name": arc["b_name"],
                "heat": feud_row["heat"], "kind": arc["kind"],
                "kind_label": arc["kind_label"], "was_kind": feud_row["was_kind"],
                "beats": feud_row["beats"], "matches": feud_row["matches"] or 0,
                "series": arc["series"]}

    # ---- titles ----------------------------------------------------------
    reigns = _rows(con,
        """SELECT r.title_id, r.wrestler_id, r.won_on, r.lost_on,
                  t.name, t.short_name, t.tier
             FROM game_title_reign r JOIN game_title t ON t.id=r.title_id
            WHERE r.won_on BETWEEN ? AND ?
            ORDER BY t.tier, r.won_on""", (lo, hi))
    for r in reigns:
        r["name_of"] = game._wname(con, r["wrestler_id"])
    champions = _rows(con,
        """SELECT t.name, t.short_name, t.tier, r.wrestler_id, r.won_on
             FROM game_title t
             LEFT JOIN game_title_reign r ON r.title_id=t.id AND r.lost_on IS NULL
            WHERE t.active=1 ORDER BY t.prestige DESC""")
    for c in champions:
        c["name_of"] = game._wname(con, c["wrestler_id"]) if c["wrestler_id"] else None

    # ---- who broke out ---------------------------------------------------
    # Approved rating progression plus Power 10 weeks: she got better AND people
    # noticed. Either alone is a weaker claim.
    risers = _rows(con,
        """SELECT c.wrestler_id, SUM(c.to_value - c.from_value) gained
             FROM rating_change c
            WHERE c.season_year=? AND c.status='approved'
            GROUP BY c.wrestler_id ORDER BY gained DESC LIMIT 5""", (season,))
    top10 = {r["wrestler_id"]: r["n"] for r in con.execute(
        """SELECT e.wrestler_id, COUNT(*) n FROM power_entry e
             JOIN power_issue i ON i.id=e.issue_id
            WHERE i.season_year=? AND e.rank_no<=10
            GROUP BY e.wrestler_id""", (season,))}
    breakout = None
    if risers:
        best_r = max(risers, key=lambda r: (r["gained"] or 0)
                     + top10.get(r["wrestler_id"], 0) * 0.4)
        breakout = {"wrestler_id": best_r["wrestler_id"],
                    "name": game._wname(con, best_r["wrestler_id"]),
                    "gained": best_r["gained"],
                    "weeks_top10": top10.get(best_r["wrestler_id"], 0)}

    # ---- the workhorse ---------------------------------------------------
    workhorse = con.execute(
        """SELECT p.wrestler_id, COUNT(*) n, AVG(m.quality) q
             FROM sim_match_participant p
             JOIN sim_match m ON m.id=p.match_id
             JOIN show s ON s.id=m.show_id
            WHERE s.held_on BETWEEN ? AND ?
            GROUP BY p.wrestler_id ORDER BY n DESC LIMIT 1""", (lo, hi)).fetchone()

    # ---- turns, walkouts, forced moves — the year's upheaval -------------
    turns_done = _rows(con,
        """SELECT wrestler_id, from_align, to_align, trigger, resolved_on
             FROM turn_suggestion WHERE status='approved'
               AND substr(resolved_on,1,4)=? ORDER BY resolved_on""", (str(season),))
    for t in turns_done:
        t["name"] = game._wname(con, t["wrestler_id"])
    forced = _rows(con,
        """SELECT wrestler_id, kind, from_brand, to_brand, on_date, reason
             FROM forced_move WHERE on_date BETWEEN ? AND ? ORDER BY on_date""",
        (lo, hi))
    for f in forced:
        f["name"] = game._wname(con, f["wrestler_id"])

    awards = _rows(con,
        """SELECT kind, wrestler_id, detail FROM award_nomination
            WHERE season_year=? AND status='won'""", (season,))
    for a in awards:
        a["name"] = game._wname(con, a["wrestler_id"]) if a["wrestler_id"] else None
        a["label"] = game.ACCOLADES.get(a["kind"], {}).get("label", a["kind"]) \
            if isinstance(game.ACCOLADES.get(a["kind"]), dict) else a["kind"]

    return {
        "season_year": season, "ran": True,
        "shows": shows["n"], "ppvs": shows["ppvs"] or 0,
        "avg_show_rating": round(shows["avg_rating"], 1) if shows["avg_rating"] else None,
        "attendance": shows["att"] or 0,
        "matches": matches["n"] or 0,
        "avg_match_quality": round(matches["avg_q"], 1) if matches["avg_q"] else None,
        "best_match": best_match,
        "best_show": dict(best_show) if best_show else None,
        "biggest_tv": dict(biggest_tv) if biggest_tv else None,
        "biggest_ppv": dict(biggest_ppv) if biggest_ppv else None,
        "feud_of_the_year": feud,
        "title_changes": reigns,
        "champions": champions,
        "breakout": breakout,
        "workhorse": ({"wrestler_id": workhorse["wrestler_id"],
                       "name": game._wname(con, workhorse["wrestler_id"]),
                       "matches": workhorse["n"],
                       "avg_quality": round(workhorse["q"], 1) if workhorse["q"] else None}
                      if workhorse else None),
        "turns": turns_done,
        "forced_moves": forced,
        "awards": awards,
        "headline": _headline(season, best_match, feud, breakout),
    }


def _headline(season: int, best_match, feud, breakout) -> str:
    """One sentence for the top of the page. Facts, not adjectives."""
    bits = []
    if best_match:
        bits.append(f"{' vs '.join(best_match['wrestlers'][:2])} went "
                    f"{best_match['stars']:g}★")
    if feud:
        bits.append(f"{feud['a_name']}–{feud['b_name']} was the story of the year")
    if breakout:
        bits.append(f"{breakout['name']} broke out")
    return f"{season}: " + ("; ".join(bits) + "." if bits
                            else "a quiet year — nothing much happened.")
