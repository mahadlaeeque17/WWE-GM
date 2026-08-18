# WWE GM 2000 — Women's Division Simulation

A GM-mode wrestling simulation. The world resets to **January 2000**; you run a
two-brand women's promotion (Raw / SmackDown) with a draft, trades, contracts,
title lineages, simulated shows, and AI-generated storylines.

**Locked scope decisions:**

| Decision | Choice |
|---|---|
| Roster | Women-only league |
| Simulation | Deep sim — stamina, psychology, pacing, crowd heat, style clash, injury |
| AI role | Creative partner — storylines, promos, commentary, rival GM. Never decides match outcomes. |
| Deployment | Local-first: FastAPI + Vite/React + SQLite, launched from a desktop shortcut |
| AI provider | Groq |

## The rating system

Four categories, all editable, **each scored out of 25 — the four sum to a
0–100 overall**. Overall is a plain sum, not a weighted average, so the number
on screen is always the four beside it added up.

| Category | Source |
|---|---|
| **Experience** | Matches worked **in the sim**, not real life. Everyone starts at 0 and earns it. `30·log₁₀(matches+1)`, so the first twenty matches teach far more than the next twenty. |
| **Charisma** | Cagematch rating (quality) blended with vote count (reach). |
| **Popularity** | Vote count as the star-power proxy, lifted by championships won **before** 2000. |
| **Looks** | **Placeholder.** Cagematch has no looks field and no review category for it. Seeded near 50 with a mild pull toward the rating, and meant to be hand-edited. |

Your edits live in `attribute_override`, a separate table that `normalize.py`
never touches — so re-harvesting or retuning a formula cannot wipe a hand-tuned
roster. `COALESCE(override, derived)` decides the effective value; `NULL` reverts
to derived. Edited fields are marked ✎ in the UI.

**Age** is exact as of 1 January 2000, computed from date of birth (106 of 127
have a full DOB; 5 are year-only and shown as `~41`; 16 are unknown). Age drives
a value multiplier peaking at 28 — a youth premium above, a veteran discount
below, floored at ×0.35. It is why Moolah at 76 is worth $270k on a 51 overall
while Stacy Keibler at 20 is worth $900k on a 49.

## Money and contracts

Each brand gets a season budget that grows **6% a year**, NBA-cap style:
$10.00M in 2000, $10.60M in 2001, $18.98M by 2011. The cap is **hard** — a
signing that would exceed it is refused rather than allowed to go negative, and
a trade cannot be used as a back door around it.

Contract value is superlinear in overall (exponent ≈3) so the top of the roster
separates sharply from the middle, then scaled by the age multiplier. The curve
is anchored to real WWE 2006 payrolls scaled to a top women's promotion in 2000:
a marquee draw (overall ~70) commands ~$1.1M, the mid-card median (~44) ~$0.28M,
and enhancement talent floors at $40k. A signed contract is **locked** at its
value; her asking price keeps moving as she gains experience.

**The draft, restructured for the 2000 relaunch:** the wrestler draft runs **8
snake rounds → 16 picks, 8 per brand**; the manager draft **3 rounds → 6 picks,
3 per brand**. Picks split into pay tiers at the midpoint of the order —
**first-round picks pay a 25% premium, second-round picks a 30% discount** — so
a first-rounder costs "way more" than a depth pick. With realistic salaries a
full 8-wrestler + 3-manager roster commits ~$5.2M of the $10M cap, leaving room
to extend and re-sign.

### Contracts come only from the draft

There is no free agency — deliberately, and enforced at the API, which has no
signing endpoint at all. A contract is created one of two ways:

| | Rule |
|---|---|
| **Draft pick** | The only way a new contract is created. |
| **Extension** | Only for someone already under contract. A **one-year deal cannot be extended.** An extension cannot itself be extended. It starts the season after the current deal ends, and must fit that season's budget. |

Releasing a wrestler returns her to the draft pool.

### The draft

