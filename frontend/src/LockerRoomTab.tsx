/**
 * The locker room — how the roster feels, and what it is asking for.
 *
 * WHY THESE FOUR THINGS SHARE ONE SCREEN. A request, the morale behind it, the
 * medical note that caused it and the turn the crowd is asking for are one
 * conversation, not four. "She wants a raise" is a shrug on its own; "she is on
 * 55% of her market rate, has not main-evented in five weeks, and this is the
 * third time she has asked" is a decision. So the request sits next to its
 * evidence, and every complaint carries the lever that fixes it.
 *
 * The ordering is deliberate: REQUESTS first, because they are the only thing on
 * the page with a deadline attached.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchLockerRoom, resolveRequest, generateRequests, resolveTurn, scanTurns,
  restWrestler, clearRest, fetchBrands, undoRequest,
  type WrestlerRequest, type MoraleSnapshot, type MedicalRow, type TurnSuggestion,
} from './api'

const money = (n: number) => `$${n.toLocaleString()}`

/** Morale colour. The bottom two bands are red because they are the two the GM
 *  has to act on — everything above is information, not an alarm. */
function moodColour(m: number): string {
  if (m <= 12) return '#f87171'
  if (m <= 25) return '#fb923c'
  if (m <= 38) return 'var(--color-gold)'
  if (m <= 66) return '#94a3b8'
  return '#34d399'
}

const SEVERITY_STYLE: Record<string, { bg: string; fg: string; label: string }> = {
  ask: { bg: 'rgba(148,163,184,0.14)', fg: '#94a3b8', label: 'ASKING' },
  firm: { bg: 'rgba(251,146,60,0.16)', fg: '#fb923c', label: 'INSISTING' },
  final: { bg: 'rgba(248,113,113,0.18)', fg: '#f87171', label: 'FINAL WARNING' },
}

