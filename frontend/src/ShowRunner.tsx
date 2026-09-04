/**
 * Show night — the card revealed one segment at a time.
 *
 * WHY THIS EXISTS. Confirming a card used to hand back a finished results table:
 * every match, every rating, all at once. That is the right way to REVIEW a show
 * you ran last month and the wrong way to experience one you just booked — the
 * payoff for a night's booking arrived as a spreadsheet, and the main event you
 * built to for six weeks appeared in a row halfway down.
 *
 * So the results are walked through. Each press reveals the next segment with
 * its result, its rating and how the crowd took it, and the night's rating is
 * withheld until the end because that is what it is: the verdict on the whole
 * card, not a number that was true from the start.
 *
 * Nothing here simulates or decides anything — the show has already run and been
 * committed. This is presentation over data that already exists, which is why it
 * can be skipped with no consequence.
 */
import { useState } from 'react'
import { REACTION_COLOUR, starsFor } from './api'
import { Stars } from './ui'

type Segment = {
  kind: 'match' | 'promo'
  slot: number
  quality: number | null
  reaction?: string | null
  label?: string
  sides?: { names: string[]; won: boolean }[]
  finish?: string
  people?: string[]
  titleId?: number | null
  seconds?: { name: string; note: string | null }[]
  interference?: string | null
  isMain?: boolean
}

/** Build the running order from what run_show returned. */
function toSegments(res: any): Segment[] {
  const out: Segment[] = []
  const matches = res?.matches ?? []
  for (const m of matches) {
    const sides = (m.teams ?? []).map((t: number[], i: number) => ({
      names: t.map((id: number) => res.names?.[id] ?? `#${id}`),
      won: m.winner_team === i,
    }))
    out.push({
      kind: 'match', slot: m.slot, quality: m.quality, reaction: m.reaction,
      sides, finish: m.finish, titleId: m.title_id,
      label: m.match_type_label,
      seconds: (m.seconds ?? []).filter(Boolean).map((s: any) => ({
        name: s.name, note: s.note ?? null,
      })),
      interference: m.interference_note ?? null,
      isMain: m.is_main_event,
    })
  }
  for (const p of res?.promos ?? []) {
    out.push({
      kind: 'promo', slot: p.slot, quality: p.quality, reaction: p.reaction,
      label: p.label,
      people: (p.wrestler_ids ?? []).map((id: number) => res.names?.[id] ?? `#${id}`),
    })
  }
  return out.sort((a, b) => a.slot - b.slot)
}

