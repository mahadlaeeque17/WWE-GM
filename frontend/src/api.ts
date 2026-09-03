export type Availability = 'active_2000' | 'legend' | 'import'

/** Each rating category is scored out of 20; the five sum to a 0-100 overall. */
export const CAT_MAX = 20
export const OVERALL_MAX = 100

/**
 * The five categories, in the order they are shown everywhere.
 *
 * Two of them are NOT editable and the UI has to know which:
 *   achievements  computed from what she has won in this save. You raise it by
 *                 awarding a title or an accolade, never by typing a number.
 *   wrestling     editable, but what you edit is the BASE. The number shown
 *                 includes a live swing from her win/loss record on top.
 */
export const CATEGORIES = [
  { key: 'wrestling', label: 'WRS', full: 'Wrestling',
    hint: 'In-ring ability, moved by her win/loss record in this save' },
  { key: 'achievements', label: 'ACH', full: 'Achievements',
    hint: 'What she has won in THIS save — titles, Rumbles, awards. Starts at 0' },
  { key: 'popularity', label: 'POP', full: 'Popularity',
    hint: 'Star power: cagematch score, how many people cared, and promo skill' },
  { key: 'looks', label: 'LKS', full: 'Looks', hint: 'Yours to set' },
  { key: 'personal', label: 'PER', full: 'Personal', hint: 'Yours alone' },
] as const

export type CategoryKey = typeof CATEGORIES[number]['key']

/** Categories you can type a number into. Achievements is earned, not set. */
export const EDITABLE: CategoryKey[] = ['wrestling', 'popularity', 'looks', 'personal']

/**
 * Every stat you can type a number into, across both roles.
 *
 * Wider than CategoryKey, which only covers a WRESTLER's five. Managers are rated
 * on Mic and Influence in the two slots where wrestlers get Wrestling and
 * Popularity, so anything editing ratings generically needs this union.
 * Achievements is absent by design: it is earned, never set.
 */
export type EditableStat =
  | 'wrestling' | 'popularity' | 'mic' | 'influence' | 'looks' | 'personal'

export interface Contract {
  id: number; wrestler_id: number; brand_id: string
  annual_value: number; years: number; start_year: number; end_year: number
  origin: 'draft' | 'extension' | 'free_agent'
  extended_from: number | null
  perks: string | null
  signing_bonus: number
  role: 'wrestler' | 'manager'
}

export interface PromiseStatus {
  perk: string; label: string; delivered: boolean; detail: string
}

export interface DraftPick {
  id: number; pick_number: number; brand_id: string
  wrestler_id: number | null; wrestler_name: string | null
  annual_value: number | null; picked_on: string | null
  tier: 'first' | 'second'; tier_factor: number; years: number
}

export interface DraftBoard {
  draft: {
    id: number; season_year: number; status: string; first_pick: string
    total_picks: number; first_round_factor: number; second_round_factor: number
  } | null
  picks: DraftPick[]
  on_the_clock: DraftPick | null
  available: number[]
}

export interface RosterRow {
  id: number
  name: string
  canonical_name: string
  age: number | null
  age_precision: 'exact' | 'year_only' | 'unknown'
  birthday: string | null
  birthplace: string | null
  style: string | null
  rating: number | null
  votes: number | null
  adj_rating: number | null
  availability: Availability
  /** In-ring ability as shown: the stored base plus her record swing. */
  wrestling: number
  /** The stored half of Wrestling — this is what an edit writes to. */
  wrestling_base: number
  /** How far her save win/loss record moves Wrestling, roughly -3..+3. */
  record_swing: number
  /** Computed from this save's titles and accolades. 0 until she wins something. */
  achievements: number
  /** Plain-English reasons behind the Achievements score, biggest first. */
  achievement_reasons: string[]
  popularity: number
  looks: number
  personal: number
  /** Managers are rated on these two instead of Wrestling and Popularity. */
  mic: number
  influence: number
  /** The two stats her overall was actually built from, in card order. */
  performance_pair: [EditableStat, EditableStat]
  overall: number
  value: number
  age_multiplier: number
  edited: Record<'wrestling' | 'popularity' | 'looks' | 'personal' | 'age' | 'name', boolean>
  notes: string | null
  nickname: string | null
  bio: string | null
  alignment: 'face' | 'heel'
  personality: string
  draft_class: number
  season_role: 'wrestler' | 'manager' | null
  holdout_brands: string[]
  career_earnings: number
  ppv_appearances: number
  sim: {
    matches: number; wins: number; losses: number; draws: number
    momentum: number; morale: number; fatigue: number; injured_until: string | null
  }
  history: {
    matches: number; wins: number; losses: number
    first_year: number | null; last_year: number | null
  }
  removed: boolean
  hall_of_fame: boolean
  alumni: boolean
  streak: number
  promises: PromiseStatus[]
  role: 'wrestler' | 'manager' | 'both'
  manager_price: number
  profile_image_id: number | null
  accolades: { id: number; kind: string; season_year: number | null; label: string }[]
  game_titles: { name: string; short_name: string | null; lost_on: string | null }[]
  stables: {
    tag_teams: { id: number; name: string }[]
    factions: { id: number; name: string; is_leader: number }[]
  }
  ring_names: string[]
  promotions: string[]
  titles_pre_2000: number
  contract: Contract | null
  images: { id: number; year: number | null; filename: string; is_profile: number }[]
}

export interface BrandFinance {
  brand_id: string; name: string; colour: string; season_year: number
  budget: number; committed: number; available: number; roster_size: number
}

export interface ShowSummary {
  id: number; brand_id: string; name: string; held_on: string
  rating: number | null; attendance: number | null; matches: number; promos: number
  is_ppv: number; ppv_name: string | null
  /** The scoreboard: what the night drew on TV, or what a pay-per-view sold. */
  tv_rating: number | null; buyrate: number | null
}

