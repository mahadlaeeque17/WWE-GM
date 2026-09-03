"""The pre-booked card — what the creative team hands the GM before she edits it.

THE POINT. Staring at four empty match rows and two empty promo slots is work,
not a game. So every show arrives already booked to a defensible card, and the
GM's job is the interesting half: deciding what is wrong with it. Nothing here
writes anything — it returns a suggestion, the booking screen renders it, and the
GM changes whatever she likes before confirming.

HOW IT DECIDES, in priority order:

  1. RIVALRIES FIRST. An active feud is a story already in progress and the
     single best reason to put two women in a ring. Hottest feuds get the best
     slots, and a feud at blow-off heat gets a stipulation to match — that is
     the payoff the heat was built for.
  2. TITLES. A belt goes on the main event when there is a credible challenger,
     taken from the contender ladder the rankings module already publishes so
     the booker and the on-screen ladder never disagree.
  3. FACE VS HEEL. Good against evil sells; the sim already rewards it, so the
     booker reaches for it rather than fighting its own engine.
  4. POPULARITY LATE. The card is ordered so star power climbs — the opener is
     the lowest-wattage match on the show and the main event is the biggest.
  5. STAMINA. Anyone worn down is passed over for a fresher body, because
     working a tired roster is how you get injuries.
  6. SHAPE VARIETY. Real tag teams get tag matches, factions get six-woman
     tags, and spare bodies with no story get folded into a triple threat or a
     fatal 4-way instead of a filler singles nobody asked for.

The two promo slots go to the stories that need building rather than the ones
already booked in a match, and the TYPE is chosen from how hot the feud is: a
callout early in a build, a contract signing before the blow-off, a run-in when
somebody needs to look dangerous.
"""
from __future__ import annotations

import random
import sqlite3

import game
import matches as MT
import medical
import promos as PR
import storylines

# A show's shape. This is the format the game is played in — four matches and two
# promos on television, six matches split evenly between the brands on a
# pay-per-view. The GM can add or drop segments; these are what she starts with.
SHOW_FORMATS: dict[str, dict] = {
    "tv": {
        "label": "Television", "matches": 4, "promos": 2, "brands": 1,
        "desc": "Four matches and two promo segments.",
    },
    "snme": {
        "label": "Saturday Night's Main Event", "matches": 4, "promos": 2, "brands": 1,
        "desc": "Four matches and two promo segments — a bigger building than a TV week.",
    },
    "ppv": {
        "label": "Pay-Per-View", "matches": 6, "promos": 2, "brands": 2,
        "per_brand": 3,
        "desc": "Six matches, three from each brand, and two promo segments.",
    },
}

# Once a feud is this hot, the match it produces should feel final — so it gets a
# gimmick. Picked by heat so a hotter feud gets a bigger gimmick.
BLOWOFF_STIPS = ["steel_cage", "last_standing", "hardcore", "extreme", "tlc"]
MID_STIPS = ["no_dq", "submission", "tables"]

FRESH_FATIGUE = 55         # above this she is tired and gets passed over
TIRED_FATIGUE = 80         # above this she is only used if there is nobody else


# ---------------------------------------------------------------- the roster

def _pool(con: sqlite3.Connection, brand_id: str) -> list[dict]:
    """Everyone this brand can actually put on a card tonight.

    Managers are excluded — they are not in matches. Injured and unsigned are
    excluded. Everyone else comes back with the numbers the booker sorts on.
    """
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if st is None:
        raise ValueError("no active save — start a new game first")
    season, today = st["season_year"], st["current_date"]
    ach = game.achievement_inputs(con)
    out = []
    for r in con.execute(
        """SELECT w.id, COALESCE(o.display_name, w.name) name, w.style,
                  COALESCE(s.momentum,50) momentum, COALESCE(s.morale,50) morale,
                  COALESCE(s.fatigue,0) fatigue, s.injured_until,
                  s.rested_until, c.role
             FROM contract c
             JOIN wrestler w ON w.id=c.wrestler_id
             LEFT JOIN attribute_override o ON o.wrestler_id=w.id
             LEFT JOIN wrestler_state s ON s.wrestler_id=w.id
            WHERE c.brand_id=? AND c.terminated_on IS NULL
              AND c.start_year<=? AND c.end_year>=?""",
        (brand_id, season, season),
    ):
        if r["role"] == "manager":
            continue
        if r["injured_until"] and r["injured_until"] > today:
            continue
        # Time off the GM granted is time off. Booking through it would make the
        # grant meaningless and is exactly what she asked you not to do.
        if r["rested_until"] and r["rested_until"] > today:
            continue
        eff = game.effective_attributes(con, r["id"], ach.get(r["id"]))
        out.append({
            "id": r["id"], "name": r["name"], "brand_id": brand_id,
            "overall": eff["overall"], "popularity": eff["popularity"],
            "alignment": eff.get("alignment") or "face",
            "fatigue": r["fatigue"], "momentum": r["momentum"],
            "style": r["style"],
            "risk": medical.risk(con, r["id"], today)["level"],
        })
    return out


