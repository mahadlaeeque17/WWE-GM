/**
 * Everything that has ever happened to one wrestler.
 *
 * The sim has always recorded enough to answer real questions — who she has
 * beaten, what she did in 2003, how she does against one specific opponent — and
 * nothing ever asked. This asks.
 *
 * Four sections, in the order a GM actually wants them:
 *
 *   cards     her yearly cards, newest first. The collection.
 *   record    season by season, so a career has a shape rather than a total
 *   versus    head-to-head against everyone she has faced. Click one to see
 *             every meeting in order, which is the part a total cannot tell you
 *   honours   title reigns and accolades with dates
 *
 * Loaded on demand, not with the roster: this is four queries for one wrestler,
 * and putting it in the roster payload would mean running them 370 times to open
 * one panel.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  fetchHistory, fetchWrestlerCards, fetchHeadToHead, fetchProgression, imageUrl,
  money, prettyDate, OVERALL_MAX, type ProgressionPoint, type RosterRow,
} from './api'
import Card from './Card'

/**
 * Overall by season, as a line.
 *
 * Reads the MINTED CARDS rather than recomputing anything, so the graph cannot
 * disagree with the cards above it — it is the same numbers, drawn as a shape
 * instead of a shelf. A season with a ribbon gets a gold marker, which is what
 * turns a line into a story: you can see the year she won the belt.
 */
