-- WWE GM 2000 — schema v2
--
-- Three layers, deliberately separated:
--
--   SOURCE   what cagematch says. Rebuilt freely by normalize.py.
--   OVERRIDE what YOU changed. normalize.py NEVER touches these.
--   GAME     mutable simulation state. Reset by starting a new save.
--
-- The effective value of any attribute is COALESCE(override, derived). That is
-- the whole reason overrides live in their own table: re-running the harvest or
-- retuning a formula must never silently wipe a hand-tuned roster.

-- ============================================================ SOURCE

CREATE TABLE IF NOT EXISTS wrestler (
    id            INTEGER PRIMARY KEY,      -- cagematch worker id
    name          TEXT NOT NULL,
    birthday      TEXT,                     -- dd.mm.yyyy as scraped
    birth_year    INTEGER,
    age_at_reset  INTEGER,                  -- exact age on 1 Jan 2000
    age_precision TEXT,                     -- exact | year_only | unknown
    birthplace    TEXT,
    height_cm     INTEGER,
    weight_kg     INTEGER,
    rating        REAL,                     -- raw cagematch rating
    votes         INTEGER,
    adj_rating    REAL,                     -- vote-shrunk
    career_start  TEXT,
    career_end    TEXT,
    style         TEXT,
    harvested_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ring_name (
    wrestler_id   INTEGER NOT NULL REFERENCES wrestler(id),
    name          TEXT NOT NULL,
    is_primary    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (wrestler_id, name)
);

CREATE TABLE IF NOT EXISTS promotion_year (
    wrestler_id   INTEGER NOT NULL REFERENCES wrestler(id),
    promotion     TEXT NOT NULL,
    year          INTEGER NOT NULL,
    matches       INTEGER NOT NULL DEFAULT 0,
    wins          INTEGER NOT NULL DEFAULT 0,
    losses        INTEGER NOT NULL DEFAULT 0,
    draws         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (wrestler_id, promotion, year)
);

CREATE TABLE IF NOT EXISTS title_reign (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    wrestler_id   INTEGER NOT NULL REFERENCES wrestler(id),
    title         TEXT NOT NULL,
    promotion     TEXT,
    won_on        TEXT,
    lost_on       TEXT,
    days          INTEGER
);

-- Derived from source by attributes.py. Rebuilt on every normalize run.
--
-- Only the STORED half of the rating system lives here. Achievements is absent
-- on purpose: it is computed from this save's championships and accolades on
-- every read, and a stored copy would go stale the moment a belt changed hands
-- and then contradict the trophy cabinet next to it. The live win/loss swing on
-- top of `wrestling` is computed the same way, for the same reason.
CREATE TABLE IF NOT EXISTS attributes (
    wrestler_id   INTEGER PRIMARY KEY REFERENCES wrestler(id),
    wrestling     INTEGER NOT NULL,         -- in-ring ability, 0-20 (base only)
    popularity    INTEGER NOT NULL,         -- score + reach + promo, 0-20
    looks         INTEGER NOT NULL,         -- 0-20, seeded then hand-edited
    personal      INTEGER NOT NULL DEFAULT 10,  -- 0-20, yours alone
    availability  TEXT NOT NULL,            -- active_2000 | legend | import
    role          TEXT NOT NULL DEFAULT 'wrestler',  -- wrestler | manager | both
    role_source   TEXT,                     -- the raw cagematch Roles string
    alignment     TEXT NOT NULL DEFAULT 'face',      -- face | heel
    personality   TEXT NOT NULL DEFAULT 'ambitious',  -- see negotiate.PERSONALITIES
    formula_ver   INTEGER NOT NULL
);

-- ============================================================ OVERRIDE

-- Wrestlers you have removed from the game.
--
-- Deliberately a soft delete recorded in the OVERRIDE layer, not a DELETE from
-- `wrestler`. A hard delete would be undone the next time normalize.py rebuilds
-- the source tables from the harvest — the roster would silently repopulate.
-- Filtering on this table instead makes the removal permanent and reversible.
CREATE TABLE IF NOT EXISTS excluded_wrestler (
    wrestler_id   INTEGER PRIMARY KEY REFERENCES wrestler(id),
    reason        TEXT,
    excluded_at   TEXT NOT NULL
);

-- Any column you edit by hand. NULL means "use the derived value".
-- normalize.py must never DELETE or UPDATE this table.
--
-- `experience` and `charisma` are RETIRED columns, kept so that old saves open
-- without a rewrite. Experience stopped being a category when Wrestling took
-- over in-ring ability; charisma was folded into Popularity as its promo
-- component. Nothing reads either one — see migrate_ratings.py, which carried
-- their values across.
CREATE TABLE IF NOT EXISTS attribute_override (
    wrestler_id   INTEGER PRIMARY KEY REFERENCES wrestler(id),
    wrestling     INTEGER,
    popularity    INTEGER,
    looks         INTEGER,
    personal      INTEGER,
    experience    INTEGER,                  -- retired
    charisma      INTEGER,                  -- retired
    age_at_reset  INTEGER,
    role          TEXT,                     -- wrestler | manager | both
    alignment     TEXT,                     -- face | heel
    personality   TEXT,                     -- see negotiate.PERSONALITIES
    draft_class   INTEGER,                  -- season she first enters the draft pool
    display_name  TEXT,
    notes         TEXT,
    updated_at    TEXT
);

-- ============================================================ GAME

CREATE TABLE IF NOT EXISTS game_state (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    current_date  TEXT NOT NULL,            -- yyyy-mm-dd, starts 2000-01-01
    season_year   INTEGER NOT NULL,
    rng_seed      INTEGER NOT NULL,         -- same seed + same booking = same show
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS brand (
    id            TEXT PRIMARY KEY,         -- RAW | SMACKDOWN
    name          TEXT NOT NULL,
    colour        TEXT
);

-- Budget per brand per season. Grows each year like an NBA cap.
CREATE TABLE IF NOT EXISTS brand_budget (
    brand_id      TEXT NOT NULL REFERENCES brand(id),
    season_year   INTEGER NOT NULL,
    budget        INTEGER NOT NULL,         -- total spendable this season
    PRIMARY KEY (brand_id, season_year)
);

CREATE TABLE IF NOT EXISTS contract (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    wrestler_id   INTEGER NOT NULL REFERENCES wrestler(id),
    brand_id      TEXT NOT NULL REFERENCES brand(id),
    annual_value  INTEGER NOT NULL,
    years         INTEGER NOT NULL,
    start_year    INTEGER NOT NULL,
    end_year      INTEGER NOT NULL,
    signed_on     TEXT NOT NULL,
    terminated_on TEXT,                     -- set on release/trade-out
    origin        TEXT NOT NULL DEFAULT 'draft',   -- draft | extension | free_agent
    extended_from INTEGER REFERENCES contract(id), -- the deal this extends
    perks         TEXT,                     -- JSON list of perk keys negotiated in
    signing_bonus INTEGER NOT NULL DEFAULT 0,
    role          TEXT NOT NULL DEFAULT 'wrestler'  -- signed as wrestler | manager
);

-- A draft per season. Snake order, brands alternate picks.
CREATE TABLE IF NOT EXISTS draft (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    season_year   INTEGER NOT NULL,
    draft_kind    TEXT NOT NULL DEFAULT 'wrestler',  -- wrestler | manager
    status        TEXT NOT NULL DEFAULT 'active',    -- active | complete
    first_pick    TEXT NOT NULL REFERENCES brand(id),
    created_at    TEXT NOT NULL,
    UNIQUE (season_year, draft_kind)
);

CREATE TABLE IF NOT EXISTS draft_pick (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id      INTEGER NOT NULL REFERENCES draft(id),
    pick_number   INTEGER NOT NULL,
    brand_id      TEXT NOT NULL REFERENCES brand(id),   -- who picks (may be traded)
    original_brand TEXT REFERENCES brand(id),           -- whose slot it was
    wrestler_id   INTEGER REFERENCES wrestler(id),   -- NULL until used
    contract_id   INTEGER REFERENCES contract(id),
    picked_on     TEXT,
    UNIQUE (draft_id, pick_number)
);

CREATE INDEX IF NOT EXISTS idx_pick_draft ON draft_pick(draft_id, pick_number);

CREATE INDEX IF NOT EXISTS idx_contract_active
    ON contract(wrestler_id) WHERE terminated_on IS NULL;

-- Experience and momentum accrue here as the sim runs.
CREATE TABLE IF NOT EXISTS wrestler_state (
    wrestler_id   INTEGER PRIMARY KEY REFERENCES wrestler(id),
    sim_matches   INTEGER NOT NULL DEFAULT 0,
    sim_wins      INTEGER NOT NULL DEFAULT 0,
    sim_losses    INTEGER NOT NULL DEFAULT 0,
    sim_draws     INTEGER NOT NULL DEFAULT 0,
    momentum      INTEGER NOT NULL DEFAULT 50,
    morale        INTEGER NOT NULL DEFAULT 50,
    fatigue       INTEGER NOT NULL DEFAULT 0,
    injured_until TEXT,
    career_earnings INTEGER NOT NULL DEFAULT 0,   -- accrues each season under contract
    ppv_appearances INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS show (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    brand_id      TEXT REFERENCES brand(id),
    name          TEXT NOT NULL,
    held_on       TEXT NOT NULL,
    rating        REAL,                     -- overall show quality 0-100
    attendance    INTEGER,
    is_ppv        INTEGER NOT NULL DEFAULT 0,
    ppv_name      TEXT                      -- e.g. "WrestleMania 2000"
);

CREATE TABLE IF NOT EXISTS sim_match (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    show_id       INTEGER NOT NULL REFERENCES show(id),
    slot          INTEGER NOT NULL,         -- card position, 1 = opener
    title_id      INTEGER REFERENCES game_title(id),
    quality       REAL,                     -- star rating 0-100
    finish        TEXT,                     -- pinfall | submission | dq | draw
    narrative     TEXT                      -- Groq-written, phase 5
);

CREATE TABLE IF NOT EXISTS sim_match_participant (
    match_id      INTEGER NOT NULL REFERENCES sim_match(id),
    wrestler_id   INTEGER NOT NULL REFERENCES wrestler(id),
    team          INTEGER NOT NULL DEFAULT 0,
    is_winner     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (match_id, wrestler_id)
);

-- Game-side championships, separate from the historical title_reign records.
--
-- brand_id NULL = shared between both brands (tag, cruiserweight, hardcore).
-- tier drives prestige, who is eligible, and how much a reign is worth.
CREATE TABLE IF NOT EXISTS game_title (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    short_name    TEXT,
    brand_id      TEXT REFERENCES brand(id),   -- NULL = shared
    tier          TEXT NOT NULL,               -- world | secondary | tag | cruiserweight | hardcore
    prestige      INTEGER NOT NULL DEFAULT 50,
    team_size     INTEGER NOT NULL DEFAULT 1,  -- 2 for tag titles
    max_weight_kg INTEGER,                     -- cruiserweight limit, NULL = open
    hardcore      INTEGER NOT NULL DEFAULT 0,  -- 1 = no-DQ, title can change on a countout
    active        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS game_title_reign (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title_id      INTEGER NOT NULL REFERENCES game_title(id),
    wrestler_id   INTEGER NOT NULL REFERENCES wrestler(id),
    won_on        TEXT NOT NULL,
    lost_on       TEXT,
    won_at_match  INTEGER REFERENCES sim_match(id)
);

-- ============================================================ ACCOLADES

-- Career accomplishments beyond championships. Some are awarded by the sim
-- (Rumble wins, MITB), some you record by hand (Playboy covers, awards).
CREATE TABLE IF NOT EXISTS accomplishment (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    wrestler_id   INTEGER NOT NULL REFERENCES wrestler(id),
    kind          TEXT NOT NULL,            -- see ACCOLADES in game.py
    season_year   INTEGER,
    detail        TEXT,
    awarded_on    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_acc_wrestler ON accomplishment(wrestler_id);
CREATE INDEX IF NOT EXISTS idx_acc_kind     ON accomplishment(kind);

-- ============================================================ TRADES

-- A proposed trade, pending your approval. Assets on each side can be
-- wrestlers, future draft picks, or cash.
CREATE TABLE IF NOT EXISTS trade_offer (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    from_brand    TEXT NOT NULL REFERENCES brand(id),
    to_brand      TEXT NOT NULL REFERENCES brand(id),
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending | accepted | rejected
    note          TEXT,
    created_on    TEXT NOT NULL,
    resolved_on   TEXT
);

CREATE TABLE IF NOT EXISTS trade_asset (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id      INTEGER NOT NULL REFERENCES trade_offer(id),
    side          TEXT NOT NULL,            -- the brand_id giving this asset up
    kind          TEXT NOT NULL,            -- wrestler | pick | cash
    wrestler_id   INTEGER REFERENCES wrestler(id),
    pick_season   INTEGER,                  -- future draft year
    pick_round    INTEGER,
    cash          INTEGER
);

CREATE INDEX IF NOT EXISTS idx_asset_offer ON trade_asset(offer_id);

-- Draft picks a brand owns, so they can be traded before the draft exists.
CREATE TABLE IF NOT EXISTS pick_asset (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    season_year   INTEGER NOT NULL,
    round_no      INTEGER NOT NULL,
    original_brand TEXT NOT NULL REFERENCES brand(id),
    owner_brand   TEXT NOT NULL REFERENCES brand(id),
    draft_kind    TEXT NOT NULL DEFAULT 'wrestler',  -- wrestler | manager
    used          INTEGER NOT NULL DEFAULT 0,
    UNIQUE (season_year, round_no, original_brand, draft_kind)
);

-- Cash a brand has on top of its salary budget, moved by trades.
CREATE TABLE IF NOT EXISTS brand_cash (
    brand_id      TEXT PRIMARY KEY REFERENCES brand(id),
    balance       INTEGER NOT NULL DEFAULT 0
);

-- ============================================================ MEDIA

-- MANY images per wrestler — a gallery, not one slot per year.
--
-- Files keep their ORIGINAL name on disk under data/images/<wrestler_id>/.
-- The old scheme stored them as "<year>.jpg", which silently overwrote a second
-- photo of the same wrestler from the same year — fine for one portrait,
-- useless for a gallery.
--
-- `year` is nullable: a filename without one is simply undated, not rejected.
-- Exactly one image per wrestler may have is_profile = 1; that is the portrait
-- shown everywhere else in the app.
CREATE TABLE IF NOT EXISTS wrestler_image (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    wrestler_id   INTEGER NOT NULL REFERENCES wrestler(id),
    year          INTEGER,
    filename      TEXT NOT NULL,
    original_name TEXT,
    drive_file_id TEXT,
    source        TEXT NOT NULL,            -- local | drive
    is_profile    INTEGER NOT NULL DEFAULT 0,
    synced_at     TEXT,
    UNIQUE (wrestler_id, filename)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_profile
    ON wrestler_image(wrestler_id) WHERE is_profile = 1;

-- ============================================================ STABLES

-- Tag teams (usually 2) and factions (any size). Both belong to a brand and can
-- be renamed/disbanded. A wrestler can be in at most one of each at a time is
-- NOT enforced in SQL — the UI manages it — but membership is unique per group.
CREATE TABLE IF NOT EXISTS tag_team (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    brand_id      TEXT REFERENCES brand(id),
    formed_on     TEXT,
    active        INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS tag_team_member (
    team_id       INTEGER NOT NULL REFERENCES tag_team(id) ON DELETE CASCADE,
    wrestler_id   INTEGER NOT NULL REFERENCES wrestler(id),
    PRIMARY KEY (team_id, wrestler_id)
);

CREATE TABLE IF NOT EXISTS faction (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    brand_id      TEXT REFERENCES brand(id),
    leader_id     INTEGER REFERENCES wrestler(id),
    formed_on     TEXT,
    active        INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS faction_member (
    faction_id    INTEGER NOT NULL REFERENCES faction(id) ON DELETE CASCADE,
    wrestler_id   INTEGER NOT NULL REFERENCES wrestler(id),
    PRIMARY KEY (faction_id, wrestler_id)
);

-- Wrestlers permanently removed from the game. Unlike excluded_wrestler (a soft
-- hide), a banned id is HARD-deleted from wrestler and must never be rebuilt by
-- normalize.py — it checks this table before inserting.
CREATE TABLE IF NOT EXISTS banned_wrestler (
    wrestler_id   INTEGER PRIMARY KEY,
    banned_at     TEXT NOT NULL
);

-- For a wrestler eligible as BOTH, which pool she counts for THIS season's
-- drafts. Absent = she shows in both pools. Cleared each season, so next year
-- she can be assigned the other role.
CREATE TABLE IF NOT EXISTS season_role (
    season_year   INTEGER NOT NULL,
    wrestler_id   INTEGER NOT NULL REFERENCES wrestler(id),
    role          TEXT NOT NULL,            -- wrestler | manager
    PRIMARY KEY (season_year, wrestler_id)
);

-- A wrestler who walked out of negotiations sits out the year for THAT brand —
-- she won't appear in that brand's pool or sign with it until the GM clears it
-- or the season rolls over.
CREATE TABLE IF NOT EXISTS holdout (
    season_year   INTEGER NOT NULL,
    wrestler_id   INTEGER NOT NULL REFERENCES wrestler(id),
    brand_id      TEXT NOT NULL REFERENCES brand(id),
    created_on    TEXT,
    PRIMARY KEY (season_year, wrestler_id, brand_id)
);

CREATE INDEX IF NOT EXISTS idx_py_wrestler  ON promotion_year(wrestler_id);
CREATE INDEX IF NOT EXISTS idx_py_year      ON promotion_year(year);
CREATE INDEX IF NOT EXISTS idx_title_w      ON title_reign(wrestler_id);
CREATE INDEX IF NOT EXISTS idx_img_wrestler ON wrestler_image(wrestler_id, year);
CREATE INDEX IF NOT EXISTS idx_smp_wrestler ON sim_match_participant(wrestler_id);
