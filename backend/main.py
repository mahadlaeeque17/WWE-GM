"""WWE GM 2000 — API.

Layers, matching the schema: source data (cagematch), user overrides, and game
state. The roster endpoint always returns EFFECTIVE values — your edits win over
the derived ones — so nothing downstream has to know an override existed.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harvester"))

import ai  # noqa: E402
import attributes as A  # noqa: E402
import booking  # noqa: E402
import cards  # noqa: E402
import game  # noqa: E402
import history  # noqa: E402
import images  # noqa: E402
import negotiate  # noqa: E402
import migrate_cards  # noqa: E402
import migrate_ratings  # noqa: E402
import rankings  # noqa: E402
import rumble  # noqa: E402
import sim  # noqa: E402

import os  # noqa: E402
import paths  # noqa: E402
import store  # noqa: E402

# Locally `data/gm2000.db` beside the code; on a host, whatever GM2000_DATA_DIR
# or GM2000_DB points at. See backend/paths.py.
DB = paths.DB_PATH

app = FastAPI(title="WWE GM 2000", version="0.5.0")
# Local dev origins by default; in production add the deployed frontend origin
# via GM2000_CORS_ORIGINS (comma-separated), e.g. "https://wwe-gm-2000.vercel.app".
_origins = ["http://localhost:5180", "http://127.0.0.1:5180"]
_extra = os.environ.get("GM2000_CORS_ORIGINS", "")
_origins += [o.strip() for o in _extra.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"], allow_headers=["*"],
)


@app.middleware("http")
async def _persist_writes(request, call_next):
    """Push the save back to durable storage after anything that wrote.

    On a free host the container's filesystem is temporary, so a committed
    SQLite write is only as durable as the next restart. GET is skipped because
    it cannot change anything; a failed request is skipped because there is
    nothing worth saving. A no-op unless GM2000_STORE is set.
    """
    # Hand this request's OIDC token to the store layer BEFORE anything runs.
    #
    # A Blob store connected through the dashboard authenticates by OIDC, and the
    # token arrives per request in this header — it is short-lived, so it cannot
    # be read once at cold start. Miss this and the save silently stops working
    # part-way through a session, or never works at all.
    store.use_request_token(request.headers.get("x-vercel-oidc-token"))

    response = await call_next(request)
    if (store.enabled() and request.method != "GET"
            and request.url.path.startswith("/api/")
            and response.status_code < 400):
        store.persist(DB)
    return response


def _raw_conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def conn() -> sqlite3.Connection:
    ensure_ready()
    if not DB.exists():
        raise HTTPException(503, f"database missing at {DB} — run harvester/normalize.py")
    # Has another container written since we last looked?
    #
    # Serverless does not give you one process. Vercel keeps several containers
    # warm and routes each request to whichever is free, so a save landing on one
    # was invisible to the next read served by another — the change appeared to
    # vanish on refresh, and saving twice "fixed" it only because the second
    # request happened to land somewhere that then served the read. One
    # conditional GET settles it; a 304 costs a few hundred bytes.
    store.refresh(DB)
    return _raw_conn()


def q(sql: str, args: tuple = ()) -> list[dict[str, Any]]:
    c = conn()
    try:
        return [dict(r) for r in c.execute(sql, args)]
    finally:
        c.close()


def current_state(c: sqlite3.Connection) -> sqlite3.Row | None:
    return c.execute("SELECT * FROM game_state WHERE id=1").fetchone()


_READY = False
_READY_LOG: list[str] = []

# How many times readiness may defer itself waiting for a blob credential. The
# first real request supplies one, so this only ever burns through when the store
# genuinely is not connected — at which point booting without it beats not booting.
_READY_ATTEMPTS = 0
MAX_READY_ATTEMPTS = 3


def ensure_ready() -> None:
    """Put the save in place and bring the schema up to date. Runs ONCE.

    Deliberately callable from two places. On a normal server the startup event
    fires it; on a serverless host the ASGI lifespan may never run at all, and
    relying on it would leave the container with no database and every endpoint
    answering 503. `conn()` calls this too, so the first request repairs it.
    """
    global _READY
    if _READY:
        return

    # WAIT FOR A CREDENTIAL BEFORE HYDRATING, when the store needs one.
    #
    # Under OIDC the token arrives in a request header, so at startup-event time
    # there is nothing to authenticate with. Hydrating anyway would pull nothing,
    # fall back to the bundled seed, and — because readiness is a one-shot flag —
    # never try again: the container would serve a fresh roster for its whole life
    # and then persist that over the real save. So this returns WITHOUT latching,
    # and the first actual request (which does carry the header) runs it properly.
    #
    # Bounded, because a genuinely missing credential must not retry forever: after
    # a few attempts it gives up and runs on the local file, which at least boots
    # and shows the NOT SAVING banner.
    global _READY_ATTEMPTS
    if store.enabled() and not store.credentials()["kind"]:
        _READY_ATTEMPTS += 1
        if _READY_ATTEMPTS <= MAX_READY_ATTEMPTS:
            return
        _READY_LOG.append("no blob credential after "
                          f"{MAX_READY_ATTEMPTS} attempts — running on the local file")

    _READY = True                      # set first: a failure must not retry forever
    try:
        seeded = paths.seed_data_dir()
        if seeded:
            _READY_LOG.append(seeded)
        # Pull the durable save down before anything opens it. No-op on a real disk.
        _READY_LOG.append(store.hydrate(DB, paths.BUNDLED_DB))
        if not DB.exists():
            _READY_LOG.append(f"no database at {DB} — /api/* will return 503")
            return
        c = _raw_conn()
        try:
            game.ensure_schema(c)
            rankings.ensure_schema(c)
            game.ensure_titles(c)
            # Bring an OLD SAVE forward to the five-category ratings.
            #
            # This has to happen here, not in a script someone remembers to run.
            # On a stateless host the save is pulled down from Blob storage above,
            # so the database this process actually opens is whatever is in the
            # store — which can predate the rating change no matter what the
            # bundled seed contains. Without this the first roster request dies
            # on `no such column: a.wrestling`. Guarded by a marker, so it is a
            # cheap no-op on every boot after the first.
            migrated = migrate_ratings.ensure_migrated(c)
            # AFTER the ratings migration, never before: that one rewrites the
            # attributes table and its DDL knows nothing about mic/influence, so
            # adding them first would lose them again on an old save.
            card_schema = migrate_cards.ensure_schema(c)
        finally:
            c.close()
        if card_schema:
            _READY_LOG.append(card_schema)
        if migrated or card_schema:
            if migrated:
                _READY_LOG.append(migrated)
            # Push the migrated save up NOW rather than waiting for the next
            # write. Otherwise the store keeps the old format and every cold
            # start pays for the migration again — and a container that dies
            # before anyone books a show would lose it entirely.
            _READY_LOG.append(f"persist after migration: {store.persist(DB)}")
        _READY_LOG.append("schema ready")
    except Exception as e:  # noqa: BLE001
        _READY_LOG.append(f"startup failed: {type(e).__name__}: {e}")
    for line in _READY_LOG:
        print(line, flush=True)


@app.on_event("startup")
def _startup() -> None:
    ensure_ready()


# ---------------------------------------------------------------- meta

@app.get("/api/store/status")
def store_status() -> dict:
    """Where the save actually lives, and whether the last sync worked.

    First thing to check when a deployed save appears to reset itself.
    """
    ensure_ready()
    return {**store.status(), "db": str(DB),
            "db_exists": DB.exists(),
            "db_bytes": DB.stat().st_size if DB.exists() else 0,
            "startup": _READY_LOG,
            "data_dir": str(paths.DATA_DIR),
            "bundled_db_exists": paths.BUNDLED_DB.exists()}


@app.get("/api/health")
def health() -> dict:
    # Before the existence check, not after. This endpoint short-circuits on a
    # missing file, so on a host that never runs lifespan startup it would
    # report "database missing" forever — having never given the lazy init a
    # chance to put the database there.
    ensure_ready()
    if not DB.exists():
        return {"ok": False, "reason": "database missing", "startup": _READY_LOG}
    c = conn()
    try:
        st = current_state(c)
        return {
            "ok": True,
            "wrestlers": c.execute("SELECT COUNT(*) FROM wrestler").fetchone()[0],
            "save": dict(st) if st else None,
        }
    finally:
        c.close()


@app.post("/api/game/new")
def new_game(seed: int = Body(2000, embed=True)) -> dict:
    c = conn()
    try:
        return game.new_game(c, seed=seed)
    finally:
        c.close()


@app.post("/api/game/advance-season")
def advance_season() -> dict:
    c = conn()
    try:
        if not current_state(c):
            raise HTTPException(400, "no active save")
        return _roll(c, game.advance_season(c))
    finally:
        c.close()


def _roll(c: sqlite3.Connection, res: dict) -> dict:
    """Whenever the calendar rolls into a new season, grade the one that ended.

    The engine only QUEUES suggestions — nothing is applied to a rating until it
    is approved on the Progression tab — so doing this automatically is safe.
    """
    if res.get("rolled_season"):
        try:
            res["ratings"] = rankings.evaluate_season(c, res["season_year"] - 1)
        except Exception as e:  # noqa: BLE001
            res["ratings"] = {"error": str(e)}
    return res


@app.get("/api/calendar")
def calendar() -> dict:
    c = conn()
    try:
        return game.calendar(c)
    finally:
        c.close()


@app.post("/api/game/advance-month")
def advance_month() -> dict:
    c = conn()
    try:
        if not current_state(c):
            raise HTTPException(400, "no active save")
        return _roll(c, game.advance_month(c))
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


# ---------------------------------------------------------------- roster

@app.get("/api/roster")
def roster(include_removed: bool = False) -> list[dict]:
    c = conn()
    try:
        st = current_state(c)
        season = st["season_year"] if st else A.RESET_YEAR
        removed = game.excluded_ids(c)

        rows = [dict(r) for r in c.execute(
            """
            SELECT w.id, w.name, w.birthday, w.birthplace, w.style,
                   w.age_at_reset AS base_age, w.age_precision,
                   w.rating, w.votes, w.adj_rating,
                   w.career_start, w.career_end,
                   a.wrestling AS d_wrestling, a.popularity AS d_popularity,
                   a.looks AS d_looks, a.personal AS d_personal,
                   a.mic AS d_mic, a.influence AS d_influence, a.availability,
                   a.alignment AS d_alignment, a.personality AS d_personality,
                   o.wrestling AS o_wrestling, o.popularity AS o_popularity,
                   o.looks AS o_looks, o.personal AS o_personal,
                   o.mic AS o_mic, o.influence AS o_influence,
                   o.age_at_reset AS o_age, o.display_name, o.notes,
                   o.role AS o_role, a.role AS d_role,
                   o.alignment AS o_alignment, o.personality AS o_personality,
                   o.draft_class AS o_draft_class,
                   COALESCE(s.sim_matches,0) sim_matches,
                   COALESCE(s.sim_wins,0)    sim_wins,
                   COALESCE(s.sim_losses,0)  sim_losses,
                   COALESCE(s.sim_draws,0)   sim_draws,
                   COALESCE(s.momentum,50)   momentum,
                   COALESCE(s.morale,50)     morale,
                   COALESCE(s.fatigue,0)     fatigue,
                   COALESCE(s.career_earnings,0) career_earnings,
                   COALESCE(s.ppv_appearances,0) ppv_appearances,
                   s.injured_until,
                   COALESCE(SUM(p.matches),0) hist_matches,
                   COALESCE(SUM(p.wins),0)    hist_wins,
                   COALESCE(SUM(p.losses),0)  hist_losses,
                   MIN(p.year) first_year, MAX(p.year) last_year
            FROM wrestler w
            JOIN attributes a ON a.wrestler_id = w.id
            LEFT JOIN attribute_override o ON o.wrestler_id = w.id
            LEFT JOIN wrestler_state s ON s.wrestler_id = w.id
            LEFT JOIN promotion_year p ON p.wrestler_id = w.id
            GROUP BY w.id
            """
        )]

        names: dict[int, list[str]] = {}
        for r in c.execute("SELECT wrestler_id, name FROM ring_name ORDER BY is_primary DESC"):
            names.setdefault(r["wrestler_id"], []).append(r["name"])

        promos: dict[int, set] = {}
        for r in c.execute("SELECT DISTINCT wrestler_id, promotion FROM promotion_year"):
            promos.setdefault(r["wrestler_id"], set()).add(r["promotion"])

        titles: dict[int, int] = {}
        for r in c.execute(
            """SELECT wrestler_id, COUNT(*) n FROM title_reign
               WHERE won_on IS NOT NULL AND CAST(substr(won_on,7,4) AS INTEGER) < 2000
               GROUP BY wrestler_id"""):
            titles[r["wrestler_id"]] = r["n"]

        contracts: dict[int, dict] = {}
        for r in c.execute(
            """SELECT * FROM contract WHERE terminated_on IS NULL
               AND start_year <= ? AND end_year >= ?""", (season, season)):
            contracts[r["wrestler_id"]] = dict(r)

        # Anyone who has ever held a contract — the basis for the Alumni view once
        # a deal lapses or is released and she is no longer signed.
        ever_contracted = {r[0] for r in c.execute("SELECT DISTINCT wrestler_id FROM contract")}
        streaks = game.streaks(c)
        bios = game.bios(c)
        stables = game.stables_all(c)
        # One pass for all 270. Achievements is computed, never stored, so the
        # roster page has to derive it — but three subqueries per row is a page
        # load you can feel, hence the bulk read.
        ach_inputs = game.achievement_inputs(c)

        season_roles = {r["wrestler_id"]: r["role"] for r in c.execute(
            "SELECT wrestler_id, role FROM season_role WHERE season_year=?", (season,))}
        holdout_of: dict[int, list[str]] = {}
        for r in c.execute("SELECT wrestler_id, brand_id FROM holdout WHERE season_year=?", (season,)):
            holdout_of.setdefault(r["wrestler_id"], []).append(r["brand_id"])

        images_by: dict[int, list[dict]] = {}
        profile_of: dict[int, int] = {}
        for r in c.execute(
            """SELECT id, wrestler_id, year, filename, is_profile FROM wrestler_image
               ORDER BY is_profile DESC, year, id"""):
            images_by.setdefault(r["wrestler_id"], []).append(
                {"id": r["id"], "year": r["year"], "filename": r["filename"],
                 "is_profile": r["is_profile"]})
            if r["is_profile"]:
                profile_of[r["wrestler_id"]] = r["id"]

        roles = {r["wrestler_id"]: r["role"] for r in c.execute(
            """SELECT a.wrestler_id, COALESCE(o.role, a.role) AS role FROM attributes a
               LEFT JOIN attribute_override o ON o.wrestler_id = a.wrestler_id""")}
        accolades_by: dict[int, list[dict]] = {}
        for r in c.execute("SELECT id, wrestler_id, kind, season_year FROM accomplishment"):
            accolades_by.setdefault(r["wrestler_id"], []).append(
                {"id": r["id"], "kind": r["kind"], "season_year": r["season_year"],
                 "label": game.ACCOLADES.get(r["kind"], (r["kind"],))[0]})
        title_reigns: dict[int, list[dict]] = {}
        for r in c.execute(
            """SELECT r.wrestler_id, t.name, t.short_name, r.lost_on
               FROM game_title_reign r JOIN game_title t ON t.id=r.title_id"""):
            title_reigns.setdefault(r["wrestler_id"], []).append(dict(r))

        out = []
        for r in rows:
            if r["id"] in removed and not include_removed:
                continue
            age = r["o_age"] if r["o_age"] is not None else r["base_age"]
            # Exactly the same arithmetic the wrestler panel uses, called rather
            # than re-implemented. The two used to be separate copies, which is
            # how a rating could read one way here and another way there.
            eff = game.with_derived({
                "wrestling_base": (r["o_wrestling"] if r["o_wrestling"] is not None
                                   else r["d_wrestling"]),
                "popularity": (r["o_popularity"] if r["o_popularity"] is not None
                               else r["d_popularity"]),
                "looks": r["o_looks"] if r["o_looks"] is not None else r["d_looks"],
                "personal": (r["o_personal"] if r["o_personal"] is not None
                             else r["d_personal"]),
                "mic": r["o_mic"] if r["o_mic"] is not None else r["d_mic"],
                "influence": (r["o_influence"] if r["o_influence"] is not None
                              else r["d_influence"]),
                "sim_matches": r["sim_matches"], "sim_wins": r["sim_wins"],
                "age": age,
                # The role decides which two stats the overall is built from.
                "role": r["o_role"] or r["d_role"] or "wrestler",
            }, ach_inputs.get(r["id"]))

            out.append({
                "id": r["id"],
                "name": r["display_name"] or r["name"],
                "canonical_name": r["name"],
                "removed": r["id"] in removed,
                "age": age,
                "age_precision": r["age_precision"],
                "birthday": r["birthday"], "birthplace": r["birthplace"], "style": r["style"],
                "rating": r["rating"], "votes": r["votes"], "adj_rating": r["adj_rating"],
                "availability": r["availability"],
                "wrestling": eff["wrestling"],
                "wrestling_base": eff["wrestling_base"],
                "record_swing": eff["record_swing"],
                "achievements": eff["achievements"],
                "achievement_reasons": eff["achievement_reasons"],
                "popularity": eff["popularity"], "looks": eff["looks"],
                "personal": eff["personal"],
                # A manager is rated on these two in place of Wrestling and
                # Popularity. Always sent, because the roster does not know which
                # screen is about to ask and one column costs nothing.
                "mic": eff["mic"], "influence": eff["influence"],
                # Which two the overall was built from — so the card and the
                # radar can label themselves without re-deriving the role rule.
                "performance_pair": eff["performance_pair"],
                "overall": eff["overall"], "value": eff["value"],
                "age_multiplier": round(A.age_multiplier(age), 3),
                "edited": {
                    "wrestling": r["o_wrestling"] is not None,
                    "popularity": r["o_popularity"] is not None,
                    "looks": r["o_looks"] is not None,
                    "personal": r["o_personal"] is not None,
                    "mic": r["o_mic"] is not None,
                    "influence": r["o_influence"] is not None,
                    "age": r["o_age"] is not None,
                    "name": bool(r["display_name"]),
                },
                "notes": r["notes"],
                "alignment": r["o_alignment"] or r["d_alignment"] or "face",
                "personality": r["o_personality"] or r["d_personality"] or "mercenary",
                "draft_class": r["o_draft_class"] or A.RESET_YEAR,
                "season_role": season_roles.get(r["id"]),
                "holdout_brands": holdout_of.get(r["id"], []),
                "career_earnings": r["career_earnings"],
                "ppv_appearances": r["ppv_appearances"],
                "sim": {"matches": r["sim_matches"], "wins": r["sim_wins"],
                        "losses": r["sim_losses"], "draws": r["sim_draws"],
                        "momentum": r["momentum"],
                        "morale": r["morale"],
                        "fatigue": r["fatigue"], "injured_until": r["injured_until"]},
                "history": {"matches": r["hist_matches"], "wins": r["hist_wins"],
                            "losses": r["hist_losses"],
                            "first_year": r["first_year"], "last_year": r["last_year"]},
                "ring_names": names.get(r["id"], []),
                "promotions": sorted(promos.get(r["id"], [])),
                "titles_pre_2000": titles.get(r["id"], 0),
                "contract": contracts.get(r["id"]),
                "promises": game.perk_status(c, r["id"], season) if contracts.get(r["id"]) else [],
                "images": images_by.get(r["id"], []),
                "profile_image_id": profile_of.get(r["id"]),
                "role": roles.get(r["id"], "wrestler"),
                "manager_price": game.manager_price(c, r["id"], eff),
                "hall_of_fame": any(a["kind"] == "hall_of_fame" for a in accolades_by.get(r["id"], [])),
                "alumni": (r["id"] in ever_contracted and r["id"] not in contracts),
                "streak": streaks.get(r["id"], 0),
                "nickname": bios.get(r["id"], {}).get("nickname"),
                "bio": bios.get(r["id"], {}).get("bio"),
                "accolades": accolades_by.get(r["id"], []),
                "game_titles": title_reigns.get(r["id"], []),
                "stables": stables.get(r["id"], game._NO_STABLES),
            })
        out.sort(key=lambda x: (-x["overall"], -(x["votes"] or 0)))
        return out
    finally:
        c.close()


class Override(BaseModel):
    # Bounded by CAT_MAX rather than a loose 100, so a value that cannot exist
    # is rejected at the edge instead of being silently clamped four layers in.
    # Achievements is absent on purpose: it is computed from what she has won, so
    # there is nothing here to set — you award the title or the accolade instead.
    wrestling: int | None = Field(None, ge=0, le=A.CAT_MAX)
    popularity: int | None = Field(None, ge=0, le=A.CAT_MAX)
    looks: int | None = Field(None, ge=0, le=A.CAT_MAX)
    personal: int | None = Field(None, ge=0, le=A.CAT_MAX)
    # A manager is scored on these two in place of Wrestling and Popularity.
    mic: int | None = Field(None, ge=0, le=A.CAT_MAX)
    influence: int | None = Field(None, ge=0, le=A.CAT_MAX)
    age_at_reset: int | None = Field(None, ge=0, le=120)
    role: str | None = None
    display_name: str | None = None
    notes: str | None = None


@app.put("/api/wrestler/{wid}/override")
def set_override(wid: int, body: Override) -> dict:
    """Edit any rating. NULL clears the edit and reverts to the derived value."""
    c = conn()
    try:
        if not c.execute("SELECT 1 FROM wrestler WHERE id=?", (wid,)).fetchone():
            raise HTTPException(404, "no such wrestler")
        from datetime import datetime, timezone
        c.execute(
            """INSERT INTO attribute_override
               (wrestler_id, wrestling, popularity, looks, personal, mic, influence,
                age_at_reset, role, display_name, notes, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(wrestler_id) DO UPDATE SET
                 wrestling=excluded.wrestling, popularity=excluded.popularity,
                 looks=excluded.looks, personal=excluded.personal,
                 mic=excluded.mic, influence=excluded.influence,
                 age_at_reset=excluded.age_at_reset, role=excluded.role,
                 display_name=excluded.display_name, notes=excluded.notes,
                 updated_at=excluded.updated_at""",
            (wid, body.wrestling, body.popularity, body.looks, body.personal,
             body.mic, body.influence,
             body.age_at_reset, body.role, body.display_name, body.notes,
             datetime.now(timezone.utc).isoformat()),
        )
        c.commit()
        return game.effective_attributes(c, wid)
    finally:
        c.close()


class RatingEdit(BaseModel):
    """One cell of the rating sheet. Absent field = leave that category alone."""
    wrestler_id: int
    wrestling: int | None = Field(None, ge=0, le=A.CAT_MAX)
    popularity: int | None = Field(None, ge=0, le=A.CAT_MAX)
    looks: int | None = Field(None, ge=0, le=A.CAT_MAX)
    personal: int | None = Field(None, ge=0, le=A.CAT_MAX)
    mic: int | None = Field(None, ge=0, le=A.CAT_MAX)
    influence: int | None = Field(None, ge=0, le=A.CAT_MAX)


@app.post("/api/ratings/bulk")
def bulk_ratings(edits: list[RatingEdit] = Body(...)) -> dict:
    """Apply many rating edits in ONE transaction.

    Exists because of what a per-cell save would cost. Two of the five categories
    are the GM's alone, so setting them across a 370-strong roster is a real sit-
    down job — and on a stateless host EVERY successful write pushes the whole
    database back to Blob storage. Three hundred and seventy cells would mean
    three hundred and seventy uploads of the same file. This is one.

    PARTIAL BY DESIGN. A field left out is not cleared, it is untouched — which is
    the difference between "I set her Looks" and "I set her Looks and silently
    froze her Wrestling at whatever the formula said this afternoon". The
    per-wrestler PUT endpoint replaces the whole row; this one does not.
    """
    if not edits:
        return {"updated": 0}
    if len(edits) > 2000:
        raise HTTPException(413, f"{len(edits)} edits at once is too many")

    c = conn()
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        known = {r[0] for r in c.execute("SELECT id FROM wrestler")}
        missing = [e.wrestler_id for e in edits if e.wrestler_id not in known]
        if missing:
            raise HTTPException(404, f"no such wrestler: {missing[:5]}")

        touched = 0
        for e in edits:
            fields = {k: v for k, v in
                      (("wrestling", e.wrestling), ("popularity", e.popularity),
                       ("looks", e.looks), ("personal", e.personal),
                       ("mic", e.mic), ("influence", e.influence))
                      if v is not None}
            if not fields:
                continue
            cols = ", ".join(fields)
            marks = ", ".join("?" for _ in fields)
            sets = ", ".join(f"{k}=excluded.{k}" for k in fields)
            c.execute(
                f"""INSERT INTO attribute_override (wrestler_id, {cols}, updated_at)
                    VALUES (?, {marks}, ?)
                    ON CONFLICT(wrestler_id) DO UPDATE SET {sets},
                      updated_at=excluded.updated_at""",
                (e.wrestler_id, *fields.values(), now))
            touched += 1
        c.commit()
        return {"updated": touched}
    finally:
        c.close()


@app.get("/api/ratings/progress")
def rating_progress() -> dict:
    """How much of the roster you have actually rated by hand.

    Looks and Personal belong to the GM outright, and a roster of 370 arrives with
    both on a placeholder — so "how far through am I" is a real question the app
    should be able to answer, rather than something to work out by scrolling.
    """
    c = conn()
    try:
        row = c.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN o.looks    IS NULL THEN 1 ELSE 0 END) AS looks_todo,
                      SUM(CASE WHEN o.personal IS NULL THEN 1 ELSE 0 END) AS personal_todo
                 FROM wrestler w
                 LEFT JOIN attribute_override o ON o.wrestler_id = w.id
                WHERE w.id NOT IN (SELECT wrestler_id FROM excluded_wrestler)"""
        ).fetchone()
        return {"total": row["total"],
                "looks_todo": row["looks_todo"] or 0,
                "personal_todo": row["personal_todo"] or 0}
    finally:
        c.close()


