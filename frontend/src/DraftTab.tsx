import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchDraft, fetchBrands, startDraft, passPick,
  money, moneyFull, ageLabel, type RosterRow, type DraftBoard,
} from './api'
import { StatCell } from './ui'
import NegotiationModal from './NegotiationModal'

/**
 * The draft is the ONLY way a contract is created, and it runs in two phases:
 * the WRESTLER draft first (2 rounds, 10 per brand), then the MANAGER draft
 * (3 rounds, 3 per brand) whose pool is everyone left undrafted. There is no
 * setup screen and no kind switch — the phase follows the state of the drafts.
 */
export default function DraftTab({ roster }: { roster: RosterRow[] }) {
  const qc = useQueryClient()
  const { data: wBoard } = useQuery({ queryKey: ['draft', 'wrestler'], queryFn: () => fetchDraft('wrestler') })
  const { data: mBoard } = useQuery({ queryKey: ['draft', 'manager'], queryFn: () => fetchDraft('manager') })
  const { data: brands = [] } = useQuery({ queryKey: ['brands'], queryFn: fetchBrands })

  const [firstPick, setFirstPick] = useState('RAW')
  const [search, setSearch] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [negotiating, setNegotiating] = useState<RosterRow | null>(null)

  const wDone = wBoard?.draft?.status === 'complete'
  const mDone = mBoard?.draft?.status === 'complete'

  // Which draft is live decides the whole screen.
  const kind: 'wrestler' | 'manager' =
    wBoard?.draft && !wDone ? 'wrestler'
    : mBoard?.draft ? 'manager'
    : wDone ? 'manager' : 'wrestler'
  const board: DraftBoard | undefined = kind === 'manager' ? mBoard : wBoard

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['draft'] })
    qc.invalidateQueries({ queryKey: ['picks'] })
    qc.invalidateQueries({ queryKey: ['roster'] })
    qc.invalidateQueries({ queryKey: ['brands'] })
  }

  const begin = useMutation({
    mutationFn: (k: 'wrestler' | 'manager') => startDraft(2, firstPick, k),
    onSuccess: () => { setErr(null); invalidate() },
    onError: (e: Error) => setErr(e.message),
  })
  const pass = useMutation({
    mutationFn: () => passPick(kind),
    onSuccess: () => { setErr(null); invalidate() },
    onError: (e: Error) => setErr(e.message),
  })

  const onClock = board?.on_the_clock ?? null
  const clockBrand = brands.find((b) => b.brand_id === onClock?.brand_id)

  const pool = useMemo(() => {
    const avail = new Set(board?.available ?? [])
    const term = search.trim().toLowerCase()
    return roster
      .filter((r) => avail.has(r.id))
      .filter((r) => !term || r.name.toLowerCase().includes(term)
        || r.ring_names.some((n) => n.toLowerCase().includes(term)))
      .sort((a, b) => b.overall - a.overall)
  }, [roster, board, search])

  const made = (board?.picks ?? []).filter((p) => p.wrestler_id !== null)

  // ---------------------------------------------------------------- intro / phase gates
  if (!brands.length) {
    return <p className="p-6 text-sm text-slate-500">Start a new game first, then open the draft.</p>
  }

  // Nothing running yet, or wrestler draft finished and manager draft not opened.
  if (!board?.draft || (kind === 'manager' && !mBoard?.draft)) {
    const startingManager = wDone && !mBoard?.draft
    return (
      <div className="p-8 max-w-xl">
        <Stepper phase={startingManager ? 'manager' : 'wrestler'} wDone={!!wDone} mDone={!!mDone} />
        <h2 className="display text-[26px] mb-2 mt-5">
          {startingManager ? 'Manager Draft' : 'Wrestler Draft'}
        </h2>
        <p className="text-sm text-slate-400 mb-5 leading-relaxed">
          {startingManager ? (
            <>The wrestler draft is done — <span className="text-slate-200">{madeCount(wBoard)} signed</span>.
            Everyone left undrafted is now eligible to be signed as a manager: 3 rounds,
            3 per brand. Picks snake between the brands.</>
          ) : (
            <>A season starts here. The wrestler draft runs first — 2 snake rounds, 10 per brand.
            The brand picking second in round one picks first in round two. Anyone not taken
            becomes eligible for the manager draft afterwards.</>
          )}
        </p>
        <div className="flex items-end gap-3">
          <label className="text-xs text-slate-500">
            First pick
            <select value={firstPick} onChange={(e) => setFirstPick(e.target.value)}
              className="block mt-1 bg-panel border border-edge rounded px-2 py-1.5 text-sm">
              {brands.map((b) => <option key={b.brand_id} value={b.brand_id}>{b.name}</option>)}
            </select>
          </label>
          <button
            onClick={() => begin.mutate(startingManager ? 'manager' : 'wrestler')}
            disabled={begin.isPending}
            className="px-5 py-2 rounded bg-gold text-black text-sm font-semibold hover:bg-gold/85 disabled:opacity-40">
            {begin.isPending ? 'Opening…' : startingManager ? 'Start manager draft' : 'Start wrestler draft'}
          </button>
        </div>
        {err && <p className="text-xs text-blood mt-3">{err}</p>}
      </div>
    )
  }

  // Both drafts complete.
  if (kind === 'manager' && mDone) {
    return (
      <div className="p-8 max-w-xl">
        <Stepper phase="done" wDone={!!wDone} mDone={!!mDone} />
        <h2 className="display text-[26px] mb-2 mt-5">Draft complete</h2>
        <p className="text-sm text-slate-400 leading-relaxed">
          Both brands are stocked — {madeCount(wBoard)} wrestlers and {madeCount(mBoard)} managers signed.
          Head to <strong className="text-slate-200">Raw</strong> or <strong className="text-slate-200">SmackDown</strong> to
          start booking, or the <strong className="text-slate-200">Shows</strong> tab to run a card.
        </p>
      </div>
    )
  }

  const accent = kind === 'manager' ? 'var(--color-gold)' : (clockBrand?.colour ?? 'var(--color-edge)')

  return (
    <div className="flex-1 flex min-h-0">
      {/* ---------------- pool ---------------- */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="px-5 pt-3">
          <Stepper phase={kind} wDone={!!wDone} mDone={!!mDone} />
        </div>
        <div
          className="px-5 py-3 mt-2 border-b-2 flex items-center gap-4 flex-wrap"
          style={{ borderColor: accent, background: onClock && clockBrand ? `${clockBrand.colour}18` : undefined }}
        >
          {onClock ? (
            <>
              <div>
                <div className="label text-[10px] text-slate-500">On the clock · {kind} draft</div>
                <div className="text-lg font-bold flex items-center gap-2" style={{ color: clockBrand?.colour }}>
                  {clockBrand?.name} · pick #{onClock.pick_number}
                  <span className="label text-[9px] px-1.5 py-[3px] rounded"
                    style={{
                      background: onClock.tier === 'first' ? 'rgba(232,185,63,0.18)' : 'rgba(148,163,184,0.15)',
                      color: onClock.tier === 'first' ? 'var(--color-gold)' : '#94a3b8',
                    }}
                    title={`${onClock.tier}-round pick — signs a ${onClock.years}-year deal`}>
                    {onClock.tier === 'first' ? `1ST RD · ${onClock.years}YR` : `2ND RD · ${onClock.years}YR`}
                  </span>
                </div>
              </div>
              <div className="text-xs text-slate-400">
                {clockBrand && <>{moneyFull(clockBrand.available)} available</>}
              </div>
              <div className="flex-1" />
              <span className="text-[11px] text-slate-500">Click Negotiate to open talks</span>
              <button onClick={() => pass.mutate()}
                className="text-xs px-3 py-1.5 rounded border border-edge hover:border-blood/60 hover:text-blood">
                Pass
              </button>
            </>
          ) : (
            <div className="flex items-center gap-3 w-full">
              <div className="text-sm text-emerald-400 font-semibold">
                {kind} draft complete — {made.length} picks used.
              </div>
              <div className="flex-1" />
              {kind === 'wrestler' && !mBoard?.draft && (
                <button onClick={() => begin.mutate('manager')} disabled={begin.isPending}
                  className="text-xs px-3 py-1.5 rounded bg-gold text-black font-semibold disabled:opacity-40">
                  {begin.isPending ? 'Opening…' : 'Start manager draft →'}
                </button>
              )}
            </div>
          )}
        </div>

        {err && <p className="text-xs text-blood px-5 py-2 bg-blood/10">{err}</p>}

        <div className="px-5 py-2 border-b border-edge flex items-center gap-3">
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder={`Search the ${kind} pool…`}
            className="bg-panel border border-edge rounded px-3 py-1.5 text-sm w-64
                       placeholder:text-slate-600 focus:outline-none focus:border-gold/60" />
          <span className="text-xs text-slate-500">{pool.length} available</span>
        </div>

        <div className="flex-1 overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-canvas border-b border-edge">
              <tr className="text-xs uppercase tracking-wider text-slate-500">
                <th className="text-left font-medium px-3 py-2">Wrestler</th>
                <th className="text-right font-medium px-2 py-2">Age</th>
                <th className="text-right font-medium px-2 py-2" title="Wrestling — in-ring ability, moved by her win/loss record">WRS</th>
                <th className="text-right font-medium px-2 py-2" title="Achievements — what she has won in THIS save. Starts at 0">ACH</th>
                <th className="text-right font-medium px-2 py-2" title="Popularity — cagematch score, reach and promo skill">POP</th>
                <th className="text-right font-medium px-2 py-2" title="Looks — yours to set">LKS</th>
                <th className="text-right font-medium px-2 py-2" title="Personal — yours alone">PER</th>
                <th className="text-right font-medium px-2 py-2">OVR</th>
                <th className="text-right font-medium px-3 py-2">Asking</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {pool.map((r) => {
                const factor = onClock?.tier_factor ?? 1
                const base = kind === 'manager' ? r.manager_price : r.value
                const price = Math.max(40000, Math.round(base * factor / 10000) * 10000)
                const affordable = !clockBrand || clockBrand.available >= price
                const heldOut = !!clockBrand && r.holdout_brands.includes(clockBrand.brand_id)
                return (
                  <tr key={r.id} className="border-b border-edge/50 hover:bg-panel">
                    <td className="px-3 py-1.5">
                      <div className="font-medium flex items-center gap-1.5">
                        {r.name}
                        <span className="label text-[8px] px-1 py-[1px] rounded bg-edge text-slate-400">
                          {r.role === 'manager' ? 'MGR' : r.role === 'both' ? 'W+M' : 'W'}
                        </span>
                      </div>
                      <div className="text-[11px] text-slate-500">{r.promotions.join(' · ')}</div>
                    </td>
                    <td className="px-2 py-1.5 text-right tnum text-slate-400">{ageLabel(r.age, r.age_precision)}</td>
                    <StatCell v={r.wrestling} swing={r.record_swing} />
                    <StatCell v={r.achievements} title={r.achievement_reasons.join(" · ") || "Nothing won yet in this save"} />
                    <StatCell v={r.popularity} />
                    <StatCell v={r.looks} />
                    <StatCell v={r.personal} />
                    <td className="px-2 py-1.5 text-right tnum text-gold font-semibold">{r.overall}</td>
                    <td className={`px-3 py-1.5 text-right tnum ${affordable ? 'text-slate-300' : 'text-orange-400'}`}>
                      ~{money(price)}
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      <button disabled={!onClock || heldOut} onClick={() => setNegotiating(r)}
                        title={heldOut ? `holding out from ${clockBrand?.brand_id} this year` : ''}
                        className="text-xs px-2.5 py-1 rounded font-semibold text-black
                                   disabled:opacity-20 disabled:cursor-not-allowed"
                        style={{ background: clockBrand?.colour ?? '#888' }}>
                        {heldOut ? 'Holding out' : 'Negotiate'}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {pool.length === 0 && <p className="p-5 text-sm text-slate-500">Nobody left in the pool.</p>}
        </div>
      </div>

      {negotiating && onClock && clockBrand && (
        <NegotiationModal
          wrestler={negotiating}
          brandId={clockBrand.brand_id}
          brandColour={clockBrand.colour}
          brandAvailable={clockBrand.available}
          context="draft"
          kind={kind}
          tierFactor={onClock.tier_factor}
          years={onClock.years}
          onClose={() => setNegotiating(null)}
          onSigned={() => { setNegotiating(null); invalidate() }}
        />
      )}

      {/* ---------------- board ---------------- */}
      <aside className="w-[300px] shrink-0 border-l border-edge overflow-auto">
        <div className="px-4 py-3 border-b border-edge">
          <h3 className="text-xs uppercase tracking-wider text-slate-500">
            {kind} board · {board.draft.season_year}
          </h3>
          <p className="text-[11px] text-slate-600 mt-0.5">{made.length} of {board.picks.length} picks used</p>
        </div>
        {board.picks.map((p) => {
          const b = brands.find((x) => x.brand_id === p.brand_id)
          const isNext = onClock?.id === p.id
          return (
            <div key={p.id}
              className={`px-4 py-1.5 border-b border-edge/40 flex items-center gap-2 text-sm ${isNext ? 'bg-gold/10' : ''}`}>
              <span className="text-[11px] text-slate-600 tnum w-6">{p.pick_number}</span>
              <span className="text-[9px] px-1.5 py-0.5 rounded font-semibold shrink-0"
                style={{ background: `${b?.colour}33`, color: b?.colour }}>
                {p.brand_id === 'SMACKDOWN' ? 'SD' : 'RAW'}
              </span>
              {p.wrestler_name ? (
                <>
                  <span className="flex-1 truncate">{p.wrestler_name}</span>
                  <span className="text-[11px] text-slate-500 tnum">{money(p.annual_value!)}</span>
                </>
              ) : (
                <span className={`flex-1 text-xs ${isNext ? 'text-gold' : 'text-slate-600'}`}>
                  {isNext ? 'on the clock' : '—'}
                </span>
              )}
            </div>
          )
        })}
      </aside>
    </div>
  )
}

function madeCount(board: DraftBoard | undefined): number {
  return (board?.picks ?? []).filter((p) => p.wrestler_id !== null).length
}

/** Two-phase progress: Wrestler draft → Manager draft. */
function Stepper({ phase, wDone, mDone }: { phase: 'wrestler' | 'manager' | 'done'; wDone: boolean; mDone: boolean }) {
  const step = (label: string, active: boolean, done: boolean) => (
    <div className="flex items-center gap-2">
      <span className={`w-5 h-5 grid place-items-center rounded-full text-[10px] font-bold
        ${done ? 'bg-emerald-400 text-black' : active ? 'bg-gold text-black' : 'bg-edge text-slate-500'}`}>
        {done ? '✓' : active ? '●' : '○'}
      </span>
      <span className={`label text-[11px] ${active || done ? 'text-slate-200' : 'text-slate-500'}`}>{label}</span>
    </div>
  )
  return (
    <div className="flex items-center gap-3">
      {step('Wrestler draft', phase === 'wrestler', wDone)}
      <span className="w-8 h-px bg-edge" />
      {step('Manager draft', phase === 'manager', mDone)}
    </div>
  )
}
