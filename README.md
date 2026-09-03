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
| `frontend/` | Vite + React UI |
| `harvester/` | Roster construction and the attribute engine |
| `data/gm2000.db` | The save: the seeded, hand-tuned roster |
| `PLAN.md` | Design document — every rule and why it is that rule |
| `DEPLOY.md` | Hosting — it runs free on Vercel, and how the save survives |
| `harvester/NOTES.md` | Data quirks and traps. Read before trusting a number |

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
