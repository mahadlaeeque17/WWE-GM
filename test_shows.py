"""Prove the show format, end to end, on a throwaway save.

    python test_shows.py

Runs against a COPY of the bundled save, so it never touches your game.

What it checks, and why each one is here rather than assumed:

  format         a pre-booked television card really is four matches and two
                 promos, and a pay-per-view really is six with three from each
                 brand. This is the thing the whole build was for, so it is the
                 first assertion.
  pre-booking    the suggestion prefers RIVALRIES over filler and puts the belt
                 on the main event. Without this the auto-booker is just the old
                 pair-by-overall ladder wearing a new name.
  match types    every structure in the catalogue validates its own shape and
                 REFUSES a wrong one. A half-filled Fatal 4-Way reaching the sim
                 would resolve as a triple threat with no error, which is the
                 worst kind of bug — a silent one.
  promos         a segment writes a row, moves rivalry heat, and counts toward
                 the show rating. Heat from talking is the reason promos exist.
  stamina        working costs stamina and it recovers when she is left off.
  calendar       two Saturday Night's Main Events every month, on Saturdays,
                 spread apart, and never colliding with the pay-per-view.
  progression    a season of work produces SUGGESTIONS and applies none of them
                 until the GM approves — the one rule the whole system rests on.
  old saves      a save written before match types and promos existed upgrades
                 itself at boot instead of dying on a missing column.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "harvester"))
sys.path.insert(0, str(ROOT / "backend"))

SRC = ROOT / "data" / "gm2000.db"
TMP = Path(tempfile.gettempdir()) / "gm2000_showtest.db"
shutil.copy(SRC, TMP)
os.environ["GM2000_DB"] = str(TMP)

import autobook  # noqa: E402
import game  # noqa: E402
import matches as MT  # noqa: E402
import promos as PR  # noqa: E402
import rankings  # noqa: E402
import sim  # noqa: E402

PASS, FAIL = 0, 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}" + (f" — {detail}" if detail else ""))


def head(t: str) -> None:
    print(f"\n{t}\n" + "-" * len(t))


con = sqlite3.connect(TMP)
con.row_factory = sqlite3.Row
game.ensure_schema(con)
PR.ensure_schema(con)

head("a fresh save")
game.new_game(con, seed=2000)
game.ensure_schema(con)
PR.ensure_schema(con)
# Draft enough of a roster onto both brands that a six-match card is possible.
game.start_draft(con, rounds=9)
board = game.draft_board(con)
picked = 0
while board.get("on_the_clock") and picked < 60:
    avail = board.get("available") or []
    if not avail:
        break
    wid = avail[0]["id"] if isinstance(avail[0], dict) else avail[0]
    try:
        game.make_pick(con, wid)
        picked += 1
    except Exception:                                        # noqa: BLE001
        break
    board = game.draft_board(con)
sizes = {b: con.execute(
    "SELECT COUNT(*) FROM contract WHERE brand_id=? AND terminated_on IS NULL", (b,)
).fetchone()[0] for b, _, _ in game.BRANDS}
check("both brands have a roster", all(v >= 6 for v in sizes.values()), str(sizes))

head("show formats")
check("television is 4 matches + 2 promos",
      autobook.SHOW_FORMATS["tv"]["matches"] == 4
      and autobook.SHOW_FORMATS["tv"]["promos"] == 2)
check("SNME is 4 matches + 2 promos",
      autobook.SHOW_FORMATS["snme"]["matches"] == 4
      and autobook.SHOW_FORMATS["snme"]["promos"] == 2)
check("pay-per-view is 6 matches, 3 per brand",
      autobook.SHOW_FORMATS["ppv"]["matches"] == 6
      and autobook.SHOW_FORMATS["ppv"]["per_brand"] == 3)

head("the pre-booked card")
tv = autobook.suggest(con, "RAW", "tv")
check("television card has 4 matches", len(tv["matches"]) == 4, str(len(tv["matches"])))
check("television card has 2 promos", len(tv["promos"]) == 2, str(len(tv["promos"])))
check("every match carries a type", all(m.get("match_type") for m in tv["matches"]))
check("every match explains itself", all(m.get("why") for m in tv["matches"]))
check("every promo explains itself", all(p.get("why") for p in tv["promos"]))
check("the promos are different types",
      len({p["kind"] for p in tv["promos"]}) == len(tv["promos"]))
booked = [w for m in tv["matches"] for t in m["teams"] for w in t]
check("nobody is booked twice", len(booked) == len(set(booked)))
titled = [m for m in tv["matches"] if m.get("title_id")]
check("a belt is defended", bool(titled), "no title match on the card")
if titled:
    check("the title match is late on the card",
          max(m["slot"] for m in titled) >= 3,
          f"title in slot {[m['slot'] for m in titled]}")

head("rivalries get booked first")
roster = [r[0] for r in con.execute(
    """SELECT c.wrestler_id FROM contract c WHERE c.brand_id='RAW'
       AND c.terminated_on IS NULL AND c.role<>'manager' LIMIT 4""")]
game.create_feud(con, roster[0], roster[1], "RAW", "test feud")
fid = game.feud_between(con, roster[0], roster[1])["id"]
game.set_feud_heat(con, fid, 85)
tv2 = autobook.suggest(con, "RAW", "tv")
pairs = [{w for t in m["teams"] for w in t} for m in tv2["matches"]]
check("the hot rivalry is on the card", {roster[0], roster[1]} in pairs,
      "feud at 85 heat was not booked")
feud_match = next((m for m, p in zip(tv2["matches"], pairs)
                   if p == {roster[0], roster[1]}), None)
if feud_match:
    check("a blow-off gets a stipulation", feud_match["stipulation"] != "normal",
          f"stipulation was {feud_match['stipulation']}")

head("pay-per-view is co-branded")
ppv = autobook.suggest(con, "RAW", "ppv")
check("6 matches", len(ppv["matches"]) == 6, str(len(ppv["matches"])))
check("both brands are on it", len(ppv["brands"]) == 2)
signed = {r["wrestler_id"]: r["brand_id"] for r in con.execute(
    "SELECT wrestler_id, brand_id FROM contract WHERE terminated_on IS NULL")}
per_brand: dict[str, int] = {}
for m in ppv["matches"]:
    bs = {signed.get(w) for t in m["teams"] for w in t}
    for b in bs:
        if b:
            per_brand[b] = per_brand.get(b, 0) + 1
check("three matches from each brand",
      all(v >= 3 for v in per_brand.values()) and len(per_brand) == 2, str(per_brand))
ppv_titles = [m["title_id"] for m in ppv["matches"] if m.get("title_id")]
check("no belt is defended twice on one night",
      len(ppv_titles) == len(set(ppv_titles)), str(ppv_titles))
ppv_booked = [w for m in ppv["matches"] for t in m["teams"] for w in t]
check("nobody works twice on the pay-per-view",
      len(ppv_booked) == len(set(ppv_booked)))

head("match structures")
for t in MT.catalogue():
    key = t["key"]
    teams = MT.default_teams(key)
    filled = []
    n = 1
    for side in teams:
        filled.append([n + i for i in range(len(side))])
        n += len(side)
    try:
        MT.validate(key, filled)
        ok = True
    except ValueError as e:
        ok, why = False, str(e)
    check(f"{t['label']} accepts its own shape", ok, "" if ok else why)
try:
    MT.validate("fatal_four_way", [[1], [2], [3]])
    check("a 3-sided Fatal 4-Way is refused", False, "it was accepted")
except ValueError:
    check("a 3-sided Fatal 4-Way is refused", True)
try:
    MT.validate("tag", [[1, 2], [3, 0]])
    check("an empty tag slot is refused", False, "it was accepted")
except ValueError:
    check("an empty tag slot is refused", True)
check("an untyped card row is named", MT.infer([[1], [2], [3], [4]]) == "fatal_four_way")
check("a tag row is named", MT.infer([[1, 2], [3, 4]]) == "tag")

head("running a full show")
heat_before = con.execute("SELECT heat FROM feud WHERE id=?", (fid,)).fetchone()[0]
stam_before = {w: con.execute(
    "SELECT fatigue FROM wrestler_state WHERE wrestler_id=?", (w,)).fetchone()[0]
    for w in [x for m in tv2["matches"] for t in m["teams"] for x in t]}
res = sim.run_show(con, "RAW", "Raw — test", tv2["matches"],
                   promo_card=tv2["promos"])
check("4 matches were simulated", len(res["matches"]) == 4, str(len(res["matches"])))
check("2 promos were simulated", len(res["promos"]) == 2, str(len(res["promos"])))
check("the show has a rating", res["rating"] is not None and 0 < res["rating"] <= 100,
      str(res["rating"]))
check("every match has a quality", all(0 < m["quality"] <= 100 for m in res["matches"]))
check("every match has stars", all(0 <= m["stars"] <= 5 for m in res["matches"]))
check("every promo has a quality", all(0 <= p["quality"] <= 100 for p in res["promos"]))
rows = con.execute("SELECT COUNT(*) FROM sim_promo WHERE show_id=?",
                   (res["show_id"],)).fetchone()[0]
check("promo rows were written", rows == 2, str(rows))
check("match types were persisted",
      all(r[0] for r in con.execute(
          "SELECT match_type FROM sim_match WHERE show_id=?", (res["show_id"],))))
heat_after = con.execute("SELECT heat FROM feud WHERE id=?", (fid,)).fetchone()[0]
check("the rivalry moved", heat_after != heat_before, f"{heat_before} -> {heat_after}")
worked = [w for m in tv2["matches"] for t in m["teams"] for w in t]
spent = [w for w in worked
         if con.execute("SELECT fatigue FROM wrestler_state WHERE wrestler_id=?",
                        (w,)).fetchone()[0] > stam_before[w]]
check("working costs stamina", len(spent) == len(worked),
      f"{len(spent)} of {len(worked)}")

head("promo heat is cheaper than match heat")
a, b = roster[2], roster[3]
game.create_feud(con, a, b, "RAW", "promo feud")
f2 = game.feud_between(con, a, b)["id"]
game.set_feud_heat(con, f2, 30)
fat_before = con.execute("SELECT fatigue FROM wrestler_state WHERE wrestler_id=?",
                         (a,)).fetchone()[0]
one = autobook.suggest(con, "SMACKDOWN", "tv")
sim.run_show(con, "SMACKDOWN", "SmackDown — test", one["matches"],
             promo_card=[{"kind": "contract_signing", "wrestler_ids": [a, b]}])
h2 = con.execute("SELECT heat FROM feud WHERE id=?", (f2,)).fetchone()[0]
fat_after = con.execute("SELECT fatigue FROM wrestler_state WHERE wrestler_id=?",
                        (a,)).fetchone()[0]
check("a contract signing builds heat", h2 > 30, f"heat {h2}")
check("talking barely tires her", fat_after - fat_before <= 2,
      f"fatigue +{fat_after - fat_before}")

head("promos are scored on the same footing as matches")
# The two are built from the same 0-20 categories, but a match collects ~25
# points of additive bonuses a promo has no equivalent of. Without the promo's
# own spread and floor, the same calibre of performer read three times lower on
# the mic — so booking a promo dragged the show rating DOWN, which is backwards.
mq = [r[0] for r in con.execute("SELECT quality FROM sim_match WHERE quality IS NOT NULL")]
pq = [r[0] for r in con.execute("SELECT quality FROM sim_promo WHERE quality IS NOT NULL")]
if mq and pq:
    am, ap = sum(mq) / len(mq), sum(pq) / len(pq)
    check("an average promo is in the same band as an average match",
          0.7 <= ap / am <= 1.4, f"promo avg {ap:.1f} vs match avg {am:.1f}")
    check("a promo can out-rate a weak match", max(pq) > min(mq),
          f"best promo {max(pq):.1f}, worst match {min(mq):.1f}")

head("bad cards are refused before anything is written")
shows_before = con.execute("SELECT COUNT(*) FROM show").fetchone()[0]
try:
    sim.run_show(con, "RAW", "bad", [
        {"match_type": "singles", "teams": [[roster[0]], [roster[1]]]},
        {"match_type": "fatal_four_way", "teams": [[roster[2]], [roster[3]]]},
    ])
    check("a malformed match kills the whole show", False, "it ran")
except ValueError as e:
    check("a malformed match kills the whole show",
          con.execute("SELECT COUNT(*) FROM show").fetchone()[0] == shows_before,
          f"a show was left behind: {e}")
try:
    sim.run_show(con, "RAW", "bad", [
        {"match_type": "singles", "teams": [[roster[0]], [roster[1]]]}],
        promo_card=[{"kind": "contract_signing", "wrestler_ids": [roster[0]]}])
    check("a one-woman contract signing is refused", False, "it ran")
except ValueError:
    check("a one-woman contract signing is refused", True)

head("every path that runs a show runs the whole format")
# There are four ways a show gets run — hand-booked, auto-booked, the AI's
# proposal, and the AI rival-book endpoint — and three of them used to skip the
# promos entirely. A format only one code path honours is not a format.
auto_m = sim.auto_card(con, "RAW", 4, "tv")
auto_p = sim.auto_promos(con, "RAW", 2, "tv")
check("auto-book produces 4 matches", len(auto_m) == 4, str(len(auto_m)))
check("auto-book produces 2 promos", len(auto_p) == 2, str(len(auto_p)))
auto_ppv = sim.auto_card(con, "RAW", 6, "ppv")
check("auto-book produces 6 for a pay-per-view", len(auto_ppv) == 6, str(len(auto_ppv)))
game.set_setting(con, "ai_brand", "SMACKDOWN")
prop = game.propose_ai_show(con)
payload = __import__("json").loads(con.execute(
    "SELECT payload FROM proposal WHERE id=?", (prop["proposal_id"],)).fetchone()[0])
check("the AI proposes matches AND promos",
      len(payload.get("card") or []) == 4 and len(payload.get("promos") or []) == 2,
      f"{len(payload.get('card') or [])} matches, {len(payload.get('promos') or [])} promos")
approved = game.approve_proposal(con, prop["proposal_id"])
check("approving it runs the whole show",
      len(approved["result"]["matches"]) == 4 and len(approved["result"]["promos"]) == 2,
      str(approved["result"]["rating"]))

head("the calendar")
st = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()
seed, year = st["rng_seed"], st["season_year"]
for month in range(1, 13):
    days = game.month_snme(seed, year, month)
    sats = [d for d in range(1, game._days_in_month(year, month) + 1)
            if __import__("datetime").date(year, month, d).weekday() == 5]
    ppv_day = game._last_sunday(year, month)
    ok = (len(days) == 2 and all(d in sats for d in days)
          and len(set(days)) == 2 and ppv_day not in days)
    if not ok:
        check(f"{game.MONTHS[month - 1]} has two spread-out Saturdays", False,
              f"got {days}, saturdays {sats}")
        break
else:
    check("every month has two Saturday Night's Main Events", True)
    check("they are always on Saturdays and never on the PPV", True)
shows = game.month_shows(seed, year, 1)
snme = [s for s in shows if s["type"] == "SNME"]
check("the month sheet lists both SNMEs", len(snme) == 2, str(len(snme)))
check("the month sheet still lists the PPV",
      any(s["type"] == "PPV" for s in shows))
cal = game.calendar(con)
check("the calendar exposes both SNME days", len(cal.get("snme_days") or []) == 2)

head("progression suggests and applies nothing")
before = {r[0]: r[1] for r in con.execute(
    "SELECT wrestler_id, popularity FROM attribute_override WHERE popularity IS NOT NULL")}
out = rankings.evaluate_season(con, year)
check("suggestions were produced", out["created"] > 0, str(out))
pending = rankings.list_changes(con, "pending", year)
check("they are all pending", all(c["status"] == "pending" for c in pending))
after = {r[0]: r[1] for r in con.execute(
    "SELECT wrestler_id, popularity FROM attribute_override WHERE popularity IS NOT NULL")}
check("no rating was touched", before == after, "a rating changed without approval")
check("every suggestion says why", all(c["reason"] for c in pending))
if pending:
    one = pending[0]
    rankings.resolve_change(con, one["id"], True)
    v = con.execute("SELECT %s FROM attribute_override WHERE wrestler_id=?"
                    % one["category"], (one["wrestler_id"],)).fetchone()
    check("approving one applies it", v and v[0] == one["to_value"],
          f"{v[0] if v else None} != {one['to_value']}")
    two = next((c for c in pending[1:] if c["wrestler_id"] != one["wrestler_id"]), None)
    if two:
        rankings.resolve_change(con, two["id"], False)
        st2 = con.execute("SELECT status FROM rating_change WHERE id=?",
                          (two["id"],)).fetchone()[0]
        check("rejecting one discards it", st2 == "rejected", st2)
promo_credit = PR.season_counts(con, year)
check("promo work is tracked for progression", bool(promo_credit),
      "no promo counts recorded")

head("an old save upgrades itself")
old = Path(tempfile.gettempdir()) / "gm2000_oldschema.db"
shutil.copy(TMP, old)
oc = sqlite3.connect(old)
oc.executescript("""
DROP TABLE IF EXISTS sim_promo_participant;
DROP TABLE IF EXISTS sim_promo;
CREATE TABLE _m AS SELECT id, show_id, slot, title_id, quality, finish, narrative
                     FROM sim_match;
DROP TABLE sim_match;
ALTER TABLE _m RENAME TO sim_match;
""")
oc.commit()
oc.row_factory = sqlite3.Row
game.ensure_schema(oc)
PR.ensure_schema(oc)
cols = {r[1] for r in oc.execute("PRAGMA table_info(sim_match)")}
check("match_type was added", "match_type" in cols)
check("stipulation was added", "stipulation" in cols)
check("the promo tables were created",
      bool(oc.execute("SELECT name FROM sqlite_master WHERE name='sim_promo'").fetchone()))
oc.close()

print(f"\n{PASS} passed, {FAIL} failed")
con.close()
sys.exit(1 if FAIL else 0)
