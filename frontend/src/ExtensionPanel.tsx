/**
 * Re-signing somebody — as a negotiation, not a button.
 *
 * WHAT THIS REPLACED. "Extend" used to be a dropdown for the length and a
 * button that paid her asking price. That turned the one genuinely interesting
 * decision in contract management — what keeping a wrestler is worth to you —
 * into data entry, and it meant morale had no consequence at the exact moment
 * morale should bite hardest.
 *
 * So the offer is put to her: salary, perks and LENGTH together, and she can
 * accept, counter, be insulted, or walk away from the table. Her position comes
 * from a RETENTION price rather than a market price, which is where the drama
 * is: a happy wrestler re-signs about 16% under what it would cost to sign her
 * cold, and an unhappy one wants about 22% OVER, because leaving is the thing
 * she actually wants.
 *
 * PUTTING AN OFFER TO HER IS NOT FREE, and the copy below says so. An early
 * draft claimed it was, which was wrong in a way the player would have found out
 * the hard way: an offer she finds INSULTING burns her patience, and at zero she
 * walks away from the table for the rest of the season. Testing a plausible
 * number costs nothing; testing an insult costs you a chance.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  fetchExtensionQuote, extensionOffer, extendContract, fetchPerks,
  type ExtensionVerdict, type Contract,
} from './api'

const money = (n: number) => `$${n.toLocaleString()}`

const MOOD: Record<string, { fg: string; label: string }> = {
  thrilled: { fg: '#34d399', label: 'Thrilled' },
  satisfied: { fg: '#34d399', label: 'Happy with that' },
  negotiating: { fg: 'var(--color-gold)', label: 'Close — she is haggling' },
  unimpressed: { fg: '#fb923c', label: 'Unimpressed' },
  insulted: { fg: '#f87171', label: 'Insulted' },
  done: { fg: '#f87171', label: 'She has walked away' },
}

export default function ExtensionPanel({
  wrestlerId, contract, role, onSigned, onError,
}: {
  wrestlerId: number
  contract: Contract
  role: string
  onSigned: () => void
  onError: (s: string) => void
}) {
  const kind = role === 'manager' ? 'manager' : 'wrestler'
  const { data: quote } = useQuery({
    queryKey: ['ext-quote', wrestlerId, kind],
    queryFn: () => fetchExtensionQuote(wrestlerId, kind),
  })
  const { data: perkList = [] } = useQuery({ queryKey: ['perks'], queryFn: fetchPerks })

  const [years, setYears] = useState(2)
  const [salary, setSalary] = useState<number | ''>('')
  const [perks, setPerks] = useState<string[]>([])
  const [bonus, setBonus] = useState<number | ''>('')
  const [verdict, setVerdict] = useState<ExtensionVerdict | null>(null)

  // Open on her asking price so the first thing on screen is a plausible deal
  // rather than an empty box.
  useEffect(() => {
    if (quote && salary === '') setSalary(quote.asking)
  }, [quote, salary])

  // Any change to the terms invalidates the last verdict — showing "accepted"
  // next to a number she was never asked about would be a lie.
  const touch = () => setVerdict(null)

  const test = useMutation({
    mutationFn: () => extensionOffer(wrestlerId, Number(salary || 0), years, perks,
                                     Number(bonus || 0)),
    onSuccess: (v) => { setVerdict(v); onError('') },
    onError: (e: Error) => onError(e.message),
  })
  const sign = useMutation({
    mutationFn: () => extendContract(wrestlerId, years, Number(salary || 0), perks,
                                     Number(bonus || 0)),
    onSuccess: () => { setVerdict(null); onSigned() },
    onError: (e: Error) => onError(e.message),
  })

  if (!quote) return <p className="text-[11px] text-slate-600 mt-2">Reading her position…</p>

  const mood = verdict ? (MOOD[verdict.mood] ?? MOOD.negotiating) : null
  const accepted = verdict?.verdict === 'accept'
  const walked = verdict?.verdict === 'walked'

  return (
    <div className="mt-2 rounded border border-edge bg-canvas/60 p-2.5">
      <div className="label text-[9px] text-slate-500 mb-1.5">
        Re-sign from {contract.end_year + 1}
      </div>

      {/* Her position, and why it is that number. */}
      <div className="flex items-baseline justify-between gap-2 text-[11px]">
        <span className="text-slate-500">She is asking</span>
        <span className="stat text-gold text-[15px]">{money(quote.asking)}</span>
      </div>
      <div className="flex items-baseline justify-between gap-2 text-[10px] text-slate-600">
        <span>market rate to sign her cold</span>
        <span className="tnum">{money(quote.market)}</span>
      </div>
      <p className="text-[10px] mt-1.5 leading-snug"
        style={{ color: quote.retention_factor > 1 ? '#fb923c' : '#34d399' }}>
        {quote.stance}
      </p>
      <p className="text-[9px] text-slate-600 mt-1 leading-snug">
        {quote.personality_label} · {quote.personality_effect}
      </p>

      {/* The terms. */}
      <div className="grid grid-cols-2 gap-1.5 mt-2.5">
        <label className="block">
          <span className="label text-[8px] text-slate-600">Salary / yr</span>
          <input type="number" value={salary}
            onChange={(e) => { touch(); setSalary(e.target.value === '' ? '' : Number(e.target.value)) }}
            className="w-full bg-canvas border border-edge rounded px-2 py-1 text-[12px] tnum" />
        </label>
        <label className="block">
          <span className="label text-[8px] text-slate-600">Length</span>
          <select value={years} onChange={(e) => { touch(); setYears(Number(e.target.value)) }}
            className="w-full bg-canvas border border-edge rounded px-2 py-1 text-[12px]">
            {[1, 2, 3, 4, 5].map((y) => <option key={y} value={y}>{y} year{y !== 1 ? 's' : ''}</option>)}
          </select>
        </label>
        <label className="block col-span-2">
          <span className="label text-[8px] text-slate-600">Signing bonus (one-off)</span>
          <input type="number" value={bonus}
            onChange={(e) => { touch(); setBonus(e.target.value === '' ? '' : Number(e.target.value)) }}
            placeholder="0"
            className="w-full bg-canvas border border-edge rounded px-2 py-1 text-[12px] tnum" />
        </label>
      </div>
      <p className="text-[9px] text-slate-600 mt-1 leading-snug">
        A long deal is worth less to somebody young and rising, and more to a veteran who wants
        the security — she prices the length as well as the money.
      </p>

      {/* Perks trade money for goodwill, and become PROMISES you have to keep. */}
      {perkList.length > 0 && (
        <div className="mt-2">
          <span className="label text-[8px] text-slate-600">Perks</span>
          <div className="flex flex-wrap gap-1 mt-1">
            {perkList.map((p) => {
              const on = perks.includes(p.key)
              return (
                <button key={p.key} title={p.desc}
                  onClick={() => { touch(); setPerks((xs) => on ? xs.filter((x) => x !== p.key) : [...xs, p.key]) }}
                  className={`label text-[8px] px-1.5 py-1 rounded border ${
                    on ? 'border-gold text-gold bg-gold/10' : 'border-edge text-slate-500 hover:text-slate-300'}`}>
                  {p.label}
                </button>
              )
            })}
          </div>
          {perks.length > 0 && (
            <p className="text-[9px] text-orange-400/80 mt-1 leading-snug">
              A perk is a promise. Not delivering it costs her morale at season's end.
            </p>
          )}
        </div>
      )}

      {/* Her verdict. */}
      {verdict && (
        <div className="mt-2 rounded px-2 py-1.5"
          style={{ background: `${mood!.fg}18`, border: `1px solid ${mood!.fg}44` }}>
          <div className="flex items-baseline justify-between gap-2">
            <span className="label text-[9px]" style={{ color: mood!.fg }}>{mood!.label}</span>
            {!accepted && (
              <span className="text-[9px]"
                style={{ color: verdict.patience <= 1 ? '#f87171' : '#64748b' }}
                title="How many more poor offers she will hear before walking away">
                {verdict.patience > 0 ? `patience ${verdict.patience}` : 'out of patience'}
              </span>
            )}
          </div>
          {verdict.counter != null && !accepted && (
            <p className="text-[11px] text-slate-300 mt-0.5">
              She wants about <span className="stat text-gold">{money(verdict.counter)}</span>.
              <button onClick={() => { setSalary(verdict.counter!); setVerdict(null) }}
                className="text-[10px] text-gold hover:underline ml-1.5">
                meet it
              </button>
            </p>
          )}
          {walked && (
            <p className="text-[10px] text-slate-400 mt-0.5">
              She will see out her deal. Try again next season.
            </p>
          )}
        </div>
      )}

      <div className="flex items-center gap-1.5 mt-2">
        <button onClick={() => test.mutate()} disabled={test.isPending || !salary}
          className="text-[11px] px-2.5 py-1 rounded border border-edge text-slate-300 hover:border-gold/60 disabled:opacity-30">
          {test.isPending ? '…' : 'Put it to her'}
        </button>
        <button onClick={() => sign.mutate()} disabled={sign.isPending || !salary || walked}
          className="text-[11px] px-2.5 py-1 rounded font-semibold text-black disabled:opacity-30"
          style={{ background: accepted ? 'var(--color-gold)' : '#4b5563',
                   color: accepted ? '#000' : '#cbd5e1' }}>
          {sign.isPending ? 'Signing…' : accepted ? 'Sign it' : 'Sign anyway'}
        </button>
      </div>
      <p className="text-[9px] text-slate-600 mt-1 leading-snug">
        A sensible offer costs nothing to float. An <em>insulting</em> one burns her patience,
        and at zero she walks away from the table until next season — so haggle, do not low-ball.
        “Sign anyway” still has to be a deal she accepts; if she refuses, nothing is signed and
        she tells you why.
      </p>
    </div>
  )
}
