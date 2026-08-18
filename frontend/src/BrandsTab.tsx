import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchBrands, fetchBudgets, fetchTitles, tradeWrestlers, advanceSeason,
  money, moneyFull, ageLabel, type RosterRow,
} from './api'
import { BeltEmblem, Logo } from './emblems'

export default function BrandsTab({ roster }: { roster: RosterRow[] }) {
  const qc = useQueryClient()
  const { data: brands = [] } = useQuery({ queryKey: ['brands'], queryFn: fetchBrands })
  const { data: budgets = [] } = useQuery({ queryKey: ['budgets'], queryFn: fetchBudgets })
  const { data: titles = [] } = useQuery({ queryKey: ['titles'], queryFn: fetchTitles })

  const [sideA, setSideA] = useState<number[]>([])
  const [sideB, setSideB] = useState<number[]>([])
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['roster'] })
    qc.invalidateQueries({ queryKey: ['brands'] })
    qc.invalidateQueries({ queryKey: ['budgets'] })
    qc.invalidateQueries({ queryKey: ['health'] })
  }

  const doTrade = useMutation({
    mutationFn: () => tradeWrestlers(sideA, sideB),
    onSuccess: (r) => {
      setErr(null); setMsg(`Traded ${r.moved} wrestlers.`)
      setSideA([]); setSideB([]); invalidate()
    },
    onError: (e: Error) => { setMsg(null); setErr(e.message) },
  })

  const nextSeason = useMutation({
    mutationFn: advanceSeason,
    onSuccess: (r) => {
      setErr(null)
      setMsg(`Now ${r.season_year}. ${r.contracts_expired} contract(s) expired, budgets grew, everyone aged a year.`)
      invalidate()
    },
    onError: (e: Error) => setErr(e.message),
  })

  const byBrand = useMemo(() => {
    const m: Record<string, RosterRow[]> = {}
    for (const r of roster) if (r.contract) (m[r.contract.brand_id] ??= []).push(r)
    for (const k of Object.keys(m)) m[k].sort((a, b) => b.overall - a.overall)
    return m
  }, [roster])

  const budgetSeries = useMemo(() => {
    const years = [...new Set(budgets.map((b) => b.season_year))].sort().slice(0, 12)
    return years.map((y) => ({
      year: y,
      budget: budgets.find((b) => b.season_year === y)?.budget ?? 0,
    }))
  }, [budgets])

  const maxBudget = Math.max(1, ...budgetSeries.map((b) => b.budget))

  function toggle(list: number[], set: (v: number[]) => void, id: number) {
    set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id])
  }

  if (!brands.length) {
    return <p className="p-6 text-sm text-slate-500">No active save. Start a new game from the header.</p>
  }

  return (
    <div className="p-6 space-y-6 overflow-auto">
      {msg && <p className="text-xs text-emerald-400 bg-emerald-400/10 border border-emerald-400/30 rounded px-3 py-2">{msg}</p>}
      {err && <p className="text-xs text-blood bg-blood/10 border border-blood/30 rounded px-3 py-2">{err}</p>}

      {/* ---- finances ---- */}
      <div className="grid grid-cols-2 gap-4">
        {brands.map((b) => {
          const pct = b.budget ? (b.committed / b.budget) * 100 : 0
          return (
            <div key={b.brand_id} className="bg-panel border border-edge rounded p-4">
              <div className="flex justify-between items-baseline mb-3">
                <h3 className="font-bold text-lg" style={{ color: b.colour }}>{b.name}</h3>
                <span className="text-xs text-slate-500">{b.roster_size} under contract</span>
              </div>
              <div className="h-2 rounded-full bg-edge overflow-hidden mb-2">
                <div
                  className="h-full rounded-full transition-all"
                  style={{ width: `${Math.min(100, pct)}%`, background: b.colour }}
                />
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">Committed <span className="tnum text-slate-200">{moneyFull(b.committed)}</span></span>
                <span className="text-slate-400">Free <span className="tnum text-emerald-400">{moneyFull(b.available)}</span></span>
              </div>
              <p className="text-[11px] text-slate-600 mt-1">
                {b.season_year} budget {moneyFull(b.budget)} · {pct.toFixed(0)}% spent
              </p>
            </div>
          )
        })}
      </div>

      {/* ---- budget growth ---- */}
      <div className="bg-panel border border-edge rounded p-4">
        <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-3">
          Budget growth · 6% a year, like an NBA cap
        </h3>
        <div className="flex items-end gap-1.5 h-28">
          {budgetSeries.map((b) => (
            <div key={b.year} className="flex-1 flex flex-col items-center justify-end h-full">
              <span className="text-[9px] text-slate-500 tnum mb-1">{money(b.budget)}</span>
              <div
                className="w-full rounded-t bg-gold/70"
                style={{ height: `${(b.budget / maxBudget) * 100}%` }}
              />
              <span className="text-[9px] text-slate-600 mt-1 tnum">{b.year}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ---- titles ---- */}
      <div className="bg-panel border border-edge rounded p-4">
        <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-2">Championships</h3>
        <div className="grid grid-cols-2 gap-3">
          {titles.map((t: any) => (
            <div key={t.id} className="text-sm flex items-center gap-2.5">
              <Logo keyName={t.short_name || t.tier} size={30} fallback={<BeltEmblem tier={t.tier} size={30} />} />
              <div className="min-w-0">
                <div className="text-slate-300 flex items-center gap-1.5 truncate">
                  {t.name}
                  {t.tier === 'manager' && <span className="label text-[8px] px-1 rounded bg-gold/15 text-gold">managers</span>}
                </div>
                <div className="text-gold font-semibold truncate">
                  {t.champions?.length
                    ? t.champions.map((c: any) => c.name).join(' & ')
                    : <span className="text-slate-600 font-normal">vacant</span>}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ---- rosters + trade ---- */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs uppercase tracking-wider text-slate-500">
            Rosters — tick wrestlers on both sides to build a trade
          </h3>
          <div className="flex gap-2">
            <button
              disabled={!sideA.length || !sideB.length || doTrade.isPending}
              onClick={() => doTrade.mutate()}
              className="text-xs px-3 py-1.5 rounded bg-gold text-black font-semibold
                         disabled:opacity-30 disabled:cursor-not-allowed hover:bg-gold/85"
            >
              Trade {sideA.length}↔{sideB.length}
            </button>
            <button
              onClick={() => nextSeason.mutate()}
              disabled={nextSeason.isPending}
              className="text-xs px-3 py-1.5 rounded border border-edge hover:border-gold/60 disabled:opacity-40"
            >
              Advance season →
            </button>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          {brands.map((b, i) => {
            const list = byBrand[b.brand_id] ?? []
            const sel = i === 0 ? sideA : sideB
            const setSel = i === 0 ? setSideA : setSideB
            return (
              <div key={b.brand_id} className="bg-panel border border-edge rounded overflow-hidden">
                <div className="px-3 py-2 text-xs font-semibold" style={{ background: `${b.colour}22`, color: b.colour }}>
                  {b.name}
                </div>
                {list.length === 0 && <p className="p-3 text-xs text-slate-600">Nobody signed yet.</p>}
                {list.map((r) => (
                  <label
                    key={r.id}
                    className="flex items-center gap-2 px-3 py-1.5 border-t border-edge/50 cursor-pointer hover:bg-canvas/50"
                  >
                    <input
                      type="checkbox"
                      checked={sel.includes(r.id)}
                      onChange={() => toggle(sel, setSel, r.id)}
                      className="accent-[var(--color-gold)]"
                    />
                    <span className="flex-1 text-sm truncate">{r.name}</span>
                    <span className="text-[11px] text-slate-500 tnum">
                      {ageLabel(r.age, r.age_precision)}y
                    </span>
                    <span className="text-xs text-gold tnum w-8 text-right">{r.overall}</span>
                    <span className="text-xs text-slate-400 tnum w-14 text-right">
                      {money(r.contract!.annual_value)}
                    </span>
                  </label>
                ))}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