export interface CalendarShow {
  day: number; weekday: string; type: 'RAW' | 'SMACKDOWN' | 'PPV' | 'SNME'; name: string | null
}
export interface Calendar {
  active: boolean; date: string; season_year: number
  month: number; month_name: string; ppv: string | null
  ppv_day?: number; days_in_month?: number; first_weekday?: number
  shows?: CalendarShow[]
  /** The two Saturday Night's Main Event days in the current month. */
  snme_days?: number[]
  is_finale?: boolean
  /** `date` is the day the show lands on, computed server-side — see game.calendar. */
  schedule: { month: number; month_name: string; name: string; date: string }[]
}

/** 0-100 match quality → 0-5 stars in half-star steps. */
export const starsFor = (quality: number | null) =>
  quality == null ? 0 : Math.max(0, Math.min(5, Math.round(quality / 20 * 2) / 2))

export interface Health {
  ok: boolean
  wrestlers?: number
  save?: { current_date: string; season_year: number; rng_seed: number } | null
}

// In dev the Vite proxy forwards /api → localhost:8010, so the base is empty.
// In production (e.g. Vercel) the API lives on another host: set VITE_API_BASE
// to its origin at build time and every call is prefixed with it.
const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')

/** Absolute URL for an <img src> — images are served by the API, not bundled. */
export const imageUrl = (imageId: number) => `${API_BASE}/api/image/${imageId}`

/** Optional user-supplied logo/belt art (see data/logos). Falls back to SVG emblems. */
export const logoUrl = (key: string) => `${API_BASE}/api/logo/${key}`
export const fetchLogos = () => req<{ keys: string[]; root: string }>('/api/logos')

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API_BASE + path, {
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
  })
  if (!res.ok) {
    // FastAPI puts the useful message in `detail`; surfacing the raw status
    // instead would hide "she will not sign below her asking price".
    let msg = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) msg = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* non-JSON error body */ }
    throw new Error(msg)
  }
  return res.json() as Promise<T>
}

export const fetchHealth = () => req<Health>('/api/health')
export const fetchRoster = () => req<RosterRow[]>('/api/roster?include_removed=true')
export const fetchBrands = () => req<BrandFinance[]>('/api/brands')
export const fetchBudgets = () => req<{ brand_id: string; season_year: number; budget: number }[]>('/api/brands/budgets')
export const fetchShows = () => req<ShowSummary[]>('/api/shows')
export const fetchShow = (id: number) => req<any>(`/api/shows/${id}`)
export const fetchTitles = () => req<any[]>('/api/titles')
export const fetchImageStatus = () => req<any>('/api/images/status')

export const newGame = (seed: number) =>
  req<any>('/api/game/new', { method: 'POST', body: JSON.stringify({ seed }) })

export const advanceSeason = () =>
  req<any>('/api/game/advance-season', { method: 'POST' })

export const fetchCalendar = () => req<Calendar>('/api/calendar')
export const advanceMonth = () => req<any>('/api/game/advance-month', { method: 'POST' })

export const setTags = (id: number, body: {
  alignment?: string; personality?: string; draft_class?: number; season_role?: string | null
}) => req<any>(`/api/wrestler/${id}/tags`, { method: 'POST', body: JSON.stringify(body) })

export const clearHoldout = (id: number, brand_id: string) =>
  req<any>(`/api/wrestler/${id}/holdout/clear`, { method: 'POST', body: JSON.stringify({ brand_id }) })

export const PERSONALITIES: Record<string, string> = {
  money_hungry: 'Money-hungry', ambitious: 'Ambitious',
  loyal: 'Loyal', prima_donna: 'Prima donna',
}

export interface Personality { key: string; label: string; desc: string; factor: number; effect: string }
export const fetchPersonalities = () => req<Personality[]>('/api/negotiate/personalities')

export interface OverrideBody {
  // No `achievements`: it is computed from what she has won, so there is nothing
  // to send. Award the title or the accolade instead.
  wrestling?: number | null; popularity?: number | null
  looks?: number | null; personal?: number | null
  mic?: number | null; influence?: number | null
  age_at_reset?: number | null; role?: string | null
  display_name?: string | null; notes?: string | null
}

export const saveOverride = (id: number, body: OverrideBody) =>
  req<any>(`/api/wrestler/${id}/override`, { method: 'PUT', body: JSON.stringify(body) })

/**
 * One cell of the rating sheet. A category left out is UNTOUCHED, not cleared —
 * unlike saveOverride, which replaces the whole row.
 */
export interface RatingEdit {
  wrestler_id: number
  wrestling?: number
  popularity?: number
  looks?: number
  personal?: number
  mic?: number
  influence?: number
}

/** Many edits, one request, one save. See the endpoint for why that matters. */
export const saveRatingsBulk = (edits: RatingEdit[]) =>
  req<{ updated: number }>('/api/ratings/bulk',
    { method: 'POST', body: JSON.stringify(edits) })

export interface RatingProgress { total: number; looks_todo: number; personal_todo: number }
export const fetchRatingProgress = () => req<RatingProgress>('/api/ratings/progress')

export const removeWrestler = (id: number, reason?: string) =>
  req<any>(`/api/wrestler/${id}/remove`, { method: 'POST', body: JSON.stringify({ reason: reason ?? null }) })

export const restoreWrestler = (id: number) =>
  req<any>(`/api/wrestler/${id}/restore`, { method: 'POST' })

export const clearOverride = (id: number) =>
  req<any>(`/api/wrestler/${id}/override`, { method: 'DELETE' })

export const renameWrestler = (id: number, display_name: string | null) =>
  req<any>(`/api/wrestler/${id}/rename`, { method: 'POST', body: JSON.stringify({ display_name }) })

export const saveBio = (id: number, nickname: string | null, bio: string | null) =>
  req<any>(`/api/wrestler/${id}/bio`, { method: 'POST', body: JSON.stringify({ nickname, bio }) })

/**
 * Re-sign somebody already on the roster.
 *
 * This is a NEGOTIATION: the salary, the perks and the length are all put to
 * her together, and she can refuse. `annual_value` omitted means "pay whatever
 * she asks". Use `extensionOffer` first to see her verdict without committing.
 */
export const extendContract = (
  wrestler_id: number, years: number, annual_value?: number,
  perks: string[] = [], signing_bonus = 0,
) =>
  req<any>('/api/contracts/extend', {
    method: 'POST',
    body: JSON.stringify({ wrestler_id, years, annual_value, perks, signing_bonus }),
  })

