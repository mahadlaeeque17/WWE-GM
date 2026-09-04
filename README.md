# WWE GM 2000

A GM-mode women's wrestling simulation. The world resets to **January 2000** and
you run a two-brand women's promotion — draft, contracts, trades, title lineages,
simulated shows, weekly power rankings, and an AI creative partner.

FastAPI + SQLite on the back, React + TypeScript + Tailwind on the front, run
locally from a desktop shortcut.

## Running it

```bash
cd backend && python -m uvicorn main:app --port 8010
```
```bash
cd frontend && npm install && npm run dev
```

UI on <http://localhost:5180>, API on <http://localhost:8010>. On Windows,
`Start WWE GM 2000.bat` does both and opens the browser.

The AI layer needs a Groq key in `backend/.env`:

```
GROQ_API_KEY=your-key-here
```

Everything else works without it — the simulation is deterministic and never
asks the AI to decide a match.

## What's in here

| Path | |
|---|---|
| `backend/` | FastAPI app — sim, GM layer, rankings, AI endpoints |
| `backend/morale.py` | How every wrestler feels, and why |
| `backend/demands.py` | What she asks for, and what she does when refused |
| `backend/storylines.py` | Feuds as stories: beats, stages, planned blow-offs |
| `backend/turns.py` | Face/heel turns the crowd asks for, you approve |
| `backend/crowd.py` | Segment reactions, and how the crowd took each woman |
| `backend/brandwar.py` | TV ratings, buyrates, and who is winning |
| `backend/medical.py` | Injury severity, relapse risk, deliberate rest |
| `backend/ringside.py` | What a manager at ringside is worth to a match |
| `backend/revise.py` | Overruling a result, and putting back what it paid out |
| `backend/advice.py` | What is wrong with a card, before you run it |
| `backend/season.py` | The year in one page. Read-only, entirely derived |
| `frontend/` | Vite + React UI |
| `harvester/` | Roster construction and the attribute engine |
| `data/gm2000.db` | The save: the seeded, hand-tuned roster |
| `PLAN.md` | Design document — every rule and why it is that rule |
| `DEPLOY.md` | Hosting — it runs free on Vercel, and how the save survives |
| `harvester/NOTES.md` | Data quirks and traps. Read before trusting a number |
| `test_shows.py` | The show format, match types and promos, end to end |
| `test_locker.py` | Morale, requests, forced moves, storylines, the ratings war |
| `test_control.py` | Result overrides, ringside managers, storyline kinds |
| `test_qol.py` | The save write-barrier, card review, undo, ideas, the season |

## The show format

Every night runs to a shape, and it arrives **pre-booked** — the card screen
opens on a full show that creative has already put together, and your job is to
decide what is wrong with it.

| Show | | |
|---|---|---|
| Raw · Monday, SmackDown · Friday | 4 matches | 2 promo segments |
| Saturday Night's Main Event — **two a month** | 4 matches | 2 promo segments |
| Pay-per-view · last Sunday | 6 matches, **3 from each brand** | 2 promo segments |

The pre-booker works in priority order: **rivalries first** (a feud at blow-off
heat gets a stipulation to match), then **belts** on the biggest match, then
**face against heel**, ordered so **star power climbs** to the main event, with
**stamina respected** and shapes mixed. Every row tells you why it is there, and
every row is one dropdown away from being something else.

**Match structures** are a separate axis from **stipulations**, so they compose —
a Fatal 4-Way inside a Steel Cage needs no entry of its own.

- Structures: Singles, Tag (2 v 2), Six-Woman Tag (3 v 3), Triple Threat,
  Fatal 4-Way, Triple Threat Tag, Handicap, Gauntlet, Battle Royal
- Stipulations: Submission, No DQ, Tables, Hardcore, Steel Cage, Ladder,
  Last Woman Standing, Extreme Rules, TLC, Iron Woman

In a multi-corner match only the woman who **takes the fall** is treated as
beaten — protecting the other losers is most of the reason to book the shape.

## Promos

Talking is the cheap way to build a rivalry — almost no stamina, no injury risk —
and a match is the expensive way to cash it in. That trade-off is why two promo
slots sit on every card. Ten types, each with its own effects: a **contract
signing** builds a lot of heat, a **run-in beatdown** swings momentum hard toward
the aggressor, a **title presentation** adds prestige to the belt. A promo is
scored on **mic work** first, so a roster has two kinds of value, and it counts
toward the show rating at half the weight of a match.

