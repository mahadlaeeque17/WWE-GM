/**
 * What the year was — one page that says it.
 *
 * WHY THIS EXISTS. The save records everything and summarised nothing. Awards
 * crown individuals, the Power 25 says who is hot this week, the ratings war
 * says who is winning — but nothing answered "what happened in 2003?", which is
 * the question you actually ask about a season three years later.
 *
 * Entirely read-only. Every number and every name here is the save's own record,
 * sorted and given a headline, so this page can never disagree with the data it
 * is summarising.
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchSeasons, fetchSeasonSummary, type SeasonSummary } from './api'
import { Stars } from './ui'

const fmt = (n: number | null | undefined, d = 2) =>
  n === null || n === undefined ? '—' : n.toFixed(d)

export default function SeasonTab() {
  const { data: years = [] } = useQuery({ queryKey: ['seasons'], queryFn: fetchSeasons })
  const [year, setYear] = useState<number | null>(null)
  useEffect(() => {
    if (year === null && years.length) setYear(years[0])
  }, [years, year])

  const { data: s, isLoading } = useQuery({
    queryKey: ['season', year],
    queryFn: () => fetchSeasonSummary(year!),
    enabled: year !== null,
  })

  if (!years.length) {
    return (
      <div className="p-6 text-sm text-slate-500 max-w-[520px]">
        No season has been played yet. Run some shows and this fills itself in — it is
        entirely derived from what the save already records.
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-auto p-5">
      <div className="flex items-baseline justify-between gap-3 flex-wrap mb-3">
        <h2 className="display text-[22px]">The season</h2>
        <div className="flex items-center gap-1">
          {years.map((y) => (
            <button key={y} onClick={() => setYear(y)}
              className={`label text-[10px] px-2 py-1 rounded border ${
                year === y ? 'border-gold text-gold bg-gold/10'
                  : 'border-edge text-slate-500 hover:text-slate-200'}`}>
              {y}
            </button>
          ))}
        </div>
      </div>

      {isLoading && <p className="text-sm text-slate-500">Reading the year…</p>}
      {s && !s.ran && <p className="text-sm text-slate-500">{s.headline}</p>}
      {s && s.ran && <Summary s={s} />}
    </div>
  )
}

function Summary({ s }: { s: SeasonSummary }) {
  return (
    <>
      <p className="text-sm text-slate-200 mb-4 max-w-[760px] leading-relaxed">{s.headline}</p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        <Stat label="Shows" value={String(s.shows ?? 0)}
          sub={`${s.ppvs ?? 0} pay-per-view${(s.ppvs ?? 0) !== 1 ? 's' : ''}`} />
        <Stat label="Matches" value={String(s.matches ?? 0)}
          sub={`avg ${fmt(s.avg_match_quality, 1)}`} />
        <Stat label="Avg show" value={fmt(s.avg_show_rating, 1)} sub="out of 100" />
        <Stat label="Through the doors"
          value={((s.attendance ?? 0) / 1000).toFixed(0) + 'k'} sub="total attendance" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div className="space-y-5 min-w-0">
          {s.best_match && (
            <Panel title="Match of the year">
              <div className="text-[15px] text-slate-100">
                {s.best_match.wrestlers.join(' vs ')}
              </div>
              <div className="flex items-center gap-2 mt-1">
                <span className="stat text-[22px] text-gold">
                  {s.best_match.stars.toFixed(1)}
                </span>
                <Stars quality={s.best_match.quality} size={14} />
                <span className="text-[11px] text-slate-500">
                  {s.best_match.quality.toFixed(1)}/100
                </span>
              </div>
              <p className="text-[11px] text-slate-500 mt-1">
                {s.best_match.show_name}{s.best_match.is_ppv ? ' ◆' : ''} ·{' '}
                {s.best_match.held_on}
                {s.best_match.stipulation && s.best_match.stipulation !== 'normal'
                  ? ` · ${s.best_match.stipulation}` : ''}
              </p>
            </Panel>
          )}

          {s.feud_of_the_year && (
            <Panel title="Story of the year">
              <div className="text-[15px] text-slate-100">
                {s.feud_of_the_year.a_name} · {s.feud_of_the_year.b_name}
              </div>
              <p className="text-[11px] text-slate-500 mt-1">
                {s.feud_of_the_year.kind_label}
                {s.feud_of_the_year.was_kind
                  ? ` (began as ${s.feud_of_the_year.was_kind})` : ''} ·{' '}
                {s.feud_of_the_year.beats} beats · {s.feud_of_the_year.matches} matches ·
                series {s.feud_of_the_year.series.a_wins}–{s.feud_of_the_year.series.b_wins}
              </p>
            </Panel>
          )}

          {(s.best_show || s.biggest_tv || s.biggest_ppv) && (
            <Panel title="The biggest nights">
              {s.best_show && (
                <Line label="Best card" value={s.best_show.name}
                  right={fmt(s.best_show.rating, 1)} />
              )}
              {s.biggest_tv && (
                <Line label="Highest rating" value={s.biggest_tv.name}
                  right={fmt(s.biggest_tv.tv_rating)} />
              )}
              {s.biggest_ppv && (
                <Line label="Biggest buyrate" value={s.biggest_ppv.name}
                  right={fmt(s.biggest_ppv.buyrate)} />
              )}
            </Panel>
          )}

          {(s.breakout || s.workhorse) && (
            <Panel title="The year's performers">
              {s.breakout && (
                <Line label="Breakout" value={s.breakout.name}
                  right={`+${s.breakout.gained}`}
                  note={`${s.breakout.weeks_top10} weeks in the Power 10`} />
              )}
              {s.workhorse && (
                <Line label="Workhorse" value={s.workhorse.name}
                  right={`${s.workhorse.matches} matches`}
                  note={`averaging ${fmt(s.workhorse.avg_quality, 1)}`} />
              )}
            </Panel>
          )}
        </div>

        <div className="space-y-5 min-w-0">
          {!!s.champions?.length && (
            <Panel title="Champions at year's end">
              {s.champions.map((c) => (
                <Line key={c.name} label={c.short_name ?? c.name}
                  value={c.name_of ?? 'vacant'}
                  right={c.won_on ? `since ${c.won_on}` : ''} />
              ))}
            </Panel>
          )}

          {!!s.title_changes?.length && (
            <Panel title={`Title changes (${s.title_changes.length})`}>
              {s.title_changes.map((t, i) => (
                <Line key={i} label={t.short_name ?? t.name} value={t.name_of}
                  right={t.won_on} />
              ))}
            </Panel>
          )}

          {!!s.turns?.length && (
            <Panel title="Turns">
              {s.turns.map((t, i) => (
                <Line key={i} label={t.from_align === 'heel' ? '▼ → ▲' : '▲ → ▼'}
                  value={t.name} right={t.trigger} />
              ))}
            </Panel>
          )}

          {!!s.forced_moves?.length && (
            <Panel title="Taken out of your hands">
              {s.forced_moves.map((f, i) => (
                <Line key={i}
                  label={f.kind === 'walkout' ? 'walked out' : 'forced trade'}
                  value={f.name}
                  right={f.to_brand ? `→ ${f.to_brand}` : 'gone'} />
              ))}
            </Panel>
          )}

          {!!s.awards?.length && (
            <Panel title="Awards">
              {s.awards.map((a, i) => (
                <Line key={i} label={a.kind.replace(/_/g, ' ')}
                  value={a.name ?? '—'} right={a.detail ?? ''} />
              ))}
            </Panel>
          )}
        </div>
      </div>

      <p className="text-[10px] text-slate-600 mt-5 max-w-[640px] leading-snug">
        Everything here is read from the save's own records. Nothing on this page decides
        anything or can disagree with the data behind it.
      </p>
    </>
  )
}

function Stat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="card p-3">
      <div className="label text-[8px] text-slate-500">{label}</div>
      <div className="stat text-[24px] leading-none text-slate-100">{value}</div>
      <div className="text-[9px] text-slate-600 truncate">{sub}</div>
    </div>
  )
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="label text-[10px] text-slate-400 tracking-wider mb-1.5">{title}</h3>
      <div className="card p-3 space-y-1">{children}</div>
    </section>
  )
}

function Line({ label, value, right, note }: {
  label: string; value: string; right?: string; note?: string
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="label text-[8px] text-slate-500 shrink-0">{label}</span>
        <span className="text-[12px] text-slate-200 truncate flex-1 text-right">{value}</span>
        {right && <span className="text-[10px] text-slate-500 shrink-0 tnum">{right}</span>}
      </div>
      {note && <div className="text-[9px] text-slate-600 text-right">{note}</div>}
    </div>
  )
}