export const fetchDraft = (kind = 'wrestler') => req<DraftBoard>(`/api/draft?kind=${kind}`)

export const startDraft = (rounds: number, first_pick: string, kind = 'wrestler') =>
  req<any>('/api/draft/start', { method: 'POST', body: JSON.stringify({ rounds, first_pick, kind }) })

export const makePick = (
  wrestler_id: number, annual_value?: number, kind = 'wrestler',
  perks: string[] = [], signing_bonus = 0,
) =>
  req<any>('/api/draft/pick', {
    method: 'POST',
    body: JSON.stringify({ wrestler_id, annual_value, kind, perks, signing_bonus }),
  })

export const passPick = (kind = 'wrestler') =>
  req<any>('/api/draft/pass', { method: 'POST', body: JSON.stringify({ kind }) })

// ---- negotiation ----
export interface Perk { key: string; label: string; desc: string }
export interface NegotiationResult {
  verdict: 'accept' | 'counter' | 'offended' | 'walked'
  mood: string; offer: number; counter: number | null
  patience: number; message: string; perks: string[]; signing_bonus: number
  personality: string; morale: number
}
export const fetchPerks = () => req<Perk[]>('/api/negotiate/perks')
export const negotiateQuote = (wrestler_id: number, kind = 'wrestler', tier_factor = 1) =>
  req<{ asking: number; base: number; toughness: number; note: string
        personality: string; personality_label: string
        personality_desc: string; personality_effect: string; morale: number }>(
    `/api/negotiate/quote?wrestler_id=${wrestler_id}&kind=${kind}&tier_factor=${tier_factor}`)
export const negotiateOffer = (body: {
  wrestler_id: number; brand_id: string; salary: number; perks: string[]
  signing_bonus: number; kind: string; context: string; tier_factor: number
}) => req<NegotiationResult>('/api/negotiate/offer', { method: 'POST', body: JSON.stringify(body) })
export const negotiateReset = (wrestler_id: number, brand_id: string) =>
  req<any>('/api/negotiate/reset', { method: 'POST', body: JSON.stringify({ wrestler_id, brand_id }) })

// ---- free agency ----
export const fetchFreeAgents = () => req<number[]>('/api/free-agents')
export const signFreeAgent = (
  wrestler_id: number, brand_id: string, annual_value: number,
  perks: string[] = [], signing_bonus = 0,
) => req<any>('/api/contracts/free-agent', {
  method: 'POST', body: JSON.stringify({ wrestler_id, brand_id, annual_value, perks, signing_bonus }),
})

// ---- stables ----
export interface StableMember { wrestler_id: number; name: string }
export interface TagTeam { id: number; name: string; brand_id: string | null; members: StableMember[] }
export interface Faction {
  id: number; name: string; brand_id: string | null
  leader_id: number | null; leader_name?: string | null; members: StableMember[]
}
export const fetchStables = () => req<{ tag_teams: TagTeam[]; factions: Faction[] }>('/api/stables')
export const createTeam = (name: string, brand_id: string | null, members: number[]) =>
  req<any>('/api/stables/teams', { method: 'POST', body: JSON.stringify({ name, brand_id, members }) })
export const updateTeam = (id: number, body: { name?: string; brand_id?: string | null; members?: number[] }) =>
  req<any>(`/api/stables/teams/${id}`, { method: 'PUT', body: JSON.stringify(body) })
export const disbandTeam = (id: number) =>
  req<any>(`/api/stables/teams/${id}`, { method: 'DELETE' })
export const createFaction = (name: string, brand_id: string | null, leader_id: number | null, members: number[]) =>
  req<any>('/api/stables/factions', { method: 'POST', body: JSON.stringify({ name, brand_id, leader_id, members }) })
export const updateFaction = (id: number, body: { name?: string; brand_id?: string | null; leader_id?: number | null; members?: number[] }) =>
  req<any>(`/api/stables/factions/${id}`, { method: 'PUT', body: JSON.stringify(body) })
export const disbandFaction = (id: number) =>
  req<any>(`/api/stables/factions/${id}`, { method: 'DELETE' })

// ---- scouting (Groq) ----
export const aiScouting = (wid: number) =>
  req<{ wrestler_id: number; nickname: string | null; report: string; also_known_as: string[] }>(
    `/api/ai/scouting/${wid}`)

// ---- gallery ----
export interface GalleryImage {
  id: number; year: number | null; filename: string
  original_name: string | null; source: string; is_profile: number
}
export const fetchGallery = (id: number) => req<GalleryImage[]>(`/api/wrestler/${id}/images`)
export const setProfileImage = (wid: number, imageId: number) =>
  req<any>(`/api/wrestler/${wid}/images/${imageId}/profile`, { method: 'POST' })
export const deleteImage = (wid: number, imageId: number) =>
  req<any>(`/api/wrestler/${wid}/images/${imageId}`, { method: 'DELETE' })

// ---- accolades ----
export interface AccoladeKind { kind: string; label: string; source: 'sim' | 'manual'; bonus: number }
export const fetchAccoladeKinds = () => req<AccoladeKind[]>('/api/accolades/kinds')
export const addAccolade = (wrestler_id: number, kind: string, season_year?: number, detail?: string) =>
  req<any>('/api/accolades', {
    method: 'POST',
    body: JSON.stringify({ wrestler_id, kind, season_year: season_year ?? null, detail: detail ?? null }),
  })
export const removeAccolade = (id: number) =>
  req<any>(`/api/accolades/${id}`, { method: 'DELETE' })

// ---- titles ----
export interface GameTitle {
  id: number; name: string; short_name: string | null
  brand_id: string | null; tier: string; prestige: number
  team_size: number; max_weight_kg: number | null; hardcore: number
  champions: { wrestler_id: number; name: string; won_on: string; profile_image_id: number | null }[]
  reign_count: number
}
export const fetchGameTitles = () => req<GameTitle[]>('/api/titles')