A woman on the injury shelf can still come out and talk, which is how a feud
survives an injury instead of dying with it.

## The locker room

Every wrestler has an opinion about working here, and she will tell you.

Morale used to move only as a side effect of a match. Now it **drifts each month**
from standing conditions, and every one of them explains itself in words with the
lever that fixes it:

| | |
|---|---|
| **Pay** | Her salary against her market rate. The biggest single factor. |
| **Booking** | Is she on television at all? And is she being run into the ground? |
| **Spotlight** | Main events and title shots — whether she is going anywhere. |
| **Results** | Losing constantly wears anybody down. |
| **Promises** | The perks written into her deal, checked against what happened. |
| **Stamina** | Worked flat out with no rest. |
| **Storyline** | Does she have a rivalry, i.e. a reason to be there? |

Her **personality** decides how the same slight feels: money-hungry feels an
underpayment nearly twice as hard, ambitious shrugs at the money and cares about
the spotlight, loyal absorbs almost anything, a prima donna amplifies everything.

### She asks before she acts

Wrestlers come to you wanting a **raise, a title shot, a push, time off, a
storyline, a character change, a trade** or **their release**. Refuse or ignore
one and she gets firmer — `asking` → `insisting` → `final warning` — and the
final ask says in plain words what she will do instead. Escalation tracks *her
patience*, not the topic, so changing the subject does not reset it.

At **rock bottom morale (10)**, a wrestler whose final trade or release demand
was refused **carries it out herself**: she forces a move to the other brand, or
walks out of the company for nothing. By that point you have turned her down
three times and been warned twice, which is what makes it fair rather than
random.

Granting is never free. A raise rewrites the contract and eats cap space (you can
meet her part-way). Time off makes her genuinely unbookable. A title shot pins the
contender ladder. A push is a promise that gets checked.

Five new requests a month at most — an in-tray of eighteen is a wall, and a wall
gets ignored. The rest wait their turn, urgent ones first.

## Contracts are negotiated, including extensions

Re-signing used to be a button that paid her asking price. Now salary, **length**
and perks are all put to her together and she can accept, counter, be insulted, or
walk away from the table.

Her price comes from a **retention** position rather than a market one, which is
where the drama is:

- **happy** → re-signs about 16% *under* what it would cost to sign her cold
- **neutral** → a small loyalty discount
- **unhappy** → wants about 22% *over* market, because leaving is what she
  actually wants

Length is a real term: somebody young and rising charges to be locked down, a
veteran takes less for the security. Floating a sensible offer costs nothing, but
an insulting one burns her patience — and at zero she walks and sees out her deal.

## Storylines

A feud is a story, not a heat counter. Every match, promo, run-in and turn between
two women is recorded as a **beat**, so the save knows she has beaten you twice
and the booker can reason about what should happen next. Each rivalry has a
**stage** — build → escalation → ready to blow off — that decides what kind of
segment the pre-booker reaches for.

The important part: **point a feud at a pay-per-view and the booker withholds the
singles match.** It books promos, run-ins and tag matches that keep the two apart
until the date instead. Anyone can book the blow-off tonight; the skill is not
booking it tonight.

## Face and heel turns

Two things are measured about every segment, and keeping them apart is the whole
design:

- **Reaction** — how hot the segment was. Quality counts but does not dominate,
  so a technically fine match nobody is invested in reads *flat*, and an ordinary
  match between two stars in a blood feud reads *hot*.
- **Pop** — how the crowd took one woman, booed to cheered. Not a measure of how
  well she did: a heel being loudly booed is a heel doing her job.

The interesting number is the **mismatch**. A heel so over the crowd cheers her
anyway is the most famous thing in wrestling booking, and it is only detectable
because those two are measured separately. Turns are also triggered by a
**betrayal** (a face laying out another face in a run-in), a long **losing run**,
or simply having **gone stale**.

Nothing ever turns on its own — the engine files a suggestion with its evidence
and waits for you, the same rule rating progression follows.

## The ratings war

Money is a constraint, not a score: you can bank a fortune running a terrible show
in a small building. So every television night draws a **rating** and every
pay-per-view sells a **buyrate**, built from the audience you already have, what
you put on, who was on it, and the storylines going in — then anchored to last
week, because an audience arrives and leaves gradually. One great show cannot
triple it; a run of them will.