Open a draft from the Draft tab for the current season. Picks **snake** — Raw,
SmackDown, SmackDown, Raw, Raw… — so the brand picking second in round one picks
first in round two; straight alternation would hand the first brand a permanent
edge at every round boundary.

The pool is everyone **not currently on a brand roster**, which includes anyone
whose deal has lapsed. A brand that cannot afford anyone can **pass**.

---

## Running it

Double-click **WWE GM 2000** on the desktop, or `Start WWE GM 2000.bat` in this
folder. It opens two console windows (API and UI) and your browser.

| Piece | URL |
|---|---|
| UI | http://localhost:5180 |
| API | http://localhost:8010 |
| API health | http://localhost:8010/api/health |

The launcher checks `data/gm2000.db` exists, runs `npm install` on first launch,
and waits for the API to answer before starting the UI — Vite proxies `/api` to
the backend, so a UI that starts first would just error. Close both console
windows to stop.

Manual start, if you prefer:

```bash
cd backend && python -m uvicorn main:app --port 8010
```
```bash
cd frontend && npm run dev
```

### If the app behaves like your code changes did nothing

A previous uvicorn can survive its parent shell and keep holding port 8010. The
new one then fails to bind and exits, while the **old process keeps answering** —
so the UI looks alive but is serving stale code, and edits to `backend/*.py`
appear to do nothing. Uvicorn is started without `--reload`, so a running server
never picks up source changes either way.

The launcher clears both ports before starting. To check by hand:

```bash
netstat -ano | findstr "LISTENING" | findstr ":8010 "
```

A health check is not proof your build is live — confirm the server you think
you started is the one answering.

**Tabs:** Roster · **Draft** (wrestler *and* manager drafts) · **Raw** and
**SmackDown** (each brand in its own colour) · **Trades** (propose, approve,
reject) · Titles · **Rankings** (Power 25 + contenders) · **Progression**
(rating approvals) · League · Shows · Images.

### Look and feel

**Type:** Anton for display (wordmark, brand headers, overall scores), Barlow
Condensed for stats and labels — condensed keeps four columns of digits compact —
and Barlow for body. Loaded from Google Fonts, so **offline the app falls back to
system sans and looks noticeably plainer**. Say the word and they can be
self-hosted.

**Portraits are never cropped.** The source images are ~2:3, so:

- The panel hero uses `object-contain` over a blurred, darkened `object-cover`
  copy of the same shot. The whole image is always visible, and it fills the
  frame instead of floating in dead space.
- Row avatars are 3:4, not square. A square frame with `contain` would letterbox
  a portrait into a thin strip.
- Wrestlers without a photo get initials rather than a broken-image icon —
  most of the roster has none.

Multiple years for one wrestler produce year chips on the hero to flick between
them.

---

## Data source: cagematch.net

Note it is `.net`, **not** `.com`.

### What is verified to work

- **The WAF blocks scripted access.** `curl` and server-side fetch get a bare
  `307` with no body (Sucuri Cloudproxy). A real browser loads fine.
- **In-page `fetch()` works.** Running `fetch()` from inside the loaded page
  context inherits the challenge cookie and returns full HTML. This is the
  harvest mechanism — not page-by-page navigation.
- **Promotion IDs:** WWE = `1`, WCW = `2`, ECW = `3`. (AJPW = 6, NJPW = 7,
  TNA = 5, ROH = 4, AEW = 2287.)
- **4,241 female wrestlers** in the database, 100 per page = 43 pages.

### Endpoint map

| URL | Contents |
|---|---|
| `?id=2&view=workers&gender=f&s=<offset>` | Female wrestler index — id, name, DOB, birthplace, height, weight, rating, votes |
| `?id=2&nr=<id>` | Profile — alter egos (ring names), roles w/ year ranges, career start/end, style, trainer, rating + vote distribution |
| `?id=2&nr=<id>&page=9` | Title history |
| `?id=2&nr=<id>&page=4` | Match list |
| `?id=8&nr=<pid>&page=16` | Promotion all-time roster |
| `?id=8&nr=<pid>&page=17` | Promotion win/loss records |
| `?id=8&nr=<pid>&page=9` | Promotion title histories |

