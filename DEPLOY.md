# Deploying WWE GM 2000

Everything runs on **Vercel's free Hobby plan** — the React frontend as static
files and the FastAPI backend as a Python function. Nothing here costs money.

| Part | Where | State it holds |
|---|---|---|
| **Frontend** | Vercel static | none |
| **Backend** | Vercel Python function (`api/index.py`) | none — deliberately |
| **The save** | Vercel Blob | everything |

## The problem free hosting creates, and how it is solved

Free hosting is **stateless**. Vercel's Python runtime gives you a container
whose filesystem is read-only apart from `/tmp` and is thrown away between
requests; Render's free tier wipes its disk on every restart. This game *is* a
SQLite file written on every draft pick, contract, show and title change — so on
any free host that file, and the save with it, disappears.

The paid answer is a mounted disk. The free answer is `backend/store.py`:

- At boot the whole database is pulled down into a local file, and the app talks
  to it as ordinary local SQLite — full speed, real transactions, **and not one
  line of the app's SQL changes**.
- After any request that wrote something, the file is pushed back up.

The save is well under a megabyte and this is a single-player game, so moving
the whole file per write is cheap and safe. (It would be the wrong design for a
multi-user app, where two writers could overwrite each other.)

The alternative — swapping SQLite for a hosted database — was rejected: it
rewrites every query in `game.py`, `sim.py`, `rankings.py` and `main.py`, and
the client for the SQLite-compatible option ships as a compiled extension with
no wheel for the development machine's Python, so the port could not have been
tested at all before deploying. `store.py` is ~150 lines and the whole
wipe-and-recover cycle is covered by a test.

Verified: boot an empty container, start a game, **delete the entire filesystem**,
boot again — the save comes back intact, including the Power 25 issues. GETs
never write, failed requests never write.

---

## Deploy

### 1. Create the Blob store

Vercel dashboard → **Storage** → **Create** → **Blob**. Free on Hobby.

| Field | Pick | Why |
|---|---|---|
| Store Name | `wwe-gm-2000` | just a label |
| Region | leave the default (`iad1`) | it should match where the function runs — the round trip that matters is function↔blob, not you↔blob |
| Access | **Private** | it is your save file. Public means anyone holding the URL can download it |

`store.py` reads a private store by sending the store token, and falls back to an
unauthenticated read if the store turns out to be public — so either choice works
and the token is only ever sent to a `vercel-storage.com` host.

Then **connect the store to the project**; Vercel injects `BLOB_READ_WRITE_TOKEN`
automatically. Without that connection the API still boots but reports
`"configured": false` on `/api/store/status` and the save will not survive.

### 2. Import the repo

**New Project** → `mahadlaeeque17/WWE-GM`. `vercel.json` already sets the build,
the output directory, the Python function and the routing, so there is nothing
to configure.

> **Set Framework Preset to `Other`.** This is the one setting that cannot be
> fixed from the repo. Vercel decides it when you first import, stores it in
> project settings, and if it guesses "backend framework project" it routes
> every request — including static assets like `/favicon.svg` — into the Python
> function, which presents as the site being broken rather than as a
> misconfiguration.
>
> And **leave `requirements.txt` at the repo root.** It looks like the cause of
> that misdetection, but deleting it breaks the build outright: Vercel only
> enables its Python runtime when it finds a manifest there, and without one
> `api/index.py` is not a function at all. The preset, not the manifest, is the
> thing to change.

### 3. Set the environment variables

| Var | Value | Why |
|---|---|---|
| `GROQ_API_KEY` | your key | optional — only the AI commentary/promos need it |

**`GM2000_STORE` is no longer needed** and this table used to insist on it. The
app turns the Blob backend on from the presence of `BLOB_READ_WRITE_TOKEN`
alone — which Vercel injects when you connect the store in step 1 — so the only
thing that matters is that the store is actually connected. Setting
`GM2000_STORE` still wins if you want to force `disk` on a host with a real
volume.

That correction matters because it moves where you look when the save is not
persisting: it is almost never a missing variable, it is the store not being
linked to the project.

`GM2000_DATA_DIR` is set in code to `/tmp/gm2000` and needs no attention.

`VITE_API_BASE` is **not needed** — the API is served from the same domain under
`/api`, so the frontend calls it same-origin. That also means no CORS setup.

### 4. Check it

Live at **https://wwe-gm.vercel.app** — recorded here because it was not written
down anywhere and had to be guessed at.

Open **`/api/store/status`**. It is the first thing to look at if a save ever
appears to reset itself:

```json
{ "mode": "blob", "enabled": true, "configured": true, "durable": true,
  "put_variant": "private", "hydrated": 0.3, "error": null, "db_bytes": 606208 }
```

Read it in this order:

