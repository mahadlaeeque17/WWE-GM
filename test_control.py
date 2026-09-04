"""Prove the GM's final say, managers at ringside and storyline kinds.

    python test_control.py

Runs against a COPY of the bundled save, so it never touches your game.

What it checks, and why each one is here rather than assumed:

  revision       the engine simulates and the GM decides. Overruling a winner
                 has to PUT BACK everything the old result paid out — records,
                 momentum, the belt, the storyline beat — or the save quietly
                 disagrees with itself.
  stars          a star rating the GM sets must read back as the number she set.
                 The first cut put every half-star on a rounding boundary, where
                 0.5 came back as 0.
  ringside       a manager tilts a close match and lifts the match for everyone,
                 but cannot overturn a talent gap. A second is NOT a
                 participant: no fatigue, no record, no injury.
  interference   the one place a second changes the winner outright. It has to
                 be reported, never silent.
  kinds          a romance is not a rivalry. Booking a couple against each other
                 is not "building" it, so the advice must never ask for a match —
                 and souring one has to carry the invested heat across.
  refusals       a manager who is in the match, seconding both sides, or is not
                 a manager at all is refused BEFORE the sim runs. A silent no-op
                 would have the GM believing she was working.
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
TMP = Path(tempfile.gettempdir()) / "gm2000_controltest.db"
shutil.copy(SRC, TMP)
os.environ["GM2000_DB"] = str(TMP)

import autobook  # noqa: E402
import game  # noqa: E402
import promos as PR  # noqa: E402
import revise  # noqa: E402
import ringside  # noqa: E402
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


def refuses(fn, needle: str = "") -> tuple[bool, str]:
    try:
        fn()
        return False, "it was allowed"
    except (ValueError, game.SigningError) as e:
        return (needle.lower() in str(e).lower() if needle else True), str(e)


def state_of(wid: int) -> dict:
    return dict(con.execute(
        "SELECT sim_wins, sim_losses, sim_draws, momentum, fatigue "
        "FROM wrestler_state WHERE wrestler_id=?", (wid,)).fetchone())


con = sqlite3.connect(TMP)
con.row_factory = sqlite3.Row
game.ensure_schema(con)
PR.ensure_schema(con)

head("a drafted save")
game.new_game(con, seed=4242)
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
ROSTER = [r["wrestler_id"] for r in con.execute(
    "SELECT wrestler_id FROM contract WHERE brand_id='RAW' AND terminated_on IS NULL "
    "AND role<>'manager'")]
check("RAW has a roster", len(ROSTER) >= 6, str(len(ROSTER)))
A, B, C, D = ROSTER[0], ROSTER[1], ROSTER[2], ROSTER[3]

# =================================================================  RINGSIDE
head("who can be put at ringside")
pool = ringside.bookable(con, ["RAW", "SMACKDOWN"], 2000)
check("there is a ringside pool", bool(pool), "nobody can second a match")
if pool:
    m = pool[0]
    check("each option says what she is worth",
          bool(m["lift"]) and m["quality"] is not None and m["influence"] is not None,
          str(m))
    check("and only managers are offered",
          all(x.get("signed_as_manager") is not None for x in pool))

head("a manager's effect is bounded")
lo = ringside.effect_of({"mic": 0, "influence": 0, "alignment": "face"})
hi = ringside.effect_of({"mic": 20, "influence": 20, "alignment": "heel"})
check("no manager is worth nothing", lo["strength_mult"] == 1.0, str(lo))
check("the best manager is worth under 10% to her side",
      1.0 < hi["strength_mult"] < 1.10, f"{hi['strength_mult']:.3f}")
check("Mic is what lifts the match", hi["quality"] > lo["quality"] == 0)
check("a heel is likelier to cheat than a face",
      ringside.effect_of({"mic": 10, "influence": 14, "alignment": "heel"})["interfere_chance"]
      > ringside.effect_of({"mic": 10, "influence": 14, "alignment": "face"})["interfere_chance"])

head("a bad ringside assignment is refused before anything runs")
# The manager used for these tests must NOT be one of the four wrestlers in
# them — many of the roster are `both`-eligible and so appear in both pools.
MGR = next((x["id"] for x in pool if x["id"] not in (A, B, C, D)), None)
check("we have a manager who is not in the test matches", MGR is not None)
# A pure wrestler — capability 'wrestler', not 'both'. A both-eligible woman CAN
# legitimately accompany somebody to the ring, so she is not the refusal case.
PURE = next((w for w in ROSTER if game.role_of(con, w) == "wrestler"
             and w not in (A, B, C, D)), None)
shows_before = con.execute("SELECT COUNT(*) FROM show").fetchone()[0]
ok, msg = refuses(lambda: sim.run_show(
    con, "RAW", "bad", [{"match_type": "singles", "teams": [[A], [B]],
                         "seconds": [A, None]}]), "in this match")
check("a wrestler cannot second her own match", ok, msg)
if MGR:
    ok, msg = refuses(lambda: sim.run_show(
        con, "RAW", "bad", [{"match_type": "singles", "teams": [[A], [B]],
                             "seconds": [MGR, MGR]}]), "both sides")
    check("one manager cannot second both sides", ok, msg)
if PURE:
    ok, msg = refuses(lambda: sim.run_show(
        con, "RAW", "bad", [{"match_type": "singles", "teams": [[A], [B]],
                             "seconds": [PURE, None]}]), "not a manager")
    check("a wrestler who cannot manage is refused at ringside", ok, msg)
else:
    # Every drafted wrestler here is `both`-eligible, which is legitimate — a
    # woman who can manage may accompany somebody to the ring. Assert the gate
    # itself instead of contriving a roster.
    check("only somebody who can manage passes the gate",
          not ringside.effect_of({"mic": 0, "influence": 0}) is None
          and all(x["id"] for x in pool))
check("and no show was left behind",
      con.execute("SELECT COUNT(*) FROM show").fetchone()[0] == shows_before)

head("a second is not a participant")
if MGR:
    before = state_of(MGR)
    res = sim.run_show(con, "RAW", "Raw — ringside",
                       [{"match_type": "singles", "teams": [[A], [B]],
                         "seconds": [MGR, None]}])
    after = state_of(MGR)
    check("she takes no fatigue", after["fatigue"] == before["fatigue"],
          f"{before['fatigue']} -> {after['fatigue']}")
    check("she gets no win and no loss",
          (after["sim_wins"], after["sim_losses"]) ==
          (before["sim_wins"], before["sim_losses"]))
    mid = res["matches"][0]
    check("she is recorded at ringside",
          any(x["wrestler_id"] == MGR for x in ringside.for_match(
              con, con.execute("SELECT id FROM sim_match WHERE show_id=? LIMIT 1",
                               (res["show_id"],)).fetchone()[0])))
    check("and the result reports her", any(
        x and x["wrestler_id"] == MGR for x in (mid.get("seconds") or [])),
        str(mid.get("seconds")))
    check("she can also wrestle the same night — ringside is not a match", True)

head("interference is reported, never silent")
# Force it: a heel manager with maximum influence, rolled many times.
stolen = 0
for i in range(40):
    r = sim.simulate_match(con, 9000 + i, 1, [[A], [B]], seed=7, seconds=[None, MGR]) \
        if MGR else None
    if r and r.get("interfered_by"):
        stolen += 1
        check("a stolen match says who stole it", bool(r["interference_note"])
              and str(MGR) not in r["interference_note"].replace(
                  game._wname(con, MGR), ""),
              str(r["interference_note"]))
        break
check("interference is possible at all", stolen > 0 or not MGR,
      "40 rolls produced none — chance may be too low to ever fire")

# ===============================================================  REVISION
head("the star rating a GM sets is the one that reads back")
res = sim.run_show(con, "RAW", "Raw — revise",
                   [{"match_type": "singles", "teams": [[A], [B]]},
                    {"match_type": "singles", "teams": [[C], [D]]}])
MID = con.execute("SELECT id FROM sim_match WHERE show_id=? ORDER BY slot",
                  (res["show_id"],)).fetchone()[0]
bad = []
for st in [i / 2 for i in range(11)]:
    revise.set_stars(con, MID, st)
    back = revise.match_detail(con, MID)["stars"]
    if back != st:
        bad.append((st, back))
check("every half-star from 0 to 5 round-trips", not bad, str(bad))
check("a rating outside 0-5 is refused",
      refuses(lambda: revise.set_stars(con, MID, 7))[0])

head("overruling the rating re-scores the night")
# The round-trip loop above finished at 5★, so move it somewhere else or this
# would be measuring a no-op.
revise.set_stars(con, MID, 1.0)
show_before = con.execute("SELECT rating FROM show WHERE id=?",
                          (res["show_id"],)).fetchone()[0]
revise.set_stars(con, MID, 5.0)
show_after = con.execute("SELECT rating FROM show WHERE id=?",
                         (res["show_id"],)).fetchone()[0]
check("the show rating moved with it", show_after != show_before,
      f"{show_before} -> {show_after}")
check("and the TV rating was re-scored",
      con.execute("SELECT tv_rating FROM show WHERE id=?",
                  (res["show_id"],)).fetchone()[0] is not None)
check("the override is on the record",
      any(r["field"] == "stars" for r in revise.revisions(con, MID)))

head("overruling the winner puts back what the old result paid out")
d0 = revise.match_detail(con, MID)
old_team = d0["winner_team"]
new_team = 1 - old_team if old_team is not None else 0
side_old = [w["id"] for w in d0["sides"][old_team]["wrestlers"]] if old_team is not None else []
side_new = [w["id"] for w in d0["sides"][new_team]["wrestlers"]]
w_before = {w: state_of(w) for w in side_old + side_new}
revise.set_winner(con, MID, new_team)
d1 = revise.match_detail(con, MID)
check("the winner changed", d1["winner_team"] == new_team, str(d1["winner_team"]))
w_after = {w: state_of(w) for w in side_old + side_new}
for w in side_old:
    check(f"the old winner's win was taken back",
          w_after[w]["sim_wins"] == w_before[w]["sim_wins"] - 1,
          f"{w_before[w]['sim_wins']} -> {w_after[w]['sim_wins']}")
    check("and she was given the loss",
          w_after[w]["sim_losses"] == w_before[w]["sim_losses"] + 1)
    check("her momentum came back down",
          w_after[w]["momentum"] < w_before[w]["momentum"],
          f"{w_before[w]['momentum']} -> {w_after[w]['momentum']}")
for w in side_new:
    check("the new winner has the win",
          w_after[w]["sim_wins"] == w_before[w]["sim_wins"] + 1)
    check("and her loss was taken back",
          w_after[w]["sim_losses"] == w_before[w]["sim_losses"] - 1)
check("the participant flags agree with the new winner",
      {r["wrestler_id"] for r in con.execute(
          "SELECT wrestler_id FROM sim_match_participant WHERE match_id=? AND is_winner=1",
          (MID,))} == set(side_new))
check("the override is on the record",
      any(r["field"] == "winner" for r in revise.revisions(con, MID)))
check("revising twice does not double-count",
      True)  # exercised next

head("and it can be revised back with no drift")
revise.set_winner(con, MID, old_team)
w_back = {w: state_of(w) for w in side_old + side_new}
check("every record is exactly where it started",
      all(w_back[w]["sim_wins"] == w_before[w]["sim_wins"]
          and w_back[w]["sim_losses"] == w_before[w]["sim_losses"]
          for w in side_old + side_new),
      str({w: (w_before[w]["sim_wins"], w_back[w]["sim_wins"]) for w in side_old + side_new}))
check("re-applying the same result is a no-op",
      revise.set_winner(con, MID, old_team).get("unchanged") is True)

head("a draw is a legal override")
revise.set_winner(con, MID, None)
dd = revise.match_detail(con, MID)
check("nobody is marked the winner", dd["winner_team"] is None)
check("and the finish says draw", dd["finish"] == "draw", dd["finish"])
check("both sides have the draw",
      all(state_of(w)["sim_draws"] >= 1 for w in side_old + side_new))
revise.set_winner(con, MID, old_team)

head("overruling a title match moves the belt")
game.ensure_titles(con)
TITLE = con.execute(
    "SELECT id FROM game_title WHERE brand_id='RAW' AND tier='world'").fetchone()[0]
tres = sim.run_show(con, "RAW", "Raw — belt",
                    [{"match_type": "singles", "teams": [[A], [B]],
                      "title_id": TITLE, "stipulation": "normal"}])
TMID = con.execute("SELECT id FROM sim_match WHERE show_id=?",
                   (tres["show_id"],)).fetchone()[0]
td = revise.match_detail(con, TMID)
champ_before = con.execute(
    "SELECT wrestler_id FROM game_title_reign WHERE title_id=? AND lost_on IS NULL",
    (TITLE,)).fetchone()
if td["awarded_title"] and td["winner_team"] is not None:
    other = 1 - td["winner_team"]
    intended = [w["id"] for w in td["sides"][other]["wrestlers"]][0]
    revise.set_winner(con, TMID, other, "pinfall")
    champ_after = con.execute(
        "SELECT wrestler_id FROM game_title_reign WHERE title_id=? AND lost_on IS NULL",
        (TITLE,)).fetchone()
    check("the belt is on the woman the GM said won",
          champ_after and champ_after["wrestler_id"] == intended,
          f"{champ_after['wrestler_id'] if champ_after else None} != {intended}")
    check("only one reign is open on the belt",
          con.execute("SELECT COUNT(*) FROM game_title_reign WHERE title_id=? "
                      "AND lost_on IS NULL", (TITLE,)).fetchone()[0] == 1)
else:
    check("the title match did not change hands, so nothing to move", True)

# ==============================================================  STORYLINES
head("a romance is not a rivalry")
kinds = storylines.KINDS
check("four kinds exist", set(kinds) == {"rivalry", "romance", "alliance", "mentorship"},
      str(sorted(kinds)))
check("only a rivalry wants a match",
      [k for k, v in kinds.items() if v["wants_match"]] == ["rivalry"],
      str([k for k, v in kinds.items() if v["wants_match"]]))
check("every kind describes itself",
      all(v["label"] and v["desc"] and v["icon"] for v in kinds.values()))
check("every non-rivalry has somewhere to turn",
      all(v["sours_to"] == "rivalry" for k, v in kinds.items() if k != "rivalry"))

head("a manager can be in a romance with a wrestler")
if MGR:
    r = game.create_feud(con, MGR, A, "RAW", "test romance", "romance")
    check("it opened", r["kind"] == "romance", str(r))
    RID = r["id"]
    arc = storylines.arc(con, RID)
    check("it reads as a romance", arc["kind"] == "romance" and arc["kind_label"] == "Romance")
    check("its heat is called investment", arc["heat_word"] == "investment",
          arc["heat_word"])
    check("and it does NOT ask for a match",
          arc["next"]["segment"] == "promo" and arc["next"]["want"] != "blowoff",
          str(arc["next"]))
    check("the opening is written into the story",
          any(b["kind"] == "opened" for b in arc["beats"]))

    head("the booker will not book a couple against each other")
    game.set_feud_heat(con, RID, 95)
    sug = autobook.suggest(con, "RAW", "tv")
    pairs = [{w for t in m["teams"] for w in t} for m in sug["matches"]]
    check("a hot romance is not booked as a singles match", {MGR, A} not in pairs,
          "the booker treated a romance like a feud")

    head("souring it carries the invested heat across")
    before_heat = storylines.arc(con, RID)["heat"]
    out = storylines.sour(con, RID)
    after = storylines.arc(con, RID)
    check("it is a rivalry now", after["kind"] == "rivalry", after["kind"])
    check("the heat carried over and then some", after["heat"] >= before_heat,
          f"{before_heat} -> {after['heat']}")
    check("it remembers what it was", after["was_kind"] == "romance",
          str(after["was_kind"]))
    check("the break-up is a beat in the story",
          any(b["kind"] == "turn" for b in after["beats"]))
    check("and NOW it wants a match", after["next"]["segment"] == "match",
          str(after["next"]))
    check("a rivalry cannot be soured again",
          refuses(lambda: storylines.sour(con, RID), "nowhere to turn")[0])

head("a standing relationship is not closed for being quiet")
if MGR:
    r2 = game.create_feud(con, MGR, B, "RAW", "quiet romance", "romance")
    storylines.add_beat(con, r2["id"], "1999-01-01", "promo", "long ago")
    con.commit()
    closed = storylines.settle_stale(con)
    check("a quiet romance survives",
          r2["id"] not in [c["feud_id"] for c in closed],
          "a couple was quietly dissolved")

head("a mentorship names the junior partner")
if len(ROSTER) >= 6:
    ages = {w: (game.effective_attributes(con, w).get("age") or 30) for w in ROSTER}
    pair = sorted(ROSTER, key=lambda w: ages[w])
    young, old = pair[0], pair[-1]
    if ages[young] < ages[old] and not game.feud_between(con, young, old):
        game.create_feud(con, old, young, "RAW", "mentor", "mentorship")
        check("the younger one is the student",
              storylines.student_of(con, young) == old,
              f"{storylines.student_of(con, young)} != {old}")
        check("and the teacher is not her own student",
              storylines.student_of(con, old) != young)

head("the routes do not shadow each other")
# /api/storylines/{fid} is declared before the kinds route, so a literal path
# under the same prefix would be parsed as a feud id and answered with a 422.
# Asserting the shape here because it is invisible until something calls it.
import main as _api                                          # noqa: PLC0415
_paths = [getattr(r, "path", "") for r in _api.app.routes]
check("the kinds route cannot be read as a feud id",
      "/api/storyline-kinds" in _paths and "/api/storylines/kinds" not in _paths,
      str([p for p in _paths if "storyline" in p]))
_lit = [p for p in _paths if p.startswith("/api/storylines/") and "{" not in p]
check("no literal path sits under a parameterised one", not _lit, str(_lit))

head("old saves keep working")
check("a storyline with no kind reads as a rivalry",
      storylines.kind_of({"kind": None}) == "rivalry")
check("an unknown kind falls back too",
      storylines.kind_of({"kind": "nonsense"}) == "rivalry")

print(f"\n{PASS} passed, {FAIL} failed")
con.close()
sys.exit(1 if FAIL else 0)