export default function LockerRoomTab() {
  const qc = useQueryClient()
  const [brand, setBrand] = useState<string | undefined>(undefined)
  const [err, setErr] = useState<string | null>(null)
  const { data: brands = [] } = useQuery({ queryKey: ['brands'], queryFn: fetchBrands })
  const { data, isLoading } = useQuery({
    queryKey: ['locker', brand],
    queryFn: () => fetchLockerRoom(brand),
  })

  const invalidate = () => {
    setErr(null)
    qc.invalidateQueries({ queryKey: ['locker'] })
    qc.invalidateQueries({ queryKey: ['roster'] })
    qc.invalidateQueries({ queryKey: ['brands'] })
    qc.invalidateQueries({ queryKey: ['news'] })
  }

  const ask = useMutation({ mutationFn: generateRequests, onSuccess: invalidate })
  const scan = useMutation({ mutationFn: scanTurns, onSuccess: invalidate })

  if (isLoading) return <div className="p-6 text-sm text-slate-500">Reading the room…</div>
  if (!data?.active) {
    return <div className="p-6 text-sm text-slate-500">Start a new game to see the locker room.</div>
  }

  const finals = data.requests.filter((r) => r.severity === 'final')
  const bottom = data.room.filter((r) => r.rock_bottom)

  return (
    <div className="flex-1 overflow-auto p-5">
      <div className="flex items-baseline justify-between gap-3 flex-wrap mb-1">
        <h2 className="display text-[22px]">Locker room</h2>
        <div className="flex items-center gap-1.5">
          <BrandFilter brands={brands} value={brand} onChange={setBrand} />
          <button onClick={() => ask.mutate()} disabled={ask.isPending}
            className="label text-[9px] px-2 py-1 rounded border border-edge text-slate-400 hover:border-gold/60 hover:text-gold disabled:opacity-40">
            {ask.isPending ? '…' : '🗣 Ask the room'}
          </button>
          <button onClick={() => scan.mutate()} disabled={scan.isPending}
            className="label text-[9px] px-2 py-1 rounded border border-edge text-slate-400 hover:border-gold/60 hover:text-gold disabled:opacity-40">
            {scan.isPending ? '…' : '🔄 Read the crowd'}
          </button>
        </div>
      </div>
      <p className="text-xs text-slate-500 mb-4 max-w-[720px] leading-relaxed">
        Everyone asks before she acts. A wrestler who is refused or ignored gets firmer, and at
        rock bottom ({data.rock_bottom} morale) a final trade or release demand is one she will
        carry out herself. Requests, morale and the medical room all update when the month turns.
      </p>

      {/* The two alarms that deserve to be at the top of the page. */}
      {(finals.length > 0 || bottom.length > 0) && (
        <div className="card p-3 mb-4 border-l-2" style={{ borderLeftColor: '#f87171' }}>
          <div className="label text-[9px] text-blood mb-1">Needs you now</div>
          <ul className="text-[11px] text-slate-300 space-y-0.5">
            {finals.map((r) => (
              <li key={r.id}>
                <span className="text-blood">●</span> {r.name} is on her final ask for{' '}
                {r.label.toLowerCase()}.
              </li>
            ))}
            {bottom.filter((b) => !finals.some((f) => f.wrestler_id === b.wrestler_id))
              .map((b) => (
                <li key={b.wrestler_id}>
                  <span className="text-blood">●</span> {b.name} is at rock bottom (morale{' '}
                  {b.morale}) — {b.headline}
                </li>
              ))}
          </ul>
        </div>
      )}

      {err && <p className="text-[11px] text-blood mb-3 bg-blood/10 border border-blood/30 rounded px-2 py-1.5">{err}</p>}

      <div className="grid grid-cols-1 xl:grid-cols-[1.25fr_1fr] gap-5">
        <div className="space-y-5 min-w-0">
          <Requests reqs={data.requests} onDone={invalidate} onErr={setErr} />
          <Turns turns={data.turns} onDone={invalidate} onErr={setErr} />
          <Room room={data.room} />
        </div>
        <div className="space-y-5 min-w-0">
          <Medical med={data.medical} onDone={invalidate} onErr={setErr} />
          <Forced forced={data.forced} />
          <History rows={data.history} onDone={invalidate} onErr={setErr} />
        </div>
      </div>
    </div>
  )
}

function BrandFilter({ brands, value, onChange }: {
  brands: { brand_id: string; name: string }[]
  value?: string; onChange: (v: string | undefined) => void
}) {
  return (
    <select value={value ?? ''} onChange={(e) => onChange(e.target.value || undefined)}
      className="bg-canvas border border-edge rounded px-2 py-1 text-[11px]">
      <option value="">Both brands</option>
      {brands.map((b) => <option key={b.brand_id} value={b.brand_id}>{b.name}</option>)}
    </select>
  )
}

function Section({ title, note, count, children }: {
  title: string; note?: string; count?: number; children: React.ReactNode
}) {
  return (
    <section>
      <div className="flex items-baseline gap-2 mb-2">
        <h3 className="label text-[11px] text-slate-400 tracking-wider">{title}</h3>
        {count !== undefined && count > 0 && (
          <span className="stat text-[11px] text-gold">{count}</span>
        )}
      </div>
      {note && <p className="text-[10px] text-slate-600 mb-2 leading-snug">{note}</p>}
      {children}
    </section>
  )
}

// ---------------------------------------------------------------- requests

function Requests({ reqs, onDone, onErr }: {
  reqs: WrestlerRequest[]; onDone: () => void; onErr: (s: string) => void
}) {
  return (
    <Section title="In your in-tray" count={reqs.length}
      note="Granting costs something real. Refusing costs goodwill, and it costs more each time she has to ask.">
      {reqs.length === 0
        ? <p className="text-xs text-slate-600">Nobody is asking for anything. Enjoy it.</p>
        : <div className="space-y-2">
            {reqs.map((r) => <RequestCard key={r.id} r={r} onDone={onDone} onErr={onErr} />)}
          </div>}
    </Section>
  )
}