export interface Reign {
  reign_no: number; wrestler_id: number; name: string; profile_image_id: number | null
  won_on: string; lost_on: string | null; days: number; ongoing: boolean; age_at_win: number | null
}
export interface TitleLineage {
  title: GameTitle
  reigns: Reign[]
  as_of: string
  stats: {
    total_reigns: number; distinct_champions: number
    first_champion: Reign | null; current_champions: Reign[]
    longest_reign: Reign | null; shortest_reign: Reign | null
    oldest_at_win: Reign | null; youngest_at_win: Reign | null
    most_reigns: { wrestler_id: number; name: string; reigns: number } | null
  }
}
export const fetchLineage = (titleId: number) => req<TitleLineage>(`/api/titles/${titleId}/lineage`)

// ---- trades ----
export interface TradeAsset {
  id: number; side: string; kind: 'wrestler' | 'pick' | 'cash'
  wrestler_id: number | null; wrestler_name: string | null
  pick_season: number | null; pick_round: number | null; cash: number | null
  value?: number; overall?: number
}
export interface TradeOffer {
  id: number; from_brand: string; to_brand: string; status: string
  note: string | null; created_on: string; assets: TradeAsset[]
}
export const fetchTrades = (status?: string) =>
  req<TradeOffer[]>(`/api/trades${status ? `?status=${status}` : ''}`)
export const proposeTrade = (from_brand: string, to_brand: string, assets: any[], note?: string) =>
  req<any>('/api/trades/propose', {
    method: 'POST', body: JSON.stringify({ from_brand, to_brand, assets, note: note ?? null }),
  })
export const resolveTrade = (offer_id: number, accept: boolean) =>
  req<any>(`/api/trades/${offer_id}/resolve`, { method: 'POST', body: JSON.stringify({ accept }) })
export const fetchPicks = () => req<any[]>('/api/picks')
export const fetchBrandCash = () => req<any[]>('/api/brands/cash')

export const ROLE_LABEL: Record<string, string> = {
  wrestler: 'Wrestler', manager: 'Manager', both: 'Wrestler + Manager',
}

export const releaseContract = (wrestler_id: number) =>
  req<any>('/api/contracts/release', { method: 'POST', body: JSON.stringify({ wrestler_id }) })

export const tradeWrestlers = (side_a: number[], side_b: number[]) =>
  req<any>('/api/contracts/trade', { method: 'POST', body: JSON.stringify({ side_a, side_b }) })

/** Auto-book and run in one call. `kind` picks the show format (tv | snme | ppv),
 *  which decides how many matches and promos the card is built to. */
export const runShow = (brand_id: string, name: string, matches = 4, is_ppv = false,
                        ppv_name?: string, kind?: string) =>
  req<any>('/api/sim/show', {
    method: 'POST',
    body: JSON.stringify({ brand_id, name, matches, is_ppv, ppv_name: ppv_name ?? null,
                           kind: kind ?? (is_ppv ? 'ppv' : 'tv') }),
  })

// ---- manual booking ----
/**
 * One row of a card. `match_type` is the STRUCTURE (singles, tag, triple
 * threat, fatal 4-way...) and `stipulation` the RULES (steel cage, tables,
 * no-DQ) — two independent axes that compose, so a Fatal 4-Way inside a cage
 * needs no entry of its own.
 */
export interface CardMatch {
  teams: number[][]; title_id: number | null; managers?: number[]
  stipulation?: string; match_type?: string
  /** Why the pre-booker put this match on the show. Not sent back. */
  why?: string; slot?: number
}
/** One promo segment. `wrestler_ids[0]` is whoever has the mic. */
export interface CardPromo {
  kind: string; wrestler_ids: number[]; topic?: string | null
  why?: string; slot?: number; label?: string
}
export interface Logistics { arena: string; production: string; effects: string; advertising: string }
export const runCard = (
  brand_id: string, name: string, card: CardMatch[], is_ppv = false, ppv_name?: string,
  promos: CardPromo[] = [], logistics?: Logistics,
) =>
  req<any>('/api/sim/show', {
    method: 'POST',
    body: JSON.stringify({
      brand_id, name, is_ppv, ppv_name: ppv_name ?? null,
      card: card.map((m) => ({
        teams: m.teams, title_id: m.title_id, stipulation: m.stipulation ?? 'normal',
        match_type: m.match_type ?? 'singles', ...(m.managers ? { managers: m.managers } : {}),
      })),
      promos: promos.map((p) => ({ kind: p.kind, wrestler_ids: p.wrestler_ids, topic: p.topic ?? null })),
      logistics: logistics ?? null,
    }),
  })

export interface MatchType {
  key: string; label: string; short: string; desc: string
  min_sides: number; max_sides: number; min_per_side: number; max_per_side: number
  quality: number; fatigue: number; uneven: boolean; wrestlers: number
}
export interface PromoType {
  key: string; label: string; desc: string; min: number; max: number
  heat: number; momentum: number; guest_mom: number; quality: number
  fatigue: number; needs_feud: boolean
}
export interface ShowFormat {
  key: string; label: string; desc: string
  matches: number; promos: number; brands: number; per_brand?: number
}
export interface Tier { key: string; label: string; cost: number; capacity?: number; ticket?: number; att_mult?: number; quality?: number; fan_growth?: number; no_dq?: boolean }
export interface BookingCatalogue {
  stipulations: Tier[]; arenas: Tier[]; production: Tier[]; effects: Tier[]; advertising: Tier[]
  match_types: MatchType[]; promo_types: PromoType[]; formats: ShowFormat[]
}
export const fetchBookingCatalogue = () => req<BookingCatalogue>('/api/booking/catalogue')

/** The pre-booked card the GM starts from. Writes nothing. */
export interface Suggestion {
  format: string; format_label: string; brands: string[]
  matches: CardMatch[]; promos: CardPromo[]; notes: string[]
  wanted: { matches: number; promos: number }
}
export const fetchSuggestion = (brand_id: string, kind: string) =>
  req<Suggestion>(`/api/booking/suggest?brand_id=${brand_id}&kind=${kind}`)
export interface BookingPreview { fans: number; attendance: number; gate: number; cost: number; budget: number; stipend: number; proj_quality: number; affordable: boolean; capacity: number }
export const bookingPreview = (brand_id: string, card: CardMatch[], logistics: Logistics) =>
  req<BookingPreview>('/api/booking/preview', { method: 'POST', body: JSON.stringify({ brand_id, card, logistics }) })

