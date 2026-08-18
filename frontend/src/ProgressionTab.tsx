import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchRatingChanges, evaluateRatings, resolveRatingChange, resolveAllRatingChanges,
  fetchHealth, CAT_MAX, type RatingChange, type RosterRow,
} from './api'
import { Avatar, Pill } from './ui'

const CAT_LABEL: Record<string, string> = {
  charisma: 'Charisma', popularity: 'Popularity', looks: 'Looks',
}

/** from → to as a bar, so the size of the move is visible before you read it. */
function Move({ from, to }: { from: number; to: number }) {
  const up = to > from
  return (
    <div className="flex items-center gap-2">
      <span className="stat text-[15px] text-slate-500">{from}</span>
      <span className={up ? 'text-emerald-400' : 'text-blood'}>{up ? '▶' : '▶'}</span>
      <span className={`stat text-[17px] ${up ? 'text-emerald-300' : 'text-blood'}`}>{to}</span>
      <span className={`label text-[10px] ${up ? 'text-emerald-400' : 'text-blood'}`}>
        {up ? '+' : ''}{to - from}
      </span>
      <div className="ml-1 h-[4px] w-16 rounded-full bg-edge-soft overflow-hidden relative">
        <div className="h-full bg-slate-600" style={{ width: `${(from / CAT_MAX) * 100}%` }} />
        <div className={`h-full absolute top-0 ${up ? 'bg-emerald-400' : 'bg-blood'}`}
          style={{
            left: `${(Math.min(from, to) / CAT_MAX) * 100}%`,
            width: `${(Math.abs(to - from) / CAT_MAX) * 100}%`,
          }} />
      </div>
    </div>
  )
}

function ChangeRow({ c, row, onDone }: {
  c: RatingChange; row?: RosterRow; onDone: () => void
}) {
  const [value, setValue] = useState(c.to_value)
  const resolve = useMutation({
    mutationFn: (approve: boolean) => resolveRatingChange(c.id, approve, approve ? value : undefined),
    onSuccess: onDone,
  })
  const edited = value !== c.suggested

  return (
    <div className="panel rounded-lg p-3 flex gap-3 items-start">
      {row && <Avatar row={row} width={48} />}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="label text-[12px] text-slate-100">{c.name}</span>
          <Pill tone={c.to_value > c.from_value ? 'green' : 'red'}>{CAT_LABEL[c.category]}</Pill>
          <span className="label text-[9px] text-slate-600">SEASON {c.season_year}</span>
          {c.score != null && (
            <span className="label text-[9px] text-slate-500">GRADE {Math.round(c.score)}/100</span>
          )}
        </div>

        <div className="mt-2"><Move from={c.from_value} to={value} /></div>

        <p className="text-[11px] text-slate-500 leading-snug mt-2">{c.reason}</p>

        <div className="flex items-center gap-2 mt-2.5 flex-wrap">
          <label className="label text-[9px] text-slate-600">Approve at</label>
          <input type="number" min={1} max={CAT_MAX} value={value}
            onChange={(e) => setValue(Math.max(1, Math.min(CAT_MAX, +e.target.value || 1)))}
            className="w-16 bg-raised border border-edge rounded px-2 py-1 stat text-[13px] text-slate-100" />
          {edited && (
            <button onClick={() => setValue(c.suggested)}
              className="label text-[9px] text-slate-500 hover:text-gold">
              reset to {c.suggested}
            </button>
          )}
          <div className="flex-1" />
          <button onClick={() => resolve.mutate(true)} disabled={resolve.isPending}
            className="label text-[10px] px-3 py-1.5 rounded bg-emerald-400/15 text-emerald-300 hover:bg-emerald-400/25">
            Approve
          </button>
          <button onClick={() => resolve.mutate(false)} disabled={resolve.isPending}
            className="label text-[10px] px-3 py-1.5 rounded bg-raw/15 text-blood hover:bg-raw/25">
            Reject
          </button>
        </div>
        {resolve.error && (
          <p className="text-[11px] text-blood mt-1">{(resolve.error as Error).message}</p>
        )}
      </div>
    </div>
  )
}

