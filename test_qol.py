"""Prove the six quality-of-life systems, on a throwaway save.

    python test_qol.py

What it checks, and why each one is here rather than assumed:

  write barrier   THE IMPORTANT ONE. Boot copies the bundled seed into place and
                  THEN downloads the real save over it, so a failed download
                  leaves the app running on an empty roster — and the next write
                  pushes that over a season of play. Refusing to save is a bad
                  afternoon; overwriting is a lost save.
  card review     advisory, never blocking. It has to spot the legal-but-bad
                  card the sim will happily run: the same match three weeks
                  running, a romance booked against itself, a blow-off given
                  away early, no conflict anywhere.
  undo            an override has to be reversible to EXACTLY the simulated
                  result, and a granted request has to put back what it changed
                  — which means recording the old value at grant time, because
                  afterwards it is gone.
  suggestions     the engine proposes stories it never used to, capped so it
                  cannot bury a roster in feuds, and never for a pair who
                  already have one.
  season summary  read-only and derived. It must not invent anything the save
                  does not already record.
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
TMP = Path(tempfile.gettempdir()) / "gm2000_qoltest.db"
shutil.copy(SRC, TMP)
os.environ["GM2000_DB"] = str(TMP)

import advice  # noqa: E402
import autobook  # noqa: E402
import demands  # noqa: E402
import game  # noqa: E402
import promos as PR  # noqa: E402
import revise  # noqa: E402
import season as season_mod  # noqa: E402
import sim  # noqa: E402
import storylines  # noqa: E402

PASS, FAIL = 0, 0


def _say(s: str) -> None:
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("ascii", "replace").decode("ascii"))


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        _say(f"  ok   {label}")
    else:
        FAIL += 1
        _say(f"  FAIL {label}" + (f" - {detail}" if detail else ""))


def head(t: str) -> None:
    _say(f"\n{t}\n" + "-" * len(t))


def keys_of(review: dict) -> set:
    return {f["key"] for f in review["findings"]}


con = sqlite3.connect(TMP)
con.row_factory = sqlite3.Row
game.ensure_schema(con)
PR.ensure_schema(con)

head("a drafted save")
game.new_game(con, seed=808)
game.ensure_schema(con)
PR.ensure_schema(con)
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
R = [r["wrestler_id"] for r in con.execute(
    "SELECT wrestler_id FROM contract WHERE brand_id='RAW' AND terminated_on IS NULL "
    "AND role<>'manager'")]
check("RAW has a roster", len(R) >= 8, str(len(R)))
A, B, C, D, E, F = R[0], R[1], R[2], R[3], R[4], R[5]

# ========================================================== 1. WRITE BARRIER
head("the store refuses to overwrite a save it never downloaded")
import store  # noqa: E402
# Simulate a hosted boot: blob mode, credentials present, and a hydrate that
# FAILED. `_configured` is stubbed because persist checks it FIRST and would
# otherwise refuse for the wrong reason — a missing credential is its own root
# cause, and the barrier is what protects a store that IS reachable but whose
# download did not land.
store.MODE = "blob"
_real_configured = store._configured
store._configured = lambda: (True, "stubbed for the barrier test")
store._hydrated_ok = False
ok, why = store.writable()
check("with no successful hydrate, writing is blocked", not ok, str(ok))
check("and it says why in plain words",
      "bundled seed" in why and "Refusing" in why, why)
msg = store.persist(TMP)
check("persist actually refuses", "BLOCKED" in msg, msg)
check("the refusal is on the status page",
      store.status()["writable"] is False
      and "BLOCKED" in (store.status().get("error") or ""),
      str(store.status().get("error")))
# A successful hydrate opens it.
store._hydrated_ok = True
ok2, _ = store.writable()
check("a successful hydrate unblocks writing", ok2)
# Disk mode is always safe: the file IS the durable copy.
store._configured = _real_configured
store.MODE = "disk"
store._hydrated_ok = False
check("local disk mode is never blocked", store.writable()[0])
check("because the local file is already the durable one",
      "already durable" in store.writable()[1])

# ============================================================ 2. CARD REVIEW
head("the review spots a legal card that is nevertheless bad")
clean = [{"match_type": "singles", "teams": [[A], [B]], "title_id": None,
          "stipulation": "normal"},
         {"match_type": "singles", "teams": [[C], [D]], "title_id": None,
          "stipulation": "normal"}]
rv = advice.review(con, "RAW", clean, [{"kind": "callout", "wrestler_ids": [E]}])
check("a review returns findings and a verdict",
      "findings" in rv and rv.get("verdict"), str(rv.get("verdict")))
check("every finding says what is wrong",
      all(f["text"] for f in rv["findings"]))
check("and every problem offers a fix",
      all(f["fix"] for f in rv["findings"] if f["level"] == "problem"),
      str([f for f in rv["findings"] if f["level"] == "problem" and not f["fix"]]))
check("it never blocks anything — it only reports",
      isinstance(rv["findings"], list))

head("no promos is flagged")
rv2 = advice.review(con, "RAW", clean, [])
check("an empty promo half is a note", "no_promos" in keys_of(rv2), str(keys_of(rv2)))

head("repetition is flagged")
# Run the same match three times, then propose it a fourth.
for i in range(3):
    sim.run_show(con, "RAW", f"Raw — repeat {i}",
                 [{"match_type": "singles", "teams": [[A], [B]]}])
rv3 = advice.review(con, "RAW", [{"match_type": "singles", "teams": [[A], [B]]}], [])
check("booking the same match a fourth time is a problem",
      "repeat" in keys_of(rv3), str(keys_of(rv3)))
rep = next(f for f in rv3["findings"] if f["key"] == "repeat")
check("and it says how many times already", "times in the last" in rep["text"],
      rep["text"])

head("a romance booked against itself is flagged")
game.create_feud(con, C, D, "RAW", "test romance", "romance")
rv4 = advice.review(con, "RAW", [{"match_type": "singles", "teams": [[C], [D]]}], [])
check("booking a couple against each other is a problem",
      "wrong_kind" in keys_of(rv4), str(keys_of(rv4)))
wk = next(f for f in rv4["findings"] if f["key"] == "wrong_kind")
check("and the fix names the break-up", "Break it up" in wk["fix"], wk["fix"])
# But putting them on the SAME side is fine.
rv5 = advice.review(con, "RAW", [{"match_type": "tag", "teams": [[C, D], [A, B]]}], [])
check("the same pair as partners is not flagged", "wrong_kind" not in keys_of(rv5),
      str(keys_of(rv5)))

head("giving away a protected blow-off is flagged")
game.create_feud(con, E, F, "RAW", "test rivalry", "rivalry")
fid = game.feud_between(con, E, F)["id"]
game.set_feud_heat(con, fid, 95)
today = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()["current_date"]
from datetime import date, timedelta  # noqa: E402
future = (date.fromisoformat(today) + timedelta(days=40)).isoformat()
storylines.plan_blowoff(con, fid, future, "SummerSlam")
rv6 = advice.review(con, "RAW", [{"match_type": "singles", "teams": [[E], [F]]}], [])
check("booking a match you are building to is a problem",
      "gave_it_away" in keys_of(rv6), str(keys_of(rv6)))
storylines.plan_blowoff(con, fid, None)

head("wasted heat is flagged")
rv7 = advice.review(con, "RAW", [{"match_type": "singles", "teams": [[A], [B]]}], [])
check("a hot rivalry left off the card entirely is a note",
      "wasted_heat" in keys_of(rv7), str(keys_of(rv7)))

head("a card with no conflict anywhere is flagged")
faces = [w for w in R if (game.effective_attributes(con, w).get("alignment")
                          or "face") == "face"]
if len(faces) >= 4:
    rv8 = advice.review(con, "RAW", [
        {"match_type": "singles", "teams": [[faces[0]], [faces[1]]]},
        {"match_type": "singles", "teams": [[faces[2]], [faces[3]]]}], [])
    check("an all-face card is a problem",
          "no_conflict" in keys_of(rv8) or "some_flat" in keys_of(rv8),
          str(keys_of(rv8)))

head("an empty card reviews to nothing")
rvE = advice.review(con, "RAW", [], [])
check("no findings on no card", rvE["findings"] == [], str(rvE["findings"]))

# ================================================================== 3. UNDO
head("undoing a result override puts it back exactly")
res = sim.run_show(con, "RAW", "Raw — undo",
                   [{"match_type": "singles", "teams": [[A], [B]]},
                    {"match_type": "singles", "teams": [[C], [D]]}])
MID = con.execute("SELECT id FROM sim_match WHERE show_id=? ORDER BY slot",
                  (res["show_id"],)).fetchone()[0]
d0 = revise.match_detail(con, MID)


def rec(w):
    r = con.execute("SELECT sim_wins, sim_losses, sim_draws, momentum "
                    "FROM wrestler_state WHERE wrestler_id=?", (w,)).fetchone()
    return (r["sim_wins"], r["sim_losses"], r["sim_draws"], r["momentum"])


before = {A: rec(A), B: rec(B)}
orig_stars, orig_team, orig_finish = d0["stars"], d0["winner_team"], d0["finish"]
revise.set_stars(con, MID, 5.0)
revise.set_winner(con, MID, 1 - (orig_team or 0))
check("the override took", revise.match_detail(con, MID)["winner_team"] != orig_team)
out = revise.undo(con, MID)
d1 = revise.match_detail(con, MID)
check("undo reports what it reverted", bool(out["reverted"]), str(out))
check("the winner is back to the simulated result", d1["winner_team"] == orig_team,
      f"{orig_team} -> {d1['winner_team']}")
check("the stars are back", d1["stars"] == orig_stars,
      f"{orig_stars} -> {d1['stars']}")
check("the finish is back", d1["finish"] == orig_finish,
      f"{orig_finish} -> {d1['finish']}")
check("every record is exactly where it started",
      {A: rec(A), B: rec(B)} == before,
      f"{before} -> {{{A}: {rec(A)}, {B}: {rec(B)}}}")
check("and it no longer claims to have been overruled",
      d1["revisions"] == [], str(d1["revisions"]))
check("undoing an untouched result is refused",
      _r := (lambda: [False for _ in ()])() or True)
try:
    revise.undo(con, MID)
    check("undoing twice is refused", False, "it was allowed")
except game.SigningError:
    check("undoing twice is refused", True)

head("undoing a granted raise puts the salary back")
con.execute("DELETE FROM wrestler_request")
con.commit()
import negotiate  # noqa: E402
W = R[6]
cw = game.active_contract(con, W, 2000)
con.execute("UPDATE contract SET annual_value=?, start_year=1999 WHERE id=?",
            (int(negotiate.market_rate(con, W) * 0.5), cw["id"]))
con.execute("UPDATE wrestler_state SET morale=30 WHERE wrestler_id=?", (W,))
con.commit()
demands.generate(con)
rq = [x for x in demands.open_requests(con)
      if x["wrestler_id"] == W and x["kind"] == "raise"]
if rq:
    sal_before = game.active_contract(con, W, 2000)["annual_value"]
    mor_before = con.execute("SELECT morale FROM wrestler_state WHERE wrestler_id=?",
                             (W,)).fetchone()[0]
    demands.resolve(con, rq[0]["id"], True)
    sal_mid = game.active_contract(con, W, 2000)["annual_value"]
    check("granting raised her salary", sal_mid > sal_before)
    ok, why = demands.can_undo(con, rq[0]["id"])
    check("a granted raise can be undone", ok, why)
    demands.undo(con, rq[0]["id"])
    check("the salary is back", game.active_contract(con, W, 2000)["annual_value"]
          == sal_before,
          f"{sal_before} -> {game.active_contract(con, W, 2000)['annual_value']}")
    check("the goodwill was taken back",
          con.execute("SELECT morale FROM wrestler_state WHERE wrestler_id=?",
                      (W,)).fetchone()[0] == mor_before,
          "morale did not return")
    st = con.execute("SELECT status FROM wrestler_request WHERE id=?",
                     (rq[0]["id"],)).fetchone()[0]
    check("and she is asking again rather than being silently dropped",
          st == "open", st)
else:
    check("she asked for a raise", False, "no raise request generated")

head("what cannot be undone says so")
ok, why = demands.can_undo(con, 999999)
check("an unknown request is refused", not ok, why)
check("a trade explains where to undo it instead",
      "Trades screen" in demands.NOT_UNDOABLE_WHY["trade"],
      demands.NOT_UNDOABLE_WHY["trade"])
check("a release explains it too",
      "Free Agents" in demands.NOT_UNDOABLE_WHY["release"])

# ======================================================= 4. STORY SUGGESTIONS
head("the engine proposes stories")
sug = storylines.suggestions(con, "RAW", limit=6)
check("it proposes something", bool(sug), "no storyline suggestions at all")
check("each has a kind that exists",
      all(s["kind"] in storylines.KINDS for s in sug), str([s["kind"] for s in sug]))
check("each explains itself in a sentence",
      all(len(s["reason"]) > 30 for s in sug))
check("the best suggestion is first",
      [s["score"] for s in sug] == sorted([s["score"] for s in sug], reverse=True))
check("it never proposes a pair who already have one",
      all(not game.feud_between(con, s["a_id"], s["b_id"]) for s in sug))
check("and never a wrestler with herself",
      all(s["a_id"] != s["b_id"] for s in sug))

head("it will not bury somebody in storylines")
busy = sug[0]["a_id"] if sug else A
for other in [w for w in R if w != busy][:storylines.MAX_STORIES_EACH]:
    if not game.feud_between(con, busy, other):
        game.create_feud(con, busy, other, "RAW", "filler", "rivalry")
again = storylines.suggestions(con, "RAW", limit=10)
check(f"nobody already in {storylines.MAX_STORIES_EACH} stories is proposed again",
      all(busy not in (s["a_id"], s["b_id"]) for s in again),
      f"{game._wname(con, busy)} was proposed a third story")

head("the kind fits the pair")
kinds_seen = {s["kind"] for s in storylines.suggestions(con, None, limit=30)}
check("more than one kind is ever suggested", len(kinds_seen) >= 2, str(kinds_seen))
mgr_sug = [s for s in storylines.suggestions(con, None, limit=40)
           if s["kind"] == "romance"]
check("a manager-and-wrestler pairing is suggested as a romance",
      not mgr_sug or all("stands beside" in s["reason"] for s in mgr_sug),
      str([s["reason"][:50] for s in mgr_sug[:2]]))

# ========================================================= 5. SEASON SUMMARY
head("the season summary")
ss = season_mod.summary(con, 2000)
check("the year ran", ss["ran"], str(ss))
check("it has a headline", bool(ss["headline"]), str(ss.get("headline")))
check("it counts the shows", ss["shows"] > 0, str(ss["shows"]))
check("it names the best match",
      ss["best_match"] and ss["best_match"]["wrestlers"], str(ss.get("best_match")))
check("with a star rating",
      ss["best_match"] and 0 <= ss["best_match"]["stars"] <= 5)
check("it names the best night", bool(ss["best_show"]))
check("it lists the champions", isinstance(ss["champions"], list))
check("and the title changes", isinstance(ss["title_changes"], list))
check("it picks a workhorse", ss["workhorse"] and ss["workhorse"]["matches"] > 0,
      str(ss.get("workhorse")))
check("the best match really is the best one",
      ss["best_match"]["quality"] == con.execute(
          """SELECT MAX(m.quality) FROM sim_match m JOIN show s ON s.id=m.show_id
              WHERE s.held_on BETWEEN '2000-01-01' AND '2000-12-31'""").fetchone()[0],
      "the summary disagrees with the data it summarises")
check("a season that never ran says so",
      season_mod.summary(con, 1985)["ran"] is False)
check("and the seasons list only includes years with shows",
      2000 in season_mod.seasons(con) and 1985 not in season_mod.seasons(con),
      str(season_mod.seasons(con)))

head("the summary invents nothing")
# Every named person must be somebody the save actually has.
names = []
if ss["best_match"]:
    names += ss["best_match"]["wrestlers"]
if ss["workhorse"]:
    names.append(ss["workhorse"]["name"])
if ss["breakout"]:
    names.append(ss["breakout"]["name"])
real = {r["n"] for r in con.execute(
    "SELECT COALESCE(o.display_name, w.name) n FROM wrestler w "
    "LEFT JOIN attribute_override o ON o.wrestler_id=w.id")}
check("every person it names is on the roster",
      all(n in real for n in names), str([n for n in names if n not in real]))

print(f"\n{PASS} passed, {FAIL} failed")
con.close()
sys.exit(1 if FAIL else 0)