@app.post("/api/wrestler/{wid}/rename")
def rename_wrestler(wid: int, display_name: str | None = Body(None, embed=True)) -> dict:
    """Rename for display only — the original harvested name is kept for ID.

    Touches ONLY display_name (a full override upsert would clobber rating edits),
    so a rename and a rating edit never interfere. Empty/whitespace reverts to
    the original name.
    """
    c = conn()
    try:
        if not c.execute("SELECT 1 FROM wrestler WHERE id=?", (wid,)).fetchone():
            raise HTTPException(404, "no such wrestler")
        name = (display_name or "").strip() or None
        from datetime import datetime, timezone
        c.execute(
            """INSERT INTO attribute_override (wrestler_id, display_name, updated_at)
               VALUES (?,?,?)
               ON CONFLICT(wrestler_id) DO UPDATE SET
                 display_name=excluded.display_name, updated_at=excluded.updated_at""",
            (wid, name, datetime.now(timezone.utc).isoformat()),
        )
        c.commit()
        row = c.execute("SELECT name FROM wrestler WHERE id=?", (wid,)).fetchone()
        return {"wrestler_id": wid, "display_name": name, "canonical_name": row["name"]}
    finally:
        c.close()


class TagsBody(BaseModel):
    alignment: str | None = None       # face | heel
    personality: str | None = None
    draft_class: int | None = None
    season_role: str | None = "__keep__"   # wrestler | manager | null(clear); "__keep__" leaves it


