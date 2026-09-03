/**
 * The booking screen — a card that arrives PRE-BOOKED and is then edited.
 *
 * The old version of this screen opened on three empty rows and two dropdowns,
 * which made the interesting decision (what is wrong with this card?) into a
 * data-entry chore (who is even on my roster?). So the screen now loads the
 * suggestion from /api/booking/suggest — rivalries booked, belts on the main
 * event, face vs heel, stamina respected — and every row shows WHY it is there.
 * Changing any of it is one dropdown away, and "Re-suggest" throws the whole
 * thing away and asks again.
 *
 * A row's shape follows its MATCH TYPE: picking Fatal 4-Way turns two slots into
 * four, picking Tag Team turns two into two-and-two. That is why the row state
 * holds `teams: number[][]` rather than the old fixed `a`/`b` pair — a fixed
 * pair cannot represent a triple threat at all.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchBookable, fetchBookingCatalogue, fetchSuggestion, runCard, fetchRoster,
  imageUrl, type CardMatch, type CardPromo, type BrandFinance, type Calendar,
  type MatchType, type BookableWrestler,
} from './api'
import { BrandCrest, PPVBadge, Logo } from './emblems'
import { usePhotos } from './prefs'

type Row = {
  teams: number[][]
  title: number
  stip: string
  type: string
  managers: number[]
  why?: string
}
type PromoRow = { kind: string; ids: number[]; why?: string }

const SLOT = (i: number, n: number) => (i === 0 ? 'OPENER' : i === n - 1 ? 'MAIN EVENT' : 'MID CARD')

/** A stamina bar. Below 45 she is worn down and the card should say so. */
function Stamina({ value }: { value: number }) {
  const colour = value >= 70 ? '#34d399' : value >= 45 ? 'var(--color-gold)' : '#f87171'
  return (
    <span className="inline-flex items-center gap-1" title={`Stamina ${value}/100`}>
      <span className="w-8 h-[3px] rounded bg-raised overflow-hidden inline-block">
        <span className="block h-full" style={{ width: `${value}%`, background: colour }} />
      </span>
      <span className="text-[9px]" style={{ color: colour }}>{value}</span>
    </span>
  )
}