When both brands have run the same number of shows, the higher rating **wins the
week**. Weeks won is the season table. A week with only one brand in it is
deliberately not a win — you cannot beat somebody who did not turn up.

## Injuries and rest

An injury has a **severity** (knock, strain, tear, break), a body part, an
expected return, and a **relapse risk** that lingers after she is back — so
rushing somebody back is a real gamble. Before you book anyone you can see how
dangerous it is and why: *"stamina down to 14/100, just back from a tear, 39
years old."*

**Resting** somebody is a decision, not an accident: she recovers at over twice
the rate of simply being left off the card, and she is unbookable while it lasts.
Booking through time off you granted is refused.

## Results are yours to overrule

Every match shows who won, who lost, how it finished, who was at ringside and a
**star rating** out of five. And you can overrule any of it — the winner, the
finish, the stars. The engine simulates, you decide; that is how ratings
progression, turns and the pre-booked card already worked, and results were the
last place it did not.

An override puts back what the old result paid out: the win/loss records, the
momentum swing, the championship if that match awarded one, and the storyline
beat that said "she beat her via pinfall". Changing the stars re-scores the night
and its TV rating with it. What it does *not* do is re-simulate later shows that
were booked off the old outcome — the screen says so, and every override is kept
on the record.

## Managers actually do something

A manager at ringside is not decoration. She does three separate things:

| | |
|---|---|
| **Lifts her side** | Influence is "how much she elevates whoever she stands beside", so it feeds her side's strength — up to about +9%. Enough to tilt a close match, never enough to overturn a talent gap. |
| **Lifts the match** | Mic work adds crowd investment, for *both* sides' seconds. A good manager opposite a good manager is a better match than neither. |
| **Interferes** | The one place she changes the winner outright rather than nudging the odds. Rare, weighted heavily toward heels, and always reported — a stolen match never looks like a bug. |

Add or remove one per side on **any** match, not just the Manager's
Championship. She is not a participant: no fatigue, no injury risk, no win or
loss on her record, and she can second a match on a night she also wrestles.

Anyone the sim would refuse is refused *before* it runs — a manager who is in
the match, seconding both sides, or who is not somebody who manages. A silent
no-op would have you believing she was working.

## Storylines are not all rivalries

Four kinds, and the difference is mechanical rather than cosmetic:

| | | |
|---|---|---|
| ⚔ **Rivalry** | *heat* | They want to fight. Build with promos, pay off with a match. |
| ❤ **Romance** | *investment* | A couple on screen. Segments build it. |
| 🤝 **Alliance** | *trust* | Same side. The booker puts them in a tag as **partners**. |
| 🎓 **Mentorship** | *bond* | A veteran bringing somebody up. |

Only a rivalry wants a match. Booking a couple against each other *breaks* the
story, so the pre-booker will not do it — it books romances into segments and
alliances into tag matches on the same side. Managers count: a romance between a
manager and the woman she manages is one of the most useful things on the list.

**Turning one sour is the payoff, not a failure.** A break-up, a betrayal or a
student turning on her teacher converts a story the crowd is already invested in
into a rivalry that starts *hot* — strictly better than opening a cold feud
between the same two people. The new rivalry remembers what it used to be.

## Auto-book is opt-in

The card screen opens **empty**, in the format's shape — four match rows and two
promo slots, six on a pay-per-view — and you fill it. Booking a card from
scratch is the game, so the pre-booked suggestion is a button you press
(*Pre-book it for me*) rather than something that has already happened to your
card. The choice is remembered.

## Show night

Confirming a card walks you through it: each press reveals the next segment with
its result, its rating and how the crowd took it. The night's rating is withheld
until the end, because that is what it is — the verdict on the whole card, not a
number that was already true when the opener started. Skippable, and it can be
re-read as a table any time.

## The card tells you what is wrong with it

The sim refuses an **illegal** card — a half-filled Fatal 4-Way, somebody booked
twice, a woman on the injury shelf. Far more common is a card that is perfectly
legal and simply bad, and the review catches those before you run it:

- the same match for the third week running
- somebody who has worked every show, or who is risky to book at all
- a title match with no rivalry behind it
- a card with no face-vs-heel conflict anywhere
- an opener with more star power than the main event
- a blow-off you are building to, given away early
- a romance booked against itself
- a rivalry at 90 heat left off the card entirely

Every finding names a fix. It is **advice, not a gate** — confirm anyway if you
disagree, because you are the one booking the show.

