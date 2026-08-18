import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchPerks, negotiateQuote, negotiateOffer, negotiateReset,
  makePick, signFreeAgent, moneyFull, type RosterRow, type NegotiationResult,
} from './api'

/**
 * A contract negotiation. The same flow drives a draft pick (multi-year, tier
 * premium) and a free-agent signing (one year). You table a salary + perks; she
 * accepts, counters, or is insulted. Only an accepted offer can be signed.
 */
export default function NegotiationModal({
  wrestler, brandId, brandColour, brandAvailable, context, kind, tierFactor, years, onClose, onSigned,
}: {
  wrestler: RosterRow; brandId: string; brandColour: string; brandAvailable: number
  context: 'draft' | 'free_agent'; kind: 'wrestler' | 'manager'
  tierFactor: number; years: number
  onClose: () => void; onSigned: () => void
}) {
  const qc = useQueryClient()
  const { data: perks = [] } = useQuery({ queryKey: ['perks'], queryFn: fetchPerks })
  const { data: quote } = useQuery({
    queryKey: ['quote', wrestler.id, kind, tierFactor],
    queryFn: () => negotiateQuote(wrestler.id, kind, tierFactor),
  })

  const [salary, setSalary] = useState<number | null>(null)
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [bonus, setBonus] = useState(0)
  const [result, setResult] = useState<NegotiationResult | null>(null)

  // Default the salary field to her opening ask once the quote arrives.
  const salaryVal = salary ?? quote?.asking ?? wrestler.value

  const offer = useMutation({
    mutationFn: () => negotiateOffer({
      wrestler_id: wrestler.id, brand_id: brandId, salary: salaryVal,
      perks: [...chosen], signing_bonus: bonus, kind, context, tier_factor: tierFactor,
    }),
    onSuccess: (r) => setResult(r),
  })

  const sign = useMutation({
    mutationFn: () => context === 'draft'
      ? makePick(wrestler.id, salaryVal, kind, [...chosen], bonus)
      : signFreeAgent(wrestler.id, brandId, salaryVal, [...chosen], bonus),
    onSuccess: () => { onSigned(); qc.invalidateQueries() },
    onError: (e: Error) => setResult((r) => r ? { ...r, message: e.message, verdict: 'counter' } : r),
  })

  const togglePerk = (k: string) =>
    setChosen((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n })

  const canSign = result?.verdict === 'accept'
  const walked = result?.verdict === 'walked'
  const overCap = salaryVal > brandAvailable
  const moodColour = result?.verdict === 'accept' ? 'text-emerald-400'
    : result?.verdict === 'offended' ? 'text-blood'
    : result?.verdict === 'walked' ? 'text-blood' : 'text-gold'

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}>
      <div className="w-[440px] max-w-full bg-panel border border-edge rounded-lg overflow-hidden"
        onClick={(e) => e.stopPropagation()} style={{ boxShadow: `0 0 40px ${brandColour}44` }}>
        <div className="px-5 py-3 border-b border-edge flex items-center justify-between"
          style={{ background: `${brandColour}18` }}>
          <div>
            <div className="label text-[9px] text-slate-500">
              {context === 'draft' ? `Negotiating a ${years}-year deal` : 'Negotiating a 1-year deal'} · {brandId}
            </div>
            <h3 className="display text-[22px] leading-none">{wrestler.name}</h3>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-white text-xl leading-none">×</button>
        </div>

        <div className="p-5 space-y-4">
          <div className="flex justify-between text-xs">
            <span className="text-slate-400">Overall <span className="text-gold font-semibold">{wrestler.overall}</span></span>
            {quote && (
              <span className="text-slate-400">
                Expecting ~<span className="text-slate-100">{moneyFull(quote.asking)}</span>
                <span className="ml-1.5 text-slate-600">({quote.note})</span>
              </span>
            )}
          </div>
          {quote && (
            <>
              <div className="flex justify-between text-[11px] -mt-1">
                <span className="text-gold font-semibold label text-[10px]">{quote.personality_label}</span>
                <span className={quote.morale >= 66 ? 'text-emerald-400' : quote.morale <= 34 ? 'text-blood' : 'text-slate-500'}>
                  morale {quote.morale}{quote.morale <= 34 ? ' · fed up, wants more' : quote.morale >= 66 ? ' · happy, flexible' : ''}
                </span>
              </div>
              <p className="text-[11px] text-slate-500 leading-snug -mt-2 border-l-2 border-gold/40 pl-2">
                {quote.personality_effect}
              </p>
            </>
          )}

          {/* salary */}
          <div>
            <label className="label text-[10px] text-slate-500">Annual salary offer</label>
            <input type="number" step={10000} min={0} value={salaryVal}
              onChange={(e) => { setSalary(Number(e.target.value)); setResult(null) }}
              className="mt-1 w-full bg-canvas border border-edge rounded px-3 py-2 text-lg tnum
                         focus:outline-none focus:border-gold/60" />
            <div className="flex justify-between text-[10px] mt-1">
              <span className={overCap ? 'text-blood' : 'text-slate-600'}>
                {brandId} has {moneyFull(brandAvailable)} free
              </span>
              <span className="text-slate-600">{moneyFull(salaryVal)}/yr</span>
            </div>
          </div>

          {/* perks */}
          <div>
            <label className="label text-[10px] text-slate-500">Perks — promises she'll hold you to</label>
            <div className="grid grid-cols-2 gap-1.5 mt-1.5">
              {perks.map((p) => (
                <button key={p.key} onClick={() => { togglePerk(p.key); setResult(null) }}
                  title={p.desc}
                  className={`px-2 py-1.5 rounded border text-left transition-colors ${
                    chosen.has(p.key) ? 'border-gold/60 bg-gold/10' : 'border-edge hover:border-slate-500'}`}>
                  <div className={`text-[11px] font-semibold ${chosen.has(p.key) ? 'text-gold' : 'text-slate-300'}`}>
                    {chosen.has(p.key) ? '✓ ' : ''}{p.label}
                  </div>
                  <div className="text-[9px] text-slate-500 leading-tight mt-0.5">{p.desc}</div>
                </button>
              ))}
            </div>
            <p className="text-[10px] text-slate-600 mt-1.5 leading-snug">
              Perks lower her number now, but they're tracked all season — fail to deliver and her
              morale takes a hit at year's end.
            </p>
          </div>

          {/* signing bonus */}
          <div className="flex items-center gap-2">
            <label className="label text-[10px] text-slate-500 flex-1">One-time signing bonus</label>
            <input type="number" step={10000} min={0} value={bonus}
              onChange={(e) => { setBonus(Number(e.target.value)); setResult(null) }}
              className="w-28 bg-canvas border border-edge rounded px-2 py-1 text-right tnum text-sm" />
          </div>

          {/* reaction */}
          {result && (
            <div className={`text-sm rounded p-3 border ${
              canSign ? 'border-emerald-400/30 bg-emerald-400/5'
              : walked || result.verdict === 'offended' ? 'border-blood/30 bg-blood/5'
              : 'border-gold/30 bg-gold/5'}`}>
              <p className={`italic ${moodColour}`}>“{result.message}”</p>
              {result.verdict === 'counter' && result.counter && (
                <button onClick={() => { setSalary(result.counter!); setResult(null) }}
                  className="mt-2 text-[11px] px-2 py-1 rounded border border-gold/50 text-gold hover:bg-gold/10">
                  Meet her counter of {moneyFull(result.counter)}
                </button>
              )}
              {!walked && (
                <p className="text-[10px] text-slate-500 mt-1.5">patience: {'●'.repeat(result.patience)}{'○'.repeat(Math.max(0, 3 - result.patience))}</p>
              )}
            </div>
          )}

          {/* actions */}
          <div className="flex gap-2 pt-1">
            <button onClick={() => offer.mutate()} disabled={offer.isPending || walked || overCap}
              className="flex-1 text-sm py-2 rounded border border-edge hover:border-gold/60 disabled:opacity-40">
              {offer.isPending ? 'Talking…' : 'Make offer'}
            </button>
            <button onClick={() => sign.mutate()} disabled={!canSign || sign.isPending || overCap}
              className="flex-1 text-sm py-2 rounded font-semibold text-black disabled:opacity-30"
              style={{ background: canSign && !overCap ? brandColour : '#444' }}>
              {sign.isPending ? 'Signing…' : `Sign${context === 'draft' ? ` (${years}yr)` : ' (1yr)'}`}
            </button>
          </div>
          {walked && (
            <div className="text-center">
              <p className="text-[11px] text-blood">
                She walked out — she'll sit out the year rather than take this, and won't sign
                with {brandId} again until next season (clear the holdout on her profile to reopen).
              </p>
              <button onClick={() => { negotiateReset(wrestler.id, brandId); setResult(null) }}
                className="mt-1 text-[11px] text-slate-500 hover:text-slate-300 underline">
                reset this negotiation
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