@app.post("/api/wrestler/{wid}/tags")
def set_tags(wid: int, body: TagsBody) -> dict:
    """Set alignment / personality / draft class (each optional) without touching
    rating overrides, plus this season's role pin for a BOTH-eligible wrestler."""
    c = conn()
    try:
        if not c.execute("SELECT 1 FROM wrestler WHERE id=?", (wid,)).fetchone():
            raise HTTPException(404, "no such wrestler")
        from datetime import datetime, timezone
        c.execute(
            """INSERT INTO attribute_override (wrestler_id, alignment, personality, draft_class, updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(wrestler_id) DO UPDATE SET
                 alignment   = COALESCE(excluded.alignment, attribute_override.alignment),
                 personality = COALESCE(excluded.personality, attribute_override.personality),
                 draft_class = COALESCE(excluded.draft_class, attribute_override.draft_class),
                 updated_at  = excluded.updated_at""",
            (wid, body.alignment, body.personality, body.draft_class,
             datetime.now(timezone.utc).isoformat()),
        )
        c.commit()
        if body.season_role != "__keep__":
            game.set_season_role(c, wid, body.season_role)
        return {"wrestler_id": wid, "ok": True}
    finally:
        c.close()


class BioBody(BaseModel):
    nickname: str | None = None
    bio: str | None = None


