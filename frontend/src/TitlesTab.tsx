import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  fetchGameTitles, fetchLineage, fetchBrands, imageUrl,
  type Reign, type TitleLineage,
} from './api'
import { BeltEmblem, Logo } from './emblems'
import { usePhotos } from './prefs'

const TIER_LABEL: Record<string, string> = {
  world: 'World', secondary: 'Secondary', tag: 'Tag Team',
  cruiserweight: 'Cruiserweight', hardcore: 'Hardcore', manager: 'Managerial',
}

function reignLength(days: number): string {
  if (days < 1) return 'new'
  if (days < 365) return `${days}d`
  const y = Math.floor(days / 365), d = days % 365
  return d ? `${y}y ${d}d` : `${y}y`
}

/** Champion face — profile portrait if we have one, else initials. */
function Face({ id, name, size = 40 }: { id: number | null; name: string; size?: number }) {
  const h = Math.round(size * 4 / 3)
  const photos = usePhotos()
  if (photos && id) return <img src={imageUrl(id)} alt={name} className="rounded portrait border border-edge object-cover"
    style={{ width: size, height: h }} />
  const initials = name.split(/\s+/).slice(0, 2).map((w) => w[0]).join('')
  return (
    <div className="rounded grid place-items-center border border-edge bg-raised text-slate-500 label"
      style={{ width: size, height: h, fontSize: size * 0.34 }}>{initials}</div>
  )
}

export default function TitlesTab() {
  const { data: titles = [] } = useQuery({ queryKey: ['titles'], queryFn: fetchGameTitles })
  const { data: brands = [] } = useQuery({ queryKey: ['brands'], queryFn: fetchBrands })
  const [sel, setSel] = useState<number | null>(null)
  useEffect(() => { if (sel === null && titles.length) setSel(titles[0].id) }, [titles, sel])

  const { data: lineage } = useQuery({
    queryKey: ['lineage', sel], queryFn: () => fetchLineage(sel!), enabled: sel !== null,
  })

  const brandColour = (id: string | null) => brands.find((b) => b.brand_id === id)?.colour

  if (!titles.length) {
    return <p className="p-6 text-sm text-slate-500">No championships yet — start a new game.</p>
  }

  return (
    <div className="flex-1 flex min-h-0">
      {/* ---- belt list ---- */}
      <div className="w-[340px] shrink-0 border-r border-edge overflow-auto">
        {titles.map((t) => {
          const champ = t.champions[0]
          const active = sel === t.id
          return (
            <button key={t.id} onClick={() => setSel(t.id)}
              className={`w-full text-left px-4 py-3 border-b border-edge/50 flex items-center gap-3 transition-colors
                          ${active ? 'bg-gold/10' : 'hover:bg-panel'}`}
              style={active ? { boxShadow: 'inset 3px 0 0 var(--color-gold)' } : undefined}>
              <Logo keyName={t.short_name || t.tier} size={34} fallback={<BeltEmblem tier={t.tier} size={34} />} />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold truncate flex items-center gap-1.5">
                  {t.name}
                  {t.brand_id && <span className="label text-[8px] px-1 rounded"
                    style={{ background: `${brandColour(t.brand_id)}22`, color: brandColour(t.brand_id) }}>
                    {t.brand_id === 'SMACKDOWN' ? 'SD' : 'RAW'}</span>}
                </div>
                <div className="text-[11px] text-slate-500 truncate">
                  {champ ? <>👑 {t.champions.map((c) => c.name).join(' & ')}</>
                    : <span className="text-slate-600">vacant</span>}
                </div>
              </div>
              <div className="text-right shrink-0">
                <div className="stat text-gold text-lg leading-none">{t.prestige}</div>
                <div className="label text-[8px] text-slate-600">prestige</div>
              </div>
            </button>
          )
        })}
      </div>

      {/* ---- lineage ---- */}
      <div className="flex-1 overflow-auto p-6">
        {!lineage ? <p className="text-sm text-slate-500">Loading lineage…</p> : (
          <Lineage lineage={lineage} brandColour={brandColour(lineage.title.brand_id)} />
        )}
      </div>
    </div>
  )
}

