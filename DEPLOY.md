# Deploying WWE GM 2000

The app has three moving parts:

| Part | What it is | State it holds |
|---|---|---|
| **Frontend** | Vite + React static bundle | none — pure static files |
| **Backend** | FastAPI (`backend/`) | **writes constantly** to SQLite |
| **Data** | `gm2000.db` + `images/` | the entire save + portraits |

## The one thing to understand before Vercel

**Vercel cannot host the backend.** Vercel's Python runtime is *serverless*: each
request runs in a fresh, throwaway container with a **read-only filesystem** (only
`/tmp`, wiped between requests). Our whole game *is* a SQLite file that must
persist every draft pick, contract, show and title change — plus a folder of
images. On Vercel serverless that state evaporates between clicks.

So: **frontend on Vercel, backend on a host with a persistent disk.** That is the
shape below, and it needs no rewrite — the code already supports it.

---

## Deploy — frontend on Vercel, backend on Render

### 1. Backend → Render

The repo has a **`render.yaml`** blueprint. In the Render dashboard:
*New → Blueprint*, point it at `mahadlaeeque17/WWE-GM`, and it reads the file.

It provisions a web service from `backend/` with a **1 GB disk mounted at
`/var/data`**, health-checked on `/api/health`.

> **Plan note.** Persistent disks require a **paid instance type** on Render — a
> free web service has an ephemeral filesystem and would lose the save on every
> restart, which defeats the point. `render.yaml` therefore specifies `starter`.
> Fly.io offers volumes more cheaply if that matters; the app is host-agnostic,
> only the config file changes.

Two env vars are marked `sync: false`, so Render will prompt for them:

| Var | Value |
|---|---|
| `GM2000_CORS_ORIGINS` | your Vercel URL, e.g. `https://wwe-gm.vercel.app` |
| `GROQ_API_KEY` | the key from your local `backend/.env` |

Leave `GROQ_API_KEY` unset if you don't want the AI layer in production —
everything else works without it, because the simulation is deterministic and
never asks the AI to decide a match.

### 2. Frontend → Vercel

*New Project* → import `mahadlaeeque17/WWE-GM`. The repo's **`vercel.json`** sets
the build (`cd frontend && npm install && npm run build`) and the output
directory (`frontend/dist`), so there are no settings to change.

Add one environment variable:

| Var | Value |
|---|---|
| `VITE_API_BASE` | your Render URL, e.g. `https://wwe-gm-2000-api.onrender.com` |

**This is baked in at build time, not read at runtime** — set it *before* the
first build, or redeploy after adding it, or the bundle ships with an empty API
base and every call 404s against Vercel itself.

### 3. Close the loop

The two services each need the other's URL, so one of them is always deployed
first with a placeholder:

1. Deploy Render, note its URL.
2. Deploy Vercel with `VITE_API_BASE` = that URL.
3. Go back to Render, set `GM2000_CORS_ORIGINS` = the Vercel URL.

Skipping step 3 gives you a UI that loads and then fails every request with a
CORS error in the console — the classic symptom, and it looks like the backend
is down when it is not.

---

## How the data directory works

`backend/paths.py` resolves everything the app writes:

```
GM2000_DATA_DIR=/var/data     # moves db + images + logos onto the mounted disk
GM2000_DB=/path/to.db         # overrides just the database (used by the tests)
```

Unset, both fall back to `data/` beside the code, so **local development is
unchanged**.

On a host, the disk starts **empty** — and the API refuses to serve without a
database, so a naive first deploy comes up 503 and stays there. `seed_data_dir()`
handles that: on startup it copies the bundled `data/gm2000.db` (the seeded
270-wrestler roster) onto the disk **once**. If a save is already there it is left
completely alone, because that file is now the live game and the bundled one is
only a seed.

Verified both ways locally against a fake mount: first boot logs
`seeded /var/data/gm2000.db from …` and reports 270 wrestlers; a restart after
starting a new game does *not* re-seed and the running save survives intact.

## What the code already does for deployment

- `frontend/src/api.ts` reads **`VITE_API_BASE`** — empty in dev (Vite proxies
  `/api` → `localhost:8010`), set to the backend origin in production. All API
  calls *and* image URLs go through it.
- `backend/main.py` reads **`GM2000_CORS_ORIGINS`** (comma-separated) and adds
  them to the allow-list.
- `backend/paths.py` reads **`GM2000_DATA_DIR`** / **`GM2000_DB`**.
- `backend/requirements.txt` pins the Python deps.
- The **Groq key stays server-side** — backend env only, never in the frontend
  bundle. The browser only ever calls our own `/api/ai/*` endpoints.

## If you'd rather run everything on Vercel

That means swapping the storage layer, and it is a real chunk of work rather
than config:

- **SQLite → Postgres** (Neon / Vercel Postgres). Every `sqlite3` call in
  `main.py`, `game.py`, `sim.py` and `rankings.py` gets ported. Mechanical, but
  it touches a lot — and the raw SQL uses a few SQLite-isms (`INSERT OR IGNORE`,
  `ON CONFLICT DO UPDATE`, partial unique indexes) that need translating.
- **`data/images/` → object storage** (Vercel Blob / S3), with the image
  endpoints streaming from the bucket.

Then the backend can run as Vercel Python functions. Say the word and I'll scope
it separately.
