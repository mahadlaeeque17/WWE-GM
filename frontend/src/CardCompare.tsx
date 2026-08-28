/**
 * Two cards, side by side, with their shapes on the same axes.
 *
 * WHY IT NEEDS TO EXIST. Two overalls in the fifties can be completely different
 * performers — Trish Stratus and Meiko Satomura sat two apart and looked nothing
 * alike, one a wide flat kite and the other a single spike. A number cannot say
 * that; two shapes on one pentagon can.
 *
 * Works across wrestlers AND across years, which is the same operation: comparing
 * her 2003 card to her 2009 one is comparing two cards. So the picker is just a
 * flat list of every card either side could be.
 */
import { useMemo, useState } from 'react'
import { CAT_MAX, type PlayerCard } from './api'
import Card from './Card'
import Pentagon from './Pentagon'

const A_COLOUR = 'var(--color-gold)'
const B_COLOUR = 'var(--color-smackdown)'

/** A card's five stored values in pentagon axis order. */
function valuesOfCard(c: PlayerCard): number[] {
  return c.stats.map((s) => s.v20)
}

function labelsOfCard(c: PlayerCard): string[] {
  return c.stats.map((s) => s.label)
}

export default function CardCompare({
  cards, portraitOf, onClose,
}: {
  cards: PlayerCard[]
  portraitOf?: (id: number) => string | null
  onClose?: () => void
}) {
  const [aKey, setAKey] = useState<string | null>(null)
  const [bKey, setBKey] = useState<string | null>(null)

  const keyOf = (c: PlayerCard) => `${c.wrestler_id}-${c.season_year}`
  const byKey = useMemo(() => new Map(cards.map((c) => [keyOf(c), c])), [cards])
  const a = aKey ? byKey.get(aKey) : undefined
  const b = bKey ? byKey.get(bKey) : undefined

  // Sorted by overall so the picker reads like the set does.
  const options = useMemo(
    () => [...cards].sort((x, y) => y.overall - x.overall), [cards])

  /**
   * The axis labels only agree if both cards are the same ROLE. Comparing a
   * manager to a wrestler puts MIC against WRS on the same spoke, which is
   * meaningless — so it says so rather than drawing a lie.
   */
  const mismatched = !!a && !!b && (a.role === 'manager') !== (b.role === 'manager')

  const Picker = ({ value, onChange, label, colour }: {
    value: string | null; onChange: (v: string) => void; label: string; colour: string
  }) => (
    <label className="flex-1 min-w-0">
      <span className="label text-[9px] block mb-1" style={{ color: colour }}>{label}</span>
      <select
        value={value ?? ''} onChange={(e) => onChange(e.target.value)}
        className="w-full bg-canvas border border-edge rounded px-2 py-1.5 text-xs
                   focus:outline-none focus:border-gold/60"
      >
        <option value="">— pick a card —</option>
        {options.map((c) => (
          <option key={keyOf(c)} value={keyOf(c)}>
            {c.overall} · {c.name} · {c.season_year}
            {c.role === 'manager' ? ' (mgr)' : ''}
          </option>
        ))}
      </select>
    </label>
  )

  return (
    <section className="card p-4">
      <div className="flex items-center gap-3 mb-3">
        <h3 className="display text-base leading-none">Compare</h3>
        <p className="text-[11px] text-slate-500 flex-1">
          Two overalls can match and describe completely different wrestlers.
          The shape is the part that tells you which.
        </p>
        {onClose && (
          <button onClick={onClose} className="label text-[10px] text-slate-500 hover:text-gold">
            close
          </button>
        )}
      </div>

      <div className="flex gap-3 mb-4">
        <Picker value={aKey} onChange={setAKey} label="Card A" colour={A_COLOUR} />
        <Picker value={bKey} onChange={setBKey} label="Card B" colour={B_COLOUR} />
      </div>

      {!a && !b && (
        <p className="text-xs text-slate-500">
          Pick two. They can be two wrestlers, or the same wrestler in two
          different years — a career is easiest to see as one card against another.
        </p>
      )}

      {mismatched && (
        <p className="text-[11px] text-gold mb-3">
          One of these is a manager. Her two performance stats are Mic and
          Influence where a wrestler's are Wrestling and Popularity, so the
          overlaid spokes would be comparing different measurements. The cards
          below are still worth reading side by side; the shape is not.
        </p>
      )}

      <div className="flex flex-wrap items-start gap-5">
        {a && <Card card={a} size="md" portrait={portraitOf?.(a.wrestler_id) ?? null} />}

        {a && b && !mismatched && (
          <div className="flex-1 min-w-[220px] flex flex-col items-center">
            <Pentagon
              values={valuesOfCard(a)}
              overlay={valuesOfCard(b)}
              labels={labelsOfCard(a)}
              colour={A_COLOUR}
              overlayColour={B_COLOUR}
              size={230}
            />
            <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-2 gap-y-0.5 mt-2 w-full text-[11px]">
              {a.stats.map((st, i) => {
                const bv = b.stats[i]?.v20 ?? 0
                const diff = st.v20 - bv
                return (
                  <div key={st.key} className="contents">
                    <span className="label text-[9px] text-slate-500 self-center">{st.label}</span>
                    <span className="stat text-right" style={{ color: A_COLOUR }}>{st.v99}</span>
                    <span className="stat text-right" style={{ color: B_COLOUR }}>
                      {b.stats[i]?.v99 ?? '—'}
                    </span>
                    <span className={`stat text-right w-8 ${
                      diff > 0 ? 'text-emerald-400' : diff < 0 ? 'text-blood' : 'text-slate-600'}`}>
                      {diff === 0 ? '—' : `${diff > 0 ? '+' : ''}${Math.round(diff / CAT_MAX * 99)}`}
                    </span>
                  </div>
                )
              })}
              <span className="label text-[9px] text-gold self-center pt-1 border-t border-edge-soft">OVR</span>
              <span className="stat text-right pt-1 border-t border-edge-soft" style={{ color: A_COLOUR }}>
                {a.overall}
              </span>
              <span className="stat text-right pt-1 border-t border-edge-soft" style={{ color: B_COLOUR }}>
                {b.overall}
              </span>
              <span className={`stat text-right pt-1 border-t border-edge-soft ${
                a.overall > b.overall ? 'text-emerald-400'
                  : a.overall < b.overall ? 'text-blood' : 'text-slate-600'}`}>
                {a.overall === b.overall ? '—'
                  : `${a.overall > b.overall ? '+' : ''}${a.overall - b.overall}`}
              </span>
            </div>
          </div>
        )}

        {b && <Card card={b} size="md" portrait={portraitOf?.(b.wrestler_id) ?? null} />}
      </div>
    </section>
  )
}