@app.post("/api/wrestler/{wid}/bio")
def set_bio(wid: int, body: BioBody) -> dict:
    c = conn()
    try:
        if not c.execute("SELECT 1 FROM wrestler WHERE id=?", (wid,)).fetchone():
            raise HTTPException(404, "no such wrestler")
        return game.set_bio(c, wid, body.nickname, body.bio)
    finally:
        c.close()


@app.post("/api/wrestler/{wid}/holdout/clear")
def clear_holdout_ep(wid: int, brand_id: str = Body(..., embed=True)) -> dict:
    c = conn()
    try:
        return game.clear_holdout(c, wid, brand_id)
    finally:
        c.close()


@app.delete("/api/wrestler/{wid}/override")
def clear_override(wid: int) -> dict:
    c = conn()
    try:
        c.execute("DELETE FROM attribute_override WHERE wrestler_id=?", (wid,))
        c.commit()
        return game.effective_attributes(c, wid)
    finally:
        c.close()


@app.post("/api/wrestler/{wid}/remove")
def remove_wrestler(wid: int, reason: str | None = Body(None, embed=True)) -> dict:
    """Remove from the game PERMANENTLY — a hard delete, not reversible."""
    c = conn()
    try:
        return game.ban(c, wid)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.post("/api/wrestler/{wid}/restore")
def restore_wrestler(wid: int) -> dict:
    c = conn()
    try:
        return game.restore(c, wid)
    finally:
        c.close()


@app.get("/api/wrestler/{wid}")
def wrestler(wid: int) -> dict:
    base = q("SELECT * FROM wrestler WHERE id=?", (wid,))
    if not base:
        raise HTTPException(404, "no such wrestler")
    c = conn()
    try:
        eff = game.effective_attributes(c, wid)
    finally:
        c.close()
    return {
        **base[0],
        "effective": eff,
        "ring_names": [r["name"] for r in q(
            "SELECT name FROM ring_name WHERE wrestler_id=? ORDER BY is_primary DESC", (wid,))],
        "promotion_years": q(
            """SELECT promotion, year, matches, wins, losses, draws
               FROM promotion_year WHERE wrestler_id=? ORDER BY year, promotion""", (wid,)),
        # dd.mm.yyyy sorts by DAY as a string — reorder to yyyymmdd
        "titles": q(
            """SELECT title, won_on, lost_on, days FROM title_reign WHERE wrestler_id=?
               ORDER BY CASE WHEN won_on IS NULL THEN 1 ELSE 0 END,
                        substr(won_on,7,4)||substr(won_on,4,2)||substr(won_on,1,2)""", (wid,)),
        "images": q("SELECT year, filename, source FROM wrestler_image "
                    "WHERE wrestler_id=? ORDER BY year", (wid,)),
    }


@app.get("/api/wrestler/{wid}/image/{year}")
def wrestler_image(wid: int, year: int):
    rows = q("SELECT filename FROM wrestler_image WHERE wrestler_id=? AND year=?", (wid, year))
    if not rows:
        raise HTTPException(404, "no image for that year")
    path = images.IMAGES_ROOT / str(wid) / rows[0]["filename"]
    if not path.exists():
        raise HTTPException(404, "file missing on disk")
    return FileResponse(path)


# ---------------------------------------------------------------- gm layer

@app.get("/api/brands")
def brands() -> list[dict]:
    c = conn()
    try:
        st = current_state(c)
        if not st:
            return []
        return game.brand_finances(c, st["season_year"])
    finally:
        c.close()


@app.get("/api/brands/budgets")
def budgets() -> list[dict]:
    return q("SELECT brand_id, season_year, budget FROM brand_budget ORDER BY season_year, brand_id")


# There is no free-agent signing endpoint by design — contracts are only
# created through the draft. Everything else is extensions, trades and releases.

class ExtendBody(BaseModel):
    wrestler_id: int
    years: int = Field(2, ge=game.MIN_CONTRACT_YEARS, le=game.MAX_CONTRACT_YEARS)
    annual_value: int | None = None


@app.post("/api/contracts/extend")
def extend(body: ExtendBody) -> dict:
    c = conn()
    try:
        return game.extend(c, body.wrestler_id, body.years, body.annual_value)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


# ---------------------------------------------------------------- draft

class StartDraftBody(BaseModel):
    # None -> use the per-kind default (8 wrestler rounds, 3 manager rounds).
    rounds: int | None = Field(None, ge=1, le=30)
    first_pick: str = "RAW"
    kind: str = "wrestler"       # wrestler | manager


