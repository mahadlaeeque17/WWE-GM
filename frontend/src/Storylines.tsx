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
  fetchStorylineKinds, sourStoryline, createStoryline, fetchRoster,
  fetchStorylineIdeas,
  type Storyline, type StorylineIdea,
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

/** A romance is not a rivalry, so it should not be the colour of one. */
const KIND_COLOUR: Record<string, string> = {
  rivalry: '#f87171', romance: '#f472b6', alliance: '#38bdf8', mentorship: '#a78bfa',
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

  return (
    <div className="px-4 py-3 border-b border-edge">
      <div className="flex items-baseline gap-2 mb-1">
        <h3 className="label text-[11px] text-slate-400 tracking-wider">Live storylines</h3>
        {arcs.length > 0 && <span className="stat text-[11px] text-gold">{arcs.length}</span>}
      </div>
      <p className="text-[10px] text-slate-600 mb-2.5 max-w-[680px] leading-snug">
        A rivalry is not the only story two people can be in. A romance, an alliance or a
        mentorship builds the crowd's investment — and turning one sour hands you a feud that
        starts hot instead of cold. Managers count.
      </p>
      {err && <p className="text-[11px] text-blood mb-2">{err}</p>}

      <div className="flex items-center gap-1.5 flex-wrap">
        <NewStoryline onDone={invalidate} onErr={setErr} />
        <Ideas onDone={invalidate} onErr={setErr} />
      </div>

      {arcs.length === 0
        ? <p className="text-[11px] text-slate-600 max-w-[560px] mt-2">
            Nothing running. Start one above, or grant a storyline request in the locker room.
          </p>
        : <div className="space-y-1.5 mt-2.5">
            {arcs.map((a) => (
              <ArcRow key={a.id} a={a} cal={cal} open={open === a.id}
                onToggle={() => setOpen(open === a.id ? null : a.id)}
                onDone={invalidate} onErr={setErr} />
            ))}
          </div>}
    </div>
  )
}

/**
 * Stories the engine thinks you are missing.
 *
 * The locker room proposes requests and the crowd proposes turns, but nothing
 * proposed STORIES — so a roster could sit there with fifteen unbooked women
 * and no rivalries and the game would never once say "these two should be
 * feuding", which is the most useful thing it could say. Suggestions only: each
 * is one click to open and there is no cost to ignoring them.
 */
