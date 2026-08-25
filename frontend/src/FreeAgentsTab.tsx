import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchBrands, money, ageLabel, ROLE_LABEL, type RosterRow } from './api'
import { StatCell } from './ui'
import NegotiationModal from './NegotiationModal'

/**
 * Free agency: anyone not under contract can be signed to a NEGOTIATED ONE-YEAR
 * deal with the brand of your choosing. The draft hands out the multi-year
 * money; this is the short, haggled business in between.
 */
export default function FreeAgentsTab({ roster }: { roster: RosterRow[] }) {
  const qc = useQueryClient()
  const { data: brands = [] } = useQuery({ queryKey: ['brands'], queryFn: fetchBrands })
  const [brandId, setBrandId] = useState('RAW')
  const [search, setSearch] = useState('')
  const [negotiating, setNegotiating] = useState<RosterRow | null>(null)

  const brand = brands.find((b) => b.brand_id === brandId)
  const freeAgents = useMemo(() => {
    const term = search.trim().toLowerCase()
    return roster
      .filter((r) => !r.removed && !r.contract)
      .filter((r) => !term || r.name.toLowerCase().includes(term)
        || r.ring_names.some((n) => n.toLowerCase().includes(term)))
      .sort((a, b) => b.overall - a.overall)
  }, [roster, search])

  return (
    <div className="flex-1 overflow-auto">
      <div className="px-6 py-4 border-b border-edge flex items-center gap-4 flex-wrap">
        <div>
          <h2 className="display text-[24px] leading-none">Free Agents</h2>
          <p className="text-[11px] text-slate-500 mt-1">One-year deals, negotiated. Pick the brand, then talk terms.</p>
        </div>
        <div className="flex-1" />
        <div className="flex gap-2">
          {brands.map((b) => (
            <button key={b.brand_id} onClick={() => setBrandId(b.brand_id)}
              className="text-xs px-3 py-1.5 rounded font-semibold transition-all"
              style={brandId === b.brand_id
                ? { background: b.colour, color: '#000', boxShadow: `0 0 16px ${b.colour}55` }
                : { color: b.colour, background: `${b.colour}18` }}>
              Sign to {b.name}
            </button>
          ))}
        </div>
        <input value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="Search…"
          className="bg-panel border border-edge rounded px-3 py-1.5 text-sm w-48
                     placeholder:text-slate-600 focus:outline-none focus:border-gold/60" />
      </div>

      {brand && (
        <div className="px-6 py-2 text-xs text-slate-500 border-b border-edge">
          Signing to <span style={{ color: brand.colour }} className="font-semibold">{brand.name}</span> ·
          {' '}{money(brand.available)} of the cap free · {freeAgents.length} free agents
        </div>
      )}

      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-canvas border-b border-edge">
          <tr className="text-[10px] uppercase tracking-wider text-slate-500">
            <th className="text-left font-medium px-3 py-2">Wrestler</th>
            <th className="text-right font-medium px-2 py-2">Age</th>
            <th className="text-right font-medium px-2 py-2" title="Wrestling — in-ring ability, moved by her win/loss record">WRS</th>
            <th className="text-right font-medium px-2 py-2" title="Achievements — what she has won in THIS save. Starts at 0">ACH</th>
            <th className="text-right font-medium px-2 py-2" title="Popularity — cagematch score, reach and promo skill">POP</th>
            <th className="text-right font-medium px-2 py-2" title="Looks — yours to set">LKS</th>
            <th className="text-right font-medium px-2 py-2" title="Personal — yours alone">PER</th>
            <th className="text-right font-medium px-2 py-2">OVR</th>
            <th className="text-right font-medium px-3 py-2">~Asking</th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {freeAgents.map((r) => (
            <tr key={r.id} className="border-b border-edge/50 hover:bg-panel">
              <td className="px-3 py-1.5">
                <div className="font-medium">{r.name}</div>
                <div className="text-[11px] text-slate-500">
                  {ROLE_LABEL[r.role]} · {r.promotions.join(' · ')}
                </div>
              </td>
              <td className="px-2 py-1.5 text-right tnum text-slate-400">{ageLabel(r.age, r.age_precision)}</td>
              <StatCell v={r.wrestling} swing={r.record_swing} />
              <StatCell v={r.achievements} title={r.achievement_reasons.join(" · ") || "Nothing won yet in this save"} />
              <StatCell v={r.popularity} />
              <StatCell v={r.looks} />
              <StatCell v={r.personal} />
              <td className="px-2 py-1.5 text-right tnum text-gold font-semibold">{r.overall}</td>
              <td className="px-3 py-1.5 text-right tnum text-slate-400">~{money(r.value)}</td>
              <td className="px-3 py-1.5 text-right">
                <button onClick={() => setNegotiating(r)}
                  className="text-xs px-2.5 py-1 rounded font-semibold text-black"
                  style={{ background: brand?.colour ?? '#888' }}>
                  Negotiate
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {freeAgents.length === 0 && <p className="p-6 text-sm text-slate-500">No free agents match.</p>}

      {negotiating && brand && (
        <NegotiationModal
          wrestler={negotiating}
          brandId={brand.brand_id}
          brandColour={brand.colour}
          brandAvailable={brand.available}
          context="free_agent"
          kind="wrestler"
          tierFactor={1}
          years={1}
          onClose={() => setNegotiating(null)}
          onSigned={() => { setNegotiating(null); qc.invalidateQueries() }}
        />
      )}
    </div>
  )
}