function OverallGraph({ points }: { points: ProgressionPoint[] }) {
  if (points.length < 2) return null
  const W = 260, H = 62, PAD = 6
  const lo = Math.min(...points.map((p) => p.overall)) - 4
  const hi = Math.max(...points.map((p) => p.overall)) + 4
  const span = Math.max(1, hi - lo)
  const x = (i: number) => PAD + (i / (points.length - 1)) * (W - PAD * 2)
  const y = (v: number) => H - PAD - ((v - lo) / span) * (H - PAD * 2)
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.overall).toFixed(1)}`).join(' ')

  return (
    <div className="mt-3">
      <div className="label text-[9px] text-slate-600 mb-1">
        Overall by season · {points[0].overall} → {points[points.length - 1].overall}
      </div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ maxWidth: W }}
           role="img" aria-label={points.map((p) => `${p.season_year}: ${p.overall}`).join(', ')}>
        <path d={`${path} L${x(points.length - 1).toFixed(1)},${H - PAD} L${x(0).toFixed(1)},${H - PAD} Z`}
              fill="var(--color-gold)" fillOpacity={0.10} />
        <path d={path} fill="none" stroke="var(--color-gold)" strokeWidth={1.6}
              strokeLinejoin="round" />
        {points.map((p, i) => (
          <circle key={p.season_year} cx={x(i).toFixed(1)} cy={y(p.overall).toFixed(1)}
                  r={p.special ? 3.4 : 2.2}
                  fill={p.special ? 'var(--color-gold)' : 'var(--color-panel)'}
                  stroke="var(--color-gold)" strokeWidth={1.2}>
            <title>
              {p.season_year}: {p.overall}/{OVERALL_MAX}
              {p.record ? ` · ${p.record}` : ''}{p.special ? ` · ${p.special}` : ''}
            </title>
          </circle>
        ))}
      </svg>
      <div className="flex justify-between text-[9px] text-slate-600 mt-0.5" style={{ maxWidth: W }}>
        <span>{points[0].season_year}</span>
        <span>{points[points.length - 1].season_year}</span>
      </div>
    </div>
  )
}

type Section = 'cards' | 'record' | 'versus' | 'honours'

const SECTIONS: { key: Section; label: string }[] = [
  { key: 'cards', label: 'Cards' },
  { key: 'record', label: 'Record' },
  { key: 'versus', label: 'Head to head' },
  { key: 'honours', label: 'Honours' },
]

export default function CareerHistory({ row }: { row: RosterRow }) {
  const [section, setSection] = useState<Section>('cards')
  const [opponent, setOpponent] = useState<number | null>(null)

  const { data: hist, isLoading } = useQuery({
    queryKey: ['history', row.id], queryFn: () => fetchHistory(row.id),
  })
  const { data: cards } = useQuery({
    queryKey: ['cards', row.id], queryFn: () => fetchWrestlerCards(row.id),
    enabled: section === 'cards',
  })
  const { data: progression = [] } = useQuery({
    queryKey: ['progression', row.id], queryFn: () => fetchProgression(row.id),
    enabled: section === 'cards',
  })
  const { data: h2h } = useQuery({
    queryKey: ['h2h', row.id, opponent],
    queryFn: () => fetchHeadToHead(row.id, opponent!),
    enabled: opponent !== null,
  })

  const portrait = row.profile_image_id ? imageUrl(row.profile_image_id) : null

  return (
    <section className="mb-5">
      <div className="flex items-center gap-1 mb-2.5 flex-wrap">
        <h3 className="text-xs uppercase tracking-wider text-slate-500 mr-1">Career</h3>
        {SECTIONS.map((s) => (
          <button
            key={s.key} onClick={() => setSection(s.key)}
            className={`label text-[10px] px-2 py-[3px] rounded border transition-colors
              ${section === s.key ? 'border-gold text-gold bg-gold/10'
                : 'border-edge text-slate-500 hover:text-slate-200'}`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {isLoading && <p className="text-xs text-slate-500">Reading the record books…</p>}

      {hist && hist.total.matches === 0 && section !== 'cards' && (
        <p className="text-xs text-slate-500">
          She has not worked a match in this save yet. Book her on a show and this
          fills in — record, opponents, the lot.
        </p>
      )}

      {/* ------------------------------------------------------------- cards */}
      {section === 'cards' && (
        <div className="flex gap-2.5 overflow-x-auto pb-1">
          {cards ? (
            <>
              <Card card={cards.live} size="md" portrait={portrait} />
              {cards.seasons.map((c) => (
                <Card key={c.season_year} card={c} size="sm" portrait={portrait} />
              ))}
              {cards.seasons.length === 0 && (
                <p className="text-[11px] text-slate-500 self-center max-w-[190px]">
                  The live card is this season, still moving. A permanent card is
                  minted for her when the season ends.
                </p>
              )}
            </>
          ) : (
            <p className="text-xs text-slate-500">Printing…</p>
          )}
        </div>
      )}

      {section === 'cards' && <OverallGraph points={progression} />}

      {/* ------------------------------------------------------------ record */}
      {section === 'record' && hist && hist.total.matches > 0 && (
        <>
          <div className="grid grid-cols-4 gap-2 mb-3">
            {([
              ['Record', `${hist.total.wins}-${hist.total.losses}${hist.total.draws ? `-${hist.total.draws}` : ''}`],
              ['Win rate', `${hist.total.win_pct}%`],
              ['PPVs', hist.total.ppv],
              ['Days champ', hist.total.title_days.toLocaleString()],
            ] as const).map(([k, v]) => (
              <div key={k} className="rounded bg-canvas/60 border border-edge-soft px-2 py-1.5">
                <div className="label text-[9px] text-slate-600">{k}</div>
                <div className="stat text-[15px] text-slate-200">{v}</div>
              </div>
            ))}
          </div>

          <table className="w-full text-xs">
            <thead>
              <tr className="label text-[9px] text-slate-600 border-b border-edge-soft">
                <th className="text-left py-1">Season</th>
                <th className="text-right">W-L-D</th>
                <th className="text-right">PPV</th>
                <th className="text-right">Titles</th>
                <th className="text-right">Avg ★</th>
              </tr>
            </thead>
            <tbody>
              {hist.seasons.map((s) => (
                <tr key={s.season} className="border-b border-edge-soft/50">
                  <td className="py-1 stat text-slate-300">{s.season}</td>
                  <td className="text-right stat text-slate-200">
                    {s.wins}-{s.losses}{s.draws ? `-${s.draws}` : ''}
                  </td>
                  <td className="text-right stat text-slate-500">{s.ppv || '—'}</td>
                  <td className="text-right stat text-gold">{s.titles_won || '—'}</td>
                  <td className="text-right stat text-slate-400">
                    {s.avg_quality != null ? (s.avg_quality / 20).toFixed(1) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {hist.best_matches.length > 0 && (
            <div className="mt-3">
              <div className="label text-[9px] text-slate-600 mb-1">Best matches</div>
              {hist.best_matches.slice(0, 4).map((m) => (
                <div key={m.match_id} className="flex items-baseline gap-2 text-[11px] py-0.5">
                  <span className="stat text-gold w-7 shrink-0">{(m.quality / 20).toFixed(1)}★</span>
                  <span className={m.won ? 'text-emerald-400' : 'text-slate-500'}>
                    {m.won ? 'W' : 'L'}
                  </span>
                  <span className="text-slate-400 truncate">
                    {m.show}{m.title ? ` · ${m.title}` : ''}
                  </span>
                  <span className="text-slate-600 ml-auto shrink-0">{prettyDate(m.held_on)}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* ------------------------------------------------------------ versus */}
      {section === 'versus' && hist && (
        <>
          {hist.versus.length === 0 && hist.total.matches > 0 && (
            <p className="text-xs text-slate-500">No opponents on record yet.</p>
          )}
          {hist.versus.length > 0 && (
            <div className="max-h-[190px] overflow-y-auto pr-1">
              {hist.versus.map((v) => (
                <button
                  key={v.wrestler_id}
                  onClick={() => setOpponent(opponent === v.wrestler_id ? null : v.wrestler_id)}
                  className={`w-full flex items-baseline gap-2 text-[11px] px-1.5 py-1 rounded
                              text-left transition-colors
                              ${opponent === v.wrestler_id ? 'bg-gold/10' : 'hover:bg-raised/50'}`}
                >
                  <span className="text-slate-300 truncate flex-1">{v.name}</span>
                  <span className="stat text-slate-200">
                    {v.wins}-{v.losses}{v.draws ? `-${v.draws}` : ''}
                  </span>
                  <span className={`stat w-9 text-right ${v.win_pct >= 50 ? 'text-emerald-400' : 'text-blood'}`}>
                    {v.win_pct}%
                  </span>
                </button>
              ))}
            </div>
          )}

          {/* The sequence, which is the thing a win-loss total cannot tell you. */}
          {h2h && (
            <div className="mt-2 pt-2 border-t border-edge-soft">
              <div className="flex items-baseline gap-2 mb-1">
                <span className="label text-[10px] text-slate-400">
                  {h2h.a.name} <span className="text-gold">{h2h.a.wins}</span>
                  {' – '}
                  <span className="text-gold">{h2h.b.wins}</span> {h2h.b.name}
                </span>
                {h2h.draws > 0 && (
                  <span className="text-[10px] text-slate-600">{h2h.draws} drawn</span>
                )}
              </div>
              {h2h.meetings.map((m) => (
                <div key={m.match_id} className="flex items-baseline gap-2 text-[11px] py-0.5">
                  <span className={`label text-[9px] w-4 ${
                    m.winner_id === null ? 'text-slate-500'
                      : m.winner_id === row.id ? 'text-emerald-400' : 'text-blood'}`}>
                    {m.winner_id === null ? 'D' : m.winner_id === row.id ? 'W' : 'L'}
                  </span>
                  <span className="text-slate-600 shrink-0">{prettyDate(m.held_on)}</span>
                  <span className="text-slate-400 truncate">
                    {m.show}{m.is_ppv ? ' ◆' : ''}{m.title ? ` · ${m.title}` : ''}
                    {m.stipulation ? ` · ${m.stipulation}` : ''}
                  </span>
                  {m.quality != null && (
                    <span className="stat text-slate-500 ml-auto shrink-0">
                      {(m.quality / 20).toFixed(1)}★
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}

          {hist.partners.length > 0 && (
            <div className="mt-2 pt-2 border-t border-edge-soft">
              <div className="label text-[9px] text-slate-600 mb-1">Tag partners</div>
              {hist.partners.slice(0, 5).map((p) => (
                <div key={p.wrestler_id} className="flex items-baseline gap-2 text-[11px] py-0.5">
                  <span className="text-slate-400 truncate flex-1">{p.name}</span>
                  <span className="stat text-slate-500">{p.wins}-{p.losses} together</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* ----------------------------------------------------------- honours */}
      {section === 'honours' && hist && (
        <>
          {hist.reigns.length === 0 && hist.accolades.length === 0 && (
            <p className="text-xs text-slate-500">
              Nothing won yet. Championships, Rumbles and awards all land here —
              and all move her Achievements rating.
            </p>
          )}
          {hist.reigns.map((r) => (
            <div key={r.id} className="flex items-baseline gap-2 text-[11px] py-0.5">
              <span className="label text-[9px] text-gold w-16 shrink-0 truncate">
                {r.short_name || r.tier}
              </span>
              <span className="text-slate-300 truncate flex-1">{r.name}</span>
              <span className="stat text-slate-400 shrink-0">
                {r.days}d{r.ongoing ? ' · current' : ''}
              </span>
              <span className="text-slate-600 shrink-0">{prettyDate(r.won_on)}</span>
            </div>
          ))}
          {hist.accolades.length > 0 && (
            <div className="mt-2 pt-2 border-t border-edge-soft">
              {hist.accolades.map((a, i) => (
                <div key={i} className="flex items-baseline gap-2 text-[11px] py-0.5">
                  <span className="text-gold">★</span>
                  <span className="text-slate-300">{a.label}</span>
                  <span className="text-slate-600">{a.season_year}</span>
                  {a.detail && <span className="text-slate-600 truncate">· {a.detail}</span>}
                </div>
              ))}
            </div>
          )}
          {hist.contracts.length > 0 && (
            <div className="mt-2 pt-2 border-t border-edge-soft">
              <div className="label text-[9px] text-slate-600 mb-1">Contract history</div>
              {hist.contracts.map((c, i) => (
                <div key={i} className="flex items-baseline gap-2 text-[11px] py-0.5">
                  <span className={c.brand_id === 'RAW' ? 'text-raw' : 'text-smackdown'}>
                    {c.brand_id}
                  </span>
                  <span className="text-slate-500">{c.start_year}–{c.end_year}</span>
                  <span className="text-slate-400">{money(c.annual_value)}/yr</span>
                  <span className="text-slate-600 ml-auto">
                    {c.terminated_on ? 'ended' : c.origin}
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  )
}