export default function ShowRunner({
  result, onFinish,
}: { result: any; onFinish: () => void }) {
  const segments = toSegments(result)
  // How many are revealed. Starts at 0 so the first press is the opener.
  const [shown, setShown] = useState(0)
  const done = shown >= segments.length

  if (!segments.length) return null

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="max-w-[720px] mx-auto">
        <div className="text-center mb-5">
          <div className="label text-[9px] text-slate-500">
            {result.is_ppv ? 'Pay-per-view' : 'Show night'}
          </div>
          <h2 className="display text-[26px] leading-tight">{result.name}</h2>
          <p className="text-[11px] text-slate-500 mt-1">
            {result.city ? `${result.city} · ` : ''}
            {result.attendance?.toLocaleString()} in the building
          </p>
        </div>

        <div className="space-y-2">
          {segments.slice(0, shown).map((s, i) => (
            <SegmentCard key={`${s.kind}-${s.slot}`} s={s} fresh={i === shown - 1} />
          ))}
        </div>

        {!done && (
          <div className="text-center mt-5">
            <button onClick={() => setShown((n) => n + 1)}
              className="px-6 py-2.5 rounded font-bold text-black"
              style={{ background: 'var(--color-gold)' }}>
              {shown === 0 ? 'Start the show'
                : shown === segments.length - 1 ? 'And the main event…'
                : 'Next segment →'}
            </button>
            <div className="text-[10px] text-slate-600 mt-2">
              {shown} of {segments.length} ·{' '}
              <button onClick={() => setShown(segments.length)}
                className="hover:text-slate-300 underline">
                show me everything
              </button>
            </div>
          </div>
        )}

        {/* The night's verdict is withheld until the end, because that is what
            it is — the rating of the whole card, not a number that was already
            true when the opener started. */}
        {done && (
          <div className="card p-5 mt-5 text-center champ-glow">
            <div className="label text-[9px] text-slate-500">The night</div>
            <div className="stat text-[38px] leading-none text-gold">
              {result.rating?.toFixed(1)}
            </div>
            <div className="flex justify-center mt-1">
              <Stars quality={result.rating} size={16} />
            </div>
            {result.tv?.tv_rating != null && (
              <p className="text-[12px] text-slate-300 mt-2">
                📺 a <span className="stat text-gold">{result.tv.tv_rating.toFixed(2)}</span>{' '}
                rating — {result.tv.viewers?.toLocaleString()} homes
                {result.tv.previous != null && (
                  <span className="text-slate-500">
                    {' '}(was {result.tv.previous.toFixed(2)})
                  </span>
                )}
              </p>
            )}
            {result.tv?.buyrate != null && (
              <p className="text-[12px] text-slate-300 mt-2">
                💸 a <span className="stat text-gold">{result.tv.buyrate.toFixed(2)}</span>{' '}
                buyrate — about {result.tv.buys?.toLocaleString()} buys
              </p>
            )}
            {result.crowd?.loudest && (
              <p className="text-[11px] text-slate-500 mt-2">
                Loudest of the night:{' '}
                {result.crowd.loudest.kind === 'promo'
                  ? 'a promo' : `match ${result.crowd.loudest.slot}`} —{' '}
                <span style={{ color: REACTION_COLOUR[result.crowd.loudest.reaction ?? ''] ?? '#94a3b8' }}>
                  {result.crowd.loudest.reaction}
                </span>
              </p>
            )}
            {result.ledger && (
              <p className="text-[11px] text-slate-500 mt-2">
                Net ${result.ledger.net?.toLocaleString()} · fanbase{' '}
                {result.ledger.fan_change >= 0 ? '+' : ''}
                {result.ledger.fan_change?.toLocaleString()}
              </p>
            )}
            <button onClick={onFinish}
              className="mt-4 text-xs px-4 py-2 rounded border border-edge text-slate-300 hover:border-gold/60">
              See the full card
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function SegmentCard({ s, fresh }: { s: Segment; fresh: boolean }) {
  const colour = REACTION_COLOUR[s.reaction ?? ''] ?? '#94a3b8'
  return (
    <div className={`card p-3 ${fresh ? 'pop-in' : ''}`}
      style={{ borderLeft: `2px solid ${s.kind === 'promo' ? '#34d399' : colour}` }}>
      <div className="flex items-baseline justify-between gap-2 mb-1">
        <span className="label text-[9px] text-slate-500">
          {s.kind === 'promo' ? `🎤 ${s.label ?? 'Promo'}`
            : s.isMain ? 'Main event' : `Match ${s.slot}`}
          {s.kind === 'match' && s.label && s.label !== 'Singles' && (
            <span className="text-slate-400"> · {s.label}</span>
          )}
          {s.titleId ? <span className="text-gold"> · ◆ championship</span> : null}
        </span>
        <span className="flex items-baseline gap-2 shrink-0">
          <span className="label text-[8px]" style={{ color: colour }}>{s.reaction}</span>
          <span className="stat text-[16px] text-slate-100">{s.quality?.toFixed(1)}</span>
        </span>
      </div>

      {s.kind === 'match' ? (
        <>
          <div className="flex items-center gap-2 flex-wrap">
            {s.sides?.map((side, i) => (
              <span key={i} className="flex items-center gap-2">
                {i > 0 && <span className="text-slate-600 text-[11px]">vs</span>}
                <span className={`text-[13px] ${side.won ? 'text-emerald-400 font-semibold' : 'text-slate-400'}`}>
                  {side.names.join(' & ')}{side.won ? ' ✓' : ''}
                </span>
              </span>
            ))}
          </div>
          <div className="text-[10px] text-slate-500 mt-1">
            via {s.finish}
            {!!s.seconds?.length && (
              <span className="text-slate-400">
                {' '}· ringside: {s.seconds.map((x) => x.name).join(', ')}
              </span>
            )}
          </div>
          {s.interference && (
            <p className="text-[11px] text-orange-400 mt-1">🫱 {s.interference}</p>
          )}
        </>
      ) : (
        <div className="text-[13px] text-slate-300">{s.people?.join(' & ')}</div>
      )}
      <div className="flex mt-1"><Stars quality={s.quality} size={11} /></div>
    </div>
  )
}

/** Exported so the caller can decide whether a result is worth walking through. */
export const segmentCount = (res: any) =>
  (res?.matches?.length ?? 0) + (res?.promos?.length ?? 0)

export { starsFor }