### Traps found

- **The `promotion=` filter on worker search only covers *active* promotions.**
  WCW and ECW return zero rows. They are not in the dropdown at all.
- **Even for WWE the promotion filter is not "ever worked here."** It returned 82
  women and omitted Lita, Chyna, Ivory, Moolah, and Wendi Richter. It reflects
  current association, not history. **Do not use it to build the roster.**
  Use promotion all-time roster pages (`page=16`) intersected with the female
  master index instead.

### Harvest etiquette

Single-operator hobbyist site. 700ms between requests, harvest once, cache raw
to `data/raw/`, re-parse from cache. Dataset stays local and is not republished.

---

## Two numbers that need care

**Win/loss records are a sample, not a ledger.** Cagematch's pre-2000 women's
coverage is TV/PPV-weighted; house shows are largely absent. A 400-match career
may show 40 results. Store `matches_recorded` alongside every record and treat
win% as a *booking-strength signal*, never as history.

**Ratings are noisy at low vote counts.** Many wrestlers of this era have <20
votes. Shrink toward the site mean before using a rating for anything:

```
adjusted = (v * R + m * C) / (v + m)      # m ≈ 25 votes, C ≈ 6.0
```

Vote count is itself the better **notability** proxy, and notability — not
rating — should drive contract value.

---

## Roster construction

Women active *in 2000* is thin (~15 WWF, ~12 WCW, ~6 ECW). The full 1980–2000
window is harvested instead, and each wrestler gets an availability state:

- **Active 2000** — starts on a brand. Trish, Lita, Chyna, Ivory, Molly Holly,
  Jacqueline, Torrie, Stacy, Francine, Dawn Marie, Jazz.
- **Legend / free agent** — signable at a discount, or usable as manager,
  trainer, or authority figure. Richter, Sherri, Blayze, Nakano, Sunny, Luna.
- **Import pool** — expensive, high-workrate international signings.
  Toyota, Hokuto, Aja Kong, Yoshida.

---

## Build phases

1. ✅ **Harvest** — in-browser collector → raw cache → normalized SQLite.
2. ✅ **Attribute engine** — the four categories plus age, all overridable.
3. ✅ **Sim core** — seeded RNG (same seed + same booking → same show). Match
   resolution, crowd heat, fatigue, injuries, momentum, title lineages.
   **No AI here**, so it stays deterministic and testable.
4. ✅ **GM layer** — budgets, contracts, free agency, releases, trades, season
   rollover.
5. ✅ **Groq AI layer** (`backend/ai.py`) — match commentary, show recaps, promos,
   feud pitches, and a rival-GM booker. Queries Groq `/models` at runtime and
   picks a strong + fast model (no hardcoded IDs). Reads sim state, **never
   writes match outcomes** — the rival GM only picks matchups, the deterministic
   sim still decides winners — so a failed API call cannot corrupt a save. Key
   in `backend/.env`, server-side only.
6. ✅ **UI** — React + TS + Tailwind + TanStack Query over FastAPI + Pydantic.
   Shows tab is now a booking hub: auto-book, **manual card builder**, and
   AI-GM booking, with per-match AI commentary and a show recap.

### How the sim reads the four categories

Match quality weights experience 0.45, charisma 0.30, popularity 0.15, looks
0.10 — and the best worker in a match pulls the floor up, which is what carrying
someone means. Crowd heat weights popularity 0.50 instead, because draw sells
tickets and workrate does not.

Because experience starts at 0, **early shows are deliberately rough** and climb
as the roster works. Measured: show 1 rated 46.7, show 21 rated 63.0. Flip
`SEED_EXPERIENCE_FROM_CAREER` in `harvester/attributes.py` if you would rather
start everyone at their real-career level.

## Images