| What you see | What it means |
|---|---|
| `"durable": true` | the save will survive. This is the only line that matters |
| `"mode": "disk"` on Vercel | **no Blob store is connected** — the game is writing to a filesystem that is about to be deleted. `durable_detail` says what to do |
| `"enabled": false` | same thing, said another way: the store backend never turned on because no token arrived |
| `"put_variant": null` after playing | nothing has been uploaded yet. If `error` is also set, that is the upload failing |
| `"error"` | the response body Vercel actually sent back, not just a status code |

The app puts a **NOT SAVING** banner on screen whenever `durable` is false, so
this is a confirmation rather than a discovery.

### 5. Prove the Blob store works without a deploy

Nine commits were once spent guessing at this from a banner. Two scripts exist so
that never happens again:

```bash
python test_blob_shape.py
```

Asserts every Blob request against a local stub — no token, no network,
milliseconds. Catches the class of bug that caused all nine (the pathname
belongs in the query string, and putting it in the path silently disables the
access header).

```bash
python smoke_blob.py
```

Full round trip against the **real** store from your laptop: list, upload,
download, overwrite, delete. Reads `BLOB_READ_WRITE_TOKEN` from the environment
only, never writes it anywhere, and uses a throwaway key — so it is safe to run
while a game is in progress.

```powershell
$env:BLOB_READ_WRITE_TOKEN = "vercel_blob_rw_..."   # Storage -> your store -> .env.local
python smoke_blob.py
```

### 6. Upgrading an existing save

Nothing to do. The API migrates the save it finds to the current rating system at
boot and pushes the result back up — which is not a nicety: the database the
deploy runs on is whatever is in Blob storage, not what shipped in the bundle, so
a save uploaded before a schema change would otherwise 500 on the first request.
Guarded by a marker, so it happens once.

---

## Known limits of the free deploy

Worth knowing before you rely on it:

- **Portraits do not persist.** Images are files, and `data/images/` lives on the
  throwaway filesystem. The app already degrades cleanly — it shows initials
  where there is no photo — but the Drive sync has nowhere durable to put what it
  downloads, so image endpoints are effectively local-only. Run the app locally
  when you want to work with portraits.
- **Cold starts.** The first request after an idle period pays for the container
  starting plus one database download. Subsequent requests are warm.
- **One writer.** Two browser tabs booking shows at the same moment can have the
  later write overwrite the earlier one. Fine for one person playing.
- **Function ceiling.** `vercel.json` sets `maxDuration: 60`. Simulating a show
  is far quicker than that, but a very long loop would be cut off.

If any of that becomes annoying, the app is unchanged by moving to a host with a
real disk — set `GM2000_STORE=disk` and point `GM2000_DATA_DIR` at the mount.

---

## Running the API somewhere other than Vercel

`render.yaml` is included as an optional fallback, on Render's **free** plan (no
disk, sleeps when idle) using the same Blob store for durability. If you use it,
the frontend then needs `VITE_API_BASE` set to the Render URL **before its first
build** (Vite bakes it in at build time), and Render needs `GM2000_CORS_ORIGINS`
set to the Vercel URL — otherwise the UI loads and every request dies as CORS,
which looks exactly like the backend being down.

---

## How the paths work

`backend/paths.py` resolves everything the app writes:

```
GM2000_DATA_DIR=/tmp/gm2000    # where the db, images and logos live
GM2000_DB=/path/to.db          # overrides just the database (used by the tests)
```

Unset, both fall back to `data/` beside the code, so **local development is
completely unchanged** — `store.MODE` is `disk` and none of the sync code runs.

`seed_data_dir()` copies the bundled `data/gm2000.db` (the seeded 270-wrestler
roster) into that directory if it is empty, because the API refuses to serve
without a database and a fresh container starts with nothing. It copies **once**
and never touches an existing save. `store.hydrate()` then runs immediately
after and, if durable storage already holds a save, that one wins — the bundled
roster is only ever a starting point.

## Environment variables, all of them

| Var | Default | What it does |
|---|---|---|
| `GM2000_STORE` | `disk` | `disk` (file is already durable) · `blob` (Vercel Blob) · `dir` (another folder — used by the tests) |
| `BLOB_READ_WRITE_TOKEN` | — | injected by Vercel when a Blob store is connected |
| `GM2000_BLOB_KEY` | `gm2000.db` | the key the save is stored under |
| `GM2000_REMOTE_DIR` | — | `dir` mode target |
| `GM2000_DATA_DIR` | `data/` | where db + images + logos live |
| `GM2000_DB` | — | overrides just the database file |
| `GM2000_CORS_ORIGINS` | — | extra allowed origins; unnecessary when the API is same-origin |
| `GROQ_API_KEY` | — | the AI layer. Everything else works without it |

The **Groq key stays server-side** — backend env only, never in the frontend
bundle. The browser only ever calls our own `/api/ai/*` endpoints.

## Testing the deploy story locally

```bash
python smoke_store.py
```

Boots the API against a throwaway directory, starts a game, **deletes the entire
filesystem**, boots again and asserts the save came back — plus that GETs and
failed requests never write. That is the whole free-hosting risk, covered.