@app.post("/api/draft/start")
def draft_start(body: StartDraftBody) -> dict:
    c = conn()
    try:
        # Structure is fixed by DRAFT_STRUCTURE (2 wrestler rounds, 3 manager
        # rounds); body.rounds is ignored by start_draft and kept only for
        # signature compatibility.
        return game.start_draft(c, body.rounds, body.first_pick, body.kind)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.get("/api/draft")
def draft_get(kind: str = "wrestler") -> dict:
    c = conn()
    try:
        return game.draft_board(c, kind)
    finally:
        c.close()


class PickBody(BaseModel):
    wrestler_id: int
    annual_value: int | None = None      # settled by negotiation; None = base ask
    kind: str = "wrestler"
    perks: list[str] = []
    signing_bonus: int = 0


@app.post("/api/draft/pick")
def draft_pick(body: PickBody) -> dict:
    c = conn()
    try:
        return game.make_pick(c, body.wrestler_id, None, body.annual_value, body.kind,
                              perks=body.perks, signing_bonus=body.signing_bonus)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


# ---------------------------------------------------------------- negotiation

class OfferBody(BaseModel):
    wrestler_id: int
    brand_id: str
    salary: int
    perks: list[str] = []
    signing_bonus: int = 0
    kind: str = "wrestler"
    context: str = "free_agent"          # free_agent | draft
    tier_factor: float = 1.0


_PERK_DESC = {
    "main_event": "A spot at the top of the card. If she works no main events this "
                  "season, morale suffers.",
    "title_shot": "At least one shot at a championship this season. Not delivered → morale hit.",
    "creative": "A say in her booking — don't job her out. Beaten clean too often breaks it.",
    "light_schedule": "A lighter workload. Overbook her and morale suffers at season's end.",
}


@app.get("/api/negotiate/perks")
def negotiate_perks() -> list[dict]:
    return [{"key": k, "label": v[0], "desc": _PERK_DESC.get(k, "")}
            for k, v in negotiate.PERKS.items()]


@app.get("/api/negotiate/personalities")
def negotiate_personalities() -> list[dict]:
    """The four negotiating personalities and the one distinct rule each applies."""
    return [{"key": k, "label": v[0], "desc": v[1], "factor": v[2], "effect": v[3]}
            for k, v in negotiate.PERSONALITIES.items()]


@app.get("/api/negotiate/quote")
def negotiate_quote(wrestler_id: int, kind: str = "wrestler",
                    tier_factor: float = 1.0) -> dict:
    c = conn()
    try:
        return negotiate.opening_quote(c, wrestler_id, kind, tier_factor)
    finally:
        c.close()


@app.post("/api/negotiate/offer")
def negotiate_offer(body: OfferBody) -> dict:
    """Evaluate an offer. Adds a Groq-written reaction line (canned if AI down)."""
    c = conn()
    try:
        res = negotiate.offer(c, body.wrestler_id, body.brand_id, body.salary,
                              body.perks, body.kind, body.tier_factor, body.signing_bonus)
        nm = c.execute(
            "SELECT COALESCE(o.display_name,w.name) n FROM wrestler w "
            "LEFT JOIN attribute_override o ON o.wrestler_id=w.id WHERE w.id=?",
            (body.wrestler_id,)).fetchone()
        name = nm["n"] if nm else "She"
        res["message"] = ai.negotiation_line(
            name, res["verdict"], res["mood"], body.salary, negotiate.perk_labels(body.perks))
        return res
    finally:
        c.close()


@app.post("/api/negotiate/reset")
def negotiate_reset(wrestler_id: int = Body(...), brand_id: str = Body(...)) -> dict:
    negotiate.reset(wrestler_id, brand_id)
    return {"reset": True}


# ---------------------------------------------------------------- free agency

class FreeAgentBody(BaseModel):
    wrestler_id: int
    brand_id: str
    annual_value: int
    perks: list[str] = []
    signing_bonus: int = 0


@app.post("/api/contracts/free-agent")
def free_agent(body: FreeAgentBody) -> dict:
    c = conn()
    try:
        r = game.free_agent_sign(c, body.wrestler_id, body.brand_id, body.annual_value,
                                 body.perks, body.signing_bonus)
        negotiate.reset(body.wrestler_id, body.brand_id)
        return r
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.get("/api/free-agents")
def free_agents_list() -> list[int]:
    """Wrestler ids with no active contract this season — the free-agent pool."""
    c = conn()
    try:
        st = current_state(c)
        if not st:
            return []
        return game.free_agents(c, st["season_year"])
    finally:
        c.close()


@app.post("/api/draft/pass")
def draft_pass(kind: str = Body("wrestler", embed=True)) -> dict:
    c = conn()
    try:
        return game.pass_pick(c, kind)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.post("/api/contracts/release")
def release(wrestler_id: int = Body(..., embed=True)) -> dict:
    c = conn()
    try:
        return game.release(c, wrestler_id)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


class TradeBody(BaseModel):
    side_a: list[int]
    side_b: list[int]


@app.post("/api/contracts/trade")
def trade(body: TradeBody) -> dict:
    c = conn()
    try:
        return game.trade(c, body.side_a, body.side_b)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


# ---------------------------------------------------------------- sim

class ShowBody(BaseModel):
    brand_id: str
    name: str
    card: list[dict] | None = None
    matches: int = 4
    is_ppv: bool = False
    ppv_name: str | None = None
    logistics: dict | None = None


@app.post("/api/sim/show")
def run_show(body: ShowBody) -> dict:
    c = conn()
    try:
        card = body.card or sim.auto_card(c, body.brand_id, body.matches)
        # For a hand-booked card, enforce title eligibility (weight class, brand
        # exclusivity) before anything is simulated — the auto card already only
        # books eligible wrestlers, but a manual booker can put anyone anywhere.
        if body.card:
            for m in card:
                if m.get("title_id"):
                    for team in m["teams"]:
                        for wid in team:
                            ok, why = game.title_eligible(c, m["title_id"], wid)
                            if not ok:
                                raise HTTPException(400, why)
        return sim.run_show(c, body.brand_id, body.name, card,
                            is_ppv=body.is_ppv, ppv_name=body.ppv_name,
                            logistics=body.logistics)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.get("/api/booking/catalogue")
def booking_catalogue() -> dict:
    return booking.catalogue()


class PreviewBody(BaseModel):
    brand_id: str
    card: list[dict] = []
    logistics: dict | None = None


@app.post("/api/booking/preview")
def booking_preview(body: PreviewBody) -> dict:
    c = conn()
    try:
        return booking.preview(c, body.brand_id, body.card, body.logistics)
    finally:
        c.close()


@app.get("/api/sim/bookable")
def bookable(brand_id: str) -> dict:
    """Who a brand can put on a card right now, and which belts can be defended.

    Healthy wrestlers under a live contract for this brand — the manual card
    builder's roster. Shared belts (brand_id NULL) plus this brand's own are
    listed as bookable titles.
    """
    c = conn()
    try:
        st = current_state(c)
        if not st:
            return {"wrestlers": [], "titles": [], "managers": []}
        game.ensure_titles(c)
        season, today = st["season_year"], st["current_date"]
        rows = c.execute(
            """SELECT w.id, COALESCE(o.display_name, w.name) name, w.style,
                      COALESCE(s.momentum,50) momentum, COALESCE(s.morale,50) morale,
                      COALESCE(s.fatigue,0) fatigue, s.injured_until
               FROM contract c
               JOIN wrestler w ON w.id=c.wrestler_id
               LEFT JOIN attribute_override o ON o.wrestler_id=w.id
               LEFT JOIN wrestler_state s ON s.wrestler_id=w.id
               WHERE c.brand_id=? AND c.terminated_on IS NULL
                 AND c.start_year<=? AND c.end_year>=?
               ORDER BY name""", (brand_id, season, season)).fetchall()
        wrestlers = []
        ach = game.achievement_inputs(c)
        for r in rows:
            d = dict(r)
            d["overall"] = game.effective_attributes(c, r["id"], ach.get(r["id"]))["overall"]
            d["healthy"] = not (r["injured_until"] and r["injured_until"] > today)
            wrestlers.append(d)
        titles = [dict(t) for t in c.execute(
            "SELECT id, name, short_name, tier, prestige, team_size, brand_id "
            "FROM game_title WHERE active=1 AND (brand_id=? OR brand_id IS NULL) "
            "ORDER BY prestige DESC", (brand_id,))]
        # Managers signed to this brand — needed to book a Manager's Championship
        # match, where each wrestler fights on behalf of a manager.
        managers = [dict(r) for r in c.execute(
            """SELECT w.id, COALESCE(o.display_name, w.name) name
               FROM contract c
               JOIN wrestler w ON w.id=c.wrestler_id
               LEFT JOIN attribute_override o ON o.wrestler_id=w.id
               WHERE c.brand_id=? AND c.terminated_on IS NULL AND c.role='manager'
                 AND c.start_year<=? AND c.end_year>=?
               ORDER BY name""", (brand_id, season, season))]
        return {"wrestlers": wrestlers, "titles": titles, "managers": managers}
    finally:
        c.close()