export default function ProgressionTab({ roster }: { roster: RosterRow[] }) {
  const qc = useQueryClient()
  const [status, setStatus] = useState<'pending' | 'approved' | 'rejected'>('pending')
  const { data: health } = useQuery({ queryKey: ['health'], queryFn: fetchHealth })
  const season = health?.save?.season_year

  const { data: changes = [], isLoading } = useQuery({
    queryKey: ['ratingChanges', status], queryFn: () => fetchRatingChanges(status),
  })
  const invalidate = () => qc.invalidateQueries()

  const evaluate = useMutation({ mutationFn: () => evaluateRatings(), onSuccess: invalidate })
  const bulk = useMutation({
    mutationFn: (approve: boolean) => resolveAllRatingChanges(approve),
    onSuccess: invalidate,
  })

  const byId = new Map(roster.map((r) => [r.id, r]))
  const ups = changes.filter((c) => c.delta > 0).length
  const downs = changes.filter((c) => c.delta < 0).length

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="px-4 py-3 border-b border-edge flex items-center gap-2 flex-wrap">
        {(['pending', 'approved', 'rejected'] as const).map((s) => (
          <button key={s} onClick={() => setStatus(s)}
            className={`label text-[10px] px-3 py-1.5 rounded ${status === s
              ? 'bg-gold/15 text-gold' : 'text-slate-500 hover:text-slate-300'}`}>
            {s}
          </button>
        ))}
        <div className="flex-1" />
        {status === 'pending' && changes.length > 0 && (
          <>
            <span className="label text-[10px] text-emerald-400">{ups} ▲</span>
            <span className="label text-[10px] text-blood">{downs} ▼</span>
            <button onClick={() => bulk.mutate(true)} disabled={bulk.isPending}
              className="label text-[10px] px-3 py-1.5 rounded bg-emerald-400/15 text-emerald-300 hover:bg-emerald-400/25">
              Approve all
            </button>
            <button onClick={() => bulk.mutate(false)} disabled={bulk.isPending}
              className="label text-[10px] px-3 py-1.5 rounded bg-raw/15 text-blood hover:bg-raw/25">
              Reject all
            </button>
          </>
        )}
        <button onClick={() => evaluate.mutate()} disabled={evaluate.isPending}
          className="label text-[10px] px-3 py-1.5 rounded bg-gold/15 text-gold hover:bg-gold/25">
          {evaluate.isPending ? 'Grading…' : `Re-grade ${season ?? 'season'}`}
        </button>
      </div>

      <div className="flex-1 overflow-auto p-4">
        <p className="text-[11px] text-slate-600 mb-3 max-w-3xl leading-snug">
          Charisma, popularity and looks move at the end of each season based on what
          she actually did — record, match quality, main events, title reigns, weeks
          in the POWER 25, awards, momentum and age. <span className="text-slate-400">
          Nothing here is applied until you approve it</span>, and you can approve at a
          different number than the one suggested. Experience is not listed: it is
          already earned in the sim and updates itself.
        </p>

        {isLoading && <p className="text-sm text-slate-500">Loading…</p>}
        {!isLoading && !changes.length && (
          <div className="text-sm text-slate-500 space-y-2">
            <p>Nothing {status}.</p>
            {status === 'pending' && (
              <p className="text-[12px] text-slate-600">
                Suggestions are generated automatically when a season rolls over. To
                see where the roster stands mid-season, hit <em>Re-grade</em>.
              </p>
            )}
          </div>
        )}

        <div className="grid gap-2.5"
          style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(440px, 1fr))' }}>
          {changes.map((c) => (
            status === 'pending'
              ? <ChangeRow key={c.id} c={c} row={byId.get(c.wrestler_id)} onDone={invalidate} />
              : (
                <div key={c.id} className="panel rounded-lg p-3 flex gap-3 items-center">
                  {byId.get(c.wrestler_id) && <Avatar row={byId.get(c.wrestler_id)!} width={38} />}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="label text-[12px] text-slate-200">{c.name}</span>
                      <Pill>{CAT_LABEL[c.category]}</Pill>
                      <span className="label text-[9px] text-slate-600">S{c.season_year}</span>
                    </div>
                    <div className="mt-1"><Move from={c.from_value} to={c.to_value} /></div>
                  </div>
                  <Pill tone={c.status === 'approved' ? 'green' : 'red'}>{c.status}</Pill>
                </div>
              )
          ))}
        </div>
      </div>
    </div>
  )
}