Per wrestler, per year. Drop files in `data/images/inbox` and hit **Scan inbox**;
they file to `data/images/<wrestler_id>/<year>.<ext>`.

Filenames are matched leniently against **every ring name** — `Miss Congeniality
1999.jpg` files to Lita, `Mona 1999.jpg` to Molly Holly.

**The year is optional.** A file with no year is stored under year `0`, the
*default portrait*, used whenever there is no year-specific shot. So
`Trish Stratus.jpg` just works, and adding `Trish Stratus 2002.jpg` later takes
precedence automatically without disturbing the default. Only a file whose
*wrestler* cannot be identified is reported rather than guessed at.

## Removing wrestlers

**Remove from game** at the bottom of the wrestler panel. She disappears from
the roster, the draft pool and every brand; any live contract is terminated so
her salary stops counting against a budget, and the draft pick she was taken
with is freed.

It is a **soft delete** — a row in `excluded_wrestler`, not a `DELETE FROM
wrestler`. A hard delete would be undone the moment `normalize.py` rebuilt the
source tables from the harvest, silently repopulating the roster. Verified: a
removal survives a full re-normalize.

Removed wrestlers live behind the **Removed** filter on the Roster tab and can
be restored from the same panel. Their sim history is kept, so past shows still
read correctly.

### Google Drive — live

Wired to folder `1zGgyubKfJZ0QBtQABvH3l7E9XZIlD5Wl`, authorised via **OAuth**,
read-only. Hit **Sync** on the Images tab; already-pulled files are skipped, so
repeat syncs are cheap.

**Do not try to use a service account here.** This Google account enforces
`iam.disableServiceAccountKeyCreation`, and — as the NBA Alternate Universe
build found — even overriding that org policy hits a Google-managed
`KeyExposureResponse` policy that re-blocks key creation, with no user-facing
way around it. An API key is not an option either: it can only read *public*
files, and this folder is not link-shared.

OAuth Desktop clients are subject to neither restriction. `oauth_setup.py`
reuses the client already created for the NBA app, so there is no Google Cloud
console work at all:

```bash
cd backend && python oauth_setup.py
```

Opens a browser once, you click Allow, and a refresh token caches to
`backend/drive_token.json` (gitignored). Re-run it if the token is ever revoked.
The API server never launches a consent flow itself — that would hang a web
request waiting on a browser.

### Groq model selection

Do not hardcode model IDs from memory. Query Groq `/models` at setup and pick
from what is live on the account: a fast model for bulk generation, a stronger
one for storyline reasoning. Key lives in `.env`, gitignored from commit one.


---

## Championships

Seven belts. `brand_id` NULL means shared between both brands.

| Tier | Belt | Scope |
|---|---|---|
| World | Raw Women's World Championship | Raw |
| World | SmackDown Women's World Championship | SmackDown |
| Secondary | Raw Women's Intercontinental Championship | Raw |
| Secondary | SmackDown Women's United States Championship | SmackDown |
| Tag | World Women's Tag Team Championship | Shared, 2-woman |
| Cruiserweight | Women's Cruiserweight Championship | Shared, ≤62 kg |
| Hardcore | **Queen of Extreme Championship** | Shared, no-DQ |

Names are era-honest: WWF ran Intercontinental in 2000, WCW ran United States,
Television and Cruiserweight, and "Queen of Extreme" was ECW's own phrase for
Francine. The 62 kg cruiserweight limit puts ~31 of the roster in the division —
weights come from cagematch, and an *unknown* weight is never a disqualification.

## Accomplishments

Eight awarded by the sim (Royal Rumble, Money in the Bank, Queen of the Ring,
WrestleMania appearance and main event, Survivor Series sole survivor, Iron Woman,
Grand Slam) and nine recorded by hand (Playboy cover, Babe of the Year, Woman of
the Year, Match of the Year, Feud of the Year, Most Improved, Rookie of the Year,
Hall of Fame, Slammy).

Grand Slam is derived, not manual — it fires automatically once she has held
every singles title.

## Roles and the manager draft