## Undo

A result override can be put back exactly as the simulation left it — the
revision log records the *from* value, so undo replays it rather than guessing.
A granted request can be taken back too: the change is reversed, the goodwill is
taken back, and she goes back into the in-tray still asking. A trade or a release
cannot be undone, and the screen says where to handle those instead rather than
pretending.

## Stories you are missing

The locker room proposes requests and the crowd proposes turns; nothing proposed
**stories**. Press *Ideas* and the engine reads the roster for pairings worth
opening — opposite alignments at a similar level for a rivalry, a manager and the
woman she stands beside for a romance, a big age-and-ability gap for a
mentorship — each with the reason, one click to start. Capped at two storylines
per person, so it cannot bury a roster in feuds.

## The season

One page for "what happened in 2003?": match of the year, story of the year,
biggest rating and buyrate, who broke out, the workhorse, every title change,
turns, walkouts and awards. Entirely read-only and derived from the save's own
records, so it can never disagree with the data behind it.

## Wrestler, manager, or both

Some women can do either job. For anyone marked **Wrestler + Manager**, you pick
which one she is *doing* from a dropdown on her panel, and she stays that until
you switch her back.

The switch is one decision with two halves, because either half alone would be a
lie:

- **Her ratings change system.** A manager is scored on **Mic** and **Influence**
  where a wrestler gets **Wrestling** and **Popularity**. Switching her re-rates
  her card, her radar, her overall and her contract value — and the sliders you
  edit her with follow, so you are never editing a number nothing is showing you.
- **Her eligibility changes.** Working as a manager she cannot be booked in a
  match (the pre-booker leaves her out and the sim refuses a hand-booked one),
  she becomes available for the Manager's Championship, and she moves from the
  wrestler draft pool to the manager pool.

This is deliberately separate from three things it could be confused with:

| | |
|---|---|
| **capability** (`role`) | what she is *able* to do — wrestler, manager, or both. Overwriting this to say "she is managing" would destroy the fact that she can also wrestle, leaving no way back. |
| **this season's draft** | a per-season pin that only scopes which draft pool she enters. Wiped every rollover. |
| **contract role** | what she was actually *signed* as, which is the deal and does not change underneath her. |

A wrestler who is not `both` cannot be switched — pinning a pure wrestler to
"manager" would be a rating system she has no numbers for.

## The rating system

Five categories, each out of 20, summing to a 0–100 overall.

- **Achievements** — earned in *your* save, not from real life. Everyone starts
  at 0; you raise it by winning things, never by typing a number.
- **Wrestling** — in-ring ability. What you edit is the stored base; the number
  shown adds a live swing from her win/loss record in this save.
- **Popularity**, **Looks**, **Personal** — seeded from the source data (Looks and
  Personal are yours outright) and fully editable.

Wrestling and Popularity *move*: the progression engine grades a season from what
actually happened — record, match quality against the league, main events, title
reigns, Power 10 weeks, promo work — and **proposes** growth or regression.
Nothing reaches a rating until the GM approves it, and she can approve it at a
different number.

Your edits live in a separate `attribute_override` table that the roster
rebuild never touches, so re-running the harvest cannot wipe a hand-tuned
roster.

## Power 25 and contenders

A weekly cross-brand top 25 in the shape of the old WWE.com board — rank,
movement, last week, and a line of copy explaining the move. Each week is a
stored *issue*, not a live query, because last-week and the arrows are history.

Alongside it, a contender ladder per championship that respects brand
exclusivity, weight limits and signed role, and names a #1 contender you can
override by hand.

## Deploying it

The whole thing runs on **Vercel's free plan** — frontend as static files, the
FastAPI backend as a Python function, and the save in Vercel Blob.

Free hosting is stateless, and this game *is* a SQLite file that gets written on
every action, so `backend/store.py` pulls the database down at boot and pushes it
back after each write. The app itself talks to ordinary local SQLite throughout —
no query anywhere changed. `smoke_store.py` proves it by deleting the entire
filesystem between two boots and checking the save comes back.

See `DEPLOY.md`.

## Data

The roster is derived from a one-time cagematch.net harvest, cached locally and
re-parsed offline. **The raw scrape is not republished** — only the game database
built from it ships here. See `harvester/NOTES.md`.

Wrestler portraits and brand/belt art are not included; drop your own into
`data/images/inbox` and `data/logos`. Without them the app draws its own
original emblems and shows initials.