def _star_power(w: dict) -> float:
    """How big a deal she is tonight. Drives where on the card she goes.

    Popularity leads because the card is ordered by who the crowd came to see,
    not by who is technically best. Momentum counts (she is hot right now) and
    fatigue is a straight subtraction — a worn-out headliner is a worse main
    event than a fresh one.
    """
    return (w["popularity"] * 2.6 + w["overall"] * 0.5
            + (w["momentum"] - 50) * 0.10 - w["fatigue"] * 0.12)


def _usable(w: dict, desperate: bool = False) -> bool:
    return w["fatigue"] <= (TIRED_FATIGUE if desperate else FRESH_FATIGUE)


# ---------------------------------------------------------------- ingredients

def _feuds_for(con: sqlite3.Connection, ids: set[int]) -> list[dict]:
    """Active rivalries where BOTH women are available tonight, hottest first."""
    out = []
    for f in game.list_feuds(con, "active"):
        if f["a_id"] in ids and f["b_id"] in ids:
            out.append(f)
    return sorted(out, key=lambda f: -f["heat"])


def _teams_for(con: sqlite3.Connection, ids: set[int]) -> list[dict]:
    """Tag teams whose whole roster is available — a real 2 v 2 rather than two
    singles wrestlers stapled together."""
    st = game.list_stables(con)
    out = []
    for t in st["tag_teams"]:
        mem = [m["wrestler_id"] for m in t["members"]]
        if len(mem) >= 2 and all(m in ids for m in mem):
            out.append({"name": t["name"], "members": mem[:2], "id": t["id"]})
    return out


def _factions_for(con: sqlite3.Connection, ids: set[int]) -> list[dict]:
    out = []
    for f in game.list_stables(con)["factions"]:
        mem = [m["wrestler_id"] for m in f["members"] if m["wrestler_id"] in ids]
        if len(mem) >= 3:
            out.append({"name": f["name"], "members": mem[:3], "id": f["id"]})
    return out


def _champion(con: sqlite3.Connection, title_id: int) -> int | None:
    r = con.execute("SELECT wrestler_id FROM game_title_reign "
                    "WHERE title_id=? AND lost_on IS NULL", (title_id,)).fetchone()
    return r["wrestler_id"] if r else None


def _titles_for(con: sqlite3.Connection, brand_id: str) -> list[dict]:
    game.ensure_titles(con)
    return [dict(t) for t in con.execute(
        "SELECT id, name, short_name, tier, prestige, team_size FROM game_title "
        "WHERE active=1 AND (brand_id=? OR brand_id IS NULL) AND tier<>'manager' "
        "ORDER BY prestige DESC", (brand_id,))]


def _challenger(con: sqlite3.Connection, title_id: int, champ: int | None,
                pool: dict[int, dict]) -> int | None:
    """Who has earned the shot. The contender ladder first, then star power.

    Reading the published ladder matters: the GM can see that ladder on the
    Contenders screen, and a booker that ignored it would be proposing title
    matches the game itself says are unearned.
    """
    try:
        import rankings
        for r in rankings.ladder_for(con, title_id):
            wid = r.get("wrestler_id")
            if wid and wid != champ and wid in pool:
                return wid
    except Exception:                                        # noqa: BLE001
        pass
    cands = [w for w in pool.values() if w["id"] != champ and _usable(w)]
    if not cands:
        return None
    return max(cands, key=_star_power)["id"]


def _stipulation_for(heat: int, rng: random.Random) -> str:
    """A gimmick sized to the feud. Cold feuds stay clean — a steel cage in week
    one of a build spends the payoff before it is earned."""
    if heat >= game.FEUD_BLOWOFF_HEAT:
        return rng.choice(BLOWOFF_STIPS[:3] if heat < 85 else BLOWOFF_STIPS)
    if heat >= 50:
        return rng.choice(MID_STIPS)
    return "normal"


