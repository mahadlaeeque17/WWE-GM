import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchBookable, fetchBookingCatalogue, runCard, fetchRoster,
  imageUrl, type CardMatch, type BrandFinance, type Calendar,
} from './api'
import { BrandCrest, PPVBadge, Logo } from './emblems'
import { usePhotos } from './prefs'

type Row = { a: number; b: number; title: number; m1: number; m2: number; stip: string }
const emptyRow = (): Row => ({ a: 0, b: 0, title: 0, m1: 0, m2: 0, stip: 'normal' })
const SLOT = (i: number, n: number) => (i === 0 ? 'OPENER' : i === n - 1 ? 'MAIN EVENT' : 'MID CARD')

export default function BookingScreen({
  brandId, brand, calendar, onBooked,
}: { brandId: string; brand?: BrandFinance; calendar?: Calendar; onBooked: (showId?: number) => void }) {
  const qc = useQueryClient()
  const photos = usePhotos()
  const { data: bookable } = useQuery({ queryKey: ['bookable', brandId], queryFn: () => fetchBookable(brandId) })
  const { data: cat } = useQuery({ queryKey: ['bookcat'], queryFn: fetchBookingCatalogue })
  const { data: roster = [] } = useQuery({ queryKey: ['roster'], queryFn: fetchRoster })

  const [rows, setRows] = useState<Row[]>([emptyRow(), emptyRow(), emptyRow()])
  const [isPPV, setIsPPV] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const mgrTitleId = bookable?.titles.find((t) => t.tier === 'manager')?.id ?? 0
  const managers = bookable?.managers ?? []
  const healthy = (bookable?.wrestlers ?? []).filter((w) => w.healthy)
  const imgOf = useMemo(() => {
    const m = new Map<number, number | null>()
    for (const r of roster) m.set(r.id, r.profile_image_id)
    return m
  }, [roster])
  const used = useMemo(() => {
    const s = new Set<number>()
    for (const r of rows) { if (r.a) s.add(r.a); if (r.b) s.add(r.b) }
    return s
  }, [rows])

  const stipLabel = (key: string) => cat?.stipulations.find((s) => s.key === key)?.label ?? key

  const card: CardMatch[] = useMemo(() => rows
    .filter((r) => r.a && r.b && r.a !== r.b)
    .map((r) => ({
      teams: [[r.a], [r.b]],
      title_id: r.title || null,
      stipulation: r.stip,
      ...(r.title === mgrTitleId && mgrTitleId ? { managers: [r.m1, r.m2] } : {}),
    })), [rows, mgrTitleId])

  const setRow = (i: number, patch: Partial<Row>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))

  const confirm = useMutation({
    mutationFn: () => {
      if (!card.length) throw new Error('Book at least one match with two different wrestlers.')
      for (const m of card) {
        if (m.title_id === mgrTitleId && mgrTitleId) {
          const [x, y] = m.managers ?? []
          if (!x || !y || x === y) throw new Error("Assign two different managers to the Manager's Championship match.")
        }
      }
      const ppvName = calendar?.ppv ?? undefined
      const asPPV = isPPV && !!ppvName
      const nm = asPPV ? ppvName! : `${brand?.name} · Week`
      // No logistics — venue/production removed; a straight card run.
      return runCard(brandId, nm, card, asPPV, asPPV ? ppvName : undefined)
    },
    onSuccess: (r) => { setErr(null); onBooked(r.show_id); setRows([emptyRow(), emptyRow(), emptyRow()]); setIsPPV(false); qc.invalidateQueries() },
    onError: (e: Error) => setErr(e.message),
  })

  const canConfirm = card.length > 0 && !confirm.isPending

  return (
    <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[1.4fr_0.7fr] gap-4 p-4 overflow-auto">
      {/* ============ MATCH CARD ============ */}
      <div className="flex flex-col min-h-0">
        <ColHead>Match Card</ColHead>
        <div className="space-y-2 overflow-auto pr-1">
          {rows.map((r, i) => (
            <div key={i} className="card p-3 pop-in" style={{ animationDelay: `${i * 60}ms` }}>
              <div className="flex items-center justify-between mb-2">
                <span className="label text-[9px] text-gold">{SLOT(i, rows.length)}</span>
                {r.stip !== 'normal' && <span className="label text-[8px] px-1.5 py-[2px] rounded bg-gold/15 text-gold">{stipLabel(r.stip)}</span>}
              </div>
              <div className="flex items-center gap-2">
                <Fighter id={r.a} imgOf={imgOf} photos={photos} name={healthy.find((w) => w.id === r.a)?.name} />
                <div className="flex-1 space-y-1.5">
                  <WSelect value={r.a} self={r.a} exclude={used} options={healthy} onChange={(v) => setRow(i, { a: v })} />
                  <div className="text-center text-[9px] text-slate-600 label">vs</div>
                  <WSelect value={r.b} self={r.b} exclude={used} options={healthy} onChange={(v) => setRow(i, { b: v })} />
                </div>
                <Fighter id={r.b} imgOf={imgOf} photos={photos} name={healthy.find((w) => w.id === r.b)?.name} />
              </div>
              <div className="grid grid-cols-2 gap-1.5 mt-2">
                <select value={r.stip} onChange={(e) => setRow(i, { stip: e.target.value })}
                  className="bg-canvas border border-edge rounded px-2 py-1 text-[11px]">
                  {(cat?.stipulations ?? []).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                </select>
                <select value={r.title} onChange={(e) => setRow(i, { title: Number(e.target.value) })}
                  className="bg-canvas border border-edge rounded px-2 py-1 text-[11px] text-slate-300">
                  <option value={0}>No title</option>
                  {(bookable?.titles ?? []).map((t) => <option key={t.id} value={t.id}>◆ {t.short_name ?? t.name}</option>)}
                </select>
              </div>
              {r.title === mgrTitleId && mgrTitleId > 0 && (
                managers.length < 2
                  ? <p className="text-[10px] text-orange-400 mt-1.5">Needs two signed managers.</p>
                  : <div className="flex items-center gap-1.5 mt-1.5">
                      <MSelect value={r.m1} exclude={r.m2} options={managers} onChange={(v) => setRow(i, { m1: v })} />
                      <span className="text-[9px] text-slate-600">vs</span>
                      <MSelect value={r.m2} exclude={r.m1} options={managers} onChange={(v) => setRow(i, { m2: v })} />
                    </div>
              )}
              {rows.length > 1 && (
                <button onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}
                  className="text-[10px] text-slate-600 hover:text-blood mt-1.5">remove</button>
              )}
            </div>
          ))}
          <button onClick={() => setRows((rs) => [...rs, emptyRow()])}
            className="w-full text-xs py-2 rounded border border-dashed border-edge hover:border-gold/60 text-slate-400">
            + Add match
          </button>
        </div>
      </div>

      {/* ============ FINAL BOOKING ============ */}
      <div className="flex flex-col min-h-0">
        <ColHead>Final Booking</ColHead>
        <div className="card p-5 text-center relative overflow-hidden champ-glow">
          <div className="grid place-items-center py-2">
            <Logo keyName={brandId.toLowerCase()} size={photos ? 84 : 52} fallback={<BrandCrest brand={brandId} size={68} />} />
          </div>
          <div className="display text-[22px] leading-none mt-1" style={{ color: brand?.colour }}>{brand?.name}</div>
          <div className="text-[11px] text-slate-500 mt-1 flex items-center justify-center gap-1.5">
            {isPPV && calendar?.ppv ? <><PPVBadge size={16} finale={calendar.is_finale} /> {calendar.ppv}</> : <>{calendar?.month_name} {calendar?.season_year}</>}
          </div>
          {calendar?.ppv && (
            <label className="flex items-center justify-center gap-1.5 mt-2 text-[11px] text-slate-400 cursor-pointer">
              <input type="checkbox" checked={isPPV} onChange={(e) => setIsPPV(e.target.checked)} className="accent-[var(--color-gold)]" />
              Run as the {calendar.ppv.split(' ')[0]} pay-per-view
            </label>
          )}

          <div className="mt-3 pt-3 border-t border-edge-soft flex items-center justify-between text-sm">
            <span className="label text-[9px] text-slate-500">Matches booked</span>
            <span className="stat text-gold text-xl">{card.length}</span>
          </div>
          <p className="text-[10px] text-slate-600 mt-2 leading-snug">The last match is the main event and counts double.</p>

          {err && <p className="text-[11px] text-blood mt-2">{err}</p>}

          <button onClick={() => confirm.mutate()} disabled={!canConfirm}
            className="w-full mt-3 py-2.5 rounded font-bold text-black disabled:opacity-30 disabled:cursor-not-allowed"
            style={{ background: canConfirm ? 'var(--color-gold)' : '#444' }}>
            {confirm.isPending ? 'Running…' : 'CONFIRM BOOKING'}
          </button>
          {healthy.length < 2 && <p className="text-[11px] text-orange-400 mt-2">This brand needs 2 healthy signed wrestlers.</p>}
        </div>
      </div>
    </div>
  )
}