function Ideas({ onDone, onErr }: { onDone: () => void; onErr: (s: string) => void }) {
  const [show, setShow] = useState(false)
  const { data: ideas = [], isFetching, refetch } = useQuery({
    queryKey: ['storyline-ideas'], queryFn: () => fetchStorylineIdeas(undefined, 6),
    enabled: show,
  })
  const open = useMutation({
    mutationFn: (i: StorylineIdea) =>
      createStoryline(i.a_id, i.b_id, i.kind, i.brand_id),
    onSuccess: () => { refetch(); onDone() },
    onError: (e: Error) => onErr(e.message),
  })

  if (!show) {
    return (
      <button onClick={() => setShow(true)}
        className="label text-[9px] px-2 py-1 rounded border border-edge text-slate-400 hover:border-gold/60 hover:text-gold">
        💡 Ideas
      </button>
    )
  }
  return (
    <div className="w-full">
      <div className="flex items-baseline justify-between gap-2 mb-1.5">
        <span className="label text-[9px] text-slate-500">
          Stories you are missing
        </span>
        <button onClick={() => setShow(false)}
          className="text-[10px] text-slate-500 hover:text-slate-300">close</button>
      </div>
      {isFetching && <p className="text-[10px] text-slate-600">Reading the roster…</p>}
      {!isFetching && ideas.length === 0 && (
        <p className="text-[10px] text-slate-600">
          Nothing obvious — everybody worth pairing already has something going on.
        </p>
      )}
      <div className="space-y-1.5">
        {ideas.map((i) => (
          <div key={`${i.a_id}-${i.b_id}`} className="card p-2.5"
            style={{ borderLeft: `2px solid ${KIND_COLOUR[i.kind] ?? '#94a3b8'}` }}>
            <div className="flex items-center gap-2 flex-wrap mb-0.5">
              <span className="text-[12px] text-slate-200">{i.a_name}</span>
              <span className="text-slate-600 text-[10px]">
                {i.kind === 'rivalry' ? 'v' : '&'}
              </span>
              <span className="text-[12px] text-slate-200">{i.b_name}</span>
              <span className="label text-[8px] px-1.5 py-[2px] rounded ml-auto"
                style={{ background: `${KIND_COLOUR[i.kind] ?? '#94a3b8'}22`,
                         color: KIND_COLOUR[i.kind] ?? '#94a3b8' }}>
                {i.kind}
              </span>
            </div>
            <p className="text-[10px] text-slate-500 leading-snug">{i.reason}</p>
            <button disabled={open.isPending} onClick={() => open.mutate(i)}
              className="text-[10px] text-gold hover:underline mt-1 disabled:opacity-40">
              {open.isPending ? '…' : 'start it'}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

/**
 * Start a storyline of any kind between any two people.
 *
 * Deliberately not restricted to wrestlers: a romance between a manager and the
 * woman she manages is one of the most useful things on this list, and nothing
 * in the data model needed changing to allow it.
 */
function NewStoryline({ onDone, onErr }: { onDone: () => void; onErr: (s: string) => void }) {
  const [show, setShow] = useState(false)
  const [a, setA] = useState(0)
  const [b, setB] = useState(0)
  const [kind, setKind] = useState('rivalry')
  const { data: kinds = [] } = useQuery({
    queryKey: ['storyline-kinds'], queryFn: fetchStorylineKinds,
  })
  const { data: roster = [] } = useQuery({ queryKey: ['roster'], queryFn: fetchRoster })
  const signed = roster.filter((r) => r.contract && !r.removed)
  const create = useMutation({
    mutationFn: () => createStoryline(a, b, kind,
      signed.find((r) => r.id === a)?.contract?.brand_id ?? null),
    onSuccess: () => { setA(0); setB(0); setShow(false); onDone() },
    onError: (e: Error) => onErr(e.message),
  })
  const chosen = kinds.find((k) => k.key === kind)

  if (!show) {
    return (
      <button onClick={() => setShow(true)}
        className="label text-[9px] px-2 py-1 rounded border border-edge text-slate-400 hover:border-gold/60 hover:text-gold">
        + Start a storyline
      </button>
    )
  }
  return (
    <div className="card p-3">
      <div className="flex flex-wrap gap-1 mb-2">
        {kinds.map((k) => (
          <button key={k.key} onClick={() => setKind(k.key)} title={k.desc}
            className={`label text-[9px] px-2 py-1 rounded border ${
              kind === k.key ? 'border-gold text-gold bg-gold/10'
                : 'border-edge text-slate-500 hover:text-slate-300'}`}>
            {k.icon} {k.label}
          </button>
        ))}
      </div>
      {chosen && <p className="text-[10px] text-slate-500 mb-2 leading-snug">{chosen.desc}</p>}
      <div className="flex items-center gap-1.5">
        <PersonSelect value={a} exclude={b} options={signed} onChange={setA} />
        <span className="text-[10px] text-slate-600">{chosen?.wants_match ? 'v' : '&'}</span>
        <PersonSelect value={b} exclude={a} options={signed} onChange={setB} />
      </div>
      <div className="flex items-center gap-1.5 mt-2">
        <button disabled={!a || !b || a === b || create.isPending}
          onClick={() => create.mutate()}
          className="text-[11px] px-3 py-1 rounded font-semibold text-black disabled:opacity-30"
          style={{ background: 'var(--color-gold)' }}>
          {create.isPending ? 'Starting…' : 'Start it'}
        </button>
        <button onClick={() => setShow(false)}
          className="text-[11px] px-2 py-1 rounded border border-edge text-slate-400">
          cancel
        </button>
      </div>
    </div>
  )
}

function PersonSelect({ value, onChange, options, exclude }: {
  value: number; onChange: (v: number) => void; exclude: number
  options: { id: number; name: string; working_role: string }[]
}) {
  return (
    <select value={value} onChange={(e) => onChange(Number(e.target.value))}
      className="flex-1 min-w-0 bg-canvas border border-edge rounded px-2 py-1 text-[11px]">
      <option value={0}>— pick —</option>
      {options.map((r) => (
        <option key={r.id} value={r.id} disabled={r.id === exclude}>
          {r.name}{r.working_role === 'manager' ? ' (mgr)' : ''}
        </option>
      ))}
    </select>
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
  const sour = useMutation({
    mutationFn: () => sourStoryline(a.id),
    onSuccess: onDone,
    onError: (e: Error) => onErr(e.message),
  })
  // A non-rivalry is coloured by what it IS; a rivalry by how far along it is.
  const colour = a.kind && a.kind !== 'rivalry'
    ? (KIND_COLOUR[a.kind] ?? '#94a3b8')
    : (STAGE_COLOUR[a.stage] ?? '#94a3b8')
  const lead = a.series.leader
  const score = `${a.series.a_wins}–${a.series.b_wins}`

  return (
    <div className="card p-2.5" style={{ borderLeft: `2px solid ${colour}` }}>
      <button onClick={onToggle} className="w-full text-left">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-[13px] ${lead === a.a_id ? 'text-slate-100' : 'text-slate-400'}`}>
            {a.a_name}
          </span>
          <span className="text-slate-600 text-[11px]">
            {a.wants_match === false ? '&' : 'v'}
          </span>
          <span className={`text-[13px] ${lead === a.b_id ? 'text-slate-100' : 'text-slate-400'}`}>
            {a.b_name}
          </span>
          {a.series.matches > 0 && (
            <span className="stat text-[11px] text-slate-500" title="Series score">{score}</span>
          )}
          <span className="label text-[8px] px-1.5 py-[2px] rounded ml-auto shrink-0"
            style={{ background: `${colour}22`, color: colour }}>
            {a.kind_icon} {a.stage_label}
          </span>
          <span className="stat text-[13px] shrink-0" style={{ color: colour }}
            title={a.heat_word ? `${a.heat_word}: ${a.heat}` : undefined}>{a.heat}</span>
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
          {/* Turning it sour IS the payoff, not a failure — it converts a
              story the crowd is already invested in into a feud that starts
              hot, which is strictly better than opening a cold one. */}
          {a.sours_to && (
            <div className="mb-2.5">
              <button disabled={sour.isPending} onClick={() => sour.mutate()}
                className="text-[11px] px-3 py-1 rounded border disabled:opacity-40"
                style={{ borderColor: `${KIND_COLOUR[a.kind] ?? '#94a3b8'}88`,
                         color: KIND_COLOUR[a.kind] ?? '#94a3b8' }}>
                {sour.isPending ? 'Turning…' : `${a.sour_label} — make it a rivalry`}
              </button>
              <p className="text-[9px] text-slate-600 mt-1 leading-snug">
                The {a.heat_word} you have banked carries over, so the feud starts hot.
              </p>
            </div>
          )}
          {a.was_kind && (
            <p className="text-[10px] text-slate-500 mb-2">
              This began as {a.was_kind === 'romance' ? 'a romance' : `an ${a.was_kind}`}.
            </p>
          )}

          {/* Only a rivalry has a blow-off to build toward. */}
          {a.wants_match !== false && (
          <>
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
          </>
          )}
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