function Lineage({ lineage, brandColour }: { lineage: TitleLineage; brandColour?: string }) {
  const { title, reigns, stats } = lineage
  const champs = stats.current_champions

  return (
    <>
      {/* champion banner */}
      <div className="card p-5 mb-5 flex items-center gap-5 relative overflow-hidden pop-in champ-glow">
        <div className="absolute inset-0 pointer-events-none opacity-[0.06]"
          style={{ background: `radial-gradient(circle at 20% 0%, ${brandColour ?? '#e8b93f'}, transparent 60%)` }} />
        <Logo keyName={title.short_name || title.tier} size={64} fallback={<BeltEmblem tier={title.tier} size={64} />} />
        <div className="flex-1 min-w-0">
          <div className="label text-[10px] text-slate-500">{TIER_LABEL[title.tier] ?? title.tier} championship</div>
          <h2 className="display text-[24px] leading-tight">{title.name}</h2>
          <div className="mt-2 flex items-center gap-3">
            {champs.length ? champs.map((c) => (
              <div key={c.wrestler_id} className="flex items-center gap-2">
                <Face id={c.profile_image_id} name={c.name} size={40} />
                <div>
                  <div className="text-sm font-semibold text-gold">{c.name}</div>
                  <div className="text-[11px] text-slate-500">
                    champion · {reignLength(c.days)}{c.age_at_win != null ? ` · won at ${c.age_at_win}` : ''}
                  </div>
                </div>
              </div>
            )) : <span className="text-sm text-slate-500">Vacant — nobody holds it yet.</span>}
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="stat text-gold text-3xl leading-none">{title.prestige}</div>
          <div className="label text-[9px] text-slate-600">prestige</div>
        </div>
      </div>

      {/* records */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
        <Record label="Reigns" value={String(stats.total_reigns)} sub={`${stats.distinct_champions} champions`} />
        <Record label="First champion" value={stats.first_champion?.name ?? '—'}
          sub={stats.first_champion ? stats.first_champion.won_on : ''} />
        <Record label="Longest reign" value={stats.longest_reign ? reignLength(stats.longest_reign.days) : '—'}
          sub={stats.longest_reign?.name ?? ''} />
        <Record label="Most reigns" value={stats.most_reigns ? String(stats.most_reigns.reigns) : '—'}
          sub={stats.most_reigns?.name ?? ''} />
        <Record label="Oldest to win" value={stats.oldest_at_win?.age_at_win != null ? String(stats.oldest_at_win.age_at_win) : '—'}
          sub={stats.oldest_at_win?.name ?? ''} />
        <Record label="Youngest to win" value={stats.youngest_at_win?.age_at_win != null ? String(stats.youngest_at_win.age_at_win) : '—'}
          sub={stats.youngest_at_win?.name ?? ''} />
        <Record label="Shortest reign" value={stats.shortest_reign ? reignLength(stats.shortest_reign.days) : '—'}
          sub={stats.shortest_reign?.name ?? ''} />
        <Record label="Current champion" value={champs[0]?.name ?? 'Vacant'}
          sub={champs[0] ? reignLength(champs[0].days) : ''} />
      </div>

      {/* full history */}
      <h3 className="label text-[11px] text-slate-500 mb-2">Every reign</h3>
      {reigns.length === 0 ? (
        <p className="text-sm text-slate-500">No title change yet — win it in a match to start the lineage.</p>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="label text-[9px] text-slate-500 border-b border-edge">
                <th className="text-left px-3 py-2">#</th>
                <th className="text-left px-3 py-2">Champion</th>
                <th className="text-left px-3 py-2">Won</th>
                <th className="text-left px-3 py-2">Lost</th>
                <th className="text-right px-3 py-2">Reign</th>
                <th className="text-right px-3 py-2">Age</th>
              </tr>
            </thead>
            <tbody>
              {[...reigns].reverse().map((r: Reign) => (
                <tr key={r.reign_no} className={`border-b border-edge-soft ${r.ongoing ? 'bg-gold/5' : ''}`}>
                  <td className="px-3 py-2 tnum text-slate-600">{r.reign_no}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <Face id={r.profile_image_id} name={r.name} size={26} />
                      <span className="font-medium">{r.name}</span>
                      {r.ongoing && <span className="label text-[8px] px-1.5 py-[2px] rounded bg-gold/20 text-gold">current</span>}
                    </div>
                  </td>
                  <td className="px-3 py-2 tnum text-slate-400">{r.won_on}</td>
                  <td className="px-3 py-2 tnum text-slate-500">{r.lost_on ?? '—'}</td>
                  <td className="px-3 py-2 text-right tnum text-slate-300">{reignLength(r.days)}</td>
                  <td className="px-3 py-2 text-right tnum text-slate-400">{r.age_at_win ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

function Record({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card p-3">
      <div className="label text-[9px] text-slate-500">{label}</div>
      <div className="stat text-[17px] text-slate-100 leading-tight truncate mt-0.5">{value}</div>
      {sub && <div className="text-[10px] text-slate-500 truncate">{sub}</div>}
    </div>
  )
}