export interface BookableWrestler {
  id: number; name: string; style: string | null; overall: number
  popularity: number; alignment: string; brand_id: string; role: string
  momentum: number; morale: number; fatigue: number
  /** 100 = fresh, 0 = spent. The readable side of fatigue. */
  stamina: number
  injured_until: string | null; healthy: boolean
}
export interface Bookable {
  wrestlers: BookableWrestler[]
  titles: {
    id: number; name: string; short_name: string | null; tier: string
    prestige: number; team_size: number; brand_id: string | null
  }[]
  managers: { id: number; name: string; brand_id: string }[]
  feuds: Feud[]
  tag_teams: { id: number; name: string; members: number[] }[]
  factions: { id: number; name: string; members: number[] }[]
}
export const fetchBookable = (brand_id: string, both_brands = false) =>
  req<Bookable>(`/api/sim/bookable?brand_id=${brand_id}&both_brands=${both_brands}`)

// ---- AI (Groq, phase 5) ----
export interface AIStatus {
  ready: boolean; detail?: string
  models?: string[]; strong?: string; fast?: string
}
export const fetchAIStatus = () => req<AIStatus>('/api/ai/status')
export const aiCommentary = (matchId: number) =>
  req<{ match_id: number; narrative: string }>(`/api/ai/match/${matchId}/commentary`, { method: 'POST' })
export const aiRecap = (showId: number) =>
  req<{ show_id: number; recap: string }>(`/api/ai/show/${showId}/recap`)
export const aiPromo = (wrestler_id: number, target_id?: number, topic?: string) =>
  req<{ wrestler_id: number; promo: string }>('/api/ai/promo', {
    method: 'POST', body: JSON.stringify({ wrestler_id, target_id: target_id ?? null, topic: topic ?? null }),
  })
export const aiStoryline = (brand_id: string) =>
  req<{ brand_id: string; storyline: string }>(`/api/ai/storyline/${brand_id}`)
export const aiRivalBook = (brand_id: string, matches: number, run: boolean, name?: string) =>
  req<any>('/api/ai/rival-book', {
    method: 'POST', body: JSON.stringify({ brand_id, matches, run, name: name ?? null }),
  })

// ---- settings / AI opponent ----
export interface Settings { ai_brand: string | null; sound: string | null; photos: string | null }
export const fetchSettings = () => req<Settings>('/api/settings')
export const saveSettings = (body: { ai_brand?: string | null; sound?: string | null; photos?: string | null }) =>
  req<Settings>('/api/settings', { method: 'POST', body: JSON.stringify(body) })

// ---- proposals (approve-everything) ----
export interface Proposal {
  id: number; kind: 'draft_pick' | 'show' | 'trade'; brand_id: string | null
  summary: string; payload: any; status: string; created_on: string
}
export const fetchProposals = (status = 'pending') => req<Proposal[]>(`/api/proposals?status=${status}`)
export const approveProposal = (id: number) => req<any>(`/api/proposals/${id}/approve`, { method: 'POST' })
export const rejectProposal = (id: number) => req<any>(`/api/proposals/${id}/reject`, { method: 'POST' })
export const aiProposePick = () => req<any>('/api/ai/propose-pick', { method: 'POST' })
export const aiProposeShow = (is_ppv = false) =>
  req<any>('/api/ai/propose-show', { method: 'POST', body: JSON.stringify({ is_ppv }) })
export const aiProposeTrade = () => req<any>('/api/ai/propose-trade', { method: 'POST' })

// ---- feuds ----
export interface Feud {
  id: number; a_id: number; b_id: number; a_name: string; b_name: string
  brand_id: string | null; heat: number; status: string; note: string | null
}
export const fetchFeuds = (status = 'active') => req<Feud[]>(`/api/feuds?status=${status}`)
export const createFeud = (a_id: number, b_id: number, brand_id?: string | null, note?: string) =>
  req<any>('/api/feuds', { method: 'POST', body: JSON.stringify({ a_id, b_id, brand_id: brand_id ?? null, note: note ?? null }) })
export const setFeudHeat = (id: number, heat: number) =>
  req<any>(`/api/feuds/${id}/heat`, { method: 'POST', body: JSON.stringify({ heat }) })
export const settleFeud = (id: number) => req<any>(`/api/feuds/${id}/settle`, { method: 'POST' })

// ---- news ----
export interface NewsItem {
  id: number; on_date: string; season_year: number | null
  kind: string; brand_id: string | null; icon: string | null; text: string
}
export const fetchNews = (limit = 40) => req<NewsItem[]>(`/api/news?limit=${limit}`)

// ---- year-end awards ----
export interface Nomination {
  id: number; season_year: number; kind: string; wrestler_id: number | null
  name: string | null; label: string; detail: string | null; score: number | null; status: string
}
export const fetchNominations = (season?: number) =>
  req<Nomination[]>(`/api/awards/nominations${season != null ? `?season=${season}` : ''}`)
export const crownAward = (nomId: number) => req<any>(`/api/awards/${nomId}/crown`, { method: 'POST' })

// ------------------------------------------------------- cards & career history

/** Managers are scored on MIC/INF where wrestlers get WRS/POP. */
export type StatKey =
  | 'wrestling' | 'popularity' | 'mic' | 'influence'
  | 'achievements' | 'looks' | 'personal'

export interface CardStat {
  key: StatKey
  label: string
  /** The stored value, 0-20 — what the Rate sheet edits. */
  v20: number
  /** The same value as a 1-99 card stat. Display only; nothing stores this. */
  v99: number
}

export type CardTier = 'bronze' | 'silver' | 'gold' | 'elite'

export interface PlayerCard {
  wrestler_id: number
  season_year: number
  name: string
  role: 'wrestler' | 'manager' | 'both'
  overall: number
  tier: CardTier
  /** "World champion", "Royal Rumble winner"… or null for a plain card. */
  special: string | null
  style: string | null
  brand_id: string | null
  /** Her W-L(-D) that season, or null if she did not wrestle. */
  record: string | null
  stats: CardStat[]
  /** True for the current season, which is not minted yet. */
  live?: boolean
}

