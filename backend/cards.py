"""One card per wrestler per season — the FIFA idea, applied to a GM save.

WHY THEY ARE SNAPSHOTS. Everything on a card could be recomputed from the save
today, but not as it was THEN: ratings move, brands change, a manager stops being
a manager. A card that recomputed itself would stop being a record of 2003 and
become another view of the present, which is the one thing it must not be. So the
row is written once and never touched again.

WHAT MAKES ONE SPECIAL. A plain card is tiered by overall — bronze, silver, gold,
elite — so the colour tells you where she sat before you read a number. On top of
that, a season in which she won a WORLD title or the ROYAL RUMBLE stamps the card,
because those are the two things that actually change a career. That is what makes
a shelf of yearly cards worth having rather than a log with pictures.

Managers get their own two stats (Mic and Influence in place of Wrestling and
Popularity) — see attributes.MANAGER_CATEGORIES. They are resolved BEFORE the row
is written, so an old card never has to know which label set applied back then.
"""

from __future__ import annotations

import sqlite3

import attributes as A
import game

# What stamps a card, in descending order of how much it matters. First match wins,
# so a wrestler who won a world title AND the Rumble is remembered for the title.
SPECIALS = (
    ("world_title", "World champion"),
    ("royal_rumble", "Royal Rumble winner"),
    ("secondary_title", "Champion"),
)


def _season_special(con: sqlite3.Connection, wid: int, season: int) -> str | None:
    """What that season earned her, if anything."""
    yr = str(season)
    tiers = [r[0] for r in con.execute(
        """SELECT t.tier FROM game_title_reign r JOIN game_title t ON t.id = r.title_id
            WHERE r.wrestler_id = ? AND substr(r.won_on, 1, 4) = ?""", (wid, yr))]
    if "world" in tiers:
        return "World champion"
    rumble = con.execute(
        """SELECT 1 FROM accomplishment
            WHERE wrestler_id = ? AND kind = 'royal_rumble' AND season_year = ?""",
        (wid, season)).fetchone()
    if rumble:
        return "Royal Rumble winner"
    if tiers:
        return "Champion"
    return None


def _season_record(con: sqlite3.Connection, wid: int, season: int) -> str | None:
    r = con.execute(
        """SELECT COUNT(*) n,
                  SUM(CASE WHEN m.finish <> 'draw' AND p.is_winner THEN 1 ELSE 0 END) w,
                  SUM(CASE WHEN m.finish = 'draw' THEN 1 ELSE 0 END) d
             FROM sim_match_participant p
             JOIN sim_match m ON m.id = p.match_id
             JOIN show s      ON s.id = m.show_id
            WHERE p.wrestler_id = ? AND substr(s.held_on, 1, 4) = ?""",
        (wid, str(season))).fetchone()
    if not r or not r["n"]:
        return None
    w, d = r["w"] or 0, r["d"] or 0
    return f"{w}-{r['n'] - w - d}-{d}" if d else f"{w}-{r['n'] - w}"


