import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchBrands, fetchTitles, fetchShows, fetchBudgets, runShow,
  extendContract, releaseContract, aiStoryline,
  money, moneyFull, ageLabel, type RosterRow,
} from './api'
import { Avatar, StatCell, OverallBadge, Pill } from './ui'
import { BrandCrest, Logo } from './emblems'

/**
 * One brand, everything about it, in that brand's colour: finances, roster,
 * championship, shows. Raw and SmackDown each get their own tab so the two
 * never blur together while booking.
 */
export default function BrandTab({ brandId, roster }: { brandId: string; roster: RosterRow[] }) {
  const qc = useQueryClient()
  const { data: brands = [] } = useQuery({ queryKey: ['brands'], queryFn: fetchBrands })
  const { data: titles = [] } = useQuery({ queryKey: ['titles'], queryFn: fetchTitles })
  const { data: shows = [] } = useQuery({ queryKey: ['shows'], queryFn: fetchShows })
  const { data: budgets = [] } = useQuery({ queryKey: ['budgets'], queryFn: fetchBudgets })

  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [extYears, setExtYears] = useState<Record<number, number>>({})

  const brand = brands.find((b) => b.brand_id === brandId)
  const colour = brand?.colour ?? '#888'

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['roster'] })
    qc.invalidateQueries({ queryKey: ['brands'] })
    qc.invalidateQueries({ queryKey: ['shows'] })
    qc.invalidateQueries({ queryKey: ['titles'] })
  }

  const doShow = useMutation({
    mutationFn: () => runShow(brandId, `${brand?.name} #${myShows.length + 1}`, 4),
    onSuccess: (r) => { setErr(null); setMsg(`${r.name} rated ${r.rating}.`); invalidate() },
    onError: (e: Error) => { setMsg(null); setErr(e.message) },
  })

  // The QUICK re-sign: no salary is sent, which the API reads as "pay whatever
  // she asks" — so this always succeeds and always costs her full asking price.
  // Haggling lives on her own panel (ExtensionPanel), where perks, a signing
  // bonus and a lower number can be put to her and refused.
  const doExtend = useMutation({
    mutationFn: (id: number) => extendContract(id, extYears[id] ?? 2),
    onSuccess: (r) => {
      setErr(null)
      setMsg(`Re-signed through ${r.end_year} at her asking price, ${moneyFull(r.annual_value)}/yr. `
             + `Open her panel to negotiate instead.`)
      invalidate()
    },
    onError: (e: Error) => { setMsg(null); setErr(e.message) },
  })

  const doRelease = useMutation({
    mutationFn: (id: number) => releaseContract(id),
    onSuccess: () => { setErr(null); setMsg('Released — she returns to the draft pool.'); invalidate() },
    onError: (e: Error) => { setMsg(null); setErr(e.message) },
  })

  const [story, setStory] = useState<string | null>(null)
  const doStoryline = useMutation({
    mutationFn: () => aiStoryline(brandId),
    onSuccess: (r) => { setErr(null); setStory(r.storyline) },
    onError: (e: Error) => { setStory(null); setErr(e.message) },
  })

  const myRoster = useMemo(
    () => roster.filter((r) => r.contract?.brand_id === brandId)
      .sort((a, b) => b.overall - a.overall),
    [roster, brandId],
  )
  const myShows = useMemo(() => shows.filter((s) => s.brand_id === brandId), [shows, brandId])
  const myTitle = titles.find((t: any) => t.brand_id === brandId)
  const myBudgets = useMemo(
    () => budgets.filter((b) => b.brand_id === brandId).slice(0, 10),
    [budgets, brandId],
  )
  const maxBudget = Math.max(1, ...myBudgets.map((b) => b.budget))

  if (!brand) {
    return <p className="p-6 text-sm text-slate-500">No active save. Start a new game from the header.</p>
  }

  const pct = brand.budget ? (brand.committed / brand.budget) * 100 : 0
  const avgShow = myShows.length
    ? myShows.reduce((s, x) => s + (x.rating ?? 0), 0) / myShows.length
    : null

  return (
    <div className="flex-1 overflow-auto">
      {/* ---- brand header ---- */}
      <div
        className="px-6 py-6 border-b-2 relative overflow-hidden"
        style={{
          borderColor: colour,
          background: `linear-gradient(100deg, ${colour}33 0%, ${colour}0d 42%, transparent 72%)`,
        }}
      >
        {/* Angled sheen — cheap way to make a flat header feel like a title card. */}
        <div
          className="absolute inset-y-0 -right-24 w-1/2 opacity-[0.07] pointer-events-none"
          style={{ background: colour, transform: 'skewX(-18deg)' }}
        />
        <div className="flex items-center justify-between flex-wrap gap-4 relative">
          <div className="flex items-center gap-4">
            <Logo keyName={brandId.toLowerCase()} size={64} fallback={<BrandCrest brand={brandId} size={56} />} />
            <div>
              <h1 className="display text-[52px] leading-[0.85]" style={{ color: colour }}>
                {brand.name.toUpperCase()}
              </h1>
              <p className="label text-[10px] text-slate-400 mt-2">
                {brand.roster_size} under contract · {myShows.length} shows
                {avgShow !== null && ` · ${avgShow.toFixed(1)} avg rating`}
              </p>
            </div>
          </div>
          <button
            onClick={() => doShow.mutate()}
            disabled={doShow.isPending || myRoster.length < 2}
            title={myRoster.length < 2 ? 'needs at least 2 healthy wrestlers' : ''}
            className="label text-[13px] px-6 py-3 rounded text-black disabled:opacity-25 transition-transform
                       hover:scale-[1.03] active:scale-95"
            style={{ background: colour, boxShadow: `0 0 28px ${colour}66` }}
          >
            {doShow.isPending ? 'Running…' : '▶ Run a show'}
          </button>
        </div>
      </div>

      {msg && <p className="mx-6 mt-4 text-xs text-emerald-400 bg-emerald-400/10 border border-emerald-400/30 rounded px-3 py-2">{msg}</p>}
      {err && <p className="mx-6 mt-4 text-xs text-blood bg-blood/10 border border-blood/30 rounded px-3 py-2">{err}</p>}

      <div className="p-6 grid grid-cols-3 gap-4">
        {/* ---- money ---- */}
        <div className="bg-panel border border-edge rounded p-4 col-span-2">
          <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-3">
            {brand.season_year} budget
          </h3>
          <div className="h-2.5 rounded-full bg-edge overflow-hidden mb-2">
            <div className="h-full rounded-full transition-all"
                 style={{ width: `${Math.min(100, pct)}%`, background: colour }} />
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-slate-400">Committed <span className="tnum text-slate-100">{moneyFull(brand.committed)}</span></span>
            <span className="text-slate-400">Free <span className="tnum text-emerald-400">{moneyFull(brand.available)}</span></span>
            <span className="text-slate-400">Cap <span className="tnum text-slate-100">{moneyFull(brand.budget)}</span></span>
          </div>

          <div className="flex items-end gap-1.5 h-20 mt-5">
            {myBudgets.map((b) => (
              <div key={b.season_year} className="flex-1 flex flex-col items-center justify-end h-full">
                <div className="w-full rounded-t opacity-70"
                     style={{ height: `${(b.budget / maxBudget) * 100}%`, background: colour }} />
                <span className="text-[9px] text-slate-600 mt-1 tnum">{b.season_year}</span>
              </div>
            ))}
          </div>
          <p className="text-[10px] text-slate-600 mt-1">Grows 6% a year, like an NBA cap.</p>
        </div>

        {/* ---- title ---- */}
        <div className="bg-panel border border-edge rounded p-4">
          <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-2">Championship</h3>
          {myTitle ? (
            <>
              <div className="text-sm text-slate-300">{myTitle.name}</div>
              <div className="text-xl font-bold mt-1" style={{ color: colour }}>
                {myTitle.champions?.[0]?.name
                  ?? <span className="text-slate-600 text-base font-normal">vacant</span>}
              </div>
              {myTitle.champions?.[0]?.won_on && (
                <div className="text-[11px] text-slate-500 mt-1">since {myTitle.champions[0].won_on}</div>
              )}
              {/* Prestige — grows in classics, floored by tier. */}
              <div className="mt-3">
                <div className="flex justify-between text-[10px] text-slate-500 mb-1">
                  <span className="label">Prestige</span><span className="tnum">{myTitle.prestige}</span>
                </div>
                <div className="h-1.5 rounded-full bg-edge overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${myTitle.prestige}%`, background: colour }} />
                </div>
                <div className="text-[10px] text-slate-600 mt-1">{myTitle.reign_count} reigns all-time</div>
              </div>
            </>
          ) : <p className="text-sm text-slate-600">none</p>}
        </div>
      </div>

      {/* ---- creative (Groq) ---- */}
      <div className="px-6 pb-2">
        <button onClick={() => doStoryline.mutate()} disabled={doStoryline.isPending}
          className="text-xs px-3 py-1.5 rounded border border-gold/40 text-gold hover:bg-gold/10 disabled:opacity-40">
          {doStoryline.isPending ? 'Booking the angle…' : '🤖 Pitch a storyline (AI)'}
        </button>
        {story && (
          <p className="text-sm text-slate-300 bg-panel border border-edge rounded p-3 mt-2 leading-relaxed whitespace-pre-line max-w-3xl">
            {story}
          </p>
        )}
      </div>

      {/* ---- roster ---- */}
      <div className="px-6 pb-6">
        <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-2">Roster</h3>
        <div className="bg-panel border border-edge rounded overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-slate-500"
                  style={{ background: `${colour}18` }}>
                <th className="text-left font-medium px-3 py-2">Wrestler</th>
                <th className="text-right font-medium px-2 py-2">Age</th>
                <th className="text-right font-medium px-2 py-2" title="Wrestling — in-ring ability, moved by her win/loss record">WRS</th>
                <th className="text-right font-medium px-2 py-2" title="Achievements — what she has won in THIS save. Starts at 0">ACH</th>
                <th className="text-right font-medium px-2 py-2" title="Popularity — cagematch score, reach and promo skill">POP</th>
                <th className="text-right font-medium px-2 py-2" title="Looks — yours to set">LKS</th>
                <th className="text-right font-medium px-2 py-2" title="Personal — yours alone">PER</th>
                <th className="text-right font-medium px-2 py-2">OVR</th>
                <th className="text-right font-medium px-3 py-2">Deal</th>
                <th className="text-right font-medium px-3 py-2">Contract</th>
              </tr>
            </thead>
            <tbody>
              {myRoster.map((r) => {
                const c = r.contract!
                const canExtend = c.years > 1 && c.origin !== 'extension'
                return (
                  <tr key={r.id} className="border-t border-edge-soft row-hover">
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-3">
                        <Avatar row={r} width={32} />
                        <div className="min-w-0">
                          <div className="font-semibold text-[15px] flex items-center gap-1.5">
                            {r.name}
                            {r.sim.injured_until && <Pill tone="red">inj</Pill>}
                          </div>
                          <div className="text-[11px] text-slate-500">
                            {r.sim.matches} matches · mom {r.sim.momentum}
                            {' · '}
                            <span className={r.sim.morale >= 66 ? 'text-emerald-400'
                              : r.sim.morale <= 34 ? 'text-blood' : 'text-slate-500'}>
                              morale {r.sim.morale}
                            </span>
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-2 py-2 text-right stat text-[15px] text-slate-400">{ageLabel(r.age, r.age_precision)}</td>
                    <StatCell v={r.wrestling} swing={r.record_swing} />
                    <StatCell v={r.achievements} title={r.achievement_reasons.join(" · ") || "Nothing won yet in this save"} />
                    <StatCell v={r.popularity} />
                    <StatCell v={r.looks} />
                    <StatCell v={r.personal} />
                    <td className="px-2 py-2 text-right"><OverallBadge v={r.overall} colour={colour} /></td>
                    <td className="px-3 py-2 text-right">
                      <div className="tnum text-slate-200">{money(c.annual_value)}</div>
                      <div className="text-[10px] text-slate-500">
                        {c.start_year}–{c.end_year}
                        {c.origin === 'extension' && <span className="text-gold"> ext</span>}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      {canExtend ? (
                        <>
                          <select
                            value={extYears[r.id] ?? 2}
                            onChange={(e) => setExtYears((s) => ({ ...s, [r.id]: Number(e.target.value) }))}
                            className="bg-canvas border border-edge rounded px-1 py-0.5 text-xs mr-1"
                          >
                            {[1, 2, 3, 4, 5].map((y) => <option key={y} value={y}>{y}y</option>)}
                          </select>
                          <button
                            onClick={() => doExtend.mutate(r.id)}
                            disabled={doExtend.isPending}
                            title="Re-sign at her full asking price. Open her panel to negotiate."
                            className="text-xs px-2 py-1 rounded border border-edge hover:border-gold/60 disabled:opacity-30"
                          >
                            Re-sign at ask
                          </button>
                        </>
                      ) : (
                        <span className="text-[10px] text-slate-600 mr-1">
                          {c.origin === 'extension' ? 'already extended' : '1-yr, no extension'}
                        </span>
                      )}
                      <button
                        onClick={() => doRelease.mutate(r.id)}
                        className="text-xs px-2 py-1 rounded border border-blood/40 text-blood hover:bg-blood/10 ml-1"
                      >
                        Release
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {myRoster.length === 0 && (
            <p className="p-4 text-sm text-slate-500">
              Nobody signed. Contracts are only handed out in the <strong>Draft</strong> tab.
            </p>
          )}
        </div>
      </div>

      {/* ---- shows ---- */}
      {myShows.length > 0 && (
        <div className="px-6 pb-8">
          <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-2">Shows</h3>
          <div className="grid grid-cols-4 gap-2">
            {myShows.map((s) => (
              <div key={s.id} className="bg-panel border border-edge rounded p-3">
                <div className="flex justify-between items-baseline">
                  <span className="text-sm font-medium truncate">{s.name}</span>
                  <span className="text-lg font-bold tnum" style={{ color: colour }}>
                    {s.rating?.toFixed(1)}
                  </span>
                </div>
                <div className="text-[10px] text-slate-500">
                  {s.held_on} · {s.attendance?.toLocaleString()} in
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