# ---------------------------------------------------------------- ai (phase 5)

@app.get("/api/ai/status")
def ai_status() -> dict:
    return ai.models_info()


@app.post("/api/ai/match/{match_id}/commentary")
def ai_commentary(match_id: int) -> dict:
    c = conn()
    try:
        return ai.match_commentary(c, match_id)
    except ai.AIUnavailable as e:
        raise HTTPException(503, str(e))
    finally:
        c.close()


@app.get("/api/ai/show/{show_id}/recap")
def ai_recap(show_id: int) -> dict:
    c = conn()
    try:
        return ai.show_recap(c, show_id)
    except ai.AIUnavailable as e:
        raise HTTPException(503, str(e))
    finally:
        c.close()


class PromoBody(BaseModel):
    wrestler_id: int
    target_id: int | None = None
    topic: str | None = None


@app.post("/api/ai/promo")
def ai_promo(body: PromoBody) -> dict:
    c = conn()
    try:
        return ai.promo(c, body.wrestler_id, body.target_id, body.topic)
    except ai.AIUnavailable as e:
        raise HTTPException(503, str(e))
    finally:
        c.close()


@app.get("/api/ai/scouting/{wid}")
def ai_scouting(wid: int) -> dict:
    c = conn()
    try:
        return ai.scouting_report(c, wid)
    except ai.AIUnavailable as e:
        raise HTTPException(503, str(e))
    finally:
        c.close()


@app.get("/api/ai/storyline/{brand_id}")
def ai_storyline(brand_id: str) -> dict:
    c = conn()
    try:
        return ai.storyline(c, brand_id)
    except ai.AIUnavailable as e:
        raise HTTPException(503, str(e))
    finally:
        c.close()


class RivalBookBody(BaseModel):
    brand_id: str
    matches: int = 4
    run: bool = False        # book only, or book AND simulate immediately
    name: str | None = None


