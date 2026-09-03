/**
 * Live storylines — a feud as a STORY rather than a heat number.
 *
 * WHAT THIS ADDS OVER THE RIVALRY LIST BELOW IT. That list is history: every
 * pair who have ever met, ranked. This is the present tense — the feuds running
 * right now, what stage each is at, what has happened in it so far, and what
 * should happen next.
 *
 * THE BLOW-OFF PLANNER IS THE POINT. Pointing a feud at a date makes the
 * pre-booker WITHHOLD the singles match until then: it books promos, run-ins and
 * tag matches that keep the two apart instead. Anyone can book the blow-off
 * tonight; the skill is not booking it tonight, and until there was a plan to
 * set, the booker always reached for the hottest pairing and made that skill
 * impossible to express.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchStorylines, planBlowoff, fetchCalendar, prettyDate,
  type Storyline,
} from './api'

const STAGE_COLOUR: Record<string, string> = {
  build: '#94a3b8',
  escalation: 'var(--color-gold)',
  blowoff: '#f87171',
  settled: '#475569',
}

const BEAT_ICON: Record<string, string> = {
  match: '⚔', promo: '🎤', run_in: '💥', turn: '🔄',
  opened: '●', settled: '🤝', planned: '📌',
}

export default function Storylines() {
  const qc = useQueryClient()
  const [open, setOpen] = useState<number | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const { data: arcs = [], isLoading } = useQuery({
    queryKey: ['storylines'], queryFn: () => fetchStorylines('active'),
  })
  const { data: cal } = useQuery({ queryKey: ['calendar'], queryFn: fetchCalendar })

  const invalidate = () => {
    setErr(null)
    qc.invalidateQueries({ queryKey: ['storylines'] })
    qc.invalidateQueries({ queryKey: ['suggest'] })
    qc.invalidateQueries({ queryKey: ['feuds'] })
  }

  if (isLoading) return null
  if (!arcs.length) {
    return (
      <div className="px-4 py-3 border-b border-edge">
        <h3 className="label text-[11px] text-slate-400 tracking-wider mb-1">Live storylines</h3>
        <p className="text-[11px] text-slate-600 max-w-[560px]">
          No feuds running. Start one from a wrestler's panel, or grant a storyline request in
          the locker room — a rivalry is the single best reason to put two women in a ring.
        </p>
      </div>
    )
  }

  return (
    <div className="px-4 py-3 border-b border-edge">
      <div className="flex items-baseline gap-2 mb-1">
        <h3 className="label text-[11px] text-slate-400 tracking-wider">Live storylines</h3>
        <span className="stat text-[11px] text-gold">{arcs.length}</span>
      </div>
      <p className="text-[10px] text-slate-600 mb-2.5 max-w-[640px] leading-snug">
        Point a feud at a pay-per-view and the booker stops giving away the singles match — it
        builds with promos and tag matches until the date instead.
      </p>
      {err && <p className="text-[11px] text-blood mb-2">{err}</p>}
      <div className="space-y-1.5">
        {arcs.map((a) => (
          <ArcRow key={a.id} a={a} cal={cal} open={open === a.id}
            onToggle={() => setOpen(open === a.id ? null : a.id)}
            onDone={invalidate} onErr={setErr} />
        ))}
      </div>
    </div>
  )
}

function ArcRow({ a, cal, open, onToggle, onDone, onErr }: {
  a: Storyline
  cal?: { ppv: string | null; season_year: number
          schedule: { month: number; month_name: string; name: string; date: string }[] }
  open: boolean; onToggle: () => void; onDone: () => void; onErr: (s: string) => void
}) {
  const plan = useMutation({
    mutationFn: (v: { date: string | null; label?: string }) =>
      planBlowoff(a.id, v.date, v.label),
    onSuccess: onDone,
    onError: (e: Error) => onErr(e.message),
  })
  const colour = STAGE_COLOUR[a.stage] ?? '#94a3b8'
  const lead = a.series.leader
  const score = `${a.series.a_wins}–${a.series.b_wins}`

  return (
    <div className="card p-2.5" style={{ borderLeft: `2px solid ${colour}` }}>
      <button onClick={onToggle} className="w-full text-left">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-[13px] ${lead === a.a_id ? 'text-slate-100' : 'text-slate-400'}`}>
            {a.a_name}
          </span>
          <span className="text-slate-600 text-[11px]">v</span>
          <span className={`text-[13px] ${lead === a.b_id ? 'text-slate-100' : 'text-slate-400'}`}>
            {a.b_name}
          </span>
          {a.series.matches > 0 && (
            <span className="stat text-[11px] text-slate-500" title="Series score">{score}</span>
          )}
          <span className="label text-[8px] px-1.5 py-[2px] rounded ml-auto shrink-0"
            style={{ background: `${colour}22`, color: colour }}>
            {a.stage_label}
          </span>
          <span className="stat text-[13px] shrink-0" style={{ color: colour }}>{a.heat}</span>
        </div>
        <div className="h-[2px] rounded bg-raised overflow-hidden mt-1">
          <div className="h-full" style={{ width: `${a.heat}%`, background: colour }} />
        </div>
        <div className="flex items-baseline justify-between gap-2 mt-1">
          <span className="text-[10px] text-slate-500 truncate">{a.next.advice}</span>
          {a.planned_blowoff && (
            <span className="label text-[8px] text-gold shrink-0">
              📌 {a.blowoff_label ?? a.planned_blowoff}
            </span>
          )}
        </div>
      </button>

      {open && (
        <div className="mt-2 pt-2 border-t border-edge-soft">
          {/* ---- the planner ---- */}
          <div className="label text-[8px] text-slate-500 mb-1">Build it to</div>
          <div className="flex items-center gap-1.5 flex-wrap mb-2.5">
            {(cal?.schedule ?? []).map((p) => {
              // The date comes from the server (game.calendar), not from a
              // second copy of the "last Sunday of the month" rule out here —
              // two implementations of one rule is a drift waiting to happen.
              const d = p.date
              const active = a.planned_blowoff === d
              return (
                <button key={p.month} disabled={plan.isPending}
                  onClick={() => plan.mutate(active
                    ? { date: null }
                    : { date: d, label: `${p.name} ${cal!.season_year}` })}
                  title={active ? 'Click to clear the plan' : `Build to ${p.name}`}
                  className={`label text-[8px] px-1.5 py-1 rounded border disabled:opacity-40 ${
                    active ? 'border-gold text-gold bg-gold/10'
                      : 'border-edge text-slate-500 hover:text-slate-200'}`}>
                  {p.name}
                </button>
              )
            })}
            {a.planned_blowoff && (
              <button disabled={plan.isPending} onClick={() => plan.mutate({ date: null })}
                className="label text-[8px] px-1.5 py-1 rounded border border-edge text-blood hover:bg-blood/10 disabled:opacity-40">
                clear
              </button>
            )}
          </div>
          <p className="text-[10px] text-slate-500 mb-2.5 leading-snug">{a.stage_note}</p>

          {/* ---- the story so far ---- */}
          <div className="label text-[8px] text-slate-500 mb-1">The story so far</div>
          {a.beats.length === 0
            ? <p className="text-[10px] text-slate-600">Nothing has happened yet.</p>
            : <div className="space-y-0.5">
                {a.beats.map((b) => (
                  <div key={b.id} className="flex items-baseline gap-2 text-[10px]">
                    <span className="shrink-0 w-3 text-center">{BEAT_ICON[b.kind] ?? '·'}</span>
                    <span className="text-slate-600 w-14 shrink-0">{prettyDate(b.on_date)}</span>
                    <span className="text-slate-300 flex-1">{b.text}</span>
                    {b.heat_after != null && (
                      <span className="text-slate-600 shrink-0 tnum">{b.heat_after}</span>
                    )}
                  </div>
                ))}
              </div>}
        </div>
      )}
    </div>
  )
}