def snapshot(con: sqlite3.Connection, season: int,
             overwrite: bool = False) -> dict:
    """Mint this season's cards for everyone who was under contract.

    ONLY SIGNED WRESTLERS. A card is a record of a season she was actually part
    of; issuing 370 of them every year — most for people who never appeared —
    would make the collection meaningless and the table enormous.

    Idempotent. An existing card for the season is left alone unless `overwrite`,
    because the whole point is that a card does not move after the fact.
    """
    signed = [r[0] for r in con.execute(
        """SELECT DISTINCT wrestler_id FROM contract
            WHERE start_year <= ? AND end_year >= ?""", (season, season))]
    if not signed:
        return {"season": season, "minted": 0, "skipped": 0,
                "note": "nobody was under contract that season"}

    existing = {r[0] for r in con.execute(
        "SELECT wrestler_id FROM rating_card WHERE season_year=?", (season,))}

    brand_of = {r["wrestler_id"]: r["brand_id"] for r in con.execute(
        """SELECT wrestler_id, brand_id FROM contract
            WHERE terminated_on IS NULL AND start_year <= ? AND end_year >= ?""",
        (season, season))}
    style_of = {r["id"]: r["style"] for r in con.execute("SELECT id, style FROM wrestler")}

    ach = game.achievement_inputs(con)
    now = game.now_iso()
    minted = skipped = 0

    for wid in signed:
        if wid in existing and not overwrite:
            skipped += 1
            continue
        eff = game.effective_attributes(con, wid, ach.get(wid))
        role = game.role_of(con, wid)
        # stat_a / stat_b are the two role-dependent slots, resolved now so the
        # stored card never has to know which label set was in force.
        a_key, b_key = A.performance_pair(role)
        stat_a, stat_b = eff[a_key], eff[b_key]
        overall = A.overall(stat_a, eff["achievements"], stat_b,
                            eff["looks"], eff["personal"])
        con.execute(
            """INSERT INTO rating_card
                 (wrestler_id, season_year, role, stat_a, stat_b, achievements,
                  looks, personal, overall, style, brand_id, tier, special,
                  record, created_on)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(wrestler_id, season_year) DO UPDATE SET
                 role=excluded.role, stat_a=excluded.stat_a, stat_b=excluded.stat_b,
                 achievements=excluded.achievements, looks=excluded.looks,
                 personal=excluded.personal, overall=excluded.overall,
                 style=excluded.style, brand_id=excluded.brand_id,
                 tier=excluded.tier, special=excluded.special,
                 record=excluded.record, created_on=excluded.created_on""",
            (wid, season, role, stat_a, stat_b, eff["achievements"], eff["looks"],
             eff["personal"], overall, style_of.get(wid), brand_of.get(wid),
             A.tier_for(overall), _season_special(con, wid, season),
             _season_record(con, wid, season), now))
        minted += 1

    con.commit()
    if minted:
        game.log_event(con, "award",
                       f"{minted} player cards minted for {season}.", None, "🃏")
    return {"season": season, "minted": minted, "skipped": skipped}


def _shape(con: sqlite3.Connection, r: sqlite3.Row) -> dict:
    """One card as the UI wants it: labelled, converted, ready to draw."""
    # Walk the role's category tuple in order rather than hand-listing five
    # entries — the hand-listed version is what printed ACH twice.
    cats = A.categories_for(r["role"])
    stored = {cats[A.PERFORMANCE_SLOTS[0]]: r["stat_a"],
              cats[A.PERFORMANCE_SLOTS[1]]: r["stat_b"],
              "achievements": r["achievements"],
              "looks": r["looks"], "personal": r["personal"]}
    stats = [{"key": k, "label": A.STAT_LABELS[k],
              "v20": stored[k], "v99": A.to99(stored[k])} for k in cats]
    return {
        "wrestler_id": r["wrestler_id"], "season_year": r["season_year"],
        "name": game._wname(con, r["wrestler_id"]),
        "role": r["role"], "overall": r["overall"], "tier": r["tier"],
        "special": r["special"], "style": r["style"], "brand_id": r["brand_id"],
        "record": r["record"], "stats": stats,
    }


def for_wrestler(con: sqlite3.Connection, wid: int) -> list[dict]:
    return [_shape(con, r) for r in con.execute(
        "SELECT * FROM rating_card WHERE wrestler_id=? ORDER BY season_year DESC",
        (wid,))]


def for_season(con: sqlite3.Connection, season: int, limit: int = 60) -> list[dict]:
    return [_shape(con, r) for r in con.execute(
        "SELECT * FROM rating_card WHERE season_year=? ORDER BY overall DESC LIMIT ?",
        (season, limit))]


def seasons_available(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute(
        """SELECT season_year, COUNT(*) cards,
                  SUM(CASE WHEN special IS NOT NULL THEN 1 ELSE 0 END) specials
             FROM rating_card GROUP BY season_year ORDER BY season_year DESC""")]


# How many cards a Team of the Year holds. Not eleven — this is not football, and
# a wrestling roster's shape is different: a handful of headliners, a manager, and
# the champion whether or not she out-rates them.
TOTY_WRESTLERS = 6
TOTY_MANAGERS = 1


