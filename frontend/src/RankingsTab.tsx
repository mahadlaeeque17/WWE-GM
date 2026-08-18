import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchPowerRankings, generatePowerRankings, fetchContenders, lockContender,
  fetchBrands, type Movement, type PowerEntry, type RosterRow, type TitleLadder,
} from './api'
import { Avatar, Pill, SectionTitle } from './ui'
import { BeltEmblem } from './emblems'

const TIER_LABEL: Record<string, string> = {
  world: 'World', secondary: 'Secondary', tag: 'Tag Team',
  cruiserweight: 'Cruiserweight', hardcore: 'Hardcore', manager: 'Managerial',
}

/**
 * The movement column from the old Power 25 page: a green chevron stack for a
 * climb, red for a fall, a flat dash for no change, NR for a debut. The SIZE of
 * the move is in the glyph count, so a one-spot nudge and a ten-spot jump do not
 * look identical.
 */
function Move({ movement, delta }: { movement: Movement; delta: number | null }) {
  if (movement === 'new') {
    return <span className="label text-[10px] text-gold">NR</span>
  }
  if (movement === 'same') {
    return <span className="text-slate-600 text-lg leading-none">—</span>
  }
  const up = movement === 'up'
  const n = Math.min(3, Math.max(1, Math.ceil(Math.abs(delta ?? 1) / 3)))
  return (
    <span className={`leading-[0.6] text-center ${up ? 'text-emerald-400' : 'text-blood'}`}
      title={`${up ? 'up' : 'down'} ${Math.abs(delta ?? 0)}`}>
      {Array.from({ length: n }).map((_, i) => (
        <span key={i} className="block text-[13px]">{up ? '▲' : '▼'}</span>
      ))}
    </span>
  )
}

function PowerRow({ e, row, colour }: { e: PowerEntry; row?: RosterRow; colour?: string }) {
  const top = e.rank_no <= 3
  return (
    <div className="grid items-stretch border-b border-edge/60"
      style={{ gridTemplateColumns: '64px 52px 1fr 72px' }}>
      {/* rank */}
      <div className="grid place-items-center bg-raised/40 border-r border-edge/50">
        <span className={`display leading-none ${top ? 'text-gold' : 'text-slate-200'}`}
          style={{ fontSize: top ? 34 : 27 }}>{e.rank_no}</span>
      </div>
      {/* movement */}
      <div className="grid place-items-center border-r border-edge/50">
        <Move movement={e.movement} delta={e.delta} />
      </div>
      {/* superstar */}
      <div className="flex gap-3 px-3 py-2.5 items-start border-r border-edge/50">
        {row && <Avatar row={row} width={46} />}
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="label text-[12px] tracking-wide"
              style={{ color: colour ?? 'var(--color-gold)' }}>{e.name.toUpperCase()}</span>
            {e.titles.map((t) => <Pill key={t} tone="gold">{t}</Pill>)}
          </div>
          <p className="text-[12px] text-slate-400 leading-snug mt-1">{e.note}</p>
        </div>
      </div>
      {/* last week */}
      <div className="grid place-items-center bg-raised/40">
        <span className="stat text-[17px] text-slate-400">{e.last_week ?? 'NR'}</span>
      </div>
    </div>
  )
}