function ColHead({ children }: { children: React.ReactNode }) {
  return <h3 className="label text-[11px] text-slate-400 mb-2 tracking-wider">{children}</h3>
}
function Fighter({ id, imgOf, photos, name }: { id: number; imgOf: Map<number, number | null>; photos: boolean; name?: string }) {
  const img = id ? imgOf.get(id) : null
  if (photos && img) return <img src={imageUrl(img)} alt={name} title={name} className="w-11 h-14 rounded object-cover portrait border border-edge shrink-0" />
  const initials = name ? name.split(/\s+/).slice(0, 2).map((w) => w[0]).join('') : '—'
  return <div className="w-11 h-14 rounded grid place-items-center bg-raised border border-edge text-slate-600 label text-[10px] shrink-0">{initials}</div>
}
function WSelect({ value, onChange, options, exclude, self }: {
  value: number; onChange: (v: number) => void; self: number
  options: { id: number; name: string; overall: number }[]; exclude: Set<number>
}) {
  return (
    <select value={value} onChange={(e) => onChange(Number(e.target.value))}
      className="w-full bg-canvas border border-edge rounded px-2 py-1 text-[12px]">
      <option value={0}>— pick —</option>
      {options.map((w) => <option key={w.id} value={w.id} disabled={exclude.has(w.id) && w.id !== self}>{w.name} ({w.overall})</option>)}
    </select>
  )
}
function MSelect({ value, onChange, options, exclude }: {
  value: number; onChange: (v: number) => void; exclude: number; options: { id: number; name: string }[]
}) {
  return (
    <select value={value} onChange={(e) => onChange(Number(e.target.value))}
      className="flex-1 min-w-0 bg-canvas border border-gold/40 rounded px-2 py-1 text-[11px]">
      <option value={0}>— manager —</option>
      {options.map((m) => <option key={m.id} value={m.id} disabled={m.id === exclude}>{m.name}</option>)}
    </select>
  )
}