export const fetchWrestlerCards = (id: number) =>
  req<{ live: PlayerCard; seasons: PlayerCard[] }>(`/api/wrestler/${id}/cards`)

export interface CardSeason { season_year: number; cards: number; specials: number }
export const fetchCardSeasons = () => req<CardSeason[]>('/api/cards/seasons')
export const fetchSeasonCards = (season: number, limit = 60) =>
  req<PlayerCard[]>(`/api/cards/season/${season}?limit=${limit}`)
export const mintCards = (season?: number, overwrite = false) =>
  req<{ season: number; minted: number; skipped: number }>('/api/cards/mint',
    { method: 'POST', body: JSON.stringify({ season, overwrite }) })

export interface RivalrySide { wrestler_id: number; name: string; wins: number }
export interface Rivalry {
  a: RivalrySide
  b: RivalrySide
  meetings: number
  draws: number
  avg_quality: number
  best_quality: number | null
  first_met: string
  last_met: string
  title_matches: number
  ppv_matches: number
  /** 1.0 when dead even, 0.0 when one side has won everything. */
  closeness: number
  active_heat: number | null
  score: number
}
export const fetchRivalries = (limit = 40, season?: number) =>
  req<Rivalry[]>(`/api/rivalries?limit=${limit}${season != null ? `&season=${season}` : ''}`)

export interface TeamOfSeason {
  season: number
  wrestlers: PlayerCard[]
  managers: PlayerCard[]
  champions: string[]
  note?: string
}
export const fetchTeamOfSeason = (season: number) =>
  req<TeamOfSeason>(`/api/cards/team/${season}`)
export const fetchBestEver = (limit = 40) =>
  req<PlayerCard[]>(`/api/cards/best-ever?limit=${limit}`)

export interface ProgressionPoint {
  season_year: number
  overall: number
  tier: CardTier
  special: string | null
  record: string | null
  stats: Partial<Record<StatKey, number>>
}
export const fetchProgression = (id: number) =>
  req<ProgressionPoint[]>(`/api/wrestler/${id}/progression`)

export interface SeasonLine {
  season: number; matches: number; wins: number; losses: number; draws: number
  ppv: number; titles_won: number; avg_quality: number | null; main_events: number
}
export interface VersusLine {
  wrestler_id: number; name: string; matches: number
  wins: number; losses: number; draws: number; win_pct: number; last_met: string | null
}
export interface ReignLine {
  id: number; won_on: string; lost_on: string | null; name: string
  short_name: string | null; tier: string; days: number; ongoing: boolean
}
export interface BestMatch {
  match_id: number; quality: number; held_on: string; show: string
  title: string | null; stipulation: string | null; won: boolean
}
export interface CareerHistory {
  wrestler_id: number
  name: string
  total: {
    matches: number; wins: number; losses: number; draws: number; ppv: number
    reigns: number; title_days: number; accolades: number; win_pct: number
  }
  seasons: SeasonLine[]
  versus: VersusLine[]
  partners: VersusLine[]
  reigns: ReignLine[]
  accolades: { kind: string; season_year: number | null; detail: string | null; awarded_on: string; label: string }[]
  contracts: { brand_id: string; annual_value: number; start_year: number; end_year: number; terminated_on: string | null; origin: string; role: string }[]
  best_matches: BestMatch[]
}
export const fetchHistory = (id: number) => req<CareerHistory>(`/api/wrestler/${id}/history`)

export interface HeadToHead {
  a: { wrestler_id: number; name: string; wins: number }
  b: { wrestler_id: number; name: string; wins: number }
  draws: number
  meetings: {
    match_id: number; held_on: string; show: string; is_ppv: boolean
    quality: number | null; finish: string | null; stipulation: string | null
    title: string | null; winner_id: number | null
  }[]
}
export const fetchHeadToHead = (a: number, b: number) =>
  req<HeadToHead>(`/api/head-to-head?a=${a}&b=${b}`)

// ------------------------------------------------------------------- the Rumble

export interface RumbleEntrant {
  wrestler_id: number; name: string; number: number
  eliminations: number; lasted: number
}
export interface RumbleEvent {
  t: number; kind: 'enter' | 'out' | 'win'
  wrestler_id: number; name: string
  number?: number; by?: number | null; by_name?: string | null
}
export interface RumbleResult {
  show_id: number; match_id: number; name: string; held_on: string
  entrants: RumbleEntrant[]
  timeline: RumbleEvent[]
  winner: RumbleEntrant
  iron_woman: boolean
  most_eliminations: RumbleEntrant | null
  quality: number
}

export interface RumbleCandidate { wrestler_id: number; name: string; overall: number }

/** A ready-made field, weakest first, so the stars come in last. */
export const fetchRumbleField = (size = 30) =>
  req<RumbleCandidate[]>(`/api/rumble/field?size=${size}`)

export const runRumble = (entrants: number[], name: string, brand_id?: string | null) =>
  req<RumbleResult>('/api/rumble',
    { method: 'POST', body: JSON.stringify({ entrants, name, brand_id }) })

export const scanImages = () => req<any>('/api/images/scan', { method: 'POST' })
export const syncDrive = (folder_id?: string) =>
  req<any>('/api/images/sync-drive', { method: 'POST', body: JSON.stringify({ folder_id: folder_id ?? null }) })

export const money = (n: number) =>
  n >= 1_000_000 ? `$${(n / 1_000_000).toFixed(2)}M` : `$${(n / 1000).toFixed(0)}k`

export const moneyFull = (n: number) => `$${n.toLocaleString()}`

export function prettyDate(d: string | null): string | null {
  if (!d) return null
  const m = d.match(/^(\d{2})\.(\d{2})\.(\d{4})$/)
  if (!m) return d
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return `${+m[1]} ${months[+m[2] - 1]} ${m[3]}`
}

/** Age is only trustworthy when cagematch gave a full date of birth. */
export function ageLabel(age: number | null, precision: string): string {
  if (age === null) return '—'
  return precision === 'exact' ? String(age) : `~${age}`
}

export const AVAIL_LABEL: Record<Availability, string> = {
  active_2000: 'Active 2000', legend: 'Legend', import: 'Import',
}

