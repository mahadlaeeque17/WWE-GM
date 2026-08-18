# Deploying WWE GM 2000

The app has three moving parts:

| Part | What it is | State it holds |
|---|---|---|
| **Frontend** | Vite + React static bundle | none — pure static files |
| **Backend** | FastAPI (`backend/`) | **writes constantly** to SQLite |
| **Data** | `data/gm2000.db` + `data/images/` | the entire save + portraits |

## The one thing to understand before Vercel

**Vercel cannot host the backend as-is.** Vercel's Python runtime is *serverless*:
each request runs in a fresh, throwaway container with a **read-only filesystem**
(only `/tmp`, which is wiped between requests). Our whole game *is* a SQLite file
that must persist every draft pick, contract, show and title change — and a folder
of images. On Vercel serverless that state would evaporate between clicks.

So the frontend is a perfect fit for Vercel; the **stateful backend needs a host
with a persistent disk**. Two ways to go:

### Path A — Frontend on Vercel, backend on a persistent host  ✅ recommended

Least rework — the code already supports it (env-driven API base + CORS).

- **Frontend → Vercel.** Root `frontend/`, build `npm run build`, output `dist/`.
  Set env var `VITE_API_BASE` = your backend's public URL.
- **Backend → Render / Railway / Fly.io** (any of these give a persistent volume).
  Mount a disk, put `data/` on it, run
  `uvicorn main:app --host 0.0.0.0 --port $PORT` from `backend/`.
  Set env vars `GROQ_API_KEY` and `GM2000_CORS_ORIGINS` = your Vercel URL.
- SQLite + images just work on the mounted disk. Zero rewrite.

### Path B — Everything on Vercel  (more rework)

Requires swapping the storage layer:
- **SQLite → Postgres** (Vercel Postgres / Neon). The DB layer in
  `backend/main.py` and `backend/game.py` would be ported from `sqlite3` to a
  Postgres driver. Non-trivial but mechanical.
- **`data/images/` → object storage** (Vercel Blob / S3). The image endpoints
  would stream from the bucket instead of local disk.
- Then the backend can run as Vercel Python functions.

If you want Path B, say so and I'll do the Postgres + Blob port — budget it as a
separate chunk of work.

## What the code already does for deployment

- `frontend/src/api.ts` reads **`VITE_API_BASE`** — empty in dev (Vite proxies
  `/api` → `localhost:8010`), set to the backend origin in production. All API
  calls *and* image URLs go through it.
- `backend/main.py` reads **`GM2000_CORS_ORIGINS`** (comma-separated) and adds
  them to the allow-list, so the deployed frontend can call the backend.
- `backend/requirements.txt` pins the Python deps.
- The **Groq key stays server-side** — it lives in the backend env only and is
  never shipped in the frontend bundle. The browser only ever calls our own
  `/api/ai/*` endpoints.

## ✅ What I need from you to finish the deploy

1. **Pick a path** — A (recommended) or B.
2. **A GitHub repo** for the project (Vercel deploys from Git). Confirm you want
   me to `git init` + push, and where.
3. **For Path A, a backend host** — Render, Railway, or Fly.io — and whether you
   want me to add its config file (`render.yaml` / `fly.toml`).
4. **Confirm the Groq key** — the one in `backend/.env`
   is what will be set as `GROQ_API_KEY` on the backend host.
   If you'd rather rotate it before it goes to a cloud host, give me the new one.
5. **A project name / domain** for Vercel (e.g. `wwe-gm-2000`).

Once you pick a path and give me the repo + host, the rest is config I can write
and wire up.