def _pick_opponent(target: dict, pool: list[dict], used: set[int]) -> dict | None:
    """The best available opponent: opposite alignment, closest in level.

    Alignment is weighted heavily because the sim rewards it and because a card
    of heel-vs-heel matches has no stories on it. Level closeness stops the
    booker pairing a headliner with an enhancement talent for no reason.
    """
    best, best_score = None, -1e9
    for w in pool:
        if w["id"] in used or w["id"] == target["id"] or not _usable(w):
            continue
        s = 0.0
        s += 22.0 if w["alignment"] != target["alignment"] else -14.0
        s -= abs(w["overall"] - target["overall"]) * 0.55
        s += w["popularity"] * 0.5
        s -= w["fatigue"] * 0.10
        if s > best_score:
            best, best_score = w, s
    return best


# ---------------------------------------------------------------- the card

def suggest(con: sqlite3.Connection, brand_id: str, kind: str = "tv",
            other_brand: str | None = None) -> dict:
    """A full pre-booked card: matches, promos, and why each one is there.

    Returns {"format", "matches": [...], "promos": [...], "notes": [...]}. Every
    match carries `match_type`, `teams`, `title_id`, `stipulation` and a `why` —
    the same shape POST /api/sim/show accepts, so the GM can confirm it
    untouched or edit any row first.
    """
    fmt = SHOW_FORMATS.get(kind, SHOW_FORMATS["tv"])
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    if st is None:
        raise ValueError("no active save — start a new game first")
    rng = random.Random(st["rng_seed"] * 31 + hash(brand_id) % 9973
                        + int(st["current_date"].replace("-", "")))

    if fmt["brands"] == 2:
        brands = [brand_id, other_brand or _other_brand(brand_id)]
    else:
        brands = [brand_id]

    per_brand = fmt.get("per_brand", fmt["matches"])
    all_matches: list[dict] = []
    all_pool: dict[int, dict] = {}
    notes: list[str] = []
    # The tag, cruiserweight and hardcore belts are SHARED (brand_id NULL), so
    # both halves of a co-branded card would each happily book them and the same
    # championship would be defended twice on one show. One set, spanning brands.
    spent_titles: set[int] = set()

    for b in brands:
        pool = _pool(con, b)
        for w in pool:
            all_pool[w["id"]] = w
        n = per_brand if fmt["brands"] == 2 else fmt["matches"]
        ms, why = _brand_card(con, b, pool, n, rng, big=kind != "tv",
                              spent_titles=spent_titles)
        all_matches.extend(ms)
        notes.extend(why)

    # Order the whole show so star power climbs to the main event. A title match
    # or a blow-off outranks raw popularity — those are the reasons a match
    # closes a show even when a bigger name is on it earlier.
    def weight(m: dict) -> float:
        s = sum(_star_power(all_pool[w]) for t in m["teams"] for w in t if w in all_pool)
        s /= max(1, sum(len(t) for t in m["teams"]))
        if m.get("title_id"):
            s += 40
        s += m.get("_heat", 0) * 0.6
        return s

    all_matches.sort(key=weight)
    for i, m in enumerate(all_matches, start=1):
        m["slot"] = i
        m.pop("_heat", None)

    booked = {w for m in all_matches for t in m["teams"] for w in t}
    promo_list = _promo_card(con, brands, all_pool, booked, fmt["promos"], rng)

    return {
        "format": kind, "format_label": fmt["label"],
        "brands": brands,
        "matches": all_matches, "promos": promo_list,
        "notes": notes,
        "wanted": {"matches": fmt["matches"], "promos": fmt["promos"]},
    }


def _other_brand(brand_id: str) -> str:
    ids = [b[0] for b in game.BRANDS]
    for i in ids:
        if i != brand_id:
            return i
    return brand_id