// ------------------------------------------------------- power rankings
//
// An issue is PUBLISHED, not computed on read — `last_week` and the movement
// arrows are history, so the board is stored per week and never recalculated
// when you look at it.

export type Movement = 'up' | 'down' | 'same' | 'new'

export interface PowerEntry {
  rank_no: number
  wrestler_id: number
  name: string
  score: number
  last_week: number | null
  note: string
  movement: Movement
  delta: number | null
  titles: string[]
  brand_id: string | null
}

export interface PowerIssue {
  issue: { id: number; week_of: string; season_year: number } | null
  entries: PowerEntry[]
  buzz: { quote: string; reply: string }[]
  issues: { id: number; week_of: string; season_year: number }[]
}

export const fetchPowerRankings = (weekOf?: string) =>
  req<PowerIssue>(`/api/power-rankings${weekOf ? `?week_of=${weekOf}` : ''}`)

export const generatePowerRankings = () =>
  req<any>('/api/power-rankings/generate', { method: 'POST', body: JSON.stringify({}) })

export interface ContenderRow {
  rank_no: number; wrestler_id: number; name: string; score: number
  last_week: number | null; note: string; movement: Movement; delta: number | null
}

export interface TitleLadder {
  title: {
    id: number; name: string; short_name: string | null
    tier: string; brand_id: string | null; prestige: number
  }
  champion: { wrestler_id: number; name: string; won_on: string } | null
  locked_contender: number | null
  contenders: ContenderRow[]
}

export const fetchContenders = () => req<TitleLadder[]>('/api/contenders')

export const lockContender = (titleId: number, wrestler_id: number | null) =>
  req<any>(`/api/contenders/${titleId}/lock`, {
    method: 'POST', body: JSON.stringify({ wrestler_id }),
  })

// ------------------------------------------------------- rating progression
//
// The engine only ever proposes. `to_value` is editable right up until the
// moment it is approved, and approval is the only thing that writes a rating.

export interface RatingChange {
  id: number
  season_year: number
  wrestler_id: number
  name: string
  category: 'wrestling' | 'popularity'
  from_value: number
  to_value: number
  suggested: number
  delta: number
  reason: string
  score: number | null
  status: 'pending' | 'approved' | 'rejected'
  created_on: string
  resolved_on: string | null
}

export const fetchRatingChanges = (status = 'pending', season?: number) =>
  req<RatingChange[]>(`/api/ratings/changes?status=${status}${season ? `&season=${season}` : ''}`)

export const evaluateRatings = (season?: number) =>
  req<{ season_year: number; created: number }>('/api/ratings/evaluate', {
    method: 'POST', body: JSON.stringify({ season: season ?? null }),
  })

export const resolveRatingChange = (id: number, approve: boolean, to_value?: number) =>
  req<any>(`/api/ratings/changes/${id}/resolve`, {
    method: 'POST', body: JSON.stringify({ approve, to_value: to_value ?? null }),
  })

export const resolveAllRatingChanges = (approve: boolean, season?: number) =>
  req<any>('/api/ratings/changes/resolve-all', {
    method: 'POST', body: JSON.stringify({ approve, season: season ?? null }),
  })

// ------------------------------------------------------- durable save status
//
// `durable` is the only field worth acting on. `mode: "disk"` is correct on a
// laptop and catastrophic on a serverless host, so the mode alone cannot tell
// you whether progress is being kept.

export interface StoreStatus {
  mode: 'disk' | 'dir' | 'blob'
  enabled: boolean
  configured: boolean
  detail: string
  durable: boolean
  durable_detail: string
  ephemeral_host: boolean
  hydrated: number | null
  persisted: number | null
  error: string | null
  db_bytes: number
}

export const fetchStoreStatus = () => req<StoreStatus>('/api/store/status')

// ============================================================ the locker room
//
// How the roster feels, what it is asking for, who is hurt, and who the crowd
// wants turned. One endpoint because the screen is useless in pieces — a
// request only makes sense next to the morale that caused it.

/** One standing condition acting on her morale, with the lever the GM has. */
export interface MoraleFactor {
  key: string; label: string; delta: number; detail: string; fix: string | null
}
export interface PayPosition {
  under_contract: boolean
  salary?: number; market?: number; ratio?: number
  verdict?: 'overpaid' | 'generous' | 'fair' | 'underpaid' | 'insulted'
  label?: string; gap?: number; contract_id?: number; years_left?: number
  perks?: string[]
}
export interface MoraleSnapshot {
  wrestler_id: number; name: string
  morale: number; band: string; band_note: string; rock_bottom: boolean
  personality: string; personality_label: string
  pay: PayPosition
  factors: MoraleFactor[]
  monthly_drift: number
  stamina: number
  rested_until: string | null; injured_until: string | null
  brand_id?: string
  headline?: string
}

export interface WrestlerRequest {
  id: number; wrestler_id: number; brand_id: string | null
  kind: string; label: string; icon: string
  severity: 'ask' | 'firm' | 'final'
  ask_value: number | null; ask_target: number | null; target_name: string | null
  reason: string; detail: string | null
  status: string; created_on: string; expires_on: string | null
  times_asked: number
  name: string; morale: number; band: string; stamina: number
  can_force: boolean
}

export interface MedicalRow {
  wrestler_id: number; name: string; brand_id: string
  stamina: number; fatigue: number
  risk: number; level: 'fine' | 'elevated' | 'risky' | 'reckless'
  reasons: string[]
  out: boolean; resting: boolean
  injured_until: string | null; rested_until: string | null
  injury_note: string | null; injury_severity: string | null
  weeks_left?: number
}
export interface MedicalReport {
  out: MedicalRow[]; resting: MedicalRow[]; at_risk: MedicalRow[]
  returning: MedicalRow[]
  severities?: { key: string; label: string; note: string }[]
}

export interface TurnSuggestion {
  id: number; wrestler_id: number; name: string
  from_align: string; to_align: string
  trigger: string; trigger_label: string
  reason: string; evidence: string | null; score: number
  status: string; created_on: string
}

