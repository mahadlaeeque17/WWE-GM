import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchTrades, proposeTrade, resolveTrade, fetchBrands, fetchPicks, fetchBrandCash,
  money, moneyFull, type RosterRow, type TradeAsset,
} from './api'
import { Avatar } from './ui'

type Draft = { side: string; kind: 'wrestler' | 'pick' | 'cash'; [k: string]: any }

/**
 * Trades are PROPOSED, then you approve or reject them. Nothing moves until you
 * accept, and an accepted trade still has to leave both brands under the cap.
 */
export default function TradesTab({ roster }: { roster: RosterRow[] }) {
  const qc = useQueryClient()
  const { data: brands = [] } = useQuery({ queryKey: ['brands'], queryFn: fetchBrands })
  const { data: pending = [] } = useQuery({ queryKey: ['trades', 'pending'], queryFn: () => fetchTrades('pending') })
  const { data: history = [] } = useQuery({ queryKey: ['trades', 'all'], queryFn: () => fetchTrades() })
  const { data: picks = [] } = useQuery({ queryKey: ['picks'], queryFn: fetchPicks })
  const { data: cash = [] } = useQuery({ queryKey: ['cash'], queryFn: fetchBrandCash })

  const [assets, setAssets] = useState<Draft[]>([])
  const [note, setNote] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)

  const A = brands[0]?.brand_id ?? 'RAW'
  const B = brands[1]?.brand_id ?? 'SMACKDOWN'
  const colourOf = (b: string) => brands.find((x) => x.brand_id === b)?.colour ?? '#888'

  const invalidate = () => {
    for (const k of [['trades', 'pending'], ['trades', 'all'], ['roster'], ['brands'], ['picks'], ['cash']]) {
      qc.invalidateQueries({ queryKey: k })
    }
  }

  const propose = useMutation({
    mutationFn: () => proposeTrade(A, B, assets, note || undefined),
    onSuccess: () => { setErr(null); setMsg('Offer created — approve or reject it below.'); setAssets([]); setNote(''); invalidate() },
    onError: (e: Error) => { setMsg(null); setErr(e.message) },
  })

  const resolve = useMutation({
    mutationFn: ({ id, accept }: { id: number; accept: boolean }) => resolveTrade(id, accept),
    onSuccess: (r) => { setErr(null); setMsg(r.status === 'accepted' ? `Trade accepted — ${r.assets_moved} assets moved.` : 'Offer rejected.'); invalidate() },
    onError: (e: Error) => { setMsg(null); setErr(e.message) },
  })

  const signed = useMemo(
    () => roster.filter((r) => r.contract && !r.removed),
    [roster],
  )

  const add = (a: Draft) => setAssets((s) => [...s, a])
  const removeAt = (i: number) => setAssets((s) => s.filter((_, x) => x !== i))

  function describe(a: TradeAsset | Draft): string {
    if (a.kind === 'wrestler') {
      const w = roster.find((r) => r.id === a.wrestler_id)
      return w?.name ?? `wrestler ${a.wrestler_id}`
    }
    if (a.kind === 'pick') return `${a.pick_season} round ${a.pick_round} pick`
    return moneyFull(a.cash ?? 0)
  }

  if (!brands.length) {
    return <p className="p-6 text-sm text-slate-500">No active save. Start a new game from the header.</p>
  }

  return (
    <div className="flex-1 overflow-auto p-6 space-y-6">
      {msg && <p className="text-xs text-emerald-400 bg-emerald-400/10 border border-emerald-400/30 rounded px-3 py-2">{msg}</p>}
      {err && <p className="text-xs text-raw bg-raw/10 border border-raw/30 rounded px-3 py-2">{err}</p>}

      {/* ---------------- pending offers ---------------- */}
      <section>
        <h3 className="label text-[11px] text-slate-500 mb-2">
          Pending offers {pending.length > 0 && <span className="text-gold">({pending.length})</span>}
        </h3>
        {pending.length === 0 && (
          <p className="text-sm text-slate-600">Nothing awaiting your decision.</p>
        )}
        <div className="space-y-3">
          {pending.map((o) => {
            const bySide: Record<string, TradeAsset[]> = {}
            for (const a of o.assets) (bySide[a.side] ??= []).push(a)
            return (
              <div key={o.id} className="card p-4">
                <div className="flex items-center justify-between mb-3">
                  <span className="label text-[10px] text-slate-500">
                    Offer #{o.id} · {o.created_on}
                    {o.note && <span className="text-slate-400"> · “{o.note}”</span>}
                  </span>
                  <div className="flex gap-2">
                    <button
                      onClick={() => resolve.mutate({ id: o.id, accept: true })}
                      disabled={resolve.isPending}
                      className="label text-[11px] px-3 py-1.5 rounded bg-emerald-500 text-black disabled:opacity-40"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => resolve.mutate({ id: o.id, accept: false })}
                      disabled={resolve.isPending}
                      className="label text-[11px] px-3 py-1.5 rounded border border-raw/50 text-raw hover:bg-raw/10 disabled:opacity-40"
                    >
                      Reject
                    </button>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  {[o.from_brand, o.to_brand].map((side) => (
                    <div key={side}>
                      <div className="label text-[10px] mb-1.5" style={{ color: colourOf(side) }}>
                        {side} gives up
                      </div>
                      {(bySide[side] ?? []).map((a) => (
                        <div key={a.id} className="flex items-center gap-2 text-sm py-1">
                          {a.kind === 'wrestler' && a.wrestler_id && (
                            <Avatar row={roster.find((r) => r.id === a.wrestler_id)!} width={22} />
                          )}
                          <span className="flex-1">{describe(a)}</span>
                          {a.kind === 'wrestler' && a.overall != null && (
                            <span className="stat text-gold text-xs">{a.overall}</span>
                          )}
                          {a.kind === 'wrestler' && a.value != null && (
                            <span className="stat text-slate-500 text-xs">{money(a.value)}</span>
                          )}
                        </div>
                      ))}
                      {!(bySide[side] ?? []).length && <p className="text-xs text-slate-600">nothing</p>}
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* ---------------- build an offer ---------------- */}
      <section className="card p-4">
        <h3 className="label text-[11px] text-slate-500 mb-3">Build an offer</h3>

        <div className="grid grid-cols-2 gap-5">
          {[A, B].map((side) => (
            <div key={side}>
              <div className="label text-[11px] mb-2" style={{ color: colourOf(side) }}>
                {side} gives up
              </div>

              <select
                value=""
                onChange={(e) => e.target.value && add({ side, kind: 'wrestler', wrestler_id: Number(e.target.value) })}
                className="w-full bg-canvas border border-edge rounded px-2 py-1.5 text-sm mb-2"
              >
                <option value="">+ add a wrestler…</option>
                {signed.filter((r) => r.contract!.brand_id === side).map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name} · {r.overall} OVR · {money(r.contract!.annual_value)}
                  </option>
                ))}
              </select>

              <select
                value=""
                onChange={(e) => {
                  if (!e.target.value) return
                  const [season, round] = e.target.value.split('-').map(Number)
                  add({ side, kind: 'pick', pick_season: season, pick_round: round })
                }}
                className="w-full bg-canvas border border-edge rounded px-2 py-1.5 text-sm mb-2"
              >
                <option value="">+ add a draft pick…</option>
                {picks.filter((p) => p.owner_brand === side && p.draft_kind === 'wrestler')
                  .map((p) => (
                    <option key={p.id} value={`${p.season_year}-${p.round_no}`}>
                      {p.season_year} round {p.round_no}
                      {p.original_brand !== side ? ` (via ${p.original_brand})` : ''}
                    </option>
                  ))}
              </select>

              <div className="flex gap-2">
                <input
                  type="number" min={0} step={50000} placeholder="cash"
                  className="flex-1 bg-canvas border border-edge rounded px-2 py-1.5 text-sm tnum
                             placeholder:text-slate-600"
                  onKeyDown={(e) => {
                    const v = Number((e.target as HTMLInputElement).value)
                    if (e.key === 'Enter' && v > 0) {
                      add({ side, kind: 'cash', cash: v })
                      ;(e.target as HTMLInputElement).value = ''
                    }
                  }}
                />
                <span className="text-[10px] text-slate-600 self-center">enter ↵</span>
              </div>
              <p className="text-[10px] text-slate-600 mt-1">
                balance {money(cash.find((c) => c.brand_id === side)?.balance ?? 0)}
              </p>
            </div>
          ))}
        </div>

        {assets.length > 0 && (
          <div className="mt-4 pt-3 border-t border-edge-soft">
            <div className="flex flex-wrap gap-1.5 mb-3">
              {assets.map((a, i) => (
                <span
                  key={i}
                  className="label text-[10px] px-2 py-1 rounded flex items-center gap-1.5"
                  style={{ background: `${colourOf(a.side)}22`, color: colourOf(a.side) }}
                >
                  {a.side}: {describe(a)}
                  <button onClick={() => removeAt(i)} className="hover:text-white">×</button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="note (optional)"
                className="flex-1 bg-canvas border border-edge rounded px-2 py-1.5 text-sm placeholder:text-slate-600"
              />
              <button
                onClick={() => propose.mutate()}
                disabled={propose.isPending}
                className="label text-[11px] px-4 py-1.5 rounded bg-gold text-black disabled:opacity-40"
              >
                Propose
              </button>
            </div>
          </div>
        )}
      </section>

      {/* ---------------- history ---------------- */}
      {history.filter((o) => o.status !== 'pending').length > 0 && (
        <section>
          <h3 className="label text-[11px] text-slate-500 mb-2">History</h3>
          <div className="space-y-1">
            {history.filter((o) => o.status !== 'pending').map((o) => (
              <div key={o.id} className="flex items-center gap-3 text-xs py-1.5 border-b border-edge-soft">
                <span className={`label text-[9px] px-1.5 py-0.5 rounded ${
                  o.status === 'accepted' ? 'bg-emerald-400/15 text-emerald-300' : 'bg-raw/15 text-raw'
                }`}>
                  {o.status}
                </span>
                <span className="text-slate-400">
                  {o.assets.map((a) => `${a.side}: ${describe(a)}`).join('  ·  ')}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
