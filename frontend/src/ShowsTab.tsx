import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchShows, fetchShow, fetchBrands, fetchCalendar, runShow,
  aiCommentary, aiRecap, aiRivalBook, imageUrl, type RosterRow,
} from './api'
import { Stars } from './ui'
import { REACTION_COLOUR, reviseWinner, reviseStars, FINISHES } from './api'
import RumblePanel from './RumblePanel'
import CalendarView from './CalendarView'
import BookingScreen from './BookingScreen'
import { playShow } from './sound'
import { usePhotos } from './prefs'

function qualityColour(q: number | null): string {
  if (q === null) return 'text-slate-500'
  if (q >= 75) return 'text-emerald-400'
  if (q >= 55) return 'text-gold'
  if (q >= 40) return 'text-orange-400'
  return 'text-blood'
}

type Mode = 'auto' | 'manual' | 'ai'

export default function ShowsTab({ roster }: { roster: RosterRow[] }) {
  const qc = useQueryClient()
  const { data: shows = [] } = useQuery({ queryKey: ['shows'], queryFn: fetchShows })
  const { data: brands = [] } = useQuery({ queryKey: ['brands'], queryFn: fetchBrands })
  const { data: calendar } = useQuery({ queryKey: ['calendar'], queryFn: fetchCalendar })

  const [brandId, setBrandId] = useState('RAW')
  const [mode, setMode] = useState<Mode>('auto')
  const [matches, setMatches] = useState(4)
  const [open, setOpen] = useState<number | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const brand = brands.find((b) => b.brand_id === brandId)
  const { data: detail } = useQuery({
    queryKey: ['show', open],
    queryFn: () => fetchShow(open!),
    enabled: open !== null,
  })

  const invalidate = (id?: number) => {
    if (id) { setOpen(id); playShow() }
    qc.invalidateQueries({ queryKey: ['shows'] })
    qc.invalidateQueries({ queryKey: ['roster'] })
    qc.invalidateQueries({ queryKey: ['titles'] })
    qc.invalidateQueries({ queryKey: ['brands'] })
    qc.invalidateQueries({ queryKey: ['bookable'] })
  }

  const nextNumber = (b: string) => shows.filter((s) => s.brand_id === b).length + 1

  const runAuto = useMutation({
    mutationFn: () => runShow(brandId, `${brand?.name} #${nextNumber(brandId)}`, matches,
                              false, undefined, 'tv'),
    onSuccess: (r) => { setErr(null); invalidate(r.show_id) },
    onError: (e: Error) => setErr(e.message),
  })

  const runAI = useMutation({
    mutationFn: () => aiRivalBook(brandId, matches, true, `${brand?.name} #${nextNumber(brandId)}`),
    onSuccess: (r) => { setErr(null); invalidate(r.show?.show_id) },
    onError: (e: Error) => setErr(e.message),
  })

  // A pay-per-view is a six-match co-branded card whether it is auto-booked or
  // hand-booked, so the count comes from the format rather than the picker.
  const runPPV = useMutation({
    mutationFn: () => runShow(brandId, calendar!.ppv!, 6, true, calendar!.ppv!, 'ppv'),
    onSuccess: (r) => { setErr(null); invalidate(r.show_id) },
    onError: (e: Error) => setErr(e.message),
  })

  const busy = runAuto.isPending || runAI.isPending || runPPV.isPending

  return (
    <div className="flex-1 flex min-h-0">
      {/* ---------------- booking + show list ---------------- */}
      <div className="w-[420px] shrink-0 border-r border-edge overflow-auto">
        <div className="p-4 border-b border-edge">
          {/* this month's PPV (auto/AI — manual PPVs are booked on the card screen) */}
          {calendar?.active && calendar.ppv && mode !== 'manual' && (
            <div className="mb-3 rounded border border-gold/40 bg-gold/10 p-2.5">
              <div className="label text-[9px] text-gold">◆ {calendar.month_name} pay-per-view</div>
              <div className="flex items-center justify-between gap-2 mt-1">
                <span className="display text-[16px] text-slate-100 leading-none">{calendar.ppv}</span>
                <button onClick={() => runPPV.mutate()} disabled={busy}
                  className="text-xs px-3 py-1.5 rounded bg-gold text-black font-semibold disabled:opacity-40">
                  {runPPV.isPending ? 'Running…' : 'Run PPV (auto)'}
                </button>
              </div>
              <p className="text-[10px] text-slate-500 mt-1">Big-stage bonus to quality, prestige and the gate.</p>
            </div>
          )}
          {/* brand */}
          <div className="flex gap-2 mb-3">
            {brands.map((b) => (
              <button
                key={b.brand_id}
                onClick={() => setBrandId(b.brand_id)}
                className="flex-1 text-xs py-1.5 rounded font-semibold transition-all"
                style={brandId === b.brand_id
                  ? { background: b.colour, color: '#000', boxShadow: `0 0 16px ${b.colour}55` }
                  : { color: b.colour, background: `${b.colour}18` }}
              >
                {b.name}
              </button>
            ))}
          </div>

          {/* mode */}
          <div className="flex gap-1 mb-3">
            {([['auto', 'Auto-book'], ['manual', 'Book it myself'], ['ai', 'AI GM books']] as const).map(
              ([m, label]) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className={`flex-1 label text-[10px] px-2 py-1.5 rounded ${
                    mode === m ? 'bg-gold text-black' : 'text-slate-400 hover:text-slate-100 hover:bg-panel'}`}
                >
                  {label}
                </button>
              ),
            )}
          </div>

          {mode === 'auto' && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <label className="text-xs text-slate-500">Matches</label>
                <select value={matches} onChange={(e) => setMatches(Number(e.target.value))}
                  className="bg-panel border border-edge rounded px-2 py-1 text-sm">
                  {[2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </div>
              <button onClick={() => runAuto.mutate()} disabled={busy}
                className="w-full text-sm py-2 rounded font-semibold text-black disabled:opacity-40"
                style={{ background: brand?.colour }}>
                {runAuto.isPending ? 'Running…' : `▶ Run ${brand?.name}`}
              </button>
              <p className="text-[11px] text-slate-600 mt-2 leading-snug">
                Pre-booked the same way the card screen suggests: rivalries first, the belt on the
                main event, face against heel — plus two promo segments.
              </p>
            </div>
          )}

          {mode === 'manual' && (
            <p className="text-[11px] text-slate-500 leading-snug">
              The card on the right arrives PRE-BOOKED — four matches and two promos, six matches on
              a pay-per-view. Change anything you disagree with, then hit Confirm Booking.
            </p>
          )}

          {mode === 'ai' && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <label className="text-xs text-slate-500">Matches</label>
                <select value={matches} onChange={(e) => setMatches(Number(e.target.value))}
                  className="bg-panel border border-edge rounded px-2 py-1 text-sm">
                  {[2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </div>
              <button onClick={() => runAI.mutate()} disabled={busy}
                className="w-full text-sm py-2 rounded font-semibold text-black disabled:opacity-40"
                style={{ background: brand?.colour }}>
                {runAI.isPending ? 'The GM is booking…' : '🤖 Let the AI GM book & run'}
              </button>
              {runAI.data?.reasoning && (
                <p className="text-[11px] text-slate-400 mt-2 italic leading-snug">"{runAI.data.reasoning}"</p>
              )}
              <p className="text-[11px] text-slate-600 mt-2 leading-snug">
                The AI books the matchups; the sim still decides who wins — so results stay reproducible.
              </p>
            </div>
          )}

          {err && <p className="text-xs text-blood mt-2 bg-blood/10 border border-blood/30 rounded px-2 py-1.5">{err}</p>}
        </div>

        {shows.length === 0 && <p className="p-4 text-sm text-slate-500">No shows yet. Book one above.</p>}
        {shows.map((s) => {
          const c = brands.find((b) => b.brand_id === s.brand_id)?.colour
          return (
            <button key={s.id} onClick={() => setOpen(s.id)}
              className={`w-full text-left px-4 py-2.5 border-b border-edge/50 transition-colors
                          ${open === s.id ? 'bg-gold/10' : 'hover:bg-panel'}`}
              style={open === s.id ? undefined : c ? { boxShadow: `inset 3px 0 0 ${c}` } : undefined}>
              <div className="flex justify-between items-baseline">
                <span className="text-sm font-medium flex items-center gap-1.5">
                  {s.is_ppv ? <span className="text-gold text-[10px]">◆</span> : null}{s.name}
                </span>
                <span className={`text-sm font-bold tnum ${qualityColour(s.rating)}`}>
                  {s.rating?.toFixed(1) ?? '—'}
                </span>
              </div>
              <div className="text-[11px] text-slate-500">
                {s.held_on} · {s.matches} matches
                {s.promos ? ` · ${s.promos} promos` : ''}
                {s.tv_rating != null ? ` · 📺 ${s.tv_rating.toFixed(2)}` : ''}
                {s.buyrate != null ? ` · 💸 ${s.buyrate.toFixed(2)}` : ''}
                {s.attendance ? ` · ${s.attendance.toLocaleString()} in` : ''}
              </div>
            </button>
          )
        })}
      </div>

      {/* ---------------- booking screen / show detail / calendar ---------------- */}
      {mode === 'manual' ? (
        <BookingScreen brandId={brandId} brand={brand} calendar={calendar}
          onBooked={(id) => invalidate(id)} />
      ) : (
      <div className="flex-1 overflow-auto p-6">
        {!detail && (
          <div className="max-w-[560px]">
            <h2 className="display text-[20px] mb-1">Season calendar</h2>
            <p className="text-xs text-slate-500 mb-4">
              Raw every Monday, SmackDown every Friday, two Saturday Night's Main Events a month,
              and the pay-per-view on the last Sunday. The road runs to WrestleMania in December.
            </p>
            {calendar?.active
              ? <CalendarView cal={calendar} />
              : <p className="text-sm text-slate-500">Start a new game to see the calendar.</p>}
            <p className="text-xs text-slate-600 mt-4">Pick a show on the left to see its card.</p>
          </div>
        )}
        {/* The Rumble is a show, so it lives with the shows — and it sits under
            the calendar because the calendar is where you find out it is due. */}
        {!detail && calendar?.active && (
          <div className="max-w-[860px] mt-6">
            <RumblePanel roster={roster} />
          </div>
        )}
        {detail && <ShowDetail detail={detail} onNarrated={() => qc.invalidateQueries({ queryKey: ['show', open] })} />}
      </div>
      )}
    </div>
  )
}

/** A participant's face on the show card — portrait if we have one, else initials. */
function PFace({ p, won }: { p: any; won: boolean }) {
  const photos = usePhotos()
  const ring = won ? 'ring-2 ring-emerald-400/70' : 'ring-1 ring-edge'
  if (photos && p.profile_image_id) {
    return <img src={imageUrl(p.profile_image_id)} alt={p.name} title={p.name}
      className={`w-9 h-12 rounded object-cover portrait ${ring}`} />
  }
  const initials = String(p.name).split(/\s+/).slice(0, 2).map((w: string) => w[0]).join('')
  return (
    <div title={p.name}
      className={`w-9 h-12 rounded grid place-items-center bg-raised text-slate-500 label text-[10px] ${ring}`}>
      {initials}
    </div>
  )
}

function ShowDetail({ detail, onNarrated }: { detail: any; onNarrated: () => void }) {
  const [recap, setRecap] = useState<string | null>(null)
  const recapM = useMutation({
    mutationFn: () => aiRecap(detail.id),
    onSuccess: (r) => setRecap(r.recap),
    onError: (e: Error) => setRecap(`(AI unavailable: ${e.message})`),
  })
  const commentaryM = useMutation({
    mutationFn: (matchId: number) => aiCommentary(matchId),
    onSuccess: () => onNarrated(),
  })

  return (
    <>
      <div className="flex items-baseline gap-3 mb-1">
        {detail.is_ppv ? <span className="text-gold text-xl">◆</span> : null}
        <h2 className="text-xl font-bold">{detail.name}</h2>
        <span className={`text-2xl font-bold tnum ${qualityColour(detail.rating)}`}>
          {detail.rating?.toFixed(1)}
        </span>
      </div>
      <p className="text-xs text-slate-500 mb-3 flex items-center gap-3 flex-wrap">
        <span>{detail.held_on} · {detail.attendance?.toLocaleString()} in attendance</span>
        {detail.tv_rating != null && (
          <span className="text-slate-300">
            📺 <span className="stat text-gold">{detail.tv_rating.toFixed(2)}</span> rating
          </span>
        )}
        {detail.buyrate != null && (
          <span className="text-slate-300">
            💸 <span className="stat text-gold">{detail.buyrate.toFixed(2)}</span> buyrate
          </span>
        )}
        {detail.crowd?.loudest && (
          <span className="text-slate-400">
            loudest: {detail.crowd.loudest.kind === 'promo' ? 'a promo' : `match ${detail.crowd.loudest.slot}`}
            {' '}(<span style={{ color: REACTION_COLOUR[detail.crowd.loudest.reaction ?? ''] ?? '#94a3b8' }}>
              {detail.crowd.loudest.reaction}
            </span>)
          </span>
        )}
      </p>

      <button onClick={() => recapM.mutate()} disabled={recapM.isPending}
        className="text-xs px-3 py-1.5 rounded border border-gold/40 text-gold hover:bg-gold/10 disabled:opacity-40 mb-4">
        {recapM.isPending ? 'Writing recap…' : '🤖 AI recap of the night'}
      </button>
      {recap && (
        <p className="text-sm text-slate-300 bg-panel border border-edge rounded p-3 mb-4 leading-relaxed">{recap}</p>
      )}

      <div className="space-y-3">
        {detail.matches.map((m: any, mi: number) => {
          const teams: Record<number, any[]> = {}
          for (const p of m.participants) (teams[p.team] ??= []).push(p)
          const sides = Object.values(teams)
          const isMain = m.slot === detail.matches.length
          return (
            <div key={m.id} className={`bg-panel border rounded p-3 pop-in ${m.title_id ? 'border-gold/50' : 'border-edge'}`}
              style={{ animationDelay: `${mi * 110}ms` }}>
              <div className="flex justify-between items-start">
                <div className="flex-1 min-w-0">
                  <div className="text-[10px] text-slate-600 uppercase tracking-wider mb-1 flex items-center gap-2 flex-wrap">
                    <span>{isMain ? 'Main event' : `Match ${m.slot}`}</span>
                    {m.match_type && m.match_type !== 'singles' && (
                      <span className="text-slate-300 px-1.5 py-[1px] rounded bg-raised normal-case">
                        {m.match_type_label ?? m.match_type}
                      </span>
                    )}
                    {m.stipulation && m.stipulation !== 'normal' && (
                      <span className="text-gold px-1.5 py-[1px] rounded bg-gold/15 normal-case">
                        {STIP_LABEL[m.stipulation] ?? m.stipulation}
                      </span>
                    )}
                    {m.title_id && <span className="text-gold">◆ championship</span>}
                  </div>
                  <div className="flex items-center gap-3 flex-wrap">
                    {sides.map((side, i) => {
                      const won = side.some((p: any) => p.is_winner)
                      return (
                        <div key={i} className="flex items-center gap-2">
                          {i > 0 && <span className="text-slate-600 text-xs mr-1">vs</span>}
                          <div className="flex -space-x-2">
                            {side.map((p: any) => <PFace key={p.wrestler_id} p={p} won={won} />)}
                          </div>
                          <span className={`text-sm ${won ? 'text-emerald-400 font-semibold' : 'text-slate-400'}`}>
                            {side.map((p: any) => p.name).join(' & ')}
                            {won && <span className="ml-1" title="winner">✓</span>}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                  <div className="text-[11px] text-slate-500 mt-1 flex items-center gap-2 flex-wrap">
                    <span>via {m.finish}</span>
                    {!!m.seconds?.length && (
                      <span className="text-slate-400">
                        ringside: {m.seconds.map((x: any) =>
                          `${x.name}${x.note === 'interfered' ? ' (interfered!)' : ''}`).join(', ')}
                      </span>
                    )}
                    {!!m.revisions?.length && (
                      <span className="text-gold" title="You overruled this result">✎ overruled</span>
                    )}
                  </div>
                  <Revise m={m} sides={sides} onDone={onNarrated} />
                  {m.narrative && (
                    <p className="text-[13px] text-slate-300 mt-2 leading-relaxed border-l-2 border-gold/40 pl-2.5">
                      {m.narrative}
                    </p>
                  )}
                  {!m.narrative && (
                    <button onClick={() => commentaryM.mutate(m.id)} disabled={commentaryM.isPending}
                      className="text-[10px] text-slate-500 hover:text-gold mt-1.5 disabled:opacity-40">
                      {commentaryM.isPending && commentaryM.variables === m.id ? 'writing…' : '🤖 add commentary'}
                    </button>
                  )}
                </div>
                <div className="flex flex-col items-end ml-3 shrink-0">
                  <span className={`text-lg font-bold tnum ${qualityColour(m.quality)}`}>
                    {m.quality?.toFixed(1)}
                  </span>
                  <Stars quality={m.quality} size={12} />
                  {m.reaction && <Reaction label={m.reaction} score={m.reaction_score} />}
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* The talking half of the night. Rendered after the matches because that
          is the order it ran in, and separately because a promo is scored on a
          different thing than a match. */}
      {!!detail.promos?.length && (
        <div className="mt-5">
          <h3 className="label text-[10px] text-slate-500 mb-2 tracking-wider">Promo segments</h3>
          <div className="space-y-2">
            {detail.promos.map((p: any, pi: number) => (
              <div key={p.id} className="bg-panel border border-emerald-400/25 rounded p-3 pop-in"
                style={{ animationDelay: `${pi * 90}ms` }}>
                <div className="flex justify-between items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="text-[10px] text-emerald-400 uppercase tracking-wider mb-1">
                      🎤 {p.label ?? p.kind}
                      {p.topic && <span className="text-slate-500 ml-2 normal-case">{p.topic}</span>}
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <div className="flex -space-x-2">
                        {p.participants.map((x: any) => <PFace key={x.wrestler_id} p={x} won={false} />)}
                      </div>
                      <span className="text-sm text-slate-300">
                        {p.participants.map((x: any) => x.name).join(' & ')}
                      </span>
                    </div>
                    {!!p.feud_id && (
                      <div className="text-[11px] text-slate-500 mt-1">built a rivalry</div>
                    )}
                  </div>
                  <div className="flex flex-col items-end shrink-0">
                    <span className={`text-lg font-bold tnum ${qualityColour(p.quality)}`}>
                      {p.quality?.toFixed(1)}
                    </span>
                    <Stars quality={p.quality} size={12} />
                    {p.reaction && <Reaction label={p.reaction} score={p.reaction_score} />}
                  </div>
                </div>
              </div>
            ))}
          </div>
          <p className="text-[10px] text-slate-600 mt-2">
            Promos count toward the show rating at half the weight of a match.
          </p>
        </div>
      )}
    </>
  )
}

/**
 * Overruling a result — the GM's final say.
 *
 * WHY IT IS HERE AND NOT ON A SEPARATE SCREEN. The decision is "I disagree with
 * this", and it is made while looking at the result. Putting it behind a
 * different page would mean re-finding the match you had an opinion about.
 *
 * Collapsed by default, because most results stand. Opening it shows what the
 * override will and will NOT reach back and fix, taken from the server so the
 * warning cannot drift from the behaviour.
 */
function Revise({ m, sides, onDone }: { m: any; sides: any[]; onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const winner = useMutation({
    mutationFn: (v: { team: number | null; finish?: string }) =>
      reviseWinner(m.id, v.team, v.finish),
    onSuccess: () => { setErr(null); onDone() },
    onError: (e: Error) => setErr(e.message),
  })
  const stars = useMutation({
    mutationFn: (v: number) => reviseStars(m.id, v),
    onSuccess: () => { setErr(null); onDone() },
    onError: (e: Error) => setErr(e.message),
  })
  const busy = winner.isPending || stars.isPending

  if (!open) {
    return (
      <button onClick={() => setOpen(true)}
        className="text-[10px] text-slate-600 hover:text-gold mt-1.5">
        ✎ overrule this result
      </button>
    )
  }
  return (
    <div className="mt-2 rounded border border-gold/30 bg-gold/5 p-2.5">
      <div className="flex items-baseline justify-between gap-2 mb-1.5">
        <span className="label text-[9px] text-gold">Your call</span>
        <button onClick={() => setOpen(false)}
          className="text-[10px] text-slate-500 hover:text-slate-300">close</button>
      </div>

      <div className="label text-[8px] text-slate-500 mb-1">Winner</div>
      <div className="flex flex-wrap gap-1 mb-2">
        {sides.map((side: any[], si: number) => {
          const on = m.winner_team === si
          return (
            <button key={si} disabled={busy}
              onClick={() => winner.mutate({ team: si })}
              className={`text-[11px] px-2 py-1 rounded border disabled:opacity-40 ${
                on ? 'border-emerald-400 text-emerald-300 bg-emerald-400/10'
                  : 'border-edge text-slate-400 hover:text-slate-200'}`}>
              {side.map((p: any) => p.name).join(' & ')}
            </button>
          )
        })}
        <button disabled={busy} onClick={() => winner.mutate({ team: null })}
          className={`text-[11px] px-2 py-1 rounded border disabled:opacity-40 ${
            m.winner_team === null ? 'border-slate-400 text-slate-200 bg-raised'
              : 'border-edge text-slate-500 hover:text-slate-300'}`}>
          Draw
        </button>
      </div>

      <div className="label text-[8px] text-slate-500 mb-1">Finish</div>
      <select value={m.finish ?? 'pinfall'} disabled={busy}
        onChange={(e) => winner.mutate({ team: m.winner_team, finish: e.target.value })}
        className="w-full bg-canvas border border-edge rounded px-2 py-1 text-[11px] mb-2">
        {FINISHES.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
      </select>

      <div className="label text-[8px] text-slate-500 mb-1">Star rating</div>
      <div className="flex flex-wrap gap-1">
        {[0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5].map((v) => (
          <button key={v} disabled={busy} onClick={() => stars.mutate(v)}
            className={`text-[10px] px-1.5 py-1 rounded border tnum disabled:opacity-40 ${
              m.stars === v ? 'border-gold text-gold bg-gold/10'
                : 'border-edge text-slate-500 hover:text-slate-200'}`}>
            {v % 1 === 0 ? v : v}★
          </button>
        ))}
      </div>

      {err && <p className="text-[10px] text-blood mt-1.5">{err}</p>}
      <p className="text-[9px] text-slate-600 mt-2 leading-snug">
        Records, momentum, the belt and the storyline beat are all put back for this match.
        Later shows already booked off the old result are not re-simulated.
      </p>
    </div>
  )
}

/**
 * How the building took a segment.
 *
 * Deliberately shown NEXT TO the quality score rather than instead of it: the
 * two say different things, and the gap between them is the lesson. A clean
 * match between two women nobody is invested in reads high on quality and flat
 * on reaction, and that is the most useful thing a show recap can tell you.
 */
function Reaction({ label, score }: { label: string; score: number | null }) {
  const colour = REACTION_COLOUR[label] ?? '#94a3b8'
  return (
    <span className="label text-[8px] mt-0.5" style={{ color: colour }}
      title={score != null ? `Crowd reaction ${score.toFixed(0)}/100` : undefined}>
      {label}
    </span>
  )
}

/** Stipulation keys are stable; the labels only exist to be read. */
const STIP_LABEL: Record<string, string> = {
  submission: 'Submission', no_dq: 'No DQ', tables: 'Tables', hardcore: 'Hardcore',
  steel_cage: 'Steel Cage', ladder: 'Ladder', last_standing: 'Last Woman Standing',
  extreme: 'Extreme Rules', tlc: 'TLC', iron_woman: 'Iron Woman',
}
