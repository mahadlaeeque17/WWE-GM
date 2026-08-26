/**
 * The Royal Rumble — pick a field, run it, watch it play out.
 *
 * The match is resolved on the server in one call (deterministically, from the
 * save seed), and then REPLAYED here on a timer. That split is deliberate: the
 * result must not depend on whether you watched it, so nothing about the replay
 * can change the outcome — you can skip to the end and get the same winner.
 *
 * The reason it exists at all: a Rumble win is worth 3 points of Achievements,
 * more than a secondary title reign, and it is the single biggest thing a
 * wrestler can win in one night.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchRumbleField, runRumble, type RumbleResult, type RosterRow,
} from './api'
import { Avatar } from './ui'

const FIELD_SIZES = [10, 20, 30]

/** mm:ss from the match clock. */
function clock(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export default function RumblePanel({ roster }: { roster: RosterRow[] }) {
  const qc = useQueryClient()
  const [size, setSize] = useState(30)
  const [name, setName] = useState('Royal Rumble')
  const [result, setResult] = useState<RumbleResult | null>(null)
  const [shown, setShown] = useState(0)          // how many timeline events revealed
  const [err, setErr] = useState<string | null>(null)
  const timer = useRef<number | null>(null)

  const { data: field = [], isLoading } = useQuery({
    queryKey: ['rumble-field', size],
    queryFn: () => fetchRumbleField(size),
  })

  const byId = useMemo(() => new Map(roster.map((r) => [r.id, r])), [roster])

  const run = useMutation({
    mutationFn: () => runRumble(field.map((f) => f.wrestler_id), name.trim() || 'Royal Rumble'),
    onSuccess: (res) => {
      setErr(null)
      setResult(res)
      setShown(0)                                 // start the replay from the bell
      qc.invalidateQueries({ queryKey: ['roster'] })
      qc.invalidateQueries({ queryKey: ['shows'] })
      qc.invalidateQueries({ queryKey: ['calendar'] })
    },
    onError: (e: Error) => setErr(e.message),
  })

  // Reveal the timeline a beat at a time. Cleared on unmount so a half-watched
  // Rumble does not keep ticking behind another tab.
  useEffect(() => {
    if (!result || shown >= result.timeline.length) return
    timer.current = window.setTimeout(() => setShown((n) => n + 1), 240)
    return () => { if (timer.current) window.clearTimeout(timer.current) }
  }, [result, shown])

  const done = !!result && shown >= result.timeline.length
  const events = result ? result.timeline.slice(0, shown) : []

  // Who is in the ring right now, from the events revealed so far — so the
  // display is always consistent with what the reader has actually seen.
  const inRing = useMemo(() => {
    const set: number[] = []
    for (const e of events) {
      if (e.kind === 'enter') set.push(e.wrestler_id)
      else if (e.kind === 'out') {
        const i = set.indexOf(e.wrestler_id)
        if (i >= 0) set.splice(i, 1)
      }
    }
    return set
  }, [events])

  const lastEvent = events[events.length - 1]

  return (
    <section className="card p-4">
      <div className="flex flex-wrap items-end gap-3 mb-3">
        <div>
          <h3 className="display text-base leading-none">Royal Rumble</h3>
          <p className="text-[11px] text-slate-500 mt-1">
            Two start, one enters every 90 seconds, last woman standing wins —
            and takes 3 points of Achievements, more than a secondary title reign.
          </p>
        </div>

        <div className="ml-auto flex items-end gap-2">
          <label className="block">
            <span className="label text-[9px] text-slate-500 block mb-1">Name</span>
            <input
              value={name} onChange={(e) => setName(e.target.value)}
              className="bg-canvas border border-edge rounded px-2 py-1 text-xs w-40
                         focus:outline-none focus:border-gold/60"
            />
          </label>
          <div>
            <span className="label text-[9px] text-slate-500 block mb-1">Field</span>
            <div className="flex gap-1">
              {FIELD_SIZES.map((n) => (
                <button
                  key={n} onClick={() => setSize(n)}
                  className={`label text-[10px] px-2 py-1 rounded border transition-colors
                    ${size === n ? 'border-gold text-gold bg-gold/10'
                      : 'border-edge text-slate-500 hover:text-slate-200'}`}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>
          <button
            onClick={() => run.mutate()}
            disabled={run.isPending || field.length < 4}
            className={`label text-[10px] px-3 py-1.5 rounded transition-colors
              ${field.length >= 4 ? 'bg-gold text-canvas hover:bg-gold/85'
                : 'bg-raised text-slate-600 cursor-not-allowed'}`}
          >
            {run.isPending ? 'Ringing the bell…' : 'Run the Rumble'}
          </button>
        </div>
      </div>

      {err && <p className="text-xs text-blood mb-2">{err}</p>}

      {/* ----------------------------------------------------------- the field */}
      {!result && (
        <>
          {isLoading && <p className="text-xs text-slate-500">Building the field…</p>}
          {!isLoading && field.length < 4 && (
            <p className="text-xs text-slate-500">
              Not enough healthy wrestlers under contract yet. Run the draft first —
              a Rumble needs at least four.
            </p>
          )}
          {field.length >= 4 && (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(168px,1fr))] gap-1.5">
              {field.map((f, i) => (
                <div key={f.wrestler_id}
                     className="flex items-center gap-2 px-2 py-1.5 rounded bg-canvas/60
                                border border-edge-soft min-w-0">
                  <span className="stat text-[13px] text-slate-600 w-5 text-right shrink-0">{i + 1}</span>
                  {byId.get(f.wrestler_id) && <Avatar row={byId.get(f.wrestler_id)!} width={22} />}
                  <span className="text-xs truncate">{f.name}</span>
                  <span className="stat text-[12px] text-slate-500 ml-auto shrink-0">{f.overall}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* -------------------------------------------------------- the play-out */}
      {result && (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px]">
          <div className="min-w-0">
            <div className="flex items-center gap-3 mb-2">
              <span className="stat text-lg text-gold">{clock(lastEvent?.t ?? 0)}</span>
              <span className="label text-[10px] text-slate-500">
                {inRing.length} in the ring
              </span>
              {!done && (
                <button onClick={() => setShown(result.timeline.length)}
                        className="label text-[10px] text-slate-500 hover:text-gold ml-auto">
                  skip to the finish →
                </button>
              )}
              {done && (
                <button onClick={() => { setResult(null); setShown(0) }}
                        className="label text-[10px] text-slate-500 hover:text-gold ml-auto">
                  set another one up
                </button>
              )}
            </div>

            <div className="max-h-[340px] overflow-auto pr-1 flex flex-col-reverse gap-0.5">
              {events.map((e, i) => (
                <div key={i}
                     className={`flex items-baseline gap-2 text-xs px-2 py-1 rounded
                       ${e.kind === 'win' ? 'bg-gold/12 text-gold'
                         : e.kind === 'enter' ? 'text-slate-300' : 'text-slate-500'}`}>
                  <span className="stat text-[11px] text-slate-600 w-9 shrink-0">{clock(e.t)}</span>
                  {e.kind === 'enter' && (
                    <>
                      <span className="label text-[9px] text-emerald-400 w-8 shrink-0">IN</span>
                      <span>#{e.number} <span className="text-slate-100">{e.name}</span></span>
                    </>
                  )}
                  {e.kind === 'out' && (
                    <>
                      <span className="label text-[9px] text-blood w-8 shrink-0">OUT</span>
                      <span>
                        {e.name}
                        {e.by_name && <span className="text-slate-600"> — thrown out by {e.by_name}</span>}
                      </span>
                    </>
                  )}
                  {e.kind === 'win' && (
                    <>
                      <span className="label text-[9px] w-8 shrink-0">WIN</span>
                      <span className="display text-sm">{e.name} wins the Rumble</span>
                    </>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Held back until the match is over. The point of a replay is not
              knowing, and a result panel visible from the first second would give
              the winner away before the bell. */}
          <div className="min-w-0">
            {done ? (
              <div className="rounded border border-gold/40 bg-gold/5 p-3">
                <span className="label text-[9px] text-gold">Winner</span>
                <div className="flex items-center gap-2 mt-1 mb-2">
                  {byId.get(result.winner.wrestler_id) && (
                    <Avatar row={byId.get(result.winner.wrestler_id)!} width={34} />
                  )}
                  <div className="min-w-0">
                    <div className="display text-base leading-tight truncate">{result.winner.name}</div>
                    <div className="text-[11px] text-slate-400">
                      from number {result.winner.number}
                    </div>
                  </div>
                </div>
                <dl className="text-[11px] text-slate-400 grid grid-cols-2 gap-y-0.5">
                  <dt>Time in the match</dt>
                  <dd className="text-right stat text-slate-200">{clock(result.winner.lasted)}</dd>
                  <dt>Eliminations</dt>
                  <dd className="text-right stat text-slate-200">{result.winner.eliminations}</dd>
                  <dt>Match rating</dt>
                  <dd className="text-right stat text-slate-200">{result.quality}</dd>
                </dl>
                {result.iron_woman && (
                  <p className="mt-2 text-[11px] text-gold">
                    Iron Woman — she went the distance from an early number, and
                    picked up a second accolade for it.
                  </p>
                )}
                {result.most_eliminations && (
                  <p className="mt-2 text-[11px] text-slate-500">
                    Most eliminations: <span className="text-slate-300">
                      {result.most_eliminations.name}</span> with {result.most_eliminations.eliminations}
                  </p>
                )}
                <p className="mt-2 pt-2 border-t border-gold/20 text-[11px] text-slate-500">
                  Achievements has already moved — check her panel.
                </p>
              </div>
            ) : (
              <div className="rounded border border-edge-soft p-3 text-[11px] text-slate-600">
                Still going. The result is already decided on the server, so
                skipping ahead cannot change it.
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