Every wrestler is **wrestler**, **manager**, or **both**, derived from cagematch's
Roles field and overridable.

That field is **incomplete** for part of the roster — Meiko Satomura's whole
string is `"Promoter"`, Molly Holly's is `"Road Agent"` — so trusting it alone
turned real wrestlers into managers. Recorded match count is the cross-check and
wins: 10+ matches means she wrestles whatever the string says, and the default
when nothing is conclusive is *wrestler*, because missing data should not demote
anyone.

Managers get their **own draft** with its own picks and pool. `both` appears in
either. They are paid on presence — charisma 55%, popularity 35%, looks 10%, and
experience not at all — at roughly a third of a wrestler's rate, but it still
comes out of the same budget.

## Trades

Proposed, then **you approve or reject**. Nothing moves until you accept, and an
accepted trade still has to leave both brands under the cap. Assets can be mixed:

- **wrestlers** — the contract travels with her
- **draft picks** — including future seasons, tracked in `pick_asset` so a pick
  can change hands before that draft even exists
- **cash** — held in `brand_cash`, on top of the salary budget

## Images

A **gallery**, not one slot per year. Files keep their original name under
`data/images/<id>/`; the old `<year>.jpg` scheme silently overwrote a second
photo from the same year.

Click any image in the wrestler panel to make it her **profile portrait** — the
shot used on roster rows, the draft board and the panel hero. A partial unique
index guarantees exactly one profile per wrestler.

Duplicates are caught by **content hash**, not filename, so the same photo
uploaded twice under different names is collapsed. That pass removed 55 leftovers
from the old naming scheme on first run.


---

## Roster batches

The roster is built in additive batches, each its own idempotent script under
`harvester/`. Nothing is ever rewritten — a batch only inserts what is missing.

| Batch | Script | Adds |
|---|---|---|
| 1 | `normalize.py` | 127 women with a WWE/WCW/ECW promotion-year in 1980-2000 |
| 2 | `add_2001_2005.py` | the 2001-2005 class, with nicknames and bios |
| 3 | `add_active_2001_2005.py` | joshi, lucha, WOW and indie depth for the same window |
| 4 | `add_2005_2010.py` | **97** women *active* 2005-2010 |

**Batch 4 is "active in the window", not "debuted in the window"** — that was the
brief, and it is why Estrellita (debut 1998) and Devil Masami (debut 1979) are in
it while nobody already on the roster is duplicated.

Coverage: WWE/ECW Divas era (Layla, Kelly Kelly, Maryse, Eve, Alicia Fox, the
Bellas, AJ Lee, Kaitlyn, Naomi, Tamina, Taryn Terrell, Vickie Guerrero) · TNA
Knockouts (Madison Rayne, Lacey Von Erich, Sarah Stock, Brooke Adams, Karen
Jarrett) · ROH/SHIMMER and the US indies (Athena, Mia Yim, LuFisto, Jessicka
Havok, Allysin Kay, Santana Garrett, Ivelisse, Kimber Lee, Heidi Lovelace) ·
Europe and Australasia (Britani Knight, Alpha Female, Shanna, Madison Eagles,
Jessie McKay, Tenille Dashwood, Toni Storm, Evie) · joshi (Io Shirai, Hikaru
Shida, Riho, Syuri, Arisa Nakajima, Kagetsu, Ryo Mizunami, Mariko Yoshida) ·
CMLL/AAA (Sexy Star, Princesa Sugehit, Estrellita, Zeuxis).

Two scope notes, honestly:

- **AEW (2019) and SHINE (2012) did not exist in 2005-2010.** They are covered by
  the *wrestlers* — the women working the indies and Japan then who later built
  those rosters — which is the only way to honour "active during 2005-2010".
- **WOW was dormant across the whole window** (it ran 2000-01 and relaunched in
  2012), so batch 4 adds nobody new for it. Its 2000-01 roster is already in
  batch 3.

### Why nothing duplicated