def team_of_season(con: sqlite3.Connection, season: int) -> dict:
    """The season's best cards, as a set rather than a leaderboard.

    Picked on overall, but with two deliberate overrides, because a pure top-six
    tells you nothing you could not get by sorting:

      the champion is always in it, even if her overall is not top six. Holding
      the world title IS the season, and a set that omits the champion is wrong
      about what happened.

      a manager gets her own slot rather than competing on a scale she is not on.
      Managers are scored on Mic and Influence, so ranking them against wrestlers
      by overall compares two different measurements.
    """
    rows = [_shape(con, r) for r in con.execute(
        "SELECT * FROM rating_card WHERE season_year=? ORDER BY overall DESC",
        (season,))]
    if not rows:
        return {"season": season, "wrestlers": [], "managers": [],
                "champions": [], "note": "no cards minted for that season"}

    wrestlers = [c for c in rows if c["role"] != "manager"]
    managers = [c for c in rows if c["role"] == "manager"]

    champs = [c for c in wrestlers if c["special"] == "World champion"]
    picked = list(champs[:TOTY_WRESTLERS])
    for c in wrestlers:
        if len(picked) >= TOTY_WRESTLERS:
            break
        if c not in picked:
            picked.append(c)
    picked.sort(key=lambda c: -c["overall"])

    return {
        "season": season,
        "wrestlers": picked,
        "managers": managers[:TOTY_MANAGERS],
        "champions": [c["name"] for c in champs],
    }


def best_ever(con: sqlite3.Connection, limit: int = 40) -> list[dict]:
    """Each wrestler's HIGHEST card, ranked — the all-time set.

    One card per wrestler, not one row per season, which is the point: a ten-year
    career should appear once, at its peak, rather than filling the list with ten
    versions of the same person.
    """
    return [_shape(con, r) for r in con.execute(
        """SELECT c.* FROM rating_card c
            JOIN (SELECT wrestler_id, MAX(overall) AS best
                    FROM rating_card GROUP BY wrestler_id) m
              ON m.wrestler_id = c.wrestler_id AND m.best = c.overall
           GROUP BY c.wrestler_id
           ORDER BY c.overall DESC, c.season_year
           LIMIT ?""", (limit,))]


def progression(con: sqlite3.Connection, wid: int) -> list[dict]:
    """Her overall and five stats by season — the series behind the graph.

    Comes straight off the minted cards, so the chart cannot disagree with the
    cards: it IS the cards, read as a line instead of a shelf.
    """
    out = []
    for r in con.execute(
            "SELECT * FROM rating_card WHERE wrestler_id=? ORDER BY season_year",
            (wid,)):
        c = _shape(con, r)
        out.append({"season_year": c["season_year"], "overall": c["overall"],
                    "tier": c["tier"], "special": c["special"],
                    "record": c["record"],
                    "stats": {st["key"]: st["v20"] for st in c["stats"]}})
    return out


def live_card(con: sqlite3.Connection, wid: int) -> dict:
    """Her card AS OF RIGHT NOW — not stored, just shaped the same way.

    The wrestler panel wants a card for the current season, which has not been
    minted yet because the season has not ended. Building it on the fly keeps the
    panel honest without writing a row that would then be frozen too early.
    """
    st = con.execute("SELECT season_year FROM game_state WHERE id=1").fetchone()
    season = st["season_year"] if st else A.RESET_YEAR
    eff = game.effective_attributes(con, wid)
    role = game.role_of(con, wid)
    a_key, b_key = A.performance_pair(role)
    stat_a, stat_b = eff[a_key], eff[b_key]
    overall = A.overall(stat_a, eff["achievements"], stat_b, eff["looks"],
                        eff["personal"])
    brand = con.execute(
        """SELECT brand_id FROM contract WHERE wrestler_id=? AND terminated_on IS NULL
            AND start_year<=? AND end_year>=?""", (wid, season, season)).fetchone()
    style = con.execute("SELECT style FROM wrestler WHERE id=?", (wid,)).fetchone()
    row = {
        "wrestler_id": wid, "season_year": season, "role": role,
        "stat_a": stat_a, "stat_b": stat_b, "achievements": eff["achievements"],
        "looks": eff["looks"], "personal": eff["personal"], "overall": overall,
        "style": style["style"] if style else None,
        "brand_id": brand["brand_id"] if brand else None,
        "tier": A.tier_for(overall), "special": _season_special(con, wid, season),
        "record": _season_record(con, wid, season),
    }
    return {**_shape(con, row), "live": True}
