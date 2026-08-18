import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchCalendar, fetchBrands, fetchGameTitles, fetchFeuds, fetchNews, fetchNominations,
  fetchProposals, fetchTrades, fetchSettings, saveSettings, fetchRoster,
  aiProposePick, aiProposeShow, aiProposeTrade, approveProposal, rejectProposal, resolveTrade,
  createFeud, setFeudHeat, settleFeud, crownAward, imageUrl, moneyFull,
  type RosterRow,
} from './api'
import { BeltEmblem, BrandCrest, PPVBadge, Logo } from './emblems'
import { usePhotos } from './prefs'

export default function HomeTab({ onGoto }: { onGoto: (tab: string) => void }) {
  const qc = useQueryClient()
  const { data: cal } = useQuery({ queryKey: ['calendar'], queryFn: fetchCalendar })
  const { data: brands = [] } = useQuery({ queryKey: ['brands'], queryFn: fetchBrands })
  const { data: titles = [] } = useQuery({ queryKey: ['titles'], queryFn: fetchGameTitles })
  const { data: feuds = [] } = useQuery({ queryKey: ['feuds'], queryFn: () => fetchFeuds('active') })
  const { data: news = [] } = useQuery({ queryKey: ['news'], queryFn: () => fetchNews(30) })
  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const { data: proposals = [] } = useQuery({ queryKey: ['proposals'], queryFn: () => fetchProposals() })
  const { data: trades = [] } = useQuery({ queryKey: ['trades', 'pending'], queryFn: () => fetchTrades('pending') })
  const { data: roster = [] } = useQuery({ queryKey: ['roster'], queryFn: fetchRoster })
  const noms = useQuery({ queryKey: ['noms', cal?.season_year], queryFn: () => fetchNominations(cal?.season_year), enabled: !!cal?.season_year })

  const [err, setErr] = useState<string | null>(null)
  const invalidate = () => qc.invalidateQueries()
  const run = (fn: () => Promise<any>) => { setErr(null); return fn().then(invalidate).catch((e: Error) => setErr(e.message)) }

  const aiBrand = settings?.ai_brand ?? null
  const photos = usePhotos()

  const pendingNoms = (noms.data ?? []).filter((n) => n.status === 'nominated')
  const nomKinds = [...new Set(pendingNoms.map((n) => n.kind))]

  if (!brands.length) {
    return <p className="p-6 text-sm text-slate-500">No active save. Click <strong>New game</strong> in the header to begin.</p>
  }

  return (
    <div className="flex-1 overflow-auto p-6 space-y-5">
      {err && <p className="text-xs text-blood bg-blood/10 border border-blood/30 rounded px-3 py-2">{err}</p>}

      {/* ---- top row: next show + AI opponent ---- */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="card p-5 lg:col-span-2 relative overflow-hidden pop-in">
          <div className="label text-[10px] text-slate-500">Season {cal?.season_year} · {cal?.month_name}</div>
          <div className="flex items-center gap-3 mt-1">
            {cal?.ppv && <PPVBadge size={40} finale={cal.is_finale} />}
            <div>
              <div className="display text-[24px] leading-none">{cal?.ppv ?? 'Off-season'}</div>
              <div className="text-[11px] text-slate-500 mt-1">
                {cal?.is_finale ? 'The season finale — WrestleMania closes the year.' : 'This month’s pay-per-view, last Sunday.'}
              </div>
            </div>
            <div className="flex-1" />
            <button onClick={() => onGoto('shows')}
              className="text-xs px-3 py-1.5 rounded bg-gold text-black font-semibold">Go to Shows →</button>
          </div>
        </div>

        <div className="card p-5">
          <div className="label text-[10px] text-slate-500 mb-1">AI opponent</div>
          <p className="text-[11px] text-slate-500 mb-2 leading-snug">
            Hand a brand to the CPU GM. It never acts on its own — every pick, card and trade
            comes to your <strong className="text-slate-300">Approvals</strong> inbox first.
          </p>
          <div className="flex gap-1.5">
            {['', 'RAW', 'SMACKDOWN'].map((b) => (
              <button key={b || 'none'} onClick={() => run(() => saveSettings({ ai_brand: b || null }))}
                className="flex-1 text-xs py-1.5 rounded font-semibold transition-all"
                style={(aiBrand ?? '') === b
                  ? { background: b ? brands.find((x) => x.brand_id === b)?.colour : '#334155', color: '#000' }
                  : { color: '#94a3b8', background: 'rgba(148,163,184,0.1)' }}>
                {b ? (b === 'SMACKDOWN' ? 'SmackDown' : 'Raw') : 'None (you run both)'}
              </button>
            ))}
          </div>
          {aiBrand && (
            <div className="flex flex-wrap gap-1.5 mt-3">
              <button onClick={() => run(aiProposePick)} className="text-[11px] px-2 py-1 rounded border border-edge hover:border-gold/60">AI: draft pick</button>
              <button onClick={() => run(() => aiProposeShow(!!cal?.ppv))} className="text-[11px] px-2 py-1 rounded border border-edge hover:border-gold/60">AI: book a show</button>
              <button onClick={() => run(aiProposeTrade)} className="text-[11px] px-2 py-1 rounded border border-edge hover:border-gold/60">AI: offer a trade</button>
            </div>
          )}
        </div>
      </div>

      {/* ---- approvals inbox ---- */}
      <section className="card p-5">
        <h3 className="label text-[11px] text-slate-400 mb-3 flex items-center gap-2">
          <span className="w-1 h-3 rounded-full bg-gold" /> Approvals inbox
          {(proposals.length + trades.length + pendingNoms.length) > 0 &&
            <span className="label text-[9px] px-1.5 py-[2px] rounded bg-gold text-black">{proposals.length + trades.length + nomKinds.length}</span>}
        </h3>

        {proposals.length === 0 && trades.length === 0 && pendingNoms.length === 0 && (
          <p className="text-sm text-slate-500">Nothing to approve right now. When the AI acts, its proposals land here.</p>
        )}

        {/* AI proposals */}
        {proposals.map((p) => (
          <div key={p.id} className="flex items-center gap-3 py-2 border-b border-edge-soft">
            <span className="label text-[8px] px-1.5 py-[3px] rounded bg-edge text-slate-400">{p.kind.replace('_', ' ')}</span>
            <span className="text-sm flex-1">{p.summary}</span>
            <button onClick={() => run(() => approveProposal(p.id))}
              className="text-[11px] px-2.5 py-1 rounded bg-emerald-500/80 text-black font-semibold">Approve</button>
            <button onClick={() => run(() => rejectProposal(p.id))}
              className="text-[11px] px-2.5 py-1 rounded border border-edge text-slate-400 hover:text-blood">Reject</button>
          </div>
        ))}

        {/* pending trades */}
        {trades.map((t) => (
          <div key={`t${t.id}`} className="flex items-center gap-3 py-2 border-b border-edge-soft">
            <span className="label text-[8px] px-1.5 py-[3px] rounded bg-edge text-slate-400">trade</span>
            <span className="text-sm flex-1">
              {t.from_brand} → {t.to_brand}: {t.assets.map((a) => a.wrestler_name || a.kind).join(', ')}
              {t.note && <span className="text-slate-500"> · {t.note}</span>}
            </span>
            <button onClick={() => run(() => resolveTrade(t.id, true))}
              className="text-[11px] px-2.5 py-1 rounded bg-emerald-500/80 text-black font-semibold">Accept</button>
            <button onClick={() => run(() => resolveTrade(t.id, false))}
              className="text-[11px] px-2.5 py-1 rounded border border-edge text-slate-400 hover:text-blood">Reject</button>
          </div>
        ))}

        {/* award ceremony */}
        {nomKinds.map((kind) => {
          const cands = pendingNoms.filter((n) => n.kind === kind)
          return (
            <div key={kind} className="py-2 border-b border-edge-soft">
              <div className="label text-[9px] text-gold mb-1">🏆 {cands[0].label} {cands[0].season_year} — pick a winner</div>
              <div className="flex flex-wrap gap-1.5">
                {cands.map((n) => (
                  <button key={n.id} onClick={() => run(() => crownAward(n.id))}
                    title={n.detail ?? ''}
                    className="text-[11px] px-2.5 py-1 rounded border border-edge hover:border-gold/60 hover:text-gold">
                    {n.name ?? n.detail}
                  </button>
                ))}
              </div>
            </div>
          )
        })}
      </section>

      {/* ---- champions + cap ---- */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <section className="card p-5 lg:col-span-2">
          <h3 className="label text-[11px] text-slate-400 mb-3 flex items-center gap-2">
            <span className="w-1 h-3 rounded-full bg-gold" /> Champions
            <button onClick={() => onGoto('titles')} className="ml-auto text-[10px] text-slate-500 hover:text-gold">lineage →</button>
          </h3>
          <div className="grid grid-cols-2 gap-3">
            {titles.map((t) => (
              <div key={t.id} className="flex items-center gap-2.5">
                <Logo keyName={t.short_name || t.tier} size={30} fallback={<BeltEmblem tier={t.tier} size={30} />} />
                <div className="min-w-0 flex-1">
                  <div className="text-[11px] text-slate-500 truncate">{t.short_name ?? t.name}</div>
                  <div className="text-sm font-semibold text-gold truncate flex items-center gap-1.5">
                    {t.champions?.length ? (
                      <>
                        {photos && t.champions[0].profile_image_id &&
                          <img src={imageUrl(t.champions[0].profile_image_id)} className="w-6 h-8 rounded object-cover portrait" alt="" />}
                        {t.champions.map((c) => c.name).join(' & ')}
                      </>
                    ) : <span className="text-slate-600 font-normal">vacant</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="card p-5">
          <h3 className="label text-[11px] text-slate-400 mb-3 flex items-center gap-2">
            <span className="w-1 h-3 rounded-full bg-gold" /> Cap space
          </h3>
          {brands.map((b) => {
            const pct = b.budget ? (b.committed / b.budget) * 100 : 0
            return (
              <div key={b.brand_id} className="mb-3">
                <div className="flex items-center gap-2 mb-1">
                  <Logo keyName={b.brand_id.toLowerCase()} size={20} fallback={<BrandCrest brand={b.brand_id} size={20} />} />
                  <span className="text-sm font-semibold" style={{ color: b.colour }}>{b.name}</span>
                  {aiBrand === b.brand_id && <span className="label text-[8px] px-1 rounded bg-edge text-slate-400">AI</span>}
                  <span className="ml-auto text-xs text-emerald-400 tnum">{moneyFull(b.available)} free</span>
                </div>
                <div className="h-2 rounded-full bg-edge overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${Math.min(100, pct)}%`, background: b.colour }} />
                </div>
              </div>
            )
          })}
        </section>
      </div>

      {/* ---- feuds + news ---- */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <FeudsPanel feuds={feuds} roster={roster} onErr={setErr} onDone={invalidate} />
        <section className="card p-5">
          <h3 className="label text-[11px] text-slate-400 mb-3 flex items-center gap-2">
            <span className="w-1 h-3 rounded-full bg-gold" /> This week in the division
          </h3>
          {news.length === 0 && <p className="text-sm text-slate-500">Quiet so far. Sign, book and feud to make headlines.</p>}
          <div className="space-y-1.5 max-h-[340px] overflow-auto">
            {news.map((n) => (
              <div key={n.id} className="flex items-start gap-2 text-[13px]">
                <span className="w-4 shrink-0">{n.icon ?? '•'}</span>
                <span className="text-slate-300 flex-1">{n.text}</span>
                <span className="text-[10px] text-slate-600 tnum shrink-0">{n.on_date?.slice(5)}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}

function heatColour(h: number) {
  return h >= 70 ? '#e0223c' : h >= 40 ? '#e8b93f' : '#64748b'
}

function FeudsPanel({ feuds, roster, onErr, onDone }: {
  feuds: import('./api').Feud[]; roster: RosterRow[]; onErr: (s: string) => void; onDone: () => void
}) {
  const [a, setA] = useState(0)
  const [b, setB] = useState(0)
  const signed = useMemo(() => roster.filter((r) => r.contract).sort((x, y) => x.name.localeCompare(y.name)), [roster])
  const run = (fn: () => Promise<any>) => fn().then(onDone).catch((e: Error) => onErr(e.message))

  return (
    <section className="card p-5">
      <h3 className="label text-[11px] text-slate-400 mb-3 flex items-center gap-2">
        <span className="w-1 h-3 rounded-full bg-blood" /> 🔥 Active feuds
      </h3>
      {feuds.length === 0 && <p className="text-sm text-slate-500 mb-3">No rivalries running. Start one below — booking rivals against each other builds heat.</p>}
      <div className="space-y-3 mb-4">
        {feuds.map((f) => (
          <div key={f.id}>
            <div className="flex items-center gap-2 text-sm">
              <span className="font-medium">{f.a_name}</span>
              <span className="text-slate-600 text-xs">vs</span>
              <span className="font-medium">{f.b_name}</span>
              <span className="ml-auto tnum text-xs" style={{ color: heatColour(f.heat) }}>heat {f.heat}</span>
              <button onClick={() => run(() => settleFeud(f.id))}
                className="text-[10px] px-2 py-0.5 rounded border border-edge text-slate-500 hover:text-slate-200">settle</button>
            </div>
            <input type="range" min={0} max={100} value={f.heat}
              onChange={(e) => run(() => setFeudHeat(f.id, Number(e.target.value)))}
              className="w-full mt-1" style={{ accentColor: heatColour(f.heat) }} />
          </div>
        ))}
      </div>
      <div className="flex items-center gap-1.5 border-t border-edge-soft pt-3">
        <select value={a} onChange={(e) => setA(Number(e.target.value))}
          className="flex-1 min-w-0 bg-canvas border border-edge rounded px-2 py-1 text-[12px]">
          <option value={0}>— wrestler —</option>
          {signed.map((r) => <option key={r.id} value={r.id} disabled={r.id === b}>{r.name}</option>)}
        </select>
        <span className="text-[10px] text-slate-600">vs</span>
        <select value={b} onChange={(e) => setB(Number(e.target.value))}
          className="flex-1 min-w-0 bg-canvas border border-edge rounded px-2 py-1 text-[12px]">
          <option value={0}>— wrestler —</option>
          {signed.map((r) => <option key={r.id} value={r.id} disabled={r.id === a}>{r.name}</option>)}
        </select>
        <button disabled={!a || !b || a === b}
          onClick={() => run(() => createFeud(a, b).then(() => { setA(0); setB(0) }))}
          className="text-[11px] px-2.5 py-1 rounded bg-blood text-white font-semibold disabled:opacity-30">Start</button>
      </div>
    </section>
  )
}