def _brand_card(con: sqlite3.Connection, brand_id: str, pool: list[dict], want: int,
                rng: random.Random, big: bool = False,
                spent_titles: set[int] | None = None) -> tuple[list[dict], list[str]]:
    """`want` matches out of one brand's roster, rivalries first.

    `spent_titles` is shared across both halves of a co-branded card so a belt
    both brands can defend is not defended twice on the same night.
    """
    if spent_titles is None:
        spent_titles = set()
    if len(pool) < 2:
        return [], [f"{brand_id} has fewer than two healthy wrestlers — nothing to book."]

    by_id = {w["id"]: w for w in pool}
    ids = set(by_id)
    used: set[int] = set()
    out: list[dict] = []
    notes: list[str] = []
    protected_feuds: list[dict] = []
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    today = st["current_date"] if st else ""

    def take(wids: list[int]) -> None:
        used.update(wids)

    # ---- 1. rivalries ----------------------------------------------------
    #
    # A feud the GM has pointed at a pay-per-view is PROTECTED: the singles match
    # is deliberately withheld until the date. Anyone can book the blow-off
    # tonight — the skill is not booking it tonight, and a booker that always
    # reached for the hottest pairing made that skill impossible to express.
    for f in _feuds_for(con, ids):
        if len(out) >= want:
            break
        a, b = f["a_id"], f["b_id"]
        if a in used or b in used:
            continue
        if storylines.is_protected(con, f["id"], today):
            protected_feuds.append(f)
            continue
        stip = _stipulation_for(f["heat"], rng)
        out.append({"match_type": "singles", "teams": [[a], [b]], "title_id": None,
                    "stipulation": stip, "_heat": f["heat"], "_feud_id": f["id"],
                    "why": (f"Blow-off — {by_id[a]['name']} and {by_id[b]['name']} are at "
                            f"{f['heat']} heat" if f["heat"] >= game.FEUD_BLOWOFF_HEAT
                            else f"Rivalry — {f['heat']} heat and building")})
        take([a, b])
        notes.append(f"{by_id[a]['name']} vs {by_id[b]['name']} — the hottest story on "
                     f"{brand_id} ({f['heat']} heat).")

    # A protected pairing still needs to be ON the show — on OPPOSITE sides of a
    # tag match, which keeps them in contact without settling anything. This is
    # the single most useful thing the arc system does for the card.
    for f in protected_feuds:
        if len(out) >= want:
            break
        a, b = f["a_id"], f["b_id"]
        if a in used or b in used:
            continue
        spare_now = [w for w in pool if w["id"] not in used
                     and w["id"] not in (a, b) and _usable(w)]
        if len(spare_now) < 2:
            continue
        spare_now.sort(key=_star_power, reverse=True)
        p1, p2 = spare_now[0], spare_now[1]
        label = f.get("blowoff_label") or f.get("planned_blowoff")
        out.append({"match_type": "tag", "teams": [[a, p1["id"]], [b, p2["id"]]],
                    "title_id": None, "stipulation": "normal",
                    "_heat": f["heat"] * 0.5, "_feud_id": f["id"],
                    "why": f"Tag match — keeps {by_id[a]['name']} and {by_id[b]['name']} "
                           f"apart until {label}"})
        take([a, b, p1["id"], p2["id"]])
        notes.append(f"{by_id[a]['name']} and {by_id[b]['name']} are being built to "
                     f"{label} — tagged instead of matched, so the blow-off is not "
                     f"given away.")

    # ---- 2. a title on the biggest remaining match -----------------------
    for t in _titles_for(con, brand_id):
        if len(out) >= want:
            break
        if t["id"] in spent_titles:
            continue
        champ = _champion(con, t["id"])
        size = t["team_size"] or 1
        if size >= 2:
            teams = _teams_for(con, ids - used)
            if len(teams) >= 2:
                x, y = teams[0], teams[1]
                out.append({"match_type": "tag", "teams": [x["members"], y["members"]],
                            "title_id": t["id"], "stipulation": "normal", "_heat": 20,
                            "why": f"{t['short_name'] or t['name']} — {x['name']} defend "
                                   f"against {y['name']}"})
                take(x["members"] + y["members"])
                spent_titles.add(t["id"])
                notes.append(f"{t['short_name'] or t['name']} on the line between two real "
                             f"teams.")
            continue
        free = {k: v for k, v in by_id.items() if k not in used}
        # A VACANT belt is booked to be WON, not defended. Without this branch a
        # fresh save never books a title match, so no champion ever emerges and
        # no belt is ever defended — the whole title loop stays dead in year one.
        if champ is None or champ in used or champ not in by_id:
            a = _challenger(con, t["id"], None, free)
            if not a:
                continue
            b = _challenger(con, t["id"], a, {k: v for k, v in free.items() if k != a})
            if not b:
                continue
            if not all(game.title_eligible(con, t["id"], w)[0] for w in (a, b)):
                continue
            out.append({"match_type": "singles", "teams": [[a], [b]],
                        "title_id": t["id"], "stipulation": "normal", "_heat": 30,
                        "why": f"{t['short_name'] or t['name']} is VACANT — "
                               f"this decides it"})
            take([a, b])
            spent_titles.add(t["id"])
            notes.append(f"The {t['short_name'] or t['name']} is vacant. "
                         f"{by_id[a]['name']} and {by_id[b]['name']} settle it.")
            continue
        chal = _challenger(con, t["id"], champ, free)
        if not chal:
            continue
        ok, _ = game.title_eligible(con, t["id"], chal)
        if not ok:
            continue
        out.append({"match_type": "singles", "teams": [[champ], [chal]],
                    "title_id": t["id"], "stipulation": "normal", "_heat": 25,
                    "why": f"{t['short_name'] or t['name']} — {by_id[champ]['name']} "
                           f"defends against the #1 contender"})
        take([champ, chal])
        spent_titles.add(t["id"])
        notes.append(f"{by_id[chal]['name']} has earned the {t['short_name'] or t['name']} "
                     f"shot.")

    # ---- 3. a multi-woman match for the bodies with no story ------------
    spare = [w for w in pool if w["id"] not in used and _usable(w)]
    spare.sort(key=_star_power, reverse=True)
    if len(out) < want and len(spare) >= 4 and (big or rng.random() < 0.6):
        four = spare[:4]
        out.append({"match_type": "fatal_four_way",
                    "teams": [[w["id"]] for w in four], "title_id": None,
                    "stipulation": "normal", "_heat": 10,
                    "why": "Fatal 4-Way — four women with no story, one winner who gets one"})
        take([w["id"] for w in four])
        notes.append("A Fatal 4-Way sorts out four women who have nothing going on.")
        spare = [w for w in spare if w["id"] not in used]
    elif len(out) < want and len(spare) >= 3 and rng.random() < 0.5:
        three = spare[:3]
        out.append({"match_type": "triple_threat",
                    "teams": [[w["id"]] for w in three], "title_id": None,
                    "stipulation": "normal", "_heat": 8,
                    "why": "Triple Threat — the winner talks her way into a title shot"})
        take([w["id"] for w in three])
        spare = [w for w in spare if w["id"] not in used]

    # ---- 4. a real tag or six-woman tag if the stables are there --------
    if len(out) < want:
        facs = [f for f in _factions_for(con, ids - used)]
        if len(facs) >= 2:
            x, y = facs[0], facs[1]
            out.append({"match_type": "six_woman", "teams": [x["members"], y["members"]],
                        "title_id": None, "stipulation": "normal", "_heat": 12,
                        "why": f"Six-woman tag — {x['name']} against {y['name']}"})
            take(x["members"] + y["members"])
            notes.append(f"{x['name']} and {y['name']} settle it six-woman.")
        else:
            tt = _teams_for(con, ids - used)
            if len(tt) >= 2:
                x, y = tt[0], tt[1]
                out.append({"match_type": "tag", "teams": [x["members"], y["members"]],
                            "title_id": None, "stipulation": "normal", "_heat": 8,
                            "why": f"Tag match — {x['name']} against {y['name']}"})
                take(x["members"] + y["members"])

    # ---- 5. fill the rest with face-vs-heel singles ---------------------
    desperate = False
    while len(out) < want:
        avail = [w for w in pool if w["id"] not in used and _usable(w, desperate)]
        if len(avail) < 2:
            if not desperate:
                desperate = True                     # dig into the tired half
                notes.append("Ran short of fresh bodies — some of these women are worn down.")
                continue
            break
        avail.sort(key=_star_power, reverse=True)
        a = avail[0]
        b = _pick_opponent(a, avail, used | {a["id"]})
        if b is None:
            break
        out.append({"match_type": "singles", "teams": [[a["id"]], [b["id"]]],
                    "title_id": None, "stipulation": "normal", "_heat": 0,
                    "why": ("Face vs heel" if a["alignment"] != b["alignment"]
                            else "Filler — no natural opponent left")})
        take([a["id"], b["id"]])

    if len(out) < want:
        notes.append(f"{brand_id} could only fill {len(out)} of {want} matches — the "
                     f"roster is too thin or too tired.")
    return out, notes