function RequestCard({ r, onDone, onErr }: {
  r: WrestlerRequest; onDone: () => void; onErr: (s: string) => void
}) {
  const sev = SEVERITY_STYLE[r.severity] ?? SEVERITY_STYLE.ask
  const [counter, setCounter] = useState<number | ''>('')
  const resolve = useMutation({
    mutationFn: (v: { grant: boolean; counter?: number }) =>
      resolveRequest(r.id, v.grant, v.counter),
    onSuccess: onDone,
    onError: (e: Error) => onErr(e.message),
  })
  const busy = resolve.isPending

  return (
    <div className="card p-3" style={{ borderLeft: `2px solid ${sev.fg}` }}>
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium truncate">{r.icon} {r.name}</span>
            <span className="label text-[8px] px-1.5 py-[2px] rounded"
              style={{ background: sev.bg, color: sev.fg }}>{sev.label}</span>
            {r.times_asked > 1 && (
              <span className="text-[9px] text-slate-600">asked {r.times_asked}×</span>
            )}
          </div>
          <div className="text-[10px] text-slate-500 mt-0.5">
            wants {r.label.toLowerCase()} · morale{' '}
            <span style={{ color: moodColour(r.morale) }}>{r.morale} ({r.band})</span>
            {' '}· stamina {r.stamina}%
          </div>
        </div>
      </div>

      <p className="text-[11px] text-slate-300 leading-snug">{r.reason}</p>
      {r.detail && (
        <p className="text-[10px] mt-1 leading-snug"
          style={{ color: r.severity === 'final' ? '#f87171' : '#64748b' }}>
          {r.detail}
        </p>
      )}

      {/* A raise can be met part-way. Everything else is yes or no. */}
      {r.kind === 'raise' && r.ask_value && (
        <div className="flex items-center gap-1.5 mt-2">
          <span className="text-[10px] text-slate-600 shrink-0">counter</span>
          <input type="number" value={counter}
            onChange={(e) => setCounter(e.target.value === '' ? '' : Number(e.target.value))}
            placeholder={String(r.ask_value)}
            className="w-28 bg-canvas border border-edge rounded px-2 py-1 text-[11px] tnum" />
          <span className="text-[9px] text-slate-600">she asked {money(r.ask_value)}</span>
        </div>
      )}

      <div className="flex items-center gap-1.5 mt-2">
        <button disabled={busy}
          onClick={() => resolve.mutate({ grant: true, counter: counter === '' ? undefined : counter })}
          className="text-[11px] px-3 py-1 rounded bg-emerald-500/20 border border-emerald-400/40 text-emerald-300 hover:bg-emerald-500/30 disabled:opacity-40">
          {busy ? '…' : counter !== '' ? 'Grant at my number' : 'Grant'}
        </button>
        <button disabled={busy} onClick={() => resolve.mutate({ grant: false })}
          className="text-[11px] px-3 py-1 rounded border border-edge text-slate-400 hover:border-blood/60 hover:text-blood disabled:opacity-40">
          Turn her down
        </button>
        {r.can_force && (
          <span className="text-[9px] text-blood ml-auto">she can force this</span>
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------- turns

function Turns({ turns, onDone, onErr }: {
  turns: TurnSuggestion[]; onDone: () => void; onErr: (s: string) => void
}) {
  return (
    <Section title="Turns the crowd is asking for" count={turns.length}
      note="Nothing turns until you approve it. A heel the crowd cheers anyway is the classic case — the reaction is measured separately from the match quality, which is what makes it detectable.">
      {turns.length === 0
        ? <p className="text-xs text-slate-600">The crowd is reacting to everyone the way it should.</p>
        : <div className="space-y-2">
            {turns.map((t) => <TurnCard key={t.id} t={t} onDone={onDone} onErr={onErr} />)}
          </div>}
    </Section>
  )
}

function TurnCard({ t, onDone, onErr }: {
  t: TurnSuggestion; onDone: () => void; onErr: (s: string) => void
}) {
  const resolve = useMutation({
    mutationFn: (approve: boolean) => resolveTurn(t.id, approve),
    onSuccess: onDone,
    onError: (e: Error) => onErr(e.message),
  })
  const arrow = (a: string) => (a === 'heel' ? '▼ heel' : '▲ face')
  return (
    <div className="card p-3 border-l-2" style={{ borderLeftColor: '#a78bfa' }}>
      <div className="flex items-center gap-2 flex-wrap mb-1">
        <span className="text-sm font-medium">{t.name}</span>
        <span className="text-[11px] text-slate-500">
          {arrow(t.from_align)} → <span className="text-slate-200">{arrow(t.to_align)}</span>
        </span>
        <span className="label text-[8px] px-1.5 py-[2px] rounded bg-raised text-slate-400">
          {t.trigger_label}
        </span>
      </div>
      <p className="text-[11px] text-slate-300 leading-snug">{t.reason}</p>
      {t.evidence && <p className="text-[10px] text-slate-600 mt-1">{t.evidence}</p>}
      <div className="flex items-center gap-1.5 mt-2">
        <button disabled={resolve.isPending} onClick={() => resolve.mutate(true)}
          className="text-[11px] px-3 py-1 rounded bg-violet-500/20 border border-violet-400/40 text-violet-200 hover:bg-violet-500/30 disabled:opacity-40">
          Turn her
        </button>
        <button disabled={resolve.isPending} onClick={() => resolve.mutate(false)}
          className="text-[11px] px-3 py-1 rounded border border-edge text-slate-400 hover:text-slate-200 disabled:opacity-40">
          Leave her as she is
        </button>
      </div>
    </div>
  )
}

// -------------------------------------------------------------------- room

function Room({ room }: { room: MoraleSnapshot[] }) {
  const [open, setOpen] = useState<number | null>(null)
  const unhappy = useMemo(() => room.filter((r) => r.morale < 52), [room])
  const [showAll, setShowAll] = useState(false)
  const shown = showAll ? room : unhappy

  return (
    <Section title="The room" count={unhappy.length}
      note="Unhappiest first. Every wrestler's mood is the sum of standing conditions — pay, booking, spotlight, promises — and each one has a fix.">
      <div className="flex items-center gap-2 mb-2">
        <button onClick={() => setShowAll(false)}
          className={`label text-[9px] px-2 py-1 rounded border ${!showAll ? 'border-gold text-gold bg-gold/10' : 'border-edge text-slate-500'}`}>
          Unhappy ({unhappy.length})
        </button>
        <button onClick={() => setShowAll(true)}
          className={`label text-[9px] px-2 py-1 rounded border ${showAll ? 'border-gold text-gold bg-gold/10' : 'border-edge text-slate-500'}`}>
          Everyone ({room.length})
        </button>
      </div>
      {shown.length === 0
        ? <p className="text-xs text-slate-600">Nobody is unhappy. This will not last.</p>
        : <div className="space-y-1">
            {shown.map((r) => (
              <div key={r.wrestler_id} className="card p-2.5">
                <button onClick={() => setOpen(open === r.wrestler_id ? null : r.wrestler_id)}
                  className="w-full text-left">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[13px] truncate">{r.name}</span>
                    <span className="flex items-center gap-2 shrink-0">
                      <Drift v={r.monthly_drift} />
                      <span className="stat text-[13px]" style={{ color: moodColour(r.morale) }}>
                        {r.morale}
                      </span>
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-2 mt-0.5">
                    <span className="text-[10px] text-slate-600 truncate">{r.headline}</span>
                    <span className="label text-[8px] shrink-0" style={{ color: moodColour(r.morale) }}>
                      {r.band}
                    </span>
                  </div>
                </button>
                {open === r.wrestler_id && <MoraleDetail s={r} />}
              </div>
            ))}
          </div>}
    </Section>
  )
}

function Drift({ v }: { v: number }) {
  if (!v) return <span className="text-[10px] text-slate-600">—</span>
  const up = v > 0
  return (
    <span className="text-[10px] tnum" style={{ color: up ? '#34d399' : '#f87171' }}
      title="Where her morale is heading each month">
      {up ? '▲' : '▼'}{Math.abs(v).toFixed(1)}/mo
    </span>
  )
}

function MoraleDetail({ s }: { s: MoraleSnapshot }) {
  return (
    <div className="mt-2 pt-2 border-t border-edge-soft space-y-1.5">
      {s.pay.under_contract && (
        <div className="flex items-baseline justify-between gap-2 text-[11px]">
          <span className="text-slate-500">Pay</span>
          <span className="tnum text-slate-300">
            {money(s.pay.salary!)} vs {money(s.pay.market!)} market
            <span className="ml-1" style={{
              color: (s.pay.ratio ?? 1) >= 1 ? '#34d399' : '#f87171',
            }}>
              ({((s.pay.ratio ?? 1) * 100).toFixed(0)}%)
            </span>
          </span>
        </div>
      )}
      {s.factors.map((f) => (
        <div key={f.key} className="text-[10px] leading-snug">
          <div className="flex items-baseline justify-between gap-2">
            <span className="label text-[8px] text-slate-500">{f.label}</span>
            <span className="tnum shrink-0" style={{ color: f.delta >= 0 ? '#34d399' : '#f87171' }}>
              {f.delta >= 0 ? '+' : ''}{f.delta}
            </span>
          </div>
          <p className="text-slate-400">{f.detail}</p>
          {f.fix && <p className="text-gold/80">→ {f.fix}</p>}
        </div>
      ))}
      <p className="text-[9px] text-slate-600 pt-1">
        {s.personality_label} · she feels these differently from the next woman.
      </p>
    </div>
  )
}

// ----------------------------------------------------------------- medical

function Medical({ med, onDone, onErr }: {
  med: { out: MedicalRow[]; resting: MedicalRow[]; at_risk: MedicalRow[]; returning: MedicalRow[] }
  onDone: () => void; onErr: (s: string) => void
}) {
  const rest = useMutation({
    mutationFn: (v: { wid: number; weeks: number }) => restWrestler(v.wid, v.weeks),
    onSuccess: onDone, onError: (e: Error) => onErr(e.message),
  })
  const unrest = useMutation({
    mutationFn: (wid: number) => clearRest(wid),
    onSuccess: onDone, onError: (e: Error) => onErr(e.message),
  })
  const total = med.out.length + med.resting.length + med.at_risk.length

  return (
    <Section title="Medical room" count={total}
      note="Resting somebody is a decision that recovers her faster than forgetting about her — and she stays unbookable while it lasts.">
      {total === 0 && med.returning.length === 0
        ? <p className="text-xs text-slate-600">Everybody is fit and fresh.</p>
        : <div className="space-y-3">
            {med.out.length > 0 && (
              <Group label="Injured" colour="#f87171">
                {med.out.map((m) => (
                  <Row key={m.wrestler_id} name={m.name}
                    right={`${m.weeks_left}w left`}
                    detail={m.injury_note ?? 'injured'} />
                ))}
              </Group>
            )}
            {med.resting.length > 0 && (
              <Group label="Resting (you granted it)" colour="#38bdf8">
                {med.resting.map((m) => (
                  <Row key={m.wrestler_id} name={m.name}
                    right={`${m.weeks_left}w left`}
                    detail={`stamina ${m.stamina}%`}
                    action={
                      <button onClick={() => unrest.mutate(m.wrestler_id)}
                        className="text-[9px] text-slate-500 hover:text-blood">
                        call her back
                      </button>
                    } />
                ))}
              </Group>
            )}
            {med.at_risk.length > 0 && (
              <Group label="Should not be booked" colour="#fb923c">
                {med.at_risk.map((m) => (
                  <Row key={m.wrestler_id} name={m.name}
                    right={m.level}
                    detail={m.reasons.join(', ') || `stamina ${m.stamina}%`}
                    action={
                      <button onClick={() => rest.mutate({ wid: m.wrestler_id, weeks: 2 })}
                        className="text-[9px] text-gold hover:underline">
                        rest 2 weeks
                      </button>
                    } />
                ))}
              </Group>
            )}
            {med.returning.length > 0 && (
              <Group label="Just back — fragile" colour="#a78bfa">
                {med.returning.map((m) => (
                  <Row key={m.wrestler_id} name={m.name} right=""
                    detail={m.injury_note ?? 'recently injured'} />
                ))}
              </Group>
            )}
          </div>}
    </Section>
  )
}

function Group({ label, colour, children }: {
  label: string; colour: string; children: React.ReactNode
}) {
  return (
    <div>
      <div className="label text-[8px] mb-1" style={{ color: colour }}>{label}</div>
      <div className="space-y-1">{children}</div>
    </div>
  )
}

function Row({ name, right, detail, action }: {
  name: string; right: string; detail: string; action?: React.ReactNode
}) {
  return (
    <div className="card p-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[12px] truncate">{name}</span>
        <span className="label text-[9px] text-slate-500 shrink-0">{right}</span>
      </div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[10px] text-slate-600 truncate">{detail}</span>
        {action}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ forced

function Forced({ forced }: { forced: { id: number; name: string; kind: string; from_brand: string | null; to_brand: string | null; on_date: string; reason: string }[] }) {
  if (!forced.length) return null
  return (
    <Section title="Taken out of your hands" count={forced.length}
      note="Moves a wrestler made herself after asking three times and being refused.">
      <div className="space-y-1">
        {forced.map((f) => (
          <div key={f.id} className="card p-2 border-l-2" style={{ borderLeftColor: '#f87171' }}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[12px]">{f.name}</span>
              <span className="label text-[8px] text-blood">
                {f.kind === 'walkout' ? 'WALKED OUT' : 'FORCED TRADE'}
              </span>
            </div>
            <div className="text-[10px] text-slate-500">
              {f.on_date} · {f.from_brand}{f.to_brand ? ` → ${f.to_brand}` : ' → gone'}
            </div>
            <div className="text-[10px] text-slate-600">{f.reason}</div>
          </div>
        ))}
      </div>
    </Section>
  )
}

// ----------------------------------------------------------------- history

function History({ rows, onDone, onErr }: {
  rows: (WrestlerRequest & { resolved_on: string; can_undo?: boolean; undo_note?: string })[]
  onDone: () => void; onErr: (s: string) => void
}) {
  if (!rows.length) return null
  const style = (s: string) =>
    s === 'granted' ? '#34d399' : s === 'denied' ? '#f87171' : '#64748b'
  return (
    <Section title="What you decided"
      note="The record the room remembers. A grant can be taken back — she goes straight back to asking.">
      <div className="space-y-0.5">
        {rows.map((r) => <HistoryRow key={r.id} r={r} colour={style(r.status)}
          onDone={onDone} onErr={onErr} />)}
      </div>
    </Section>
  )
}

function HistoryRow({ r, colour, onDone, onErr }: {
  r: WrestlerRequest & { can_undo?: boolean; undo_note?: string }
  colour: string; onDone: () => void; onErr: (s: string) => void
}) {
  const undo = useMutation({
    mutationFn: () => undoRequest(r.id),
    onSuccess: onDone,
    onError: (e: Error) => onErr(e.message),
  })
  return (
    <div className="flex items-baseline justify-between gap-2 text-[11px] px-1 py-0.5">
      <span className="truncate text-slate-400">
        {r.name} — {(r.label ?? r.kind).toLowerCase()}
      </span>
      <span className="flex items-baseline gap-1.5 shrink-0">
        {r.can_undo && (
          <button disabled={undo.isPending} onClick={() => undo.mutate()}
            title="Put the change back. She will be asking again."
            className="text-[9px] text-slate-500 hover:text-gold disabled:opacity-40">
            {undo.isPending ? '…' : '↩ undo'}
          </button>
        )}
        <span className="label text-[8px]" style={{ color: colour }}>{r.status}</span>
      </span>
    </div>
  )
}
