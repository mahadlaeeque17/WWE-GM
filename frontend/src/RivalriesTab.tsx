/**
 * The save's real feuds, ranked.
 *
 * Head-to-head data already existed on every wrestler's panel; this reads it the
 * other way round — every PAIR at once instead of one wrestler against everyone.
 * The result is a list of stories you booked without necessarily noticing: the
 * four-match title series, the two-match blood feud, the pairing you have run six
 * times because they always deliver.
 *
 * Ranked by a score, not by meeting count. Meetings alone puts two enhancement
 * talents who happened to be booked together nine times above a two-match feud
 * that headlined a pay-per-view. Titles, PPVs, match quality and how EVEN the
 * series is all count — a rivalry one wrestler wins every time is a squash
 * series, not a feud. Every column is on screen so you can disagree with it.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  fetchRivalries, fetchHeadToHead, fetchCardSeasons, prettyDate, type RosterRow,
} from './api'
import { Avatar } from './ui'
import Storylines from './Storylines'

export default function RivalriesTab({ roster }: { roster: RosterRow[] }) {
  const [season, setSeason] = useState<number | null>(null)
  const [open, setOpen] = useState<[number, number] | null>(null)

  const { data: seasons = [] } = useQuery({
    queryKey: ['card-seasons'], queryFn: fetchCardSeasons,
  })
  const { data: rivalries = [], isLoading } = useQuery({
    queryKey: ['rivalries', season],
    queryFn: () => fetchRivalries(40, season ?? undefined),
  })
  const { data: h2h } = useQuery({
    queryKey: ['h2h', open?.[0], open?.[1]],
    queryFn: () => fetchHeadToHead(open![0], open![1]),
    enabled: open !== null,
  })

  const byId = new Map(roster.map((r) => [r.id, r]))

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="px-4 py-3 border-b border-edge flex flex-wrap items-center gap-3">
        <div>
          <h2 className="display text-lg leading-none">Rivalries</h2>
          <p className="text-[11px] text-slate-500 mt-1">
            Ranked on meetings, match quality, titles, pay-per-views — and how
            even the series is, because a feud one wrestler always wins is a
            squash series.
          </p>
        </div>
        <div className="ml-auto flex items-center gap-1">
          <button
            onClick={() => setSeason(null)}
            className={`label text-[10px] px-2 py-1 rounded border transition-colors
              ${season === null ? 'border-gold text-gold bg-gold/10'
                : 'border-edge text-slate-500 hover:text-slate-200'}`}
          >
            all time
          </button>
          {seasons.map((s) => (
            <button
              key={s.season_year} onClick={() => setSeason(s.season_year)}
              className={`label text-[10px] px-2 py-1 rounded border transition-colors
                ${season === s.season_year ? 'border-gold text-gold bg-gold/10'
                  : 'border-edge text-slate-500 hover:text-slate-200'}`}
            >
              {s.season_year}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        {/* The present tense first: feuds running now, and the blow-off planner.
            The ranked list below is history. */}
        <Storylines />

        {isLoading && <p className="p-6 text-sm text-slate-500">Reading the tape…</p>}

        {!isLoading && rivalries.length === 0 && (
          <p className="p-6 text-sm text-slate-500 max-w-[520px]">
            No completed rivalries yet — two wrestlers have to have met in the ring for one
            to appear here. Book some shows and this fills itself in.
          </p>
        )}

        {rivalries.map((r, i) => {
          const key = `${r.a.wrestler_id}-${r.b.wrestler_id}`
          const isOpen = open?.[0] === r.a.wrestler_id && open?.[1] === r.b.wrestler_id
          const lead = r.a.wins === r.b.wins ? null : r.a.wins > r.b.wins ? 'a' : 'b'
          return (
            <div key={key} className="border-b border-edge-soft">
              <button
                onClick={() => setOpen(isOpen ? null : [r.a.wrestler_id, r.b.wrestler_id])}
                className="w-full px-4 py-2.5 flex items-center gap-3 text-left
                           hover:bg-raised/40 transition-colors"
              >
                <span className="stat text-slate-600 w-6 text-right shrink-0">{i + 1}</span>

                <div className="flex items-center gap-2 min-w-0 flex-1 justify-end">
                  <span className={`truncate text-sm ${lead === 'a' ? 'text-slate-100' : 'text-slate-400'}`}>
                    {r.a.name}
                  </span>
                  {byId.get(r.a.wrestler_id) && <Avatar row={byId.get(r.a.wrestler_id)!} width={26} />}
                </div>

                <div className="shrink-0 text-center px-1">
                  <div className="stat text-[17px] leading-none">
                    <span className={lead === 'a' ? 'text-gold' : 'text-slate-300'}>{r.a.wins}</span>
                    <span className="text-slate-600 mx-1">–</span>
                    <span className={lead === 'b' ? 'text-gold' : 'text-slate-300'}>{r.b.wins}</span>
                  </div>
                  {r.draws > 0 && (
                    <div className="label text-[9px] text-slate-600">{r.draws} drawn</div>
                  )}
                </div>

                <div className="flex items-center gap-2 min-w-0 flex-1">
                  {byId.get(r.b.wrestler_id) && <Avatar row={byId.get(r.b.wrestler_id)!} width={26} />}
                  <span className={`truncate text-sm ${lead === 'b' ? 'text-slate-100' : 'text-slate-400'}`}>
                    {r.b.name}
                  </span>
                </div>

                <div className="shrink-0 hidden md:flex items-center gap-3 text-[11px] text-slate-500">
                  <span title="Matches against each other">{r.meetings} mtg</span>
                  <span title="Average match quality" className="text-slate-400">
                    {(r.avg_quality / 20).toFixed(1)}★
                  </span>
                  {r.title_matches > 0 && (
                    <span className="text-gold" title="Matches with a title on the line">
                      {r.title_matches} ♛
                    </span>
                  )}
                  {r.ppv_matches > 0 && (
                    <span title="Matches on a pay-per-view">{r.ppv_matches} ◆</span>
                  )}
                  {r.active_heat && (
                    <span className="text-raw label text-[9px]" title="An active feud is running">
                      live {r.active_heat}
                    </span>
                  )}
                </div>
              </button>

              {isOpen && h2h && (
                <div className="px-4 pb-3 pl-14">
                  <div className="label text-[9px] text-slate-600 mb-1">
                    every meeting · {prettyDate(r.first_met)} to {prettyDate(r.last_met)}
                  </div>
                  {h2h.meetings.map((m) => (
                    <div key={m.match_id} className="flex items-baseline gap-2 text-[11px] py-0.5">
                      <span className="text-slate-600 w-16 shrink-0">{prettyDate(m.held_on)}</span>
                      <span className="text-slate-300 truncate">
                        {m.winner_id === null
                          ? 'drawn'
                          : `${m.winner_id === r.a.wrestler_id ? r.a.name : r.b.name} won`}
                      </span>
                      <span className="text-slate-500 truncate">
                        {m.show}{m.is_ppv ? ' ◆' : ''}{m.title ? ` · ${m.title}` : ''}
                        {m.stipulation ? ` · ${m.stipulation}` : ''}
                      </span>
                      {m.quality != null && (
                        <span className="stat text-slate-400 ml-auto shrink-0">
                          {(m.quality / 20).toFixed(1)}★
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {rivalries.length > 0 && (
        <div className="border-t border-edge px-4 py-2 text-[11px] text-slate-600 shrink-0">
          {rivalries.length} shown · click one for every meeting in order · ♛ title
          match · ◆ pay-per-view
        </div>
      )}
    </div>
  )
}
