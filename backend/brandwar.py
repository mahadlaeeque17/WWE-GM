"""The scoreboard: television ratings, pay-per-view buys, and who is winning.

WHAT WAS MISSING. The save had money, titles and a power ranking, but nothing
that said "Raw beat SmackDown this week". Money is a constraint rather than a
score — you can bank a fortune running a terrible show in a small building — and
without a head-to-head number there is no answer to the only question a GM
actually has, which is whether the way she books is working.

So every television show now draws a RATING, every pay-per-view sells a
BUYRATE, and when both brands run in the same week the higher rating wins the
week. Weeks won across a season is the standings table.

HOW A RATING IS BUILT, and why in this order:

    fanbase       the audience you already have. The floor, and the slowest
                  thing to move — which is what makes it feel like a franchise.
    show quality  what you put on. The fastest thing to move, so booking well
                  shows up immediately.
    star power    who was on it. A card of nobodies rates badly however good the
                  matches were, which is the lesson the number exists to teach.
    storylines    heat going into the show. A hot rivalry is a reason to tune in.
    momentum      last week's rating. Audiences arrive and leave gradually, so a
                  rating is anchored to the one before it and a single great
                  show cannot triple your audience.

Deterministic like everything else: no dice, so the same booking always draws
the same number and a rating can be reasoned about.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import booking
import game

# A rating point, in the shape people recognise from the era. The scale is
# arbitrary but anchored: a fanbase at the default with a middling show lands
# near 3.0, a great show with stars on it pushes past 5, and a genuinely bad
# night dips under 2.
RATING_BASE = 1.15
FANBASE_PIVOT = 800_000          # booking.FANBASE_DEFAULT — the "normal" audience
FANBASE_WEIGHT = 1.45            # rating points at the pivot
QUALITY_WEIGHT = 0.042           # per point of show rating
STAR_WEIGHT = 0.055              # per point of average popularity on the card
HEAT_WEIGHT = 0.010              # per point of the hottest rivalry on the show
MOMENTUM_PULL = 0.34             # how much last week's rating anchors this one

VIEWERS_PER_POINT = 1_020_000    # rating → households, for a readable big number

# A pay-per-view is bought, not tuned into: quality and stars matter more, and
# the buyrate is expressed per thousand homes the way the industry did.
BUY_BASE = 0.18
BUY_QUALITY = 0.0075
BUY_STAR = 0.011
BUY_HEAT = 0.0028
BUY_FANBASE = 0.30


def _week_of(held_on: str) -> str:
    """The Monday of the show's calendar week. Kept for display only.

    NOT used as the head-to-head bucket — see _week_key for why it cannot be.
    """
    d = date.fromisoformat(held_on)
    return (d - timedelta(days=d.weekday())).isoformat()


def _week_key(con: sqlite3.Connection, brand_id: str, show_id: int, season: int) -> str:
    """The bucket a show is compared in: its ORDINAL among the brand's TV weeks.

    WHY NOT THE CALENDAR. The save's clock advances a month at a time, so every
    television show run inside one month carries the same `held_on`. Bucketing by
    calendar week therefore put a whole month of shows in one bucket, where they
    overwrote each other on the `(week_of, brand_id)` key — four weeks of
    television collapsing into one row, and the rating momentum anchor never
    finding a previous show to anchor to.

    So a "week" here is Raw's Nth show measured against SmackDown's Nth show.
    Given the date model that is the truthful comparison, and it makes a week
    contested exactly when both brands have actually run that many shows.
    """
    n = con.execute(
        """SELECT COUNT(*) FROM show
            WHERE brand_id=? AND is_ppv=0 AND id<=?
              AND substr(held_on,1,4)=?""",
        (brand_id, show_id, str(season))).fetchone()[0]
    return f"{season}-W{max(1, n):02d}"


def _card_star_power(con: sqlite3.Connection, show_id: int) -> float:
    """Average popularity across everyone who appeared, match or promo."""
    ids = {r[0] for r in con.execute(
        """SELECT p.wrestler_id FROM sim_match_participant p
             JOIN sim_match m ON m.id=p.match_id WHERE m.show_id=?""", (show_id,))}
    ids |= {r[0] for r in con.execute(
        """SELECT pp.wrestler_id FROM sim_promo_participant pp
             JOIN sim_promo pr ON pr.id=pp.promo_id WHERE pr.show_id=?""", (show_id,))}
    if not ids:
        return 0.0
    ach = game.achievement_inputs(con)
    tot = 0.0
    for wid in ids:
        try:
            tot += game.effective_attributes(con, wid, ach.get(wid))["popularity"]
        except ValueError:
            continue
    return tot / len(ids)


def _hottest_heat(con: sqlite3.Connection, show_id: int) -> int:
    """The hottest rivalry with a stake in this show."""
    ids = {r[0] for r in con.execute(
        """SELECT p.wrestler_id FROM sim_match_participant p
             JOIN sim_match m ON m.id=p.match_id WHERE m.show_id=?""", (show_id,))}
    ids |= {r[0] for r in con.execute(
        """SELECT pp.wrestler_id FROM sim_promo_participant pp
             JOIN sim_promo pr ON pr.id=pp.promo_id WHERE pr.show_id=?""", (show_id,))}
    if not ids:
        return 0
    best = 0
    for f in con.execute("SELECT a_id, b_id, heat FROM feud WHERE status='active'"):
        if f["a_id"] in ids or f["b_id"] in ids:
            best = max(best, f["heat"])
    return best


def _last_rating(con: sqlite3.Connection, brand_id: str, show_id: int) -> float | None:
    """The brand's PREVIOUS television rating, by show order rather than by date.

    Ordering by `held_on` alone cannot work: the clock moves monthly, so the
    show before this one usually carries the SAME date and a `held_on <` filter
    finds nothing. Show id is the only strictly increasing thing available.
    """
    r = con.execute(
        """SELECT tv_rating FROM show
            WHERE brand_id=? AND is_ppv=0 AND tv_rating IS NOT NULL AND id < ?
            ORDER BY id DESC LIMIT 1""", (brand_id, show_id)).fetchone()
    return r["tv_rating"] if r else None


def rate_show(con: sqlite3.Connection, show_id: int) -> dict:
    """Score one show and persist it. Returns the rating and its ingredients.

    Called at the end of `sim.run_show`, so no show can exist without a number
    attached to it.
    """
    s = con.execute("SELECT * FROM show WHERE id=?", (show_id,)).fetchone()
    if not s:
        raise game.SigningError("no such show")
    quality = s["rating"] or 0.0
    stars = _card_star_power(con, show_id)
    heat = _hottest_heat(con, show_id)
    fb = booking.fanbase(con, s["brand_id"]) if s["brand_id"] else FANBASE_PIVOT

    fan_term = FANBASE_WEIGHT * (fb / FANBASE_PIVOT) ** 0.62

    if s["is_ppv"]:
        buy = (BUY_BASE + BUY_QUALITY * quality + BUY_STAR * stars
               + BUY_HEAT * heat + BUY_FANBASE * (fb / FANBASE_PIVOT) ** 0.5)
        buy = max(0.05, round(buy, 2))
        con.execute("UPDATE show SET buyrate=? WHERE id=?", (buy, show_id))
        con.commit()
        return {"show_id": show_id, "is_ppv": True, "buyrate": buy,
                "buys": int(buy * VIEWERS_PER_POINT),
                "quality": quality, "stars": round(stars, 1), "heat": heat}

    raw = (RATING_BASE + fan_term + QUALITY_WEIGHT * quality
           + STAR_WEIGHT * stars + HEAT_WEIGHT * heat)
    prev = _last_rating(con, s["brand_id"], show_id)
    if prev is not None:
        # An audience does not appear or vanish overnight. Anchoring to last week
        # is what stops one great show from tripling the number and makes a
        # sustained run of good booking the thing that actually moves it.
        raw = raw * (1 - MOMENTUM_PULL) + prev * MOMENTUM_PULL
    rating = max(0.4, round(raw, 2))
    viewers = int(rating * VIEWERS_PER_POINT)
    con.execute("UPDATE show SET tv_rating=? WHERE id=?", (rating, show_id))
    con.execute(
        """INSERT INTO brand_week (week_of, season_year, brand_id, show_id, tv_rating, viewers)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(week_of, brand_id) DO UPDATE SET
             show_id=excluded.show_id, tv_rating=excluded.tv_rating,
             viewers=excluded.viewers""",
        (_week_key(con, s["brand_id"], show_id, int(s["held_on"][:4])),
         int(s["held_on"][:4]), s["brand_id"], show_id, rating, viewers))
    con.commit()
    return {"show_id": show_id, "is_ppv": False, "tv_rating": rating, "viewers": viewers,
            "quality": quality, "stars": round(stars, 1), "heat": heat,
            "previous": prev}


def week_result(con: sqlite3.Connection, week_of: str) -> dict:
    """Who won one week of television.

    A week with only one brand on it is NOT a win — you cannot beat somebody who
    did not turn up, and counting it would reward not booking the other brand.
    """
    rows = [dict(r) for r in con.execute(
        """SELECT bw.*, b.name, b.colour FROM brand_week bw
             LEFT JOIN brand b ON b.id=bw.brand_id
            WHERE bw.week_of=? ORDER BY bw.tv_rating DESC""", (week_of,))]
    contested = len(rows) >= 2
    winner = rows[0]["brand_id"] if contested and rows[0]["tv_rating"] > rows[1]["tv_rating"] else None
    tied = contested and rows[0]["tv_rating"] == rows[1]["tv_rating"]
    return {"week_of": week_of, "brands": rows, "contested": contested,
            "winner": winner, "tied": tied,
            "margin": round(rows[0]["tv_rating"] - rows[1]["tv_rating"], 2)
            if contested else None}


def weeks(con: sqlite3.Connection, season: int | None = None) -> list[dict]:
    st = con.execute("SELECT season_year FROM game_state WHERE id=1").fetchone()
    season = season or (st["season_year"] if st else None)
    # Zero-padded keys (2000-W03) sort correctly as text, which is why the
    # padding in _week_key is not cosmetic.
    ws = [r["week_of"] for r in con.execute(
        "SELECT DISTINCT week_of FROM brand_week WHERE season_year=? ORDER BY week_of DESC",
        (season,))]
    return [week_result(con, w) for w in ws]


def standings(con: sqlite3.Connection, season: int | None = None) -> dict:
    """The season table: weeks won, average rating, best night, PPV buys.

    This is the answer to "is the way I book working", which is the question the
    whole module exists for.
    """
    st = con.execute("SELECT season_year FROM game_state WHERE id=1").fetchone()
    season = season or (st["season_year"] if st else None)
    ws = weeks(con, season)

    table = {}
    for b, name, colour in game.BRANDS:
        # Counts and averages come from brand_week (the head-to-head buckets),
        # but the BEST rating is read from `show` alongside best_show below —
        # reading the peak from one table and the show that produced it from
        # another let the number and the name disagree.
        agg = con.execute(
            """SELECT COUNT(*) n, AVG(tv_rating) avg
                 FROM brand_week WHERE season_year=? AND brand_id=?""",
            (season, b)).fetchone()
        ppv = con.execute(
            """SELECT COUNT(*) n, AVG(buyrate) avg, MAX(buyrate) best
                 FROM show WHERE is_ppv=1 AND buyrate IS NOT NULL
                   AND brand_id=? AND substr(held_on,1,4)=?""",
            (b, str(season))).fetchone()
        best_show = con.execute(
            """SELECT id, name, held_on, tv_rating FROM show
                WHERE brand_id=? AND tv_rating IS NOT NULL AND substr(held_on,1,4)=?
                ORDER BY tv_rating DESC LIMIT 1""", (b, str(season))).fetchone()
        table[b] = {
            "brand_id": b, "name": name, "colour": colour,
            "shows": agg["n"] or 0,
            "avg_rating": round(agg["avg"], 2) if agg["avg"] is not None else None,
            "best_rating": round(best_show["tv_rating"], 2) if best_show else None,
            "weeks_won": sum(1 for w in ws if w["winner"] == b),
            "weeks_contested": sum(1 for w in ws if w["contested"]),
            "ppv_count": ppv["n"] or 0,
            "avg_buyrate": round(ppv["avg"], 2) if ppv["avg"] is not None else None,
            "best_show": dict(best_show) if best_show else None,
            "fanbase": booking.fanbase(con, b),
        }
    ties = sum(1 for w in ws if w["tied"])
    lead = sorted(table.values(), key=lambda t: (-t["weeks_won"],
                                                 -(t["avg_rating"] or 0)))
    leader = lead[0] if lead and lead[0]["weeks_won"] > (lead[1]["weeks_won"] if len(lead) > 1 else 0) else None
    return {"season_year": season, "brands": list(table.values()),
            "weeks": ws[:16], "ties": ties,
            "leader": leader["brand_id"] if leader else None,
            "summary": _summary(lead, ties)}


def _summary(lead: list[dict], ties: int) -> str:
    """One line for the top of the screen. Plain English, no jargon."""
    if not lead or not lead[0]["shows"]:
        return "No television has aired yet this season."
    a = lead[0]
    b = lead[1] if len(lead) > 1 else None
    if not b or not b["shows"]:
        return f"{a['name']} is the only brand on the air, averaging {a['avg_rating']}."
    if a["weeks_won"] == b["weeks_won"]:
        return (f"Dead level at {a['weeks_won']}–{b['weeks_won']}"
                + (f" with {ties} tied week{'s' if ties != 1 else ''}." if ties else "."))
    return (f"{a['name']} leads the war {a['weeks_won']}–{b['weeks_won']}, "
            f"averaging {a['avg_rating']} against {b['avg_rating']}.")
