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
| `data/gm2000.db` | The save: 270 wrestlers, seeded and hand-tuned |
| `PLAN.md` | Design document — every rule and why it is that rule |
| `DEPLOY.md` | Hosting notes, and why the backend cannot be serverless |
| `harvester/NOTES.md` | Data quirks and traps. Read before trusting a number |

## The rating system

Four categories, each out of 25, summing to a 0–100 overall.

- **Experience** — earned in *your* sim, not from real life. Everyone starts at 0.
- **Charisma**, **Popularity**, **Looks** — seeded from the source data, fully
  editable, and now they *move*: the progression engine grades each season and
  proposes growth or regression, which only the GM can approve.

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

## Data

The roster is derived from a one-time cagematch.net harvest, cached locally and
re-parsed offline. **The raw scrape is not republished** — only the game database
built from it ships here. See `harvester/NOTES.md`.

Wrestler portraits and brand/belt art are not included; drop your own into
`data/images/inbox` and `data/logos`. Without them the app draws its own
original emblems and shows initials.
