/**
 * The scoreboard — is the way you book actually working?
 *
 * WHY THIS SCREEN EXISTS. The save already had money, titles and a power
 * ranking, none of which answer the only question a GM really has. Money is a
 * constraint, not a score: you can bank a fortune running a terrible show in a
 * small building. So every television night draws a RATING, every pay-per-view
 * sells a BUYRATE, and when both brands have run the same number of shows the
 * higher rating wins the week.
 *
 * A week where only one brand ran is deliberately NOT a win — you cannot beat
 * somebody who did not turn up, and counting it would reward leaving the other
 * brand dark.
 */
import { useQuery } from '@tanstack/react-query'
import { fetchBrandWar, type BrandWarBrand, type BrandWeek } from './api'
import { BrandCrest } from './emblems'

const fmt = (n: number | null | undefined, d = 2) =>
  n === null || n === undefined ? '—' : n.toFixed(d)

export default function BrandWarTab() {
  const { data, isLoading } = useQuery({ queryKey: ['brandwar'], queryFn: () => fetchBrandWar() })

  if (isLoading) return <div className="p-6 text-sm text-slate-500">Reading the ratings…</div>
  if (!data?.brands?.length) {
    return <div className="p-6 text-sm text-slate-500">Start a new game to see the ratings war.</div>
  }

  const maxRating = Math.max(
    1, ...data.weeks.flatMap((w) => w.brands.map((b) => b.tv_rating)))

  return (
    <div className="flex-1 overflow-auto p-5">
      <h2 className="display text-[22px] mb-1">The ratings war · {data.season_year}</h2>
      <p className="text-sm text-slate-300 mb-1">{data.summary}</p>
      <p className="text-xs text-slate-600 mb-5 max-w-[720px] leading-relaxed">
        A rating is built from the audience you already have, what you put on, who was on it, and
        the storylines going in — then anchored to last week, because an audience arrives and
        leaves gradually. One great show cannot triple it; a run of them will.
      </p>

      {/* ---------------- standings ---------------- */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-6">
        {data.brands.map((b) => (
          <BrandCard key={b.brand_id} b={b} leading={data.leader === b.brand_id} />
        ))}
      </div>

      {/* ---------------- week by week ---------------- */}
      <h3 className="label text-[11px] text-slate-400 tracking-wider mb-2">Week by week</h3>
      {data.weeks.length === 0
        ? <p className="text-xs text-slate-600">No television has aired yet.</p>
        : <div className="space-y-1.5">
            {data.weeks.map((w) => <WeekRow key={w.week_of} w={w} max={maxRating} />)}
          </div>}
      {data.ties > 0 && (
        <p className="text-[10px] text-slate-600 mt-2">
          {data.ties} week{data.ties !== 1 ? 's' : ''} finished level.
        </p>
      )}
      <p className="text-[10px] text-slate-600 mt-3 leading-snug max-w-[640px]">
        A “week” is Raw's Nth show against SmackDown's Nth show — the save's clock moves a month
        at a time, so that is the only honest way to line two brands up. A week with one brand in
        it is not a win.
      </p>
    </div>
  )
}

function BrandCard({ b, leading }: { b: BrandWarBrand; leading: boolean }) {
  return (
    <div className={`card p-4 ${leading ? 'champ-glow' : ''}`}
      style={leading ? { borderColor: `${b.colour}88` } : undefined}>
      <div className="flex items-center gap-3 mb-3">
        <BrandCrest brand={b.brand_id} size={38} />
        <div className="min-w-0">
          <div className="display text-[18px] leading-none" style={{ color: b.colour }}>
            {b.name}
          </div>
          <div className="text-[10px] text-slate-500 mt-0.5">
            {b.fanbase.toLocaleString()} fans
          </div>
        </div>
        {leading && (
          <span className="label text-[8px] px-2 py-[3px] rounded bg-gold/15 text-gold ml-auto">
            LEADING
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-y-2.5 gap-x-3">
        <Stat label="Weeks won" value={String(b.weeks_won)}
          sub={b.weeks_contested ? `of ${b.weeks_contested} head-to-head` : 'none contested'} />
        <Stat label="Avg rating" value={fmt(b.avg_rating)}
          sub={`${b.shows} show${b.shows !== 1 ? 's' : ''}`} />
        <Stat label="Best night" value={fmt(b.best_rating)}
          sub={b.best_show ? b.best_show.name : '—'} />
        <Stat label="Avg buyrate" value={fmt(b.avg_buyrate)}
          sub={b.ppv_count ? `${b.ppv_count} PPV${b.ppv_count !== 1 ? 's' : ''}` : 'no PPVs'} />
      </div>
    </div>
  )
}

function Stat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="min-w-0">
      <div className="label text-[8px] text-slate-500">{label}</div>
      <div className="stat text-[20px] leading-none text-slate-100">{value}</div>
      <div className="text-[9px] text-slate-600 truncate">{sub}</div>
    </div>
  )
}

function WeekRow({ w, max }: { w: BrandWeek; max: number }) {
  const label = w.week_of.replace(/^\d{4}-W/, 'Week ')
  return (
    <div className="card p-2.5">
      <div className="flex items-baseline justify-between gap-2 mb-1.5">
        <span className="label text-[9px] text-slate-500">{label}</span>
        <span className="label text-[8px]" style={{
          color: w.tied ? '#94a3b8' : w.winner ? 'var(--color-gold)' : '#475569',
        }}>
          {w.tied ? 'LEVEL' : w.winner
            ? `${w.brands.find((b) => b.brand_id === w.winner)?.name} by ${fmt(w.margin)}`
            : 'ONE BRAND ONLY'}
        </span>
      </div>
      <div className="space-y-1">
        {w.brands.map((b) => (
          <div key={b.brand_id} className="flex items-center gap-2">
            <span className="text-[11px] w-20 shrink-0 truncate" style={{ color: b.colour }}>
              {b.name}
            </span>
            <div className="flex-1 h-[6px] rounded bg-raised overflow-hidden">
              <div className="h-full rounded" style={{
                width: `${Math.max(3, (b.tv_rating / max) * 100)}%`,
                background: b.brand_id === w.winner ? 'var(--color-gold)' : b.colour,
                opacity: b.brand_id === w.winner ? 1 : 0.55,
              }} />
            </div>
            <span className="stat text-[12px] w-10 text-right shrink-0"
              style={{ color: b.brand_id === w.winner ? 'var(--color-gold)' : '#94a3b8' }}>
              {fmt(b.tv_rating)}
            </span>
            <span className="text-[9px] text-slate-600 w-16 text-right shrink-0 tnum">
              {(b.viewers / 1_000_000).toFixed(2)}M
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
