import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchStables, fetchBrands, createTeam, updateTeam, disbandTeam,
  createFaction, updateFaction, disbandFaction,
  type RosterRow, type TagTeam, type Faction,
} from './api'

/** Create and manage tag teams and factions. */
export default function StablesTab({ roster }: { roster: RosterRow[] }) {
  const qc = useQueryClient()
  const { data: stables } = useQuery({ queryKey: ['stables'], queryFn: fetchStables })
  const { data: brands = [] } = useQuery({ queryKey: ['brands'], queryFn: fetchBrands })
  const invalidate = () => { qc.invalidateQueries({ queryKey: ['stables'] }); qc.invalidateQueries({ queryKey: ['roster'] }) }

  const colourOf = (b: string | null) => brands.find((x) => x.brand_id === b)?.colour ?? '#64748b'

  const newTeam = useMutation({ mutationFn: () => createTeam('New Tag Team', null, []), onSuccess: invalidate })
  const newFaction = useMutation({ mutationFn: () => createFaction('New Faction', null, null, []), onSuccess: invalidate })

  return (
    <div className="flex-1 overflow-auto p-6 space-y-8">
      {/* ---- tag teams ---- */}
      <section>
        <div className="flex items-center gap-3 mb-3">
          <h2 className="display text-[22px]">Tag Teams</h2>
          <button onClick={() => newTeam.mutate()}
            className="text-xs px-3 py-1.5 rounded bg-gold text-black font-semibold">+ New tag team</button>
        </div>
        <div className="grid grid-cols-2 gap-3">
          {stables?.tag_teams.map((t) => (
            <StableCard key={`t${t.id}`} kind="team" data={t} roster={roster}
              brands={brands} colourOf={colourOf} onChange={invalidate} />
          ))}
          {!stables?.tag_teams.length && <p className="text-sm text-slate-500">No tag teams yet.</p>}
        </div>
      </section>

      {/* ---- factions ---- */}
      <section>
        <div className="flex items-center gap-3 mb-3">
          <h2 className="display text-[22px]">Factions</h2>
          <button onClick={() => newFaction.mutate()}
            className="text-xs px-3 py-1.5 rounded bg-gold text-black font-semibold">+ New faction</button>
        </div>
        <div className="grid grid-cols-2 gap-3">
          {stables?.factions.map((f) => (
            <StableCard key={`f${f.id}`} kind="faction" data={f} roster={roster}
              brands={brands} colourOf={colourOf} onChange={invalidate} />
          ))}
          {!stables?.factions.length && <p className="text-sm text-slate-500">No factions yet.</p>}
        </div>
      </section>
    </div>
  )
}

function StableCard({
  kind, data, roster, brands, colourOf, onChange,
}: {
  kind: 'team' | 'faction'
  data: TagTeam | Faction
  roster: RosterRow[]
  brands: { brand_id: string; name: string; colour: string }[]
  colourOf: (b: string | null) => string
  onChange: () => void
}) {
  const [editName, setEditName] = useState(data.name)
  const isFaction = kind === 'faction'
  const faction = data as Faction
  const memberIds = data.members.map((m) => m.wrestler_id)
  const [adding, setAdding] = useState('')

  const save = (patch: any) => (isFaction ? updateFaction(data.id, patch) : updateTeam(data.id, patch)).then(onChange)
  const del = () => (isFaction ? disbandFaction(data.id) : disbandTeam(data.id)).then(onChange)

  const addable = roster.filter((r) => !r.removed && !memberIds.includes(r.id))
    .sort((a, b) => a.name.localeCompare(b.name))

  return (
    <div className="bg-panel border border-edge rounded p-3"
      style={{ boxShadow: `inset 3px 0 0 ${colourOf(data.brand_id)}` }}>
      <div className="flex items-center gap-2 mb-2">
        <input value={editName} onChange={(e) => setEditName(e.target.value)}
          onBlur={() => editName !== data.name && save({ name: editName })}
          className="flex-1 bg-transparent font-semibold text-[15px] focus:outline-none focus:bg-canvas rounded px-1" />
        <select value={data.brand_id ?? ''} onChange={(e) => save({ brand_id: e.target.value || null })}
          className="bg-canvas border border-edge rounded px-1.5 py-1 text-[11px]">
          <option value="">no brand</option>
          {brands.map((b) => <option key={b.brand_id} value={b.brand_id}>{b.name}</option>)}
        </select>
        <button onClick={del} className="text-[11px] text-blood hover:underline">disband</button>
      </div>

      <div className="flex flex-wrap gap-1.5 mb-2">
        {data.members.map((m) => {
          const isLeader = isFaction && faction.leader_id === m.wrestler_id
          return (
            <span key={m.wrestler_id}
              className={`text-[11px] px-2 py-1 rounded flex items-center gap-1 ${
                isLeader ? 'bg-gold/20 text-gold' : 'bg-edge text-slate-200'}`}>
              {isFaction && (
                <button title="make leader" onClick={() => save({ leader_id: m.wrestler_id })}
                  className={isLeader ? '' : 'opacity-40 hover:opacity-100'}>★</button>
              )}
              {m.name}
              <button onClick={() => save({ members: memberIds.filter((x) => x !== m.wrestler_id) })}
                className="text-slate-500 hover:text-blood">×</button>
            </span>
          )
        })}
        {!data.members.length && <span className="text-[11px] text-slate-600">no members</span>}
      </div>

      <select value={adding} onChange={(e) => { const v = Number(e.target.value); if (v) { save({ members: [...memberIds, v] }); setAdding('') } }}
        className="w-full bg-canvas border border-edge rounded px-2 py-1 text-[11px] text-slate-400">
        <option value="">+ add member…</option>
        {addable.map((r) => <option key={r.id} value={r.id}>{r.name} ({r.overall})</option>)}
      </select>
    </div>
  )
}