function Power25({ roster }: { roster: RosterRow[] }) {
  const qc = useQueryClient()
  const [weekOf, setWeekOf] = useState<string | undefined>(undefined)
  const { data, isLoading } = useQuery({
    queryKey: ['power', weekOf ?? 'latest'], queryFn: () => fetchPowerRankings(weekOf),
  })
  const { data: brands = [] } = useQuery({ queryKey: ['brands'], queryFn: fetchBrands })
  const regen = useMutation({
    mutationFn: generatePowerRankings,
    onSuccess: () => { setWeekOf(undefined); qc.invalidateQueries() },
  })

  const byId = new Map(roster.map((r) => [r.id, r]))
  const colourOf = (b: string | null) => brands.find((x) => x.brand_id === b)?.colour

  if (isLoading) return <p className="p-6 text-sm text-slate-500">Loading the board…</p>
  if (!data?.issue) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm text-slate-400">
          No POWER 25 has been published yet. An issue is written automatically every
          time a show is run — or publish one now from the current standings.
        </p>
        <button onClick={() => regen.mutate()} disabled={regen.isPending}
          className="label text-[11px] px-3 py-2 rounded bg-gold/15 text-gold hover:bg-gold/25">
          {regen.isPending ? 'Publishing…' : 'Publish this week'}
        </button>
        {regen.error && <p className="text-xs text-blood">{(regen.error as Error).message}</p>}
      </div>
    )
  }

  return (
    <div className="flex-1 flex min-h-0">
      <div className="flex-1 overflow-auto">
        <div className="grid label text-[10px] text-slate-500 border-b border-edge bg-panel sticky top-0 z-10"
          style={{ gridTemplateColumns: '64px 52px 1fr 72px' }}>
          <div className="px-2 py-2 text-center">This<br />Week</div>
          <div className="px-2 py-2 text-center self-center">Movement</div>
          <div className="px-3 py-2 self-center">Superstar</div>
          <div className="px-2 py-2 text-center">Last<br />Week</div>
        </div>
        {data.entries.map((e) => (
          <PowerRow key={e.rank_no} e={e} row={byId.get(e.wrestler_id)}
            colour={colourOf(e.brand_id)} />
        ))}
      </div>

      {/* ---- right rail, in the spirit of the original page ---- */}
      <aside className="w-[280px] shrink-0 border-l border-edge overflow-auto p-4 space-y-5">
        <div>
          <SectionTitle>Issue</SectionTitle>
          <select
            value={weekOf ?? data.issue.week_of}
            onChange={(ev) => setWeekOf(ev.target.value === data.issues[0]?.week_of
              ? undefined : ev.target.value)}
            className="w-full bg-raised border border-edge rounded px-2 py-1.5 text-xs text-slate-200">
            {data.issues.map((i) => (
              <option key={i.id} value={i.week_of}>
                Week of {i.week_of}{i.week_of === data.issues[0]?.week_of ? ' (current)' : ''}
              </option>
            ))}
          </select>
          <button onClick={() => regen.mutate()} disabled={regen.isPending}
            className="mt-2 w-full label text-[10px] px-3 py-2 rounded bg-gold/15 text-gold hover:bg-gold/25">
            {regen.isPending ? 'Rebuilding…' : 'Rebuild current issue'}
          </button>
          <p className="text-[10px] text-slate-600 mt-2 leading-snug">
            Past issues are never recalculated — rebuilding only republishes the
            current week, so the movement history stays honest.
          </p>
        </div>

        {data.buzz.length > 0 && (
          <div>
            <SectionTitle>What you're saying</SectionTitle>
            <div className="space-y-3">
              {data.buzz.map((b, i) => (
                <div key={i}>
                  <p className="text-[12px] text-slate-300 leading-snug">{b.quote}</p>
                  <p className="text-[11px] text-slate-500 italic mt-0.5">{b.reply}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </aside>
    </div>
  )
}

function Contenders({ roster }: { roster: RosterRow[] }) {
  const qc = useQueryClient()
  const { data: ladders = [], isLoading } = useQuery({
    queryKey: ['contenders'], queryFn: fetchContenders,
  })
  const lock = useMutation({
    mutationFn: ({ t, w }: { t: number; w: number | null }) => lockContender(t, w),
    onSuccess: () => qc.invalidateQueries(),
  })
  const byId = new Map(roster.map((r) => [r.id, r]))

  if (isLoading) return <p className="p-6 text-sm text-slate-500">Loading ladders…</p>
  const ranked = ladders.filter((l) => l.contenders.length)
  if (!ranked.length) {
    return (
      <p className="p-6 text-sm text-slate-500">
        No ladders yet — run a show (or publish a POWER 25 issue) and the contender
        rankings are built alongside it.
      </p>
    )
  }

  return (
    <div className="flex-1 overflow-auto p-4 grid gap-4"
      style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))' }}>
      {ranked.map((l: TitleLadder) => {
        const numberOne = l.contenders[0]
        return (
          <div key={l.title.id} className="panel rounded-lg overflow-hidden">
            <div className="px-3 py-2.5 flex items-center gap-2.5 border-b border-edge bg-raised/40">
              <BeltEmblem tier={l.title.tier} size={26} />
              <div className="min-w-0 flex-1">
                <div className="label text-[11px] text-gold truncate">{l.title.name}</div>
                <div className="text-[10px] text-slate-500">
                  {TIER_LABEL[l.title.tier] ?? l.title.tier} · prestige {l.title.prestige}
                  {' · '}
                  {l.champion ? `champion ${l.champion.name}` : 'vacant'}
                </div>
              </div>
            </div>

            {numberOne && (
              <div className="px-3 py-2.5 flex items-center gap-3 bg-gold/[0.06] border-b border-edge/60">
                {byId.get(numberOne.wrestler_id) &&
                  <Avatar row={byId.get(numberOne.wrestler_id)!} width={40} />}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Pill tone="gold">#1 Contender</Pill>
                    {l.locked_contender === numberOne.wrestler_id && <Pill>Pinned</Pill>}
                  </div>
                  <div className="label text-[12px] text-slate-100 mt-1">{numberOne.name}</div>
                  <p className="text-[11px] text-slate-500 leading-snug">{numberOne.note}</p>
                </div>
              </div>
            )}

            <table className="w-full text-[12px]">
              <tbody>
                {l.contenders.slice(1).map((c) => (
                  <tr key={c.rank_no} className="border-b border-edge/40">
                    <td className="w-8 px-2 py-1.5 stat text-slate-500 text-right">{c.rank_no}</td>
                    <td className="w-6 px-1 py-1.5 text-center">
                      <Move movement={c.movement} delta={c.delta} />
                    </td>
                    <td className="px-2 py-1.5 text-slate-300">{c.name}</td>
                    <td className="px-2 py-1.5 text-right">
                      <button
                        onClick={() => lock.mutate({ t: l.title.id, w: c.wrestler_id })}
                        className="label text-[9px] px-1.5 py-[3px] rounded bg-edge text-slate-400 hover:text-gold">
                        Pin #1
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {l.locked_contender && (
              <div className="px-3 py-2 border-t border-edge/60">
                <button onClick={() => lock.mutate({ t: l.title.id, w: null })}
                  className="label text-[9px] px-2 py-1 rounded bg-edge text-slate-400 hover:text-blood">
                  Clear pinned contender
                </button>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default function RankingsTab({ roster }: { roster: RosterRow[] }) {
  const [view, setView] = useState<'power' | 'contenders'>('power')
  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="flex gap-1 px-4 py-2 border-b border-edge">
        {([['power', 'Power 25'], ['contenders', 'Contenders']] as const).map(([k, label]) => (
          <button key={k} onClick={() => setView(k)}
            className={`label text-[10px] px-3 py-1.5 rounded ${view === k
              ? 'bg-gold/15 text-gold' : 'text-slate-500 hover:text-slate-300'}`}>
            {label}
          </button>
        ))}
      </div>
      {view === 'power' ? <Power25 roster={roster} /> : <Contenders roster={roster} />}
    </div>
  )
}