export default function BookingScreen({
  brandId, brand, calendar, onBooked,
}: { brandId: string; brand?: BrandFinance; calendar?: Calendar; onBooked: (showId?: number) => void }) {
  const qc = useQueryClient()
  const photos = usePhotos()

  // Which format is being booked. A pay-per-view is co-branded (six matches,
  // three from each side) so it needs the WHOLE league in the pickers, not one
  // brand's roster — that is the only reason `both` exists.
  const [kind, setKind] = useState<'tv' | 'snme' | 'ppv'>('tv')
  const both = kind === 'ppv'

  const { data: bookable } = useQuery({
    queryKey: ['bookable', brandId, both],
    queryFn: () => fetchBookable(brandId, both),
  })
  const { data: cat } = useQuery({ queryKey: ['bookcat'], queryFn: fetchBookingCatalogue })
  const { data: roster = [] } = useQuery({ queryKey: ['roster'], queryFn: fetchRoster })
  const { data: suggestion, isFetching: suggesting, refetch: resuggest } = useQuery({
    queryKey: ['suggest', brandId, kind],
    queryFn: () => fetchSuggestion(brandId, kind),
  })

  const [rows, setRows] = useState<Row[]>([])
  const [promoRows, setPromoRows] = useState<PromoRow[]>([])
  const [touched, setTouched] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const types = cat?.match_types ?? []
  const promoTypes = cat?.promo_types ?? []
  const typeOf = useCallback(
    (k: string): MatchType | undefined => types.find((t) => t.key === k), [types])

  // Load the suggestion in. Deliberately does NOT overwrite edits: once the GM
  // has changed a row, the card is hers until she asks for a new one.
  useEffect(() => {
    if (!suggestion || touched) return
    setRows(suggestion.matches.map((m) => ({
      teams: m.teams.map((t) => [...t]),
      title: m.title_id ?? 0,
      stip: m.stipulation ?? 'normal',
      type: m.match_type ?? 'singles',
      managers: m.managers ?? [],
      why: m.why,
    })))
    setPromoRows(suggestion.promos.map((p) => ({
      kind: p.kind, ids: [...p.wrestler_ids], why: p.why,
    })))
  }, [suggestion, touched])

  const mgrTitleId = bookable?.titles.find((t) => t.tier === 'manager')?.id ?? 0
  const managers = bookable?.managers ?? []
  const healthy = useMemo(
    () => (bookable?.wrestlers ?? []).filter((w) => w.healthy && w.role !== 'manager'),
    [bookable])
  // A promo can be cut from the shelf — an injury should not kill a story.
  const talkers = useMemo(
    () => (bookable?.wrestlers ?? []).filter((w) => w.role !== 'manager'), [bookable])
  const byId = useMemo(() => {
    const m = new Map<number, BookableWrestler>()
    for (const w of bookable?.wrestlers ?? []) m.set(w.id, w)
    return m
  }, [bookable])

  const imgOf = useMemo(() => {
    const m = new Map<number, number | null>()
    for (const r of roster) m.set(r.id, r.profile_image_id)
    return m
  }, [roster])

  const usedInMatches = useMemo(() => {
    const s = new Set<number>()
    for (const r of rows) for (const t of r.teams) for (const w of t) if (w) s.add(w)
    return s
  }, [rows])
  const usedInPromos = useMemo(() => {
    const s = new Set<number>()
    for (const p of promoRows) for (const w of p.ids) if (w) s.add(w)
    return s
  }, [promoRows])

  const stipLabel = (key: string) => cat?.stipulations.find((s) => s.key === key)?.label ?? key

  const edit = (fn: () => void) => { setTouched(true); fn() }
  const setRow = (i: number, patch: Partial<Row>) =>
    edit(() => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r))))

  /** Changing the match type reshapes the row, keeping whoever still fits. */
  const changeType = (i: number, key: string) => {
    const t = typeOf(key)
    if (!t) return
    edit(() => setRows((rs) => rs.map((r, j) => {
      if (j !== i) return r
      const flat = r.teams.flat().filter(Boolean)
      const sides = t.uneven ? 2 : t.min_sides
      const per = (s: number) => (t.uneven ? (s === 0 ? 1 : 2) : t.min_per_side)
      const teams: number[][] = []
      let k = 0
      for (let s = 0; s < sides; s++) {
        const side: number[] = []
        for (let p = 0; p < per(s); p++) side.push(flat[k++] ?? 0)
        teams.push(side)
      }
      return { ...r, type: key, teams, why: undefined }
    })))
  }

  const setSlot = (i: number, side: number, pos: number, wid: number) =>
    edit(() => setRows((rs) => rs.map((r, j) => {
      if (j !== i) return r
      const teams = r.teams.map((t) => [...t])
      teams[side][pos] = wid
      return { ...r, teams }
    })))

  const addSide = (i: number) => {
    const r = rows[i]; const t = typeOf(r.type)
    if (!t || r.teams.length >= t.max_sides) return
    setRow(i, { teams: [...r.teams.map((x) => [...x]), Array(t.min_per_side).fill(0)] })
  }
  const dropSide = (i: number) => {
    const r = rows[i]; const t = typeOf(r.type)
    if (!t || r.teams.length <= t.min_sides) return
    setRow(i, { teams: r.teams.slice(0, -1) })
  }

  const emptyRow = (): Row => ({ teams: [[0], [0]], title: 0, stip: 'normal', type: 'singles', managers: [] })
  const emptyPromo = (): PromoRow => ({ kind: promoTypes[0]?.key ?? 'callout', ids: [0] })

  const card: CardMatch[] = useMemo(() => rows
    .filter((r) => r.teams.every((t) => t.every(Boolean)) && r.teams.length >= 2)
    .map((r) => ({
      teams: r.teams,
      title_id: r.title || null,
      stipulation: r.stip,
      match_type: r.type,
      ...(r.title === mgrTitleId && mgrTitleId ? { managers: r.managers } : {}),
    })), [rows, mgrTitleId])

  const promos: CardPromo[] = useMemo(() => promoRows
    .filter((p) => p.ids.filter(Boolean).length > 0)
    .map((p) => ({ kind: p.kind, wrestler_ids: p.ids.filter(Boolean) })), [promoRows])

  const wanted = suggestion?.wanted ?? { matches: kind === 'ppv' ? 6 : 4, promos: 2 }

  const confirm = useMutation({
    mutationFn: () => {
      if (!card.length) throw new Error('Book at least one match with every slot filled.')
      for (const m of card) {
        if (m.title_id === mgrTitleId && mgrTitleId) {
          const [x, y] = m.managers ?? []
          if (!x || !y || x === y) throw new Error("Assign two different managers to the Manager's Championship match.")
        }
      }
      const ppvName = calendar?.ppv ?? undefined
      const asPPV = kind === 'ppv' && !!ppvName
      const nm = asPPV ? ppvName!
        : kind === 'snme' ? "Saturday Night's Main Event"
        : `${brand?.name} · Week`
      return runCard(brandId, nm, card, asPPV, asPPV ? ppvName : undefined, promos)
    },
    onSuccess: (r) => {
      setErr(null); onBooked(r.show_id); setTouched(false)
      qc.invalidateQueries()
    },
    onError: (e: Error) => setErr(e.message),
  })

  const canConfirm = card.length > 0 && !confirm.isPending
  const shortMatches = card.length < wanted.matches
  const shortPromos = promos.length < wanted.promos

  return (
    <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[1.5fr_0.7fr] gap-4 p-4 overflow-auto">
      {/* ============ MATCH CARD ============ */}
      <div className="flex flex-col min-h-0">
        <div className="flex items-center justify-between mb-2 gap-2 flex-wrap">
          <ColHead>Match Card</ColHead>
          <div className="flex items-center gap-1.5">
            {(['tv', 'snme', 'ppv'] as const).map((k) => {
              const f = cat?.formats.find((x) => x.key === k)
              const disabled = k === 'ppv' && !calendar?.ppv
              return (
                <button key={k} disabled={disabled}
                  onClick={() => { setKind(k); setTouched(false) }}
                  title={disabled ? 'No pay-per-view this month' : f?.desc}
                  className={`label text-[9px] px-2 py-1 rounded border ${
                    kind === k ? 'border-gold text-gold bg-gold/10'
                      : 'border-edge text-slate-500 hover:text-slate-300'
                  } ${disabled ? 'opacity-30 cursor-not-allowed' : ''}`}>
                  {k === 'tv' ? 'TV' : k === 'snme' ? 'SNME' : 'PPV'}
                </button>
              )
            })}
            <button onClick={() => { setTouched(false); resuggest() }} disabled={suggesting}
              className="label text-[9px] px-2 py-1 rounded border border-edge text-slate-400 hover:border-gold/60 hover:text-gold disabled:opacity-40">
              {suggesting ? '…' : '↻ Re-suggest'}
            </button>
          </div>
        </div>

        {/* Why the pre-booker built it this way. */}
        {!!suggestion?.notes.length && !touched && (
          <div className="card p-2.5 mb-2 border-l-2 border-l-gold/50">
            <div className="label text-[8px] text-gold mb-1">Creative's pitch</div>
            <ul className="text-[10px] text-slate-400 leading-relaxed space-y-0.5">
              {suggestion.notes.slice(0, 5).map((n, i) => <li key={i}>· {n}</li>)}
            </ul>
          </div>
        )}
        {touched && (
          <p className="text-[10px] text-slate-500 mb-2">
            Your changes — the pre-booked card is no longer being applied.{' '}
            <button onClick={() => setTouched(false)} className="text-gold hover:underline">
              revert to the suggestion
            </button>
          </p>
        )}

        <div className="space-y-2 overflow-auto pr-1">
          {rows.map((r, i) => {
            const t = typeOf(r.type)
            return (
              <div key={i} className="card p-3 pop-in" style={{ animationDelay: `${i * 40}ms` }}>
                <div className="flex items-center justify-between mb-2 gap-2">
                  <span className="label text-[9px] text-gold">{SLOT(i, rows.length)}</span>
                  <div className="flex items-center gap-1.5">
                    {t && t.key !== 'singles' && (
                      <span className="label text-[8px] px-1.5 py-[2px] rounded bg-raised text-slate-300">{t.short}</span>
                    )}
                    {r.stip !== 'normal' && (
                      <span className="label text-[8px] px-1.5 py-[2px] rounded bg-gold/15 text-gold">{stipLabel(r.stip)}</span>
                    )}
                  </div>
                </div>

                {r.why && !touched && <p className="text-[10px] text-slate-500 mb-2 italic">{r.why}</p>}

                {/* the sides */}
                <div className="space-y-1.5">
                  {r.teams.map((side, si) => (
                    <div key={si}>
                      {si > 0 && <div className="text-center text-[9px] text-slate-600 label my-1">vs</div>}
                      <div className="flex items-start gap-2">
                        <Fighter id={side[0]} imgOf={imgOf} photos={photos} name={byId.get(side[0])?.name} />
                        <div className="flex-1 space-y-1">
                          {side.map((wid, pi) => (
                            <WSelect key={pi} value={wid} self={wid}
                              exclude={usedInMatches} options={healthy}
                              onChange={(v) => setSlot(i, si, pi, v)} />
                          ))}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {t && (t.max_sides > t.min_sides) && (
                  <div className="flex items-center gap-2 mt-1.5">
                    <button onClick={() => addSide(i)} disabled={r.teams.length >= t.max_sides}
                      className="text-[10px] text-slate-500 hover:text-gold disabled:opacity-30">+ side</button>
                    <button onClick={() => dropSide(i)} disabled={r.teams.length <= t.min_sides}
                      className="text-[10px] text-slate-500 hover:text-blood disabled:opacity-30">− side</button>
                  </div>
                )}

                <div className="grid grid-cols-3 gap-1.5 mt-2">
                  <select value={r.type} onChange={(e) => changeType(i, e.target.value)}
                    title={t?.desc}
                    className="bg-canvas border border-edge rounded px-2 py-1 text-[11px]">
                    {types.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}
                  </select>
                  <select value={r.stip} onChange={(e) => setRow(i, { stip: e.target.value })}
                    className="bg-canvas border border-edge rounded px-2 py-1 text-[11px]">
                    {(cat?.stipulations ?? []).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                  </select>
                  <select value={r.title} onChange={(e) => setRow(i, { title: Number(e.target.value) })}
                    className="bg-canvas border border-edge rounded px-2 py-1 text-[11px] text-slate-300">
                    <option value={0}>No title</option>
                    {(bookable?.titles ?? []).map((x) => <option key={x.id} value={x.id}>◆ {x.short_name ?? x.name}</option>)}
                  </select>
                </div>

                {r.title === mgrTitleId && mgrTitleId > 0 && (
                  managers.length < 2
                    ? <p className="text-[10px] text-orange-400 mt-1.5">Needs two signed managers.</p>
                    : <div className="flex items-center gap-1.5 mt-1.5">
                        <MSelect value={r.managers[0] ?? 0} exclude={r.managers[1] ?? 0} options={managers}
                          onChange={(v) => setRow(i, { managers: [v, r.managers[1] ?? 0] })} />
                        <span className="text-[9px] text-slate-600">vs</span>
                        <MSelect value={r.managers[1] ?? 0} exclude={r.managers[0] ?? 0} options={managers}
                          onChange={(v) => setRow(i, { managers: [r.managers[0] ?? 0, v] })} />
                      </div>
                )}

                {rows.length > 1 && (
                  <button onClick={() => edit(() => setRows((rs) => rs.filter((_, j) => j !== i)))}
                    className="text-[10px] text-slate-600 hover:text-blood mt-1.5">remove</button>
                )}
              </div>
            )
          })}
          <button onClick={() => edit(() => setRows((rs) => [...rs, emptyRow()]))}
            className="w-full text-xs py-2 rounded border border-dashed border-edge hover:border-gold/60 text-slate-400">
            + Add match
          </button>

          {/* ---------------- PROMOS ---------------- */}
          <div className="pt-3">
            <ColHead>Promo Segments</ColHead>
            <p className="text-[10px] text-slate-600 mb-2 leading-snug">
              Talking is the cheap way to build a rivalry — almost no stamina, no injury risk.
              A match is how you cash it in.
            </p>
            <div className="space-y-2">
              {promoRows.map((p, i) => {
                const pt = promoTypes.find((x) => x.key === p.kind)
                return (
                  <div key={i} className="card p-3">
                    <div className="flex items-center justify-between mb-1.5 gap-2">
                      <span className="label text-[9px] text-emerald-400">SEGMENT {i + 1}</span>
                      {pt?.needs_feud && (
                        <span className="label text-[8px] px-1.5 py-[2px] rounded bg-blood/15 text-blood">needs a rivalry</span>
                      )}
                    </div>
                    {p.why && !touched && <p className="text-[10px] text-slate-500 mb-1.5 italic">{p.why}</p>}
                    <select value={p.kind} title={pt?.desc}
                      onChange={(e) => {
                        const nk = e.target.value
                        const npt = promoTypes.find((x) => x.key === nk)
                        edit(() => setPromoRows((ps) => ps.map((x, j) => {
                          if (j !== i) return x
                          const ids = x.ids.filter(Boolean)
                          const min = npt?.min ?? 1
                          while (ids.length < min) ids.push(0)
                          return { ...x, kind: nk, ids: ids.slice(0, npt?.max ?? 2), why: undefined }
                        })))
                      }}
                      className="w-full bg-canvas border border-edge rounded px-2 py-1 text-[11px] mb-1.5">
                      {promoTypes.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}
                    </select>
                    {pt && <p className="text-[9px] text-slate-600 mb-1.5">{pt.desc}</p>}
                    <div className="space-y-1">
                      {p.ids.map((wid, pi) => (
                        <div key={pi} className="flex items-center gap-1.5">
                          <span className="label text-[8px] text-slate-600 w-8 shrink-0">
                            {pi === 0 ? 'MIC' : `+${pi}`}
                          </span>
                          <WSelect value={wid} self={wid} exclude={usedInPromos} options={talkers}
                            onChange={(v) => edit(() => setPromoRows((ps) => ps.map((x, j) => {
                              if (j !== i) return x
                              const ids = [...x.ids]; ids[pi] = v
                              return { ...x, ids }
                            })))} />
                        </div>
                      ))}
                    </div>
                    <div className="flex items-center gap-2 mt-1.5">
                      {pt && p.ids.length < pt.max && (
                        <button onClick={() => edit(() => setPromoRows((ps) => ps.map((x, j) =>
                          j === i ? { ...x, ids: [...x.ids, 0] } : x)))}
                          className="text-[10px] text-slate-500 hover:text-gold">+ add</button>
                      )}
                      {pt && p.ids.length > pt.min && (
                        <button onClick={() => edit(() => setPromoRows((ps) => ps.map((x, j) =>
                          j === i ? { ...x, ids: x.ids.slice(0, -1) } : x)))}
                          className="text-[10px] text-slate-500 hover:text-blood">− drop</button>
                      )}
                      <button onClick={() => edit(() => setPromoRows((ps) => ps.filter((_, j) => j !== i)))}
                        className="text-[10px] text-slate-600 hover:text-blood ml-auto">remove</button>
                    </div>
                  </div>
                )
              })}
              <button onClick={() => edit(() => setPromoRows((ps) => [...ps, emptyPromo()]))}
                className="w-full text-xs py-2 rounded border border-dashed border-edge hover:border-emerald-400/60 text-slate-400">
                + Add promo
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* ============ FINAL BOOKING ============ */}
      <div className="flex flex-col min-h-0">
        <ColHead>Final Booking</ColHead>
        <div className="card p-5 text-center relative overflow-hidden champ-glow">
          <div className="grid place-items-center py-2">
            <Logo keyName={brandId.toLowerCase()} size={photos ? 84 : 52} fallback={<BrandCrest brand={brandId} size={68} />} />
          </div>
          <div className="display text-[22px] leading-none mt-1" style={{ color: brand?.colour }}>
            {kind === 'ppv' ? (calendar?.ppv ?? 'Pay-Per-View')
              : kind === 'snme' ? "Saturday Night's Main Event"
              : brand?.name}
          </div>
          <div className="text-[11px] text-slate-500 mt-1 flex items-center justify-center gap-1.5">
            {kind === 'ppv' && calendar?.ppv
              ? <><PPVBadge size={16} finale={calendar.is_finale} /> both brands</>
              : <>{calendar?.month_name} {calendar?.season_year}</>}
          </div>
          {kind === 'ppv' && (
            <p className="text-[10px] text-slate-500 mt-2 leading-snug">
              Six matches, three from each brand. Everyone in the league is bookable.
            </p>
          )}
          {kind === 'snme' && !!calendar?.snme_days?.length && (
            <p className="text-[10px] text-slate-500 mt-2">
              This month: the {calendar.snme_days.map(ordinal).join(' and the ')}.
            </p>
          )}

          <div className="mt-3 pt-3 border-t border-edge-soft space-y-1.5">
            <Tally label="Matches" value={card.length} want={wanted.matches} short={shortMatches} />
            <Tally label="Promos" value={promos.length} want={wanted.promos} short={shortPromos} />
          </div>
          <p className="text-[10px] text-slate-600 mt-2 leading-snug">
            The last match is the main event and counts double. Promos count half.
          </p>

          {err && <p className="text-[11px] text-blood mt-2 text-left leading-snug">{err}</p>}

          <button onClick={() => confirm.mutate()} disabled={!canConfirm}
            className="w-full mt-3 py-2.5 rounded font-bold text-black disabled:opacity-30 disabled:cursor-not-allowed"
            style={{ background: canConfirm ? 'var(--color-gold)' : '#444' }}>
            {confirm.isPending ? 'Running…' : 'CONFIRM BOOKING'}
          </button>
          {healthy.length < 2 && <p className="text-[11px] text-orange-400 mt-2">This brand needs 2 healthy signed wrestlers.</p>}
        </div>

        {/* Who is fresh and who is spent — the stamina the booker was working from. */}
        {!!healthy.length && (
          <div className="card p-3 mt-3">
            <div className="label text-[9px] text-slate-500 mb-2">Most worn down</div>
            <div className="space-y-1">
              {[...healthy].sort((a, b) => a.stamina - b.stamina).slice(0, 6).map((w) => (
                <div key={w.id} className="flex items-center justify-between gap-2 text-[11px]">
                  <span className={`truncate ${usedInMatches.has(w.id) ? 'text-gold' : 'text-slate-400'}`}>
                    {w.name}
                  </span>
                  <Stamina value={w.stamina} />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* The rivalries in play, so the GM can see what the card is building. */}
        {!!bookable?.feuds?.length && (
          <div className="card p-3 mt-3">
            <div className="label text-[9px] text-slate-500 mb-2">Live rivalries</div>
            <div className="space-y-1.5">
              {bookable.feuds.slice(0, 6).map((f) => (
                <div key={f.id}>
                  <div className="flex items-center justify-between gap-2 text-[11px] text-slate-400">
                    <span className="truncate">{f.a_name} <span className="text-slate-600">v</span> {f.b_name}</span>
                    <span className="stat text-[10px] text-gold shrink-0">{f.heat}</span>
                  </div>
                  <div className="h-[2px] rounded bg-raised overflow-hidden mt-0.5">
                    <div className="h-full" style={{
                      width: `${f.heat}%`,
                      background: f.heat >= 70 ? 'var(--color-blood)' : 'var(--color-gold)',
                    }} />
                  </div>
                </div>
              ))}
            </div>
            <p className="text-[9px] text-slate-600 mt-2 leading-snug">
              At 70 a rivalry is ready to blow off — that is when a stipulation earns its place.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

const ordinal = (d: number) =>
  `${d}${d % 10 === 1 && d !== 11 ? 'st' : d % 10 === 2 && d !== 12 ? 'nd'
    : d % 10 === 3 && d !== 13 ? 'rd' : 'th'}`

function Tally({ label, value, want, short }: { label: string; value: number; want: number; short: boolean }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="label text-[9px] text-slate-500">{label}</span>
      <span className="flex items-baseline gap-1">
        <span className={`stat text-xl ${short ? 'text-orange-400' : 'text-gold'}`}>{value}</span>
        <span className="text-[10px] text-slate-600">/ {want}</span>
      </span>
    </div>
  )
}

function ColHead({ children }: { children: React.ReactNode }) {
  return <h3 className="label text-[11px] text-slate-400 tracking-wider">{children}</h3>
}

function Fighter({ id, imgOf, photos, name }: { id: number; imgOf: Map<number, number | null>; photos: boolean; name?: string }) {
  const img = id ? imgOf.get(id) : null
  if (photos && img) return <img src={imageUrl(img)} alt={name} title={name} className="w-11 h-14 rounded object-cover portrait border border-edge shrink-0" />
  const initials = name ? name.split(/\s+/).slice(0, 2).map((w) => w[0]).join('') : '—'
  return <div className="w-11 h-14 rounded grid place-items-center bg-raised border border-edge text-slate-600 label text-[10px] shrink-0">{initials}</div>
}

function WSelect({ value, onChange, options, exclude, self }: {
  value: number; onChange: (v: number) => void; self: number
  options: BookableWrestler[]; exclude: Set<number>
}) {
  return (
    <select value={value} onChange={(e) => onChange(Number(e.target.value))}
      className="w-full bg-canvas border border-edge rounded px-2 py-1 text-[12px]">
      <option value={0}>— pick —</option>
      {options.map((w) => (
        <option key={w.id} value={w.id} disabled={exclude.has(w.id) && w.id !== self}>
          {w.alignment === 'heel' ? '▼' : '▲'} {w.name} ({w.overall}) · {w.stamina}%
          {w.healthy ? '' : ' · injured'}
        </option>
      ))}
    </select>
  )
}

function MSelect({ value, onChange, options, exclude }: {
  value: number; onChange: (v: number) => void; exclude: number; options: { id: number; name: string }[]
}) {
  return (
    <select value={value} onChange={(e) => onChange(Number(e.target.value))}
      className="flex-1 min-w-0 bg-canvas border border-gold/40 rounded px-2 py-1 text-[11px]">
      <option value={0}>— manager —</option>
      {options.map((m) => <option key={m.id} value={m.id} disabled={m.id === exclude}>{m.name}</option>)}
    </select>
  )
}