Matching is on `wrestler.name` **and every `ring_name`**, because a gimmick
change is not a new person. Without it the batch would have re-added Angelina
Love (on the roster as Angel Williams), Velvet Sky (Talia Madison), Taylor Wilde
(Shantelle Taylor), Tara (Victoria), Alissa Flash (Cheerleader Melissa) and
Sarita (Sarah Stock). Batch 4 also *records* future ring names — Paige, Emma,
Billie Kay, Allie, Rosemary, Ruby Riott, Ember Moon — so batch 5 matches on them.

`draft_class` is clamped to `[2005, 2010]`. The class is the season she enters
the draft pool and the game starts in 2000, so a 1997 debut cannot be given a
1997 class — those seasons are gone.

---

## Power 25

A weekly, cross-brand top 25 in the shape of the old WWE.com board: rank,
movement, superstar, last week, and one line of copy explaining the move.

**Each week is a published ISSUE, not a live query.** `last_week` and the arrows
are *history* — recomputing them on read would rewrite the past every time the
roster changed. An issue is written automatically at the end of every show, and
`Rebuild current issue` only republishes the current week.

Scoring is a rolling **35-day window**. Per match: win/draw/loss (a loss to the
reigning champion barely counts), match quality against a 50 baseline, a title
match bonus, a big bonus for winning a belt and a smaller one for retaining —
then multiplied by card position (main event ×1.6, semi ×1.25), PPV (×1.5) and
recency. On top of the matches sit the standing terms: momentum, popularity as
star power, live feud heat, and every belt she holds scaled by its prestige.
Work nothing all month and the whole score is multiplied by 0.55.

The blurb is built from facts, never generated — and **movement picks the
sentence**, so a champion who is *falling* is not congratulated on the belt.

## Championship rankings

A separate ladder per belt, because the Power 25 is belt-blind. The eligible
pool respects brand exclusivity, the cruiserweight weight limit and the signed
role (the Manager's Championship is contested by managers), excludes the current
champion, and excludes anyone already holding a **higher-tier** belt — a world
champion is not chasing the secondary title.

Score is power standing, recent form, drawing power, and a **title-shot drought
bonus** so the same two names do not sit on top forever. A `TIER_BAND` term pulls
the top of the board toward the world title and the mid-card toward the mid-card
belt, which is what stops every ladder coming out in the same order.

Rank 1 is the **#1 contender**. You can override it — `Pin #1` names a contender
by hand, and the pin outranks the computed ladder from the next issue on without
rewriting issues already published.

## Rating progression

Charisma, popularity and looks now **move**. (Experience is not here: it is
already earned in the sim and updates itself — those three were the ones frozen
forever at their seeded value.)

At every season rollover the engine grades each signed wrestler's year into a
0-100 **season score**: win rate, match quality *relative to the league that
season*, how often she headlined, PPV rate, title reigns, weeks in the Power 10
and Power 25, award nominations, momentum and feud heat. Both the "relative to
the league" and the rate-not-total parts matter — quality drifts upward across a
save as experience accrues, and counting main events as raw totals made the grade
depend on how many shows you happened to run.

That score becomes per-category deltas, scaled by an age band — 25 and under
improves fast and rarely regresses, 38 and over fades hard. Popularity is the
most volatile (exposure), charisma moves at half the rate (quality, heat,
recognition), looks barely moves at all. Working **no matches all year** is a
guaranteed regression. Caps: ±3 per category, ±6 overall per season, floors and
ceilings at 1 and 25.

**Nothing is applied.** Every move lands on the **Progression** tab as a pending
suggestion with its evidence attached, and only you can approve it — one at a
time, in bulk, or **at a number you edit yourself**. Rejecting changes nothing.
Approved values are written to `attribute_override`, the layer `normalize.py`
never touches, so they survive a re-harvest and show with the ✎ marker like any
hand edit. Re-running the grader replaces only *pending* rows and never
resurrects a decision you already made.

There is deliberately no endpoint that lets the engine write a rating directly.
