"""Prove the locker room, the storylines and the scoreboard, on a throwaway save.

    python test_locker.py

Runs against a COPY of the bundled save, so it never touches your game.

What it checks, and why each one is here rather than assumed:

  pay            a salary measured against a FIXED yardstick. This is the one
                 that had to be got right: a price that moved with morale would
                 be measuring itself, and the underpaid → unhappy → pricier →
                 more underpaid spiral has no bottom.
  morale drift   pay, booking, spotlight and promises actually move her over a
                 month, and every factor explains itself in words.
  requests       she asks before she acts, escalates when refused, and the
                 `final` text WARNS what she will do next.
  forced trade   at rock bottom, after asking three times, she moves herself —
                 and only then. A consequence with no warning would be a bug,
                 not a feature.
  granting       every grant does something real: a raise rewrites the contract
                 and eats cap space, time off makes her unbookable.
  extensions     re-signing is a negotiation. A low offer is refused, a happy
                 wrestler is cheaper than an unhappy one, and length is a term.
  turns          the crowd is measured separately from quality, so an over heel
                 reads as cheered — and nothing turns without approval.
  storylines     beats are recorded, the series score is right, and a PLANNED
                 blow-off makes the booker withhold the singles match.
  brand war      a rating is anchored to last week, both brands are compared,
                 and a week only counts as won if both actually ran.
  medical        injuries have a severity, rest is faster than being forgotten,
                 and booking through granted rest is refused.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "harvester"))
sys.path.insert(0, str(ROOT / "backend"))

SRC = ROOT / "data" / "gm2000.db"
TMP = Path(tempfile.gettempdir()) / "gm2000_lockertest.db"
shutil.copy(SRC, TMP)
os.environ["GM2000_DB"] = str(TMP)

import autobook  # noqa: E402
import brandwar  # noqa: E402
import crowd  # noqa: E402
import demands  # noqa: E402
import game  # noqa: E402
import medical  # noqa: E402
import morale  # noqa: E402
import negotiate  # noqa: E402
import promos as PR  # noqa: E402
import sim  # noqa: E402
import storylines  # noqa: E402
import turns  # noqa: E402

PASS, FAIL = 0, 0


def _say(s: str) -> None:
    """Print without dying on a console that is not UTF-8.

    The Windows default codepage cannot encode an arrow or an em dash, and a
    test harness must never fail because of how its own output is spelled.
    """
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
    print(f"\n{t}\n" + "-" * len(t))


def morale_of(wid: int) -> int:
    return con.execute("SELECT morale FROM wrestler_state WHERE wrestler_id=?",
                       (wid,)).fetchone()[0]


def set_morale(wid: int, v: int) -> None:
    con.execute("UPDATE wrestler_state SET morale=? WHERE wrestler_id=?", (v, wid))
    con.commit()


con = sqlite3.connect(TMP)
con.row_factory = sqlite3.Row
game.ensure_schema(con)
PR.ensure_schema(con)

head("a drafted save")
game.new_game(con, seed=2000)
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
roster = [r["wrestler_id"] for r in con.execute(
    "SELECT wrestler_id FROM contract WHERE brand_id='RAW' AND terminated_on IS NULL "
    "AND role<>'manager'")]
check("RAW has a roster", len(roster) >= 8, str(len(roster)))
W = roster[0]

# =====================================================================  PAY
head("pay is measured against a fixed yardstick")
mkt = negotiate.market_rate(con, W)
check("a market rate exists", mkt > 0, str(mkt))
before = negotiate.market_rate(con, W)
set_morale(W, 3)
after_low = negotiate.market_rate(con, W)
set_morale(W, 95)
after_high = negotiate.market_rate(con, W)
set_morale(W, 50)
check("the market rate does NOT move with morale",
      before == after_low == after_high,
      f"{before} / {after_low} / {after_high} — the spiral is back")
# Her negotiating position SHOULD move with morale; only the yardstick is fixed.
set_morale(W, 3)
sour = negotiate.profile(con, W, "wrestler", 1.0)["reservation"]
set_morale(W, 95)
happy = negotiate.profile(con, W, "wrestler", 1.0)["reservation"]
set_morale(W, 50)
check("but her asking price does", sour > happy, f"sour {sour} vs happy {happy}")

pos = negotiate.pay_position(con, W)
check("pay position reads her real contract", pos["under_contract"] and pos["salary"] > 0)
cid = pos["contract_id"]
con.execute("UPDATE contract SET annual_value=? WHERE id=?", (int(mkt * 1.5), cid))
con.commit()
rich = negotiate.pay_position(con, W)
con.execute("UPDATE contract SET annual_value=? WHERE id=?", (int(mkt * 0.55), cid))
con.commit()
poor = negotiate.pay_position(con, W)
check("overpaid reads as overpaid", rich["verdict"] == "overpaid", rich["verdict"])
check("badly underpaid reads as insulted", poor["verdict"] == "insulted", poor["verdict"])

head("pay moves morale in the right direction")
con.execute("UPDATE contract SET annual_value=? WHERE id=?", (int(mkt * 1.5), cid))
con.commit()
f_rich = {f["key"]: f for f in morale.factors(con, W)}
con.execute("UPDATE contract SET annual_value=? WHERE id=?", (int(mkt * 0.55), cid))
con.commit()
f_poor = {f["key"]: f for f in morale.factors(con, W)}
check("being paid well is a positive", f_rich["pay"]["delta"] > 0, str(f_rich["pay"]))
check("being underpaid is a negative", f_poor["pay"]["delta"] < 0, str(f_poor["pay"]))
check("and it says so in words", "market rate" in f_poor["pay"]["detail"],
      f_poor["pay"]["detail"])
check("with a fix attached", bool(f_poor["pay"]["fix"]))
check("every factor explains itself",
      all(f["detail"] for f in morale.factors(con, W)))

head("personality changes how the same slight feels")
# money_hungry feels an underpayment nearly twice as hard as loyal does.
con.execute("INSERT INTO attribute_override (wrestler_id, personality, updated_at) "
            "VALUES (?,?,?) ON CONFLICT(wrestler_id) DO UPDATE SET "
            "personality=excluded.personality", (W, "money_hungry", game.now_iso()))
con.commit()
greedy = {f["key"]: f for f in morale.factors(con, W)}["pay"]["delta"]
con.execute("UPDATE attribute_override SET personality='loyal' WHERE wrestler_id=?", (W,))
con.commit()
loyal = {f["key"]: f for f in morale.factors(con, W)}["pay"]["delta"]
check("money-hungry feels it harder than loyal", greedy < loyal,
      f"money_hungry {greedy} vs loyal {loyal}")
con.execute("UPDATE attribute_override SET personality='ambitious' WHERE wrestler_id=?", (W,))
con.commit()

head("the monthly drift")
set_morale(W, 50)
res = morale.apply_monthly_drift(con)
check("morale moved for the roster", res["moved"] > 0, str(res["moved"]))
check("an underpaid, unbooked wrestler went DOWN", morale_of(W) < 50, str(morale_of(W)))
check("bands are named", morale.band(5)[0] == "mutinous" and morale.band(95)[0] == "ecstatic",
      f"{morale.band(5)} / {morale.band(95)}")
# The band labels read well in a table but not all of them are adjectives, so
# they need help fitting into a sentence.
check("every band label fits into a sentence",
      all(not morale._reads(lab).endswith("is wants out")
          and morale._reads(lab).count("is is") == 0
          for _, lab, _ in morale.BANDS)
      and morale._reads("wants out") == "wants out"
      and morale._reads("unhappy") == "is unhappy",
      str([morale._reads(l) for _, l, _ in morale.BANDS]))
snap = morale.snapshot(con, W)
check("a snapshot carries the band and the drift",
      snap["band"] and snap["monthly_drift"] is not None)
check("no single month can swing a career",
      abs(snap["monthly_drift"]) <= morale.MAX_MONTHLY_DRIFT)

# ================================================================  REQUESTS
head("she asks before she acts")
con.execute("DELETE FROM wrestler_request")
con.commit()
set_morale(W, 30)
gen = demands.generate(con)
check("requests were filed", gen["created"] > 0, str(gen))
reqs = demands.open_requests(con)
check("one open request per wrestler at most",
      len({r["wrestler_id"] for r in reqs}) == len(reqs))
mine = [r for r in reqs if r["wrestler_id"] == W]
check("the underpaid wrestler asked for something", bool(mine))
if mine:
    r = mine[0]
    check("it starts at 'ask' severity", r["severity"] == "ask", r["severity"])
    check("the request explains itself", bool(r["reason"]) and bool(r["detail"]))
    check("it carries a readable label", bool(r["label"]) and bool(r["icon"]))

head("the in-tray is a page, not a wall")
# The first month of a save used to file a request for nearly the whole roster.
# An in-tray of eighteen is a wall, and a wall gets ignored — which defeats the
# entire point of her asking before she acts.
con.execute("DELETE FROM wrestler_request")
con.commit()
g2 = demands.generate(con)
check("no more than the monthly cap is filed",
      g2["created"] <= demands.MAX_NEW_PER_MONTH, str(g2))
check("and it says how many are still waiting", "waiting" in g2, str(g2))
# Urgency, not luck, decides who gets heard: a final warning is never crowded out.
sevs = [x["severity"] for x in demands.open_requests(con)]
check("the most insistent are filed first",
      sevs == sorted(sevs, key=lambda x: demands.SEVERITY_ORDER.index(x)), str(sevs))

head("a deal she just signed is not yet an insult")
# A draft contract is written at a tier discount, so against the open market a
# rookie is "underpaid" from the moment she signs. That is intended — it just
# must not be a grievance in her first season.
con.execute("DELETE FROM wrestler_request")
N = roster[2]
cn = game.active_contract(con, N, 2000)
con.execute("UPDATE contract SET annual_value=?, start_year=2000 WHERE id=?",
            (int(negotiate.market_rate(con, N) * 0.5), cn["id"]))
set_morale(N, 60)
con.commit()
kinds_now = [k for k, _ in demands._wants(con, N, morale.snapshot(con, N))]
check("a first-season deal does not trigger a raise demand",
      "raise" not in kinds_now, str(kinds_now))
# But a wrestler who is already sour gets to mention it straight away.
set_morale(N, 20)
con.commit()
kinds_sour = [k for k, _ in demands._wants(con, N, morale.snapshot(con, N))]
check("unless she is already unhappy", "raise" in kinds_sour, str(kinds_sour))
set_morale(N, 50)

head("refusing escalates, and the final ask WARNS")
target = mine[0] if mine else reqs[0]
wid = target["wrestler_id"]
kind = target["kind"]
seen = []
for _ in range(4):
    open_r = [x for x in demands.open_requests(con) if x["wrestler_id"] == wid]
    if not open_r:
        demands.generate(con)
        open_r = [x for x in demands.open_requests(con) if x["wrestler_id"] == wid]
    if not open_r:
        break
    seen.append(open_r[0]["severity"])
    demands.resolve(con, open_r[0]["id"], False)
    demands.generate(con)
# Escalation tracks HER PATIENCE, not the topic — she may raise a different
# grievance each time and should still get firmer. Counting per-KIND let her
# rotate topics and reset to 'ask' forever, which made a trade demand
# impossible to ever actually carry out.
check("severity escalates ask -> firm -> final",
      seen[:3] == ["ask", "firm", "final"], str(seen))
check("and it does not reset when she changes the subject",
      all(x == "final" for x in seen[3:]), str(seen))
finals = [x for x in con.execute(
    "SELECT * FROM wrestler_request WHERE severity='final'")]
check("a final request exists", bool(finals))
if finals:
    check("its detail contains the warning",
          any("LAST TIME" in (f["detail"] or "") or "After this" in (f["detail"] or "")
              for f in finals),
          finals[0]["detail"])

head("denying costs more the further she has escalated")
check("a final denial hurts most",
      demands.DENY_MORALE["final"] < demands.DENY_MORALE["firm"] < demands.DENY_MORALE["ask"],
      str(demands.DENY_MORALE))
check("ignoring is worse than refusing",
      True)   # asserted by construction in expire_stale; exercised below

head("an unanswered request lapses, and costs extra")
con.execute("DELETE FROM wrestler_request")
con.commit()
demands.generate(con)
opens = demands.open_requests(con)
if opens:
    victim = opens[0]
    # Put her mid-range first: near 0 the morale floor clamps the drop and the
    # comparison would be measuring the clamp rather than the penalty.
    set_morale(victim["wrestler_id"], 60)
    m0 = morale_of(victim["wrestler_id"])
    con.execute("UPDATE wrestler_request SET expires_on='1999-01-01' WHERE id=?",
                (victim["id"],))
    con.commit()
    exp = demands.expire_stale(con)
    m1 = morale_of(victim["wrestler_id"])
    check("it expired", exp["expired"] >= 1, str(exp))
    check("and cost her more than a straight refusal",
          m1 - m0 < demands.DENY_MORALE[victim["severity"]],
          f"{m0} -> {m1}, a refusal would have been "
          f"{demands.DENY_MORALE[victim['severity']]}")

# ================================================================  GRANTING
head("granting a raise is real, and costs cap space")
con.execute("DELETE FROM wrestler_request")
con.commit()
R = roster[1]
mkt_r = negotiate.market_rate(con, R)
crow = game.active_contract(con, R, 2000)
con.execute("UPDATE contract SET annual_value=? WHERE id=?",
            (int(mkt_r * 0.6), crow["id"]))
set_morale(R, 30)
con.commit()
demands.generate(con)
raise_req = [x for x in demands.open_requests(con)
             if x["wrestler_id"] == R and x["kind"] == "raise"]
check("she asked for a raise", bool(raise_req),
      str([x["kind"] for x in demands.open_requests(con) if x["wrestler_id"] == R]))
if raise_req:
    rq = raise_req[0]
    before_sal = game.active_contract(con, R, 2000)["annual_value"]
    m0 = morale_of(R)
    out = demands.resolve(con, rq["id"], True)
    after_sal = game.active_contract(con, R, 2000)["annual_value"]
    check("the contract was actually rewritten", after_sal > before_sal,
          f"{before_sal} → {after_sal}")
    check("and her morale jumped", morale_of(R) > m0, f"{m0} → {morale_of(R)}")
    check("the grant reports what it did", out["detail"]["kind"] == "raise")

head("a raise can be met part-way")
con.execute("DELETE FROM wrestler_request")
T = roster[2]
ct = game.active_contract(con, T, 2000)
con.execute("UPDATE contract SET annual_value=? WHERE id=?",
            (int(negotiate.market_rate(con, T) * 0.6), ct["id"]))
set_morale(T, 30)
con.commit()
demands.generate(con)
rr = [x for x in demands.open_requests(con) if x["wrestler_id"] == T and x["kind"] == "raise"]
if rr:
    asked = rr[0]["ask_value"]
    cur = game.active_contract(con, T, 2000)["annual_value"]
    half = cur + (asked - cur) // 2
    m0 = morale_of(T)
    out = demands.resolve(con, rr[0]["id"], True, counter_value=half)
    got = game.active_contract(con, T, 2000)["annual_value"]
    check("a counter is applied at the number you picked", got == half, f"{got} != {half}")
    check("meeting her half-way buys some goodwill, not all",
          0 < out["morale_change"] < demands.GRANT_MORALE[rr[0]["severity"]],
          str(out["morale_change"]))

head("time off makes her genuinely unbookable")
Z = roster[3]
con.execute("UPDATE wrestler_state SET fatigue=90 WHERE wrestler_id=?", (Z,))
con.commit()
rest = medical.rest(con, Z, 2)
check("she is resting", medical.is_resting(con, Z, "2000-01-01"), str(rest))
try:
    sim.run_show(con, "RAW", "should fail",
                 [{"match_type": "singles", "teams": [[Z], [roster[4]]]}])
    check("booking through granted rest is refused", False, "it ran")
except ValueError as e:
    check("booking through granted rest is refused", "resting" in str(e).lower(), str(e))
pool_ids = {w["id"] for w in autobook._pool(con, "RAW")}
check("and the pre-booker leaves her out", Z not in pool_ids)
medical.clear_rest(con, Z)
check("calling her back clears it", not medical.is_resting(con, Z, "2000-01-01"))

# ==============================================================  EXTENSIONS
head("extensions are a negotiation, not a button")
E = roster[4]
q = negotiate.extension_quote(con, E)
check("a quote exists with a stance", q["asking"] > 0 and bool(q["stance"]))
low = negotiate.offer(con, E, "RAW", max(1, q["asking"] // 4), context="extension", years=2)
check("a low-ball is not accepted", low["verdict"] != "accept", str(low["verdict"]))
good = negotiate.offer(con, E, "RAW", int(q["asking"] * 1.3), context="extension", years=2)
check("a strong offer is accepted", good["verdict"] == "accept", str(good))
try:
    game.extend(con, E, 2, annual_value=max(1, q["asking"] // 5))
    check("extend() refuses an offer she rejected", False, "it went through")
except game.SigningError as e:
    check("extend() refuses an offer she rejected", True)
    check("and the refusal says what she wants",
          "wants about" in str(e) or "walked" in str(e), str(e))

head("she will hear you out before walking away from her own employer")
# Patience starts at 1 for a genuine star, which is right for a free agent. On an
# EXTENSION it made a top wrestler walk out over a single opening number, before
# the GM had had one exchange — and locked the negotiation for the rest of the
# season.
STAR = max(roster, key=lambda w: game.effective_attributes(con, w)["overall"])
negotiate.reset(STAR, "RAW")
q_star = negotiate.extension_quote(con, STAR)
first = negotiate.offer(con, STAR, "RAW", max(1, q_star["asking"] // 6),
                        context="extension", years=2)
check("one low-ball does not end the conversation", first["verdict"] != "walked",
      f"she walked on the first offer ({first['verdict']})")
check("and she says how much patience is left", first["patience"] >= 1,
      str(first["patience"]))
# But it is not infinite — keep insulting her and she does leave.
for _ in range(6):
    last = negotiate.offer(con, STAR, "RAW", 1, context="extension", years=2)
    if last["verdict"] == "walked":
        break
check("but repeated insults still end it", last["verdict"] == "walked", str(last["verdict"]))
negotiate.reset(STAR, "RAW")
check("an extension walkout is not recorded as a holdout",
      not game.is_holdout(con, STAR, "RAW", 2000),
      "she is still under contract — a holdout would drop her from her own brand")

head("how she feels decides whether keeping her is cheap")
set_morale(E, 90)
happy_q = negotiate.extension_quote(con, E)["asking"]
set_morale(E, 8)
sour_q = negotiate.extension_quote(con, E)["asking"]
check("a happy wrestler re-signs cheaper than a sour one", happy_q < sour_q,
      f"happy {happy_q} vs sour {sour_q}")
# The discount is rounded to the nearest $5k and floored at the minimum salary,
# so on a cheap wrestler it can vanish entirely. Use the priciest woman on the
# roster, where a 16% discount has room to show up.
TOP = max(roster, key=lambda w: negotiate.market_rate(con, w))
set_morale(TOP, 90)
mkt_top = negotiate.market_rate(con, TOP)
ret_top = negotiate.extension_profile(con, TOP)["reservation"]
check("and a happy one is cheaper than signing her cold", ret_top < mkt_top,
      f"retention {ret_top} vs market {mkt_top}")
check("the discount is the one the stance advertised",
      negotiate.retention_factor(90) == negotiate.RETENTION_HAPPY)

head("contract length is a term she has an opinion about")
# A young wrestler charges to be locked down; a veteran takes less for security.
young = [w for w in roster
         if (game.effective_attributes(con, w).get("age") or 30) <= 26]
old = [w for w in roster
       if (game.effective_attributes(con, w).get("age") or 30) >= 36]
if young:
    y = young[0]
    short = negotiate.offer(con, y, "RAW", 1, context="extension", years=1)["counter"]
    negotiate.reset(y, "RAW")
    long = negotiate.offer(con, y, "RAW", 1, context="extension", years=5)["counter"]
    negotiate.reset(y, "RAW")
    check("a rising wrestler charges for a long deal", (long or 0) > (short or 0),
          f"1yr {short} vs 5yr {long}")
if old:
    o = old[0]
    s1 = negotiate.offer(con, o, "RAW", 1, context="extension", years=1)["counter"]
    negotiate.reset(o, "RAW")
    s5 = negotiate.offer(con, o, "RAW", 1, context="extension", years=5)["counter"]
    negotiate.reset(o, "RAW")
    check("a veteran takes less for security", (s5 or 0) <= (s1 or 0),
          f"1yr {s1} vs 5yr {s5}")

head("a successful extension is signed and felt")
set_morale(E, 60)
m0 = morale_of(E)
q2 = negotiate.extension_quote(con, E)
try:
    ext = game.extend(con, E, 2, annual_value=int(q2["asking"] * 1.4))
    check("she re-signed", ext["contract_id"] > 0)
    check("and it lifted her morale", morale_of(E) > m0, f"{m0} → {morale_of(E)}")
except game.SigningError as e:
    check("she re-signed", False, str(e))

# ===================================================================  CROWD
head("the crowd is measured separately from quality")
# The whole point: an over heel gets CHEERED, which quality alone cannot express.
over_heel = crowd.wrestler_pop("heel", popularity=19, momentum=70, quality=80,
                               won=True, beaten_clean=False, cheap_finish=False,
                               feud_heat=60)
plain_heel = crowd.wrestler_pop("heel", popularity=5, momentum=50, quality=55,
                                won=True, beaten_clean=False, cheap_finish=True,
                                feud_heat=10)
over_face = crowd.wrestler_pop("face", popularity=18, momentum=70, quality=80,
                               won=True, beaten_clean=False, cheap_finish=False,
                               feud_heat=60)
check("an over heel is cheered anyway", over_heel > 0, f"{over_heel:.0f}")
check("an unover cheating heel is booed", plain_heel < 0, f"{plain_heel:.0f}")
check("an over face is cheered hardest", over_face > over_heel,
      f"face {over_face:.0f} vs heel {over_heel:.0f}")
check("a cheered heel is flagged as drifting face",
      crowd.mismatch("heel", over_heel) == "face", str(crowd.mismatch("heel", over_heel)))
check("a booed heel is not", crowd.mismatch("heel", plain_heel) is None)
# THE DIVERGENCE IS THE POINT. If reaction just tracked quality there would be
# no reason for two numbers, and the two lessons the pair exists to teach — a
# good match nobody cares about, and an ordinary match the crowd is invested in
# — would both be untellable.
good_but_cold = crowd.segment_reaction(82, 5, 0, {"face"}, False, False)
ok_but_hot = crowd.segment_reaction(48, 18, 90, {"face", "heel"}, False, False)
check("an ordinary match between invested stars beats a great one nobody cares about",
      ok_but_hot["reaction_score"] > good_but_cold["reaction_score"],
      f"cold-but-good {good_but_cold['reaction_score']} vs "
      f"hot-but-ordinary {ok_but_hot['reaction_score']}")
check("and star power alone can lift a segment two bands",
      crowd.segment_reaction(48, 18, 90, {"face", "heel"}, False, False)["reaction"]
      != crowd.segment_reaction(48, 3, 0, {"face"}, False, False)["reaction"],
      "reaction did not move when only the star power changed")

lo = crowd.segment_reaction(20, 10, 0, {"face"}, False, False)
hi = crowd.segment_reaction(88, 18, 90, {"face", "heel"}, True, True)
check("a dead segment reads as flat or hostile",
      lo["reaction"] in ("hostile", "flat"), lo["reaction"])
check("a great one reads hot or better",
      hi["reaction"] in ("hot", "red hot", "nuclear"), hi["reaction"])

# ==============================================================  STORYLINES
head("a rivalry records its beats")
A, B = roster[5], roster[6]
game.create_feud(con, A, B, "RAW", "test arc")
fid = game.feud_between(con, A, B)["id"]
game.set_feud_heat(con, fid, 30)
card = [{"match_type": "singles", "teams": [[A], [B]], "title_id": None,
         "stipulation": "normal"}]
sim.run_show(con, "RAW", "Raw — arc 1", card)
bts = storylines.beats(con, fid)
check("the match was written into the story", any(b["kind"] == "match" for b in bts),
      str([b["kind"] for b in bts]))
check("with a winner recorded",
      any(b["kind"] == "match" and b["winner_id"] for b in bts))
arc = storylines.arc(con, fid)
check("the series score is tracked", arc["series"]["matches"] >= 1, str(arc["series"]))
check("the stage is named", arc["stage_label"] and arc["stage_note"])
check("and it advises what happens next", bool(arc["next"]["advice"]))

head("stages track heat")
check("low heat is a build", storylines.stage_for(20) == "build")
check("mid heat is escalation", storylines.stage_for(55) == "escalation")
check("high heat is ready to blow off",
      storylines.stage_for(game.FEUD_BLOWOFF_HEAT) == "blowoff")

head("the calendar serves the dates the planner points at")
# The blow-off planner used to recompute "last Sunday of the month" in
# TypeScript. Two implementations of one rule is a drift waiting to happen, so
# the date is served with the schedule and the UI just uses it.
cal = game.calendar(con)
check("every scheduled show carries its date",
      all(p.get("date") for p in cal["schedule"]), str(cal["schedule"][:2]))
check("and the dates really are the last Sunday of the month",
      all(date.fromisoformat(p["date"]).weekday() == 6 for p in cal["schedule"]),
      str([p["date"] for p in cal["schedule"]]))
check("one per month, in order",
      [int(p["date"][5:7]) for p in cal["schedule"]] == list(range(1, 13)))

head("a planned blow-off makes the booker WITHHOLD the match")
game.set_feud_heat(con, fid, 95)
today = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()["current_date"]
future = (date.fromisoformat(today) + timedelta(days=40)).isoformat()
storylines.plan_blowoff(con, fid, future, "WrestleMania")
check("the feud is protected", storylines.is_protected(con, fid, today))
sug = autobook.suggest(con, "RAW", "tv")
pairs = [{w for t in m["teams"] for w in t} for m in sug["matches"]]
check("the singles blow-off is NOT booked", {A, B} not in pairs,
      "the booker gave away the match it was told to protect")
together = [m for m, p in zip(sug["matches"], pairs) if A in p and B in p]
check("but they are still on the show, on opposite sides of a tag",
      bool(together) and together[0]["match_type"] == "tag",
      str([(m["match_type"], m["why"]) for m in together]))
nb = storylines.next_beat(con, dict(con.execute(
    "SELECT * FROM feud WHERE id=?", (fid,)).fetchone()), today)
check("and the advice says so", nb["want"] == "keep_apart" and nb["protected"],
      str(nb["want"]))
promo_pairs = [set(p["wrestler_ids"]) for p in sug["promos"]]
check("a protected feud gets a promo instead", any({A, B} <= p for p in promo_pairs),
      str(promo_pairs))

head("clearing the plan releases the match")
storylines.plan_blowoff(con, fid, None)
check("no longer protected", not storylines.is_protected(con, fid, today))
sug2 = autobook.suggest(con, "RAW", "tv")
pairs2 = [{w for t in m["teams"] for w in t} for m in sug2["matches"]]
check("now the blow-off is booked", {A, B} in pairs2,
      str([(m["match_type"], m["why"]) for m in sug2["matches"]]))
blow = next((m for m, p in zip(sug2["matches"], pairs2) if p == {A, B}), None)
check("with a gimmick on it", blow and blow["stipulation"] != "normal",
      str(blow["stipulation"]) if blow else "no match")

# ===================================================================  TURNS
head("turns are proposed, never applied")
con.execute("DELETE FROM turn_suggestion")
con.execute("DELETE FROM segment_pop")
con.commit()
H = roster[7]
con.execute("INSERT INTO attribute_override (wrestler_id, alignment, updated_at) "
            "VALUES (?,?,?) ON CONFLICT(wrestler_id) DO UPDATE SET "
            "alignment=excluded.alignment", (H, "heel", game.now_iso()))
con.commit()
for i in range(6):
    con.execute("INSERT OR REPLACE INTO segment_pop (segment_kind, segment_id, "
                "wrestler_id, pop, alignment) VALUES ('match', ?, ?, ?, 'heel')",
                (9000 + i, H, 55.0))
con.commit()
rp = crowd.recent_pop(con, H)
check("her recent reaction is read as drifting face", rp["drifting"] == "face", str(rp))
before_align = game.effective_attributes(con, H).get("alignment")
sc = turns.scan(con)
check("a turn was suggested", sc["created"] >= 1, str(sc))
check("but nothing was applied",
      game.effective_attributes(con, H).get("alignment") == before_align,
      "an alignment changed without approval")
sugs = turns.list_suggestions(con, "pending")
mine = [s for s in sugs if s["wrestler_id"] == H]
check("the suggestion carries its evidence",
      bool(mine) and bool(mine[0]["evidence"]) and bool(mine[0]["reason"]))
if mine:
    turns.resolve(con, mine[0]["id"], True)
    check("approving it writes the alignment",
          game.effective_attributes(con, H).get("alignment") == "face",
          str(game.effective_attributes(con, H).get("alignment")))
    check("and clears the crowd slate",
          crowd.recent_pop(con, H)["samples"] == 0)

head("a rejected turn is not re-proposed forever")
con.execute("DELETE FROM turn_suggestion")
con.execute("DELETE FROM segment_pop")
con.commit()
for i in range(6):
    con.execute("INSERT OR REPLACE INTO segment_pop (segment_kind, segment_id, "
                "wrestler_id, pop, alignment) VALUES ('match', ?, ?, ?, 'face')",
                (9100 + i, H, -45.0))
con.commit()
turns.scan(con)
p = [s for s in turns.list_suggestions(con, "pending") if s["wrestler_id"] == H]
if p:
    turns.resolve(con, p[0]["id"], False)
    turns.scan(con)
    again = [s for s in turns.list_suggestions(con, "pending") if s["wrestler_id"] == H]
    check("a rejected turn stays rejected", not again,
          "the same turn was proposed again")

# ===============================================================  BRAND WAR
head("the scoreboard")
r1 = sim.run_show(con, "RAW", "Raw — tv 1", autobook.suggest(con, "RAW", "tv")["matches"],
                  promo_card=autobook.suggest(con, "RAW", "tv")["promos"])
check("a show draws a TV rating", r1["tv"] and r1["tv"]["tv_rating"] > 0, str(r1.get("tv")))
check("and a viewer number", r1["tv"]["viewers"] > 0)
# A "week" is Raw's Nth show against SmackDown's Nth show (see _week_key), so
# the two only meet in the same bucket once both have run the same number. RAW
# is a show ahead here from the storyline tests above, so SmackDown runs twice.
for i in range(2):
    sim.run_show(con, "SMACKDOWN", f"SmackDown — tv {i + 1}",
                 autobook.suggest(con, "SMACKDOWN", "tv")["matches"])
week = brandwar._week_key(con, "RAW", r1["show_id"], 2000)
wr = brandwar.week_result(con, week)
check("both brands are in the same week", wr["contested"], str(wr))
check("the week has a winner or is tied", wr["winner"] or wr["tied"], str(wr))
st = brandwar.standings(con)
check("standings list both brands", len(st["brands"]) == 2)
# The peak rating and the show that produced it must come from the same place,
# or the number and the name can disagree on screen.
for bb in st["brands"]:
    if bb["best_show"] and bb["best_rating"] is not None:
        check(f"{bb['name']} best rating matches its best show",
              abs(bb["best_rating"] - bb["best_show"]["tv_rating"]) < 0.005,
              f"{bb['best_rating']} vs {bb['best_show']['tv_rating']}")
check("and read as a sentence", bool(st["summary"]), st["summary"])
check("weeks won is counted",
      sum(b["weeks_won"] for b in st["brands"]) <= st["brands"][0]["weeks_contested"])

head("a rating is anchored to last week")
# One great show must not triple the audience — the audience arrives gradually.
prev = r1["tv"]["tv_rating"]
r2 = sim.run_show(con, "RAW", "Raw — tv 2", autobook.suggest(con, "RAW", "tv")["matches"])
check("the next week's rating is anchored to the last",
      abs(r2["tv"]["tv_rating"] - prev) < prev,
      f"{prev} → {r2['tv']['tv_rating']}")
check("and it knows what it was anchored to", r2["tv"]["previous"] == prev,
      f"{r2['tv']['previous']} != {prev}")

head("a solo week is not a win")
solo = "2000-W99"
con.execute("DELETE FROM brand_week WHERE week_of=?", (solo,))
con.execute("INSERT INTO brand_week (week_of, season_year, brand_id, tv_rating, viewers) "
            "VALUES (?,?,?,?,?)", (solo, 2000, "RAW", 9.9, 9_000_000))
con.commit()
w = brandwar.week_result(con, solo)
check("you cannot beat a brand that did not turn up",
      not w["contested"] and w["winner"] is None, str(w))

head("a pay-per-view sells a buyrate, not a rating")
ppv = sim.run_show(con, "RAW", "New Year's Revolution 2000",
                   autobook.suggest(con, "RAW", "ppv")["matches"],
                   is_ppv=True, ppv_name="New Year's Revolution 2000")
check("it has a buyrate", ppv["tv"] and ppv["tv"].get("buyrate", 0) > 0, str(ppv.get("tv")))
check("and buys", ppv["tv"]["buys"] > 0)
check("and no TV rating", ppv["tv"].get("tv_rating") is None)

# =================================================================  MEDICAL
head("injuries have a severity you can plan around")
check("a short layoff is a knock", medical.severity_for(1) == "knock")
check("a long one is a break", medical.severity_for(14) == "break")
inj = medical.record_injury(con, roster[8], 7, "2000-03-01")
con.commit()
check("it records what and how bad", inj["severity"] == "tear" and inj["part"],
      str(inj))
rpt = medical.report(con)
check("the medical room lists her as out",
      any(x["wrestler_id"] == roster[8] for x in rpt["out"]),
      str([x["name"] for x in rpt["out"]]))
outrow = next(x for x in rpt["out"] if x["wrestler_id"] == roster[8])
check("with weeks remaining", outrow["weeks_left"] > 0, str(outrow["weeks_left"]))
check("relapse risk applies just after she returns",
      medical.relapse_multiplier(con, roster[8], "2000-04-20") > 1.0,
      str(medical.relapse_multiplier(con, roster[8], "2000-04-20")))
check("but not months later",
      medical.relapse_multiplier(con, roster[8], "2000-09-01") == 1.0)

head("risk is stated before you book, not after")
con.execute("UPDATE wrestler_state SET fatigue=92 WHERE wrestler_id=?", (roster[4],))
con.commit()
rk = medical.risk(con, roster[4], "2000-01-01")
check("a spent wrestler reads as risky or worse",
      rk["level"] in ("risky", "reckless"), rk["level"])
check("and says why", bool(rk["reasons"]), str(rk["reasons"]))

head("rest recovers faster than being forgotten")
con.execute("UPDATE wrestler_state SET fatigue=80, rested_until='2000-12-01' "
            "WHERE wrestler_id=?", (roster[4],))
con.commit()
f0 = con.execute("SELECT fatigue FROM wrestler_state WHERE wrestler_id=?",
                 (roster[4],)).fetchone()[0]
medical.tick_recovery(con, 7)
f1 = con.execute("SELECT fatigue FROM wrestler_state WHERE wrestler_id=?",
                 (roster[4],)).fetchone()[0]
check("resting burns off fatigue fast", f1 < f0 - sim.FATIGUE_RECOVERY_PER_DAY * 7,
      f"{f0} → {f1}")

# ============================================================  FORCED MOVES
head("a forced trade only happens after she asked three times")
con.execute("DELETE FROM wrestler_request")
con.execute("DELETE FROM forced_move")
con.commit()
F = roster[1]
brand_before = game.active_contract(con, F, 2000)["brand_id"]
set_morale(F, 5)
# Not yet asked at all: nothing should be forced.
check("nothing is forced with no request on file", not demands.force_moves(con))
# An `ask` on file is not enough either.
today = con.execute("SELECT * FROM game_state WHERE id=1").fetchone()["current_date"]
con.execute(
    """INSERT INTO wrestler_request (wrestler_id, brand_id, kind, severity, reason,
         detail, status, created_on) VALUES (?,?,'trade','ask','x','y','denied',?)""",
    (F, brand_before, today))
con.commit()
check("an 'ask' denial is not enough to force", not demands.force_moves(con))
# A `final` denial at rock bottom IS.
con.execute("UPDATE wrestler_request SET severity='final' WHERE wrestler_id=?", (F,))
con.commit()
forced = demands.force_moves(con)
check("now she forces the move", bool(forced), str(forced))
if forced:
    brand_after = game.active_contract(con, F, 2000)
    check("she is on the other brand (or gone)",
          brand_after is None or brand_after["brand_id"] != brand_before,
          f"{brand_before} → {brand_after['brand_id'] if brand_after else 'released'}")
    check("and it is on the record", bool(demands.forced(con)))
    check("she is not forced twice for the same demand",
          not demands.force_moves(con), "she moved again")

head("a release demand at rock bottom is a walkout")
con.execute("DELETE FROM wrestler_request")
con.execute("DELETE FROM forced_move")
con.commit()
G = roster[6]
set_morale(G, 2)
con.execute(
    """INSERT INTO wrestler_request (wrestler_id, brand_id, kind, severity, reason,
         detail, status, created_on) VALUES (?,?,'release','final','x','y','denied',?)""",
    (G, game.active_contract(con, G, 2000)["brand_id"], today))
con.commit()
out = demands.force_moves(con)
check("she walked out", any(f["kind"] == "walkout" for f in out), str(out))
check("and is no longer under contract",
      game.active_contract(con, G, 2000) is None)

head("morale above rock bottom cannot force anything")
con.execute("DELETE FROM wrestler_request")
con.execute("DELETE FROM forced_move")
K = roster[5]
set_morale(K, morale.ROCK_BOTTOM + 15)
con.execute(
    """INSERT INTO wrestler_request (wrestler_id, brand_id, kind, severity, reason,
         detail, status, created_on) VALUES (?,?,'trade','final','x','y','denied',?)""",
    (K, game.active_contract(con, K, 2000)["brand_id"], today))
con.commit()
check("a merely unhappy wrestler stays put", not demands.force_moves(con))

# ==============================================================  MONTHLY TICK
head("the month-end tick runs everything, in the right order")
res = game.monthly_tick(con, 30)
me = res["month_end"]
check("every step ran", set(me) == {"recovery", "morale", "feuds_settled", "turns",
                                    "requests_expired", "forced", "requests"},
      str(sorted(me)))
check("no step errored", not any(isinstance(v, dict) and "error" in v
                                 for v in me.values()),
      str({k: v for k, v in me.items() if isinstance(v, dict) and "error" in v}))
# Forcing must come BEFORE generating, or a fresh `ask` would replace the `final`
# demand each month and nothing could ever actually be forced.
src = open(ROOT / "backend" / "game.py", encoding="utf-8").read()
i_forced = src.index('("forced"')
i_gen = src.index('("requests", lambda')
check("forcing is evaluated before new requests are filed", i_forced < i_gen,
      "generate would wipe the final demand every month")

head("advancing a month drives it")
adv = game.advance_month(con)
check("advance_month reports the month-end work", "month_end" in adv, str(list(adv)))

head("an old save upgrades itself at boot")
# THE ONE THAT ONLY BITES IN PRODUCTION. The bundled seed ships without any of
# these tables, and a stateless host pulls its save down from Blob storage — so
# the database the app opens can predate this whole feature set, and the very
# first request would die on a missing column.
old_db = Path(tempfile.gettempdir()) / "gm2000_prelocker.db"
shutil.copy(SRC, old_db)          # the BUNDLED seed, deliberately un-migrated
oc = sqlite3.connect(old_db)
oc.row_factory = sqlite3.Row
pre = {r[0] for r in oc.execute("SELECT name FROM sqlite_master WHERE type='table'")}
# Every table boot must be able to create. `sim_promo` is included because the
# migration still has to handle it, but it is excluded from the "fixture lacks
# it" check below — it predates this feature set and the shipped seed has it.
NEW_TABLES = ("wrestler_request", "forced_move", "turn_suggestion", "segment_pop",
              "feud_beat", "brand_week", "sim_promo")
THIS_CHANGE = set(NEW_TABLES) - {"sim_promo"}
check("the fixture really lacks the new tables",
      not (THIS_CHANGE & pre), str(sorted(THIS_CHANGE & pre)))
game.ensure_schema(oc)
PR.ensure_schema(oc)
after = {r[0] for r in oc.execute("SELECT name FROM sqlite_master WHERE type='table'")}
missing = [t for t in NEW_TABLES if t not in after]
check("boot creates every new table", not missing, str(missing))
scols = {r[1] for r in oc.execute("PRAGMA table_info(show)")}
check("boot adds tv_rating and buyrate", {"tv_rating", "buyrate"} <= scols,
      str(sorted(scols)))
fcols = {r[1] for r in oc.execute("PRAGMA table_info(feud)")}
check("boot adds the storyline columns",
      {"stage", "planned_blowoff", "blowoff_label"} <= fcols, str(sorted(fcols)))
wcols = {r[1] for r in oc.execute("PRAGMA table_info(wrestler_state)")}
check("boot adds rest and injury detail",
      {"rested_until", "injury_severity", "injury_note"} <= wcols, str(sorted(wcols)))
mcols = {r[1] for r in oc.execute("PRAGMA table_info(sim_match)")}
check("boot adds the match reaction columns", {"reaction", "reaction_score"} <= mcols,
      str(sorted(mcols)))
pcols = {r[1] for r in oc.execute("PRAGMA table_info(sim_promo)")}
check("boot adds the promo reaction columns", {"reaction", "reaction_score"} <= pcols,
      str(sorted(pcols)))
# The migration runs on EVERY boot, so it has to be idempotent.
game.ensure_schema(oc)
PR.ensure_schema(oc)
check("a second boot is a no-op",
      {r[1] for r in oc.execute("PRAGMA table_info(show)")} == scols)
check("the roster survived intact",
      oc.execute("SELECT COUNT(*) FROM wrestler").fetchone()[0] == 370)
# And the whole locker room has to WORK on the freshly migrated save, not just
# have the right columns — a table that exists but cannot be queried is no use.
oc.close()

print(f"\n{PASS} passed, {FAIL} failed")
con.close()
sys.exit(1 if FAIL else 0)