@app.post("/api/ai/rival-book")
def ai_rival_book(body: RivalBookBody) -> dict:
    """The rival GM books a card (matchups only — the sim still decides winners).

    With run=true the booked card is simulated straight away, which is how the
    AI runs the *other* brand's show for you.
    """
    c = conn()
    try:
        booked = ai.rival_booking(c, body.brand_id, body.matches)
        if body.run:
            name = body.name or f"{body.brand_id} (AI-booked)"
            show = sim.run_show(c, body.brand_id, name, booked["card"])
            return {**booked, "show": show}
        return booked
    except ai.AIUnavailable as e:
        raise HTTPException(503, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.get("/api/shows")
def shows() -> list[dict]:
    return q("""SELECT s.*, (SELECT COUNT(*) FROM sim_match m WHERE m.show_id=s.id) matches
                FROM show s ORDER BY s.held_on DESC, s.id DESC""")


@app.get("/api/shows/{show_id}")
def show_detail(show_id: int) -> dict:
    base = q("SELECT * FROM show WHERE id=?", (show_id,))
    if not base:
        raise HTTPException(404, "no such show")
    matches = q("SELECT * FROM sim_match WHERE show_id=? ORDER BY slot", (show_id,))
    for m in matches:
        m["participants"] = q(
            """SELECT p.wrestler_id, p.team, p.is_winner,
                      COALESCE(o.display_name, w.name) name,
                      (SELECT id FROM wrestler_image i WHERE i.wrestler_id=p.wrestler_id
                         AND i.is_profile=1 LIMIT 1) profile_image_id
               FROM sim_match_participant p
               JOIN wrestler w ON w.id=p.wrestler_id
               LEFT JOIN attribute_override o ON o.wrestler_id=p.wrestler_id
               WHERE p.match_id=? ORDER BY p.team""", (m["id"],))
    return {**base[0], "matches": matches}


@app.get("/api/titles")
def titles() -> list[dict]:
    c = conn()
    try:
        game.ensure_titles(c)
    finally:
        c.close()
    rows = q("""SELECT t.* FROM game_title t WHERE t.active=1
                ORDER BY CASE t.tier WHEN 'world' THEN 0 WHEN 'secondary' THEN 1
                         WHEN 'tag' THEN 2 WHEN 'cruiserweight' THEN 3 ELSE 4 END, t.id""")
    for t in rows:
        # Tag titles have two holders, so champions are a list.
        t["champions"] = q(
            """SELECT r.wrestler_id, COALESCE(o.display_name, w.name) name, r.won_on,
                      (SELECT id FROM wrestler_image i WHERE i.wrestler_id=r.wrestler_id
                         AND i.is_profile=1 LIMIT 1) profile_image_id
               FROM game_title_reign r
               JOIN wrestler w ON w.id=r.wrestler_id
               LEFT JOIN attribute_override o ON o.wrestler_id=r.wrestler_id
               WHERE r.title_id=? AND r.lost_on IS NULL""", (t["id"],))
        t["reign_count"] = q(
            "SELECT COUNT(*) n FROM game_title_reign WHERE title_id=?", (t["id"],))[0]["n"]
    return rows


@app.get("/api/titles/{title_id}/lineage")
def title_lineage(title_id: int) -> dict:
    c = conn()
    try:
        return game.title_lineage(c, title_id)
    except game.SigningError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


# ---------------------------------------------------------------- accolades

@app.get("/api/accolades/kinds")
def accolade_kinds() -> list[dict]:
    return [{"kind": k, "label": v[0], "source": v[1],
             "bonus": game.ACCOLADE_BONUS.get(k, 0)}
            for k, v in game.ACCOLADES.items()]


@app.get("/api/accolades")
def accolades() -> list[dict]:
    rows = q("""SELECT a.*, w.name FROM accomplishment a
                JOIN wrestler w ON w.id=a.wrestler_id
                ORDER BY a.season_year DESC, a.id DESC""")
    for r in rows:
        r["label"] = game.ACCOLADES.get(r["kind"], (r["kind"], "manual"))[0]
    return rows


class AwardBody(BaseModel):
    wrestler_id: int
    kind: str
    season_year: int | None = None
    detail: str | None = None


@app.post("/api/accolades")
def add_accolade(body: AwardBody) -> dict:
    c = conn()
    try:
        return game.award(c, body.wrestler_id, body.kind, body.season_year, body.detail)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.delete("/api/accolades/{acc_id}")
def del_accolade(acc_id: int) -> dict:
    c = conn()
    try:
        return game.unaward(c, acc_id)
    finally:
        c.close()


# ---------------------------------------------------------------- trades

class ProposeBody(BaseModel):
    from_brand: str
    to_brand: str
    assets: list[dict]
    note: str | None = None


@app.post("/api/trades/propose")
def propose(body: ProposeBody) -> dict:
    c = conn()
    try:
        return game.propose_trade(c, body.from_brand, body.to_brand, body.assets, body.note)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.get("/api/trades")
def list_trades(status: str | None = None) -> list[dict]:
    c = conn()
    try:
        return game.trade_offers(c, status)
    finally:
        c.close()


@app.post("/api/trades/{offer_id}/resolve")
def resolve(offer_id: int, accept: bool = Body(..., embed=True)) -> dict:
    c = conn()
    try:
        return game.resolve_trade(c, offer_id, accept)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


# ---------------------------------------------------------------- stables

@app.get("/api/stables")
def stables() -> dict:
    c = conn()
    try:
        return game.list_stables(c)
    finally:
        c.close()


class TeamBody(BaseModel):
    name: str
    brand_id: str | None = None
    members: list[int] = []


@app.post("/api/stables/teams")
def create_team(body: TeamBody) -> dict:
    c = conn()
    try:
        return game.create_team(c, body.name, body.brand_id, body.members)
    finally:
        c.close()


class TeamUpdateBody(BaseModel):
    name: str | None = None
    brand_id: str | None = None
    members: list[int] | None = None


@app.put("/api/stables/teams/{tid}")
def update_team(tid: int, body: TeamUpdateBody) -> dict:
    c = conn()
    try:
        return game.update_team(c, tid, body.name,
                                body.brand_id if body.brand_id is not None else "__keep__",
                                body.members)
    finally:
        c.close()


@app.delete("/api/stables/teams/{tid}")
def disband_team(tid: int) -> dict:
    c = conn()
    try:
        return game.disband_team(c, tid)
    finally:
        c.close()


class FactionBody(BaseModel):
    name: str
    brand_id: str | None = None
    leader_id: int | None = None
    members: list[int] = []


@app.post("/api/stables/factions")
def create_faction(body: FactionBody) -> dict:
    c = conn()
    try:
        return game.create_faction(c, body.name, body.brand_id, body.leader_id, body.members)
    finally:
        c.close()


class FactionUpdateBody(BaseModel):
    name: str | None = None
    brand_id: str | None = None
    leader_id: int | None = None
    members: list[int] | None = None


@app.put("/api/stables/factions/{fid}")
def update_faction(fid: int, body: FactionUpdateBody) -> dict:
    c = conn()
    try:
        return game.update_faction(
            c, fid, body.name,
            body.brand_id if body.brand_id is not None else "__keep__",
            body.leader_id if body.leader_id is not None else "__keep__",
            body.members)
    finally:
        c.close()


@app.delete("/api/stables/factions/{fid}")
def disband_faction(fid: int) -> dict:
    c = conn()
    try:
        return game.disband_faction(c, fid)
    finally:
        c.close()


@app.get("/api/picks")
def picks() -> list[dict]:
    c = conn()
    try:
        return game.owned_picks(c)
    finally:
        c.close()


@app.get("/api/brands/cash")
def brand_cash() -> list[dict]:
    return q("SELECT * FROM brand_cash")


# ---------------------------------------------------------------- settings / AI

def _settings_dict(c) -> dict:
    return {"ai_brand": game.get_setting(c, "ai_brand"),
            "sound": game.get_setting(c, "sound", "off"),
            "photos": game.get_setting(c, "photos", "on")}


@app.get("/api/settings")
def get_settings() -> dict:
    c = conn()
    try:
        return _settings_dict(c)
    finally:
        c.close()


class SettingBody(BaseModel):
    ai_brand: str | None = "__keep__"
    sound: str | None = "__keep__"
    photos: str | None = "__keep__"


@app.post("/api/settings")
def post_settings(body: SettingBody) -> dict:
    c = conn()
    try:
        if body.ai_brand != "__keep__":
            game.set_setting(c, "ai_brand", body.ai_brand or None)
        if body.sound != "__keep__":
            game.set_setting(c, "sound", body.sound or None)
        if body.photos != "__keep__":
            game.set_setting(c, "photos", body.photos or None)
        return _settings_dict(c)
    finally:
        c.close()


# ---------------------------------------------------------------- proposals (AI, approve-everything)

@app.get("/api/proposals")
def proposals(status: str = "pending") -> list[dict]:
    c = conn()
    try:
        return game.list_proposals(c, status)
    finally:
        c.close()


@app.post("/api/proposals/{pid}/approve")
def approve_proposal(pid: int) -> dict:
    c = conn()
    try:
        return game.approve_proposal(c, pid)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.post("/api/proposals/{pid}/reject")
def reject_proposal(pid: int) -> dict:
    c = conn()
    try:
        return game.reject_proposal(c, pid)
    finally:
        c.close()


@app.post("/api/ai/propose-pick")
def ai_propose_pick() -> dict:
    c = conn()
    try:
        return game.propose_ai_pick(c)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.post("/api/ai/propose-show")
def ai_propose_show(is_ppv: bool = Body(False, embed=True)) -> dict:
    c = conn()
    try:
        return game.propose_ai_show(c, is_ppv)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.post("/api/ai/propose-trade")
def ai_propose_trade() -> dict:
    c = conn()
    try:
        return game.propose_ai_trade(c)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


# ---------------------------------------------------------------- feuds

@app.get("/api/feuds")
def feuds(status: str | None = "active") -> list[dict]:
    c = conn()
    try:
        return game.list_feuds(c, status)
    finally:
        c.close()


class FeudBody(BaseModel):
    a_id: int
    b_id: int
    brand_id: str | None = None
    note: str | None = None


@app.post("/api/feuds")
def create_feud(body: FeudBody) -> dict:
    c = conn()
    try:
        return game.create_feud(c, body.a_id, body.b_id, body.brand_id, body.note)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.post("/api/feuds/{fid}/heat")
def set_feud_heat(fid: int, heat: int = Body(..., embed=True)) -> dict:
    c = conn()
    try:
        return game.set_feud_heat(c, fid, heat)
    finally:
        c.close()


@app.post("/api/feuds/{fid}/settle")
def settle_feud(fid: int) -> dict:
    c = conn()
    try:
        return game.settle_feud(c, fid)
    finally:
        c.close()


# ---------------------------------------------------------------- news

@app.get("/api/news")
def news(limit: int = 40) -> list[dict]:
    c = conn()
    try:
        return game.news(c, limit)
    finally:
        c.close()


# ------------------------------------------------------- history & cards

@app.get("/api/wrestler/{wid}/history")
def wrestler_history(wid: int) -> dict:
    """Her whole career: by season, by opponent, by title, by partner."""
    c = conn()
    try:
        return history.career(c, wid)
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


@app.get("/api/head-to-head")
def head_to_head(a: int, b: int) -> dict:
    """Every match these two have had against each other, in order."""
    c = conn()
    try:
        return history.head_to_head(c, a, b)
    finally:
        c.close()


@app.get("/api/wrestler/{wid}/cards")
def wrestler_cards(wid: int) -> dict:
    """Her yearly cards, newest first, plus the live one for this season.

    The live card is not stored — the season has not ended, so freezing it now
    would be a lie. See cards.live_card.
    """
    c = conn()
    try:
        return {"live": cards.live_card(c, wid), "seasons": cards.for_wrestler(c, wid)}
    finally:
        c.close()


@app.get("/api/rivalries")
def rivalries(limit: int = 40, season: int | None = None) -> list[dict]:
    """The save's real feuds, ranked — see history.RIVALRY_WEIGHTS for the sort."""
    c = conn()
    try:
        return history.rivalries(c, max(1, min(200, limit)), season)
    finally:
        c.close()


@app.get("/api/cards/team/{season}")
def team_of_season(season: int) -> dict:
    """That season's set: the best cards, with the champion always included."""
    c = conn()
    try:
        return cards.team_of_season(c, season)
    finally:
        c.close()


@app.get("/api/cards/best-ever")
def best_ever_cards(limit: int = 40) -> list[dict]:
    """Each wrestler's highest card, ranked. One row per person, at her peak."""
    c = conn()
    try:
        return cards.best_ever(c, max(1, min(200, limit)))
    finally:
        c.close()


@app.get("/api/wrestler/{wid}/progression")
def card_progression(wid: int) -> list[dict]:
    """Her overall and five stats by season — the series behind the graph."""
    c = conn()
    try:
        return cards.progression(c, wid)
    finally:
        c.close()


@app.get("/api/cards/seasons")
def card_seasons() -> list[dict]:
    c = conn()
    try:
        return cards.seasons_available(c)
    finally:
        c.close()


@app.get("/api/cards/season/{season}")
def cards_for_season(season: int, limit: int = 60) -> list[dict]:
    c = conn()
    try:
        return cards.for_season(c, season, max(1, min(400, limit)))
    finally:
        c.close()


@app.post("/api/cards/mint")
def mint_cards(season: int | None = Body(None, embed=True),
               overwrite: bool = Body(False, embed=True)) -> dict:
    """Mint a season's cards by hand.

    They are minted automatically when the calendar rolls over; this exists so a
    season already in progress can be looked at, and so a set can be re-cut after
    a rating correction — which is what `overwrite` is for, and why it is off by
    default.
    """
    c = conn()
    try:
        st = current_state(c)
        if not st:
            raise HTTPException(400, "no active save")
        return cards.snapshot(c, season if season is not None else st["season_year"],
                              overwrite=overwrite)
    finally:
        c.close()


# ---------------------------------------------------------------- royal rumble

@app.get("/api/rumble/field")
def rumble_field(size: int = rumble.FULL_FIELD) -> list[dict]:
    """A ready-made field, so the Rumble is one click from playable."""
    c = conn()
    try:
        return rumble.suggest_field(c, max(rumble.MIN_FIELD, min(rumble.FULL_FIELD, size)))
    finally:
        c.close()


class RumbleBody(BaseModel):
    # Order matters: entrant 1 comes in first and has the furthest to go.
    entrants: list[int]
    name: str = "Royal Rumble"
    brand_id: str | None = None


@app.post("/api/rumble")
def run_rumble(body: RumbleBody) -> dict:
    c = conn()
    try:
        return rumble.simulate(c, body.entrants, body.name, brand_id=body.brand_id)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


# ---------------------------------------------------------------- year-end awards

@app.get("/api/awards/nominations")
def award_nominations(season: int | None = None) -> list[dict]:
    c = conn()
    try:
        return game.list_nominations(c, season)
    finally:
        c.close()


@app.post("/api/awards/generate")
def generate_awards(season: int | None = Body(None, embed=True)) -> dict:
    """Re-run this season's nominations.

    They are generated automatically when the calendar rolls over, but that made
    them un-re-runnable: book more shows and the shortlist stays frozen at
    whatever the roster looked like in December. Idempotent — it clears the
    pending nominations for the season and rebuilds them, leaving anything
    already crowned alone.
    """
    c = conn()
    try:
        st = current_state(c)
        if not st:
            raise HTTPException(400, "no active save")
        yr = season if season is not None else st["season_year"]
        return {"season": yr, "nominations": game.generate_nominations(c, yr)}
    finally:
        c.close()


@app.post("/api/awards/{nom_id}/crown")
def crown_award(nom_id: int) -> dict:
    c = conn()
    try:
        return game.crown_award(c, nom_id)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


# ---------------------------------------------------------------- gallery

@app.get("/api/wrestler/{wid}/images")
def wrestler_images(wid: int) -> list[dict]:
    return q("""SELECT id, year, filename, original_name, source, is_profile
                FROM wrestler_image WHERE wrestler_id=?
                ORDER BY is_profile DESC, year, id""", (wid,))


@app.post("/api/wrestler/{wid}/images/{image_id}/profile")
def set_profile_image(wid: int, image_id: int) -> dict:
    """Pick which photo represents her everywhere else in the app."""
    c = conn()
    try:
        row = c.execute("SELECT * FROM wrestler_image WHERE id=? AND wrestler_id=?",
                        (image_id, wid)).fetchone()
        if not row:
            raise HTTPException(404, "no such image for that wrestler")
        # A partial unique index enforces one profile per wrestler, so the old
        # one must be cleared before the new one is set.
        c.execute("UPDATE wrestler_image SET is_profile=0 WHERE wrestler_id=?", (wid,))
        c.execute("UPDATE wrestler_image SET is_profile=1 WHERE id=?", (image_id,))
        c.commit()
        return {"wrestler_id": wid, "profile_image_id": image_id, "filename": row["filename"]}
    finally:
        c.close()


@app.delete("/api/wrestler/{wid}/images/{image_id}")
def delete_image(wid: int, image_id: int) -> dict:
    c = conn()
    try:
        row = c.execute("SELECT * FROM wrestler_image WHERE id=? AND wrestler_id=?",
                        (image_id, wid)).fetchone()
        if not row:
            raise HTTPException(404, "no such image")
        path = images.IMAGES_ROOT / str(wid) / row["filename"]
        was_profile = row["is_profile"]
        c.execute("DELETE FROM wrestler_image WHERE id=?", (image_id,))
        if was_profile:
            nxt = c.execute("SELECT id FROM wrestler_image WHERE wrestler_id=? LIMIT 1",
                            (wid,)).fetchone()
            if nxt:
                c.execute("UPDATE wrestler_image SET is_profile=1 WHERE id=?", (nxt["id"],))
        c.commit()
        if path.exists():
            path.unlink()
        return {"deleted": image_id}
    finally:
        c.close()


@app.get("/api/image/{image_id}")
def serve_image(image_id: int):
    rows = q("SELECT wrestler_id, filename FROM wrestler_image WHERE id=?", (image_id,))
    if not rows:
        raise HTTPException(404, "no such image")
    path = images.IMAGES_ROOT / str(rows[0]["wrestler_id"]) / rows[0]["filename"]
    if not path.exists():
        raise HTTPException(404, "file missing on disk")
    return FileResponse(path)


# ---------------------------------------------------------------- images

@app.post("/api/images/scan")
def scan_images() -> dict:
    c = conn()
    try:
        return images.index_local(c)
    finally:
        c.close()


@app.post("/api/images/sync-drive")
def sync_drive(folder_id: str | None = Body(None, embed=True)) -> dict:
    c = conn()
    try:
        return images.sync_drive(c, folder_id)
    finally:
        c.close()


@app.get("/api/logos")
def logos() -> dict:
    """Which logo/belt override keys the user has dropped into data/logos."""
    return {"keys": images.logo_keys(), "root": str(images.LOGOS_ROOT)}


@app.get("/api/logo/{key}")
def logo(key: str):
    p = images.logo_path(key)
    if not p or not p.exists():
        raise HTTPException(404, "no logo for that key")
    return FileResponse(p)


@app.get("/api/images/status")
def image_status() -> dict:
    ok, why = images.drive_available()
    counts = q("SELECT source, COUNT(*) n FROM wrestler_image GROUP BY source")
    return {
        "drive_ready": ok, "drive_detail": why,
        "images_root": str(images.IMAGES_ROOT),
        "inbox": str(images.INBOX),
        "counts": counts,
        "setup": None if ok else images.DRIVE_SETUP,
    }


# ------------------------------------------------- power rankings & contenders
#
# The Power 25 is PUBLISHED, not computed on read: each week is a stored issue,
# because "last week" and the movement arrows are history. Reading never
# regenerates — that is what /generate is for.

@app.get("/api/power-rankings")
def power_rankings(week_of: str | None = None) -> dict:
    c = conn()
    try:
        return rankings.latest_issue(c, week_of)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.post("/api/power-rankings/generate")
def power_rankings_generate(week_of: str | None = Body(None, embed=True)) -> dict:
    c = conn()
    try:
        if not current_state(c):
            raise HTTPException(400, "no active save")
        return rankings.generate_issue(c, week_of)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.get("/api/power-rankings/preview")
def power_rankings_preview(limit: int = 30) -> list[dict]:
    """Live scores without publishing an issue — for tuning and for seeing where
    someone sits before the next show."""
    c = conn()
    try:
        rows = rankings.power_scores(c)[:limit]
        for r in rows:
            r["name"] = game._wname(c, r["wrestler_id"])
        return rows
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.get("/api/contenders")
def contenders(week_of: str | None = None) -> list[dict]:
    c = conn()
    try:
        return rankings.contenders(c, week_of)
    finally:
        c.close()


class ContenderLockBody(BaseModel):
    wrestler_id: int | None = None


@app.post("/api/contenders/{title_id}/lock")
def contender_lock(title_id: int, body: ContenderLockBody) -> dict:
    """Name a #1 contender by hand, or clear the pin with wrestler_id null."""
    c = conn()
    try:
        return rankings.lock_contender(c, title_id, body.wrestler_id)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


# ---------------------------------------------------------------- progression
#
# Suggestions only. There is deliberately no endpoint that writes a rating
# directly from the engine — the only way a proposed number reaches a wrestler
# is POST /api/ratings/changes/{id}/resolve with approve=true.

@app.get("/api/ratings/changes")
def rating_changes(status: str = "pending", season: int | None = None) -> list[dict]:
    c = conn()
    try:
        return rankings.list_changes(c, status, season)
    finally:
        c.close()


@app.post("/api/ratings/evaluate")
def rating_evaluate(season: int | None = Body(None, embed=True)) -> dict:
    c = conn()
    try:
        st = current_state(c)
        if not st:
            raise HTTPException(400, "no active save")
        return rankings.evaluate_season(c, season or st["season_year"])
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


class ResolveRatingBody(BaseModel):
    approve: bool
    to_value: int | None = None


@app.post("/api/ratings/changes/{change_id}/resolve")
def rating_resolve(change_id: int, body: ResolveRatingBody) -> dict:
    c = conn()
    try:
        return rankings.resolve_change(c, change_id, body.approve, body.to_value)
    except game.SigningError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.post("/api/ratings/changes/resolve-all")
def rating_resolve_all(approve: bool = Body(...), season: int | None = Body(None)) -> dict:
    c = conn()
    try:
        return rankings.resolve_all(c, approve, season)
    finally:
        c.close()