# ---------------------------------------------------------------- promos

def _promo_card(con: sqlite3.Connection, brands: list[str], by_id: dict[int, dict],
                booked: set[int], want: int, rng: random.Random) -> list[dict]:
    """Two segments (or however many the format wants), each a different type.

    Stories that are NOT already in a match tonight get first call — a promo is
    for building what you have not booked yet. Then the champions, then whoever
    is hottest. The type is chosen from the state of the story.
    """
    out: list[dict] = []
    taken: set[int] = set()
    kinds_used: set[str] = set()

    def add(kind: str, wids: list[int], why: str, topic: str | None = None) -> bool:
        if kind in kinds_used or any(w in taken for w in wids) or len(out) >= want:
            return False
        p = PR.get(kind)
        if not p["min"] <= len(wids) <= p["max"]:
            return False
        out.append({"kind": kind, "wrestler_ids": wids, "why": why, "topic": topic})
        kinds_used.add(kind)
        taken.update(wids)
        return True

    ids = set(by_id)
    feuds = _feuds_for(con, ids)

    # 1. Feuds that still need building — and the TYPE comes from the story's own
    # next beat, so the segment the booker picks is the one the Rivalries screen
    # is advising. One source of truth for "what should happen next" (see
    # storylines.next_beat) rather than two that can drift apart.
    st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
    today = st["current_date"] if st else ""
    for f in feuds:
        if len(out) >= want:
            break
        a, b = f["a_id"], f["b_id"]
        heat = f["heat"]
        arc = dict(con.execute("SELECT * FROM feud WHERE id=?", (f["id"],)).fetchone())
        nxt = storylines.next_beat(con, arc, today)
        # A protected feud is exactly the one that most needs a promo: it is the
        # only way to build it while the match is being withheld.
        if a in booked and b in booked and not nxt["protected"]:
            continue
        if nxt["want"] == "keep_apart":
            kind = rng.choice(["contract_signing", "face_to_face", "run_in_beatdown"])
            why = f"Building to {arc.get('blowoff_label') or arc.get('planned_blowoff')} — {nxt['want'].replace('_', ' ')}"
        elif nxt["want"] == "blowoff":
            kind = rng.choice(["contract_signing", "face_to_face"])
            why = f"{heat} heat — sign the match and let them stare at each other"
        elif nxt["want"] == "physical":
            kind = rng.choice(["face_to_face", "run_in_beatdown"])
            why = f"{heat} heat — turn it physical before the match"
        else:
            kind = "callout"
            why = f"{heat} heat — early in the build, she calls her out"
        if not add(kind, [a, b], why):
            add("callout", [a, b], why)

    # 2. A champion with the belt and nobody in front of her.
    if len(out) < want:
        for b in brands:
            for t in _titles_for(con, b):
                champ = _champion(con, t["id"])
                if champ and champ in by_id and champ not in taken:
                    # A champion already defending tonight opens the floor to the
                    # locker room instead; one who is not booked holds the belt up.
                    kind = "open_challenge" if champ in booked else "title_presentation"
                    why = (f"{by_id[champ]['name']} defends the "
                           f"{t['short_name'] or t['name']} tonight — set it up"
                           if champ in booked else
                           f"{by_id[champ]['name']} holds the "
                           f"{t['short_name'] or t['name']} and has no match")
                    if add(kind, [champ], why, topic=t["name"]):
                        break
            if len(out) >= want:
                break

    # 3. A faction that can announce something.
    if len(out) < want:
        for f in _factions_for(con, ids - taken):
            if add("stable_announcement", f["members"][:3],
                   f"{f['name']} have something to say", topic=f["name"]):
                break

    # 4. Whoever is hottest gets the mic — and a woman with no match tonight
    # comes first, because a segment is how she stays on television at all.
    if len(out) < want:
        hot = sorted((w for w in by_id.values() if w["id"] not in taken),
                     key=lambda w: (w["id"] in booked, -_star_power(w)))
        for w in hot:
            if len(out) >= want:
                break
            kind = next((k for k in ("backstage_interview", "callout", "gm_address",
                                     "open_challenge", "in_ring_apology")
                         if k not in kinds_used), None)
            if not kind:
                break
            add(kind, [w["id"]],
                f"{w['name']} is over and has a match to sell" if w["id"] in booked
                else f"{w['name']} is over and has nothing booked")

    for i, p in enumerate(out, start=1):
        p["slot"] = i
        p["label"] = PR.get(p["kind"])["label"]
    return out