export interface ForcedMove {
  id: number; wrestler_id: number; name: string
  kind: 'trade' | 'walkout'
  from_brand: string | null; to_brand: string | null
  on_date: string; reason: string
}

export interface LockerRoom {
  active: boolean
  room: MoraleSnapshot[]
  requests: WrestlerRequest[]
  medical: MedicalReport
  turns: TurnSuggestion[]
  forced: ForcedMove[]
  history: (WrestlerRequest & { resolved_on: string })[]
  bands: { floor: number; label: string; note: string }[]
  rock_bottom: number
}

export const fetchLockerRoom = (brand_id?: string) =>
  req<LockerRoom>(`/api/locker-room${brand_id ? `?brand_id=${brand_id}` : ''}`)
export const fetchMorale = (wid: number) => req<MoraleSnapshot>(`/api/morale/${wid}`)
/** Say yes or no. `counter_value` part-grants a raise at a number you pick. */
export const resolveRequest = (id: number, grant: boolean, counter_value?: number) =>
  req<any>(`/api/requests/${id}/resolve`, {
    method: 'POST',
    body: JSON.stringify({ grant, counter_value: counter_value ?? null }),
  })
export const generateRequests = () => req<any>('/api/requests/generate', { method: 'POST' })

export const fetchMedical = (brand_id?: string) =>
  req<MedicalReport>(`/api/medical${brand_id ? `?brand_id=${brand_id}` : ''}`)
export const restWrestler = (wid: number, weeks: number) =>
  req<any>(`/api/medical/${wid}/rest`, { method: 'POST', body: JSON.stringify({ weeks }) })
export const clearRest = (wid: number) =>
  req<any>(`/api/medical/${wid}/rest`, { method: 'DELETE' })

export const fetchTurns = (status = 'pending') =>
  req<TurnSuggestion[]>(`/api/turns?status=${status}`)
export const scanTurns = () => req<any>('/api/turns/scan', { method: 'POST' })
export const resolveTurn = (id: number, approve: boolean) =>
  req<any>(`/api/turns/${id}/resolve`, { method: 'POST', body: JSON.stringify({ approve }) })

// ================================================================ storylines

export interface FeudBeat {
  id: number; feud_id: number; on_date: string; show_id: number | null
  kind: string; text: string; heat_after: number | null
  winner_id: number | null; winner_name: string | null
}
export interface StorylineNext {
  want: 'keep_apart' | 'talk' | 'physical' | 'blowoff'
  segment: 'promo' | 'match'
  advice: string
  stage: string
  protected: boolean
  series: { a_wins: number; b_wins: number; draws: number; matches: number; leader: number | null }
}
export interface Storyline {
  id: number; a_id: number; b_id: number; a_name: string; b_name: string
  brand_id: string | null; heat: number; status: string; note: string | null
  started_on: string | null
  stage: string; stage_label: string; stage_note: string
  planned_blowoff: string | null; blowoff_label: string | null
  beats: FeudBeat[]
  next: StorylineNext
  series: StorylineNext['series']
}
export const fetchStorylines = (status = 'active') =>
  req<Storyline[]>(`/api/storylines?status=${status}`)
/** Point a feud at a date. The booker then WITHHOLDS the singles match. */
export const planBlowoff = (fid: number, on_date: string | null, label?: string) =>
  req<any>(`/api/storylines/${fid}/plan`, {
    method: 'POST', body: JSON.stringify({ on_date, label: label ?? null }),
  })

// ================================================================= brand war

export interface BrandWarBrand {
  brand_id: string; name: string; colour: string
  shows: number; avg_rating: number | null; best_rating: number | null
  weeks_won: number; weeks_contested: number
  ppv_count: number; avg_buyrate: number | null
  best_show: { id: number; name: string; held_on: string; tv_rating: number } | null
  fanbase: number
}
export interface BrandWeek {
  week_of: string
  brands: { brand_id: string; name: string; colour: string; tv_rating: number; viewers: number; show_id: number }[]
  contested: boolean; winner: string | null; tied: boolean; margin: number | null
}
export interface BrandWar {
  season_year: number
  brands: BrandWarBrand[]
  weeks: BrandWeek[]
  ties: number
  leader: string | null
  summary: string
}
export const fetchBrandWar = (season?: number) =>
  req<BrandWar>(`/api/brand-war${season ? `?season=${season}` : ''}`)

// ============================================================ crowd reaction

export interface CrowdSegment {
  kind: 'match' | 'promo'; id: number; slot: number
  promo_kind?: string
  quality: number | null
  reaction: string | null; reaction_score: number | null
}
export interface ShowCrowd {
  segments: CrowdSegment[]
  loudest: CrowdSegment | null
  avg_reaction: number | null
}
export const fetchShowCrowd = (showId: number) =>
  req<ShowCrowd>(`/api/shows/${showId}/crowd`)

/** Reaction label → a colour, so the same word reads the same everywhere. */
export const REACTION_COLOUR: Record<string, string> = {
  hostile: '#f87171', flat: '#64748b', polite: '#94a3b8',
  'into it': '#38bdf8', hot: 'var(--color-gold)',
  'red hot': '#fb923c', nuclear: '#f472b6',
}

// =============================================================== extensions

export interface ExtensionQuote {
  asking: number; market: number; base: number
  morale: number; retention_factor: number; stance: string
  toughness: number
  personality: string; personality_label: string
  personality_desc: string; personality_effect: string
}
export const fetchExtensionQuote = (wrestler_id: number, kind = 'wrestler') =>
  req<ExtensionQuote>(`/api/negotiate/extension-quote?wrestler_id=${wrestler_id}&kind=${kind}`)

export interface ExtensionVerdict {
  wrestler_id: number; verdict: 'accept' | 'counter' | 'offended' | 'walked'
  mood: string; offer: number; counter: number | null
  patience: number; years: number
  personality: string; morale: number
}
export const extensionOffer = (
  wrestler_id: number, salary: number, years: number,
  perks: string[] = [], signing_bonus = 0,
) =>
  req<ExtensionVerdict>('/api/negotiate/extension-offer', {
    method: 'POST',
    body: JSON.stringify({ wrestler_id, salary, years, perks, signing_bonus }),
  })
