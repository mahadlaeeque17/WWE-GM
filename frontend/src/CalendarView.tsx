import type { Calendar, CalendarShow } from './api'
import { PPVBadge } from './emblems'

const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const SHOW_STYLE: Record<string, { bg: string; fg: string; tag: string }> = {
  RAW:       { bg: 'rgba(224,34,60,0.16)',  fg: '#f87171', tag: 'RAW' },
  SMACKDOWN: { bg: 'rgba(59,130,246,0.16)', fg: '#60a5fa', tag: 'SD' },
  PPV:       { bg: 'rgba(232,185,63,0.20)', fg: '#e8b93f', tag: 'PPV' },
  SNME:      { bg: 'rgba(52,211,153,0.16)', fg: '#34d399', tag: 'SNME' },
}

/**
 * The season at a glance: Raw every Monday, SmackDown every Friday, the
 * pay-per-view on the last Sunday, and the one Saturday Night's Main Event of
 * the year wherever it falls. WrestleMania closes December and the season.
 */
export default function CalendarView({ cal, compact }: { cal: Calendar; compact?: boolean }) {
  if (!cal.active || cal.days_in_month == null) return null
  const byDay = new Map<number, CalendarShow>()
  for (const s of cal.shows ?? []) byDay.set(s.day, s)

  const lead = cal.first_weekday ?? 0
  const cells: (number | null)[] = [...Array(lead).fill(null), ...Array.from({ length: cal.days_in_month }, (_, i) => i + 1)]
  while (cells.length % 7 !== 0) cells.push(null)

  return (
    <div className="card p-4">
      <div className="flex items-baseline justify-between mb-3">
        <h3 className="display text-[18px] leading-none">
          {cal.month_name} <span className="text-slate-500">{cal.season_year}</span>
        </h3>
        {cal.ppv && (
          <span className="label text-[10px] text-gold flex items-center gap-1.5">
            <PPVBadge size={18} finale={cal.is_finale} />
            {cal.ppv}{cal.is_finale ? ' · season finale' : ''}
          </span>
        )}
      </div>

      <div className="grid grid-cols-7 gap-1">
        {DOW.map((d) => (
          <div key={d} className="label text-[9px] text-slate-600 text-center pb-1">{d}</div>
        ))}
        {cells.map((day, i) => {
          const show = day ? byDay.get(day) : undefined
          const st = show ? SHOW_STYLE[show.type] : undefined
          return (
            <div key={i}
              className={`rounded ${compact ? 'h-11' : 'h-16'} p-1 border text-[10px] overflow-hidden
                ${day ? 'border-edge-soft' : 'border-transparent'}`}
              style={st ? { background: st.bg, borderColor: `${st.fg}55` } : undefined}>
              {day && (
                <>
                  <div className="tnum text-[10px] text-slate-500">{day}</div>
                  {show && (
                    <div className="mt-0.5 leading-tight font-semibold" style={{ color: st!.fg }}>
                      <div className="label text-[8px]">{st!.tag}</div>
                      {!compact && show.type === 'PPV' && (
                        <div className="text-[8px] font-normal text-slate-300 truncate">{show.name}</div>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          )
        })}
      </div>

      <div className="flex flex-wrap gap-3 mt-3 pt-3 border-t border-edge-soft">
        {Object.entries(SHOW_STYLE).map(([k, v]) => (
          <span key={k} className="flex items-center gap-1.5 text-[10px] text-slate-500">
            <span className="w-2.5 h-2.5 rounded-sm" style={{ background: v.fg }} />
            {k === 'RAW' ? 'Raw · Mon' : k === 'SMACKDOWN' ? 'SmackDown · Fri'
              : k === 'PPV' ? 'PPV · last Sun' : 'SNME · a Saturday'}
          </span>
        ))}
      </div>
    </div>
  )
}
