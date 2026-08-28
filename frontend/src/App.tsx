import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchRoster, fetchBrands, fetchHealth, newGame, scanImages, syncDrive,
  fetchImageStatus, fetchCalendar, advanceMonth, fetchLogos,
  fetchSettings, saveSettings, money, ageLabel, fetchStoreStatus,
  CATEGORIES, type CategoryKey,
} from './api'
import { setSoundEnabled } from './sound'
import { Avatar, StatCell, OverallBadge, BrandChip, Pill } from './ui'
import { PentagonGlyph, valuesOf } from './Pentagon'
import WrestlerPanel from './WrestlerPanel'
import BrandsTab from './BrandsTab'
import RateTab from './RateTab'
import CardsTab from './CardsTab'
import RivalriesTab from './RivalriesTab'
import Nav, { type Tab } from './Nav'
import BrandTab from './BrandTab'
import DraftTab from './DraftTab'
import ShowsTab from './ShowsTab'
import TradesTab from './TradesTab'
import FreeAgentsTab from './FreeAgentsTab'
import StablesTab from './StablesTab'
import CalendarView from './CalendarView'
import TitlesTab from './TitlesTab'
import HomeTab from './HomeTab'
import RankingsTab from './RankingsTab'
import ProgressionTab from './ProgressionTab'


type SortKey = 'overall' | 'value' | 'age' | 'name' | 'morale' | CategoryKey

type Column = { key: SortKey; label: string; numeric: boolean; hint?: string; sortable?: false }

const COLUMNS: Column[] = [
  { key: 'name', label: 'Wrestler', numeric: false },
  { key: 'age', label: 'Age', numeric: true },
  // A shape has no ordering, so this header does not sort. Marked explicitly
  // rather than left to reuse the overall key, which would have put a second
  // sort arrow on the table and quietly re-sorted on a click.
  { key: 'overall', label: '', numeric: false, sortable: false,
    hint: 'The five ratings as a shape' },
  ...CATEGORIES.map((c) => ({ key: c.key as SortKey, label: c.label, numeric: true, hint: c.hint })),
  { key: 'morale', label: 'MRL', numeric: true },
  { key: 'overall', label: 'OVR', numeric: true },
  { key: 'value', label: 'Value', numeric: true },
]

type View = 'roster' | 'alumni' | 'hof'

// Every roster row is exactly this tall. Measured, not guessed — if the row
// layout ever changes this must change with it, or the scrollbar lies.
const ROW_H = 62
// Rows rendered beyond the viewport on each side, so a fast scroll does not
// show blank space before React catches up.
const OVERSCAN = 8

export default function App() {
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('home')
  const { data: health } = useQuery({ queryKey: ['health'], queryFn: fetchHealth })
  const { data: calendar } = useQuery({ queryKey: ['calendar'], queryFn: fetchCalendar })
  const nextMonth = useMutation({
    mutationFn: advanceMonth,
    onSuccess: () => qc.invalidateQueries(),
  })
  const { data: roster = [], isLoading, error } = useQuery({ queryKey: ['roster'], queryFn: fetchRoster })
  const { data: brands = [] } = useQuery({ queryKey: ['brands'], queryFn: fetchBrands })
  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  // Whether progress is actually being kept. Checked once a minute rather than
  // once, because linking storage and redeploying should clear the warning
  // without anyone thinking to reload.
  const { data: store } = useQuery({
    queryKey: ['storeStatus'], queryFn: fetchStoreStatus, refetchInterval: 60_000,
  })
  const soundOn = settings?.sound === 'on'
  useEffect(() => { setSoundEnabled(soundOn) }, [soundOn])
  const toggleSound = useMutation({
    mutationFn: () => saveSettings({ sound: soundOn ? 'off' : 'on' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  })
  const photosOn = settings?.photos !== 'off'
  const togglePhotos = useMutation({
    mutationFn: () => saveSettings({ photos: photosOn ? 'off' : 'on' }),
    onSuccess: () => qc.invalidateQueries(),
  })

  const [search, setSearch] = useState('')
  const [view, setView] = useState<View>('roster')
  const [status, setStatus] = useState<'all' | 'signed' | 'free'>('all')
  const [brandFilter, setBrandFilter] = useState<string | 'all'>('all')
  const [classFilter, setClassFilter] = useState<number | 'all'>('all')
  const [sort, setSort] = useState<SortKey>('overall')
  const [asc, setAsc] = useState(false)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [showCal, setShowCal] = useState(false)

  const start = useMutation({
    mutationFn: () => newGame(2000),
    onSuccess: () => qc.invalidateQueries(),
  })

  const selected = useMemo(
    () => roster.find((r) => r.id === selectedId) ?? null,
    [roster, selectedId],
  )

  // Which bucket a wrestler belongs to. Hall of Famers stand apart; anyone who
  // has held a contract and no longer has one is an alum; everyone else — signed
  // or still draftable — is on the live roster.
  const bucketOf = (r: (typeof roster)[number]): View =>
    r.hall_of_fame ? 'hof' : r.alumni ? 'alumni' : 'roster'

  const rows = useMemo(() => {
    const term = search.trim().toLowerCase()
    const filtered = roster.filter((r) => {
      if (bucketOf(r) !== view) return false
      if (view === 'roster') {
        if (status === 'signed' && !r.contract) return false
        if (status === 'free' && r.contract) return false
        if (brandFilter !== 'all' && r.contract?.brand_id !== brandFilter) return false
        if (classFilter !== 'all' && r.draft_class !== classFilter) return false
      }
      if (!term) return true
      return r.name.toLowerCase().includes(term)
        || r.ring_names.some((n) => n.toLowerCase().includes(term))
    })
    const dir = asc ? 1 : -1
    return [...filtered].sort((a, b) => {
      if (sort === 'name') return a.name.localeCompare(b.name) * dir
      if (sort === 'morale') return (a.sim.morale - b.sim.morale) * dir
      const va = a[sort] as number | null
      const vb = b[sort] as number | null
      if (va == null && vb == null) return 0
      if (va == null) return 1
      if (vb == null) return -1
      return (va - vb) * dir
    })
  }, [roster, search, view, status, brandFilter, classFilter, sort, asc])

  const counts = useMemo(() => {
    const c: Record<View, number> = { roster: 0, alumni: 0, hof: 0 }
    for (const r of roster) c[bucketOf(r)]++
    return c
  }, [roster])

  const draftClasses = useMemo(
    () => [...new Set(roster.filter((r) => bucketOf(r) === 'roster').map((r) => r.draft_class))].sort((a, b) => a - b),
    [roster],
  )

  function toggleSort(k: SortKey) {
    if (k === sort) setAsc((v) => !v)
    else { setSort(k); setAsc(k === 'name') }
  }

  const save = health?.save

  // WINDOWING. Only the rows in view are rendered; the rest are two spacer rows
  // holding the scrollbar honest. Every roster row is exactly ROW_H tall, which
  // is the property that makes this twenty lines instead of a library.
  const scrollRef = useRef<HTMLElement>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewH, setViewH] = useState(700)

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const onScroll = () => setScrollTop(el.scrollTop)
    el.addEventListener('scroll', onScroll, { passive: true })
    const ro = new ResizeObserver(() => setViewH(el.clientHeight))
    ro.observe(el)
    setViewH(el.clientHeight)
    return () => { el.removeEventListener('scroll', onScroll); ro.disconnect() }
  }, [tab, view])

  // A filter change can leave you scrolled past the end of a now-shorter list.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 })
    setScrollTop(0)
  }, [search, view, status, brandFilter, classFilter, sort, asc])

  const firstRow = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN)
  const lastRow = Math.min(rows.length, Math.ceil((scrollTop + viewH) / ROW_H) + OVERSCAN)
  const visibleRows = rows.slice(firstRow, lastRow)

  // What the rail should badge. Only the one count that is both actionable and
  // free — it falls out of the roster we already have, so no extra request. A
  // badge that costs a round trip to say "0" is not worth having.
  const navBadges = useMemo(() => ({
    rate: roster.filter((r) => !r.removed && !r.edited.personal).length || undefined,
  }) as Partial<Record<Tab, number>>, [roster])

  return (
    <div className="h-full flex flex-col">
      <header className="px-5 py-2 flex items-center gap-4 shrink-0
                         bg-gradient-to-b from-panel to-transparent"
              style={{ borderBottom: '2px solid transparent',
                       borderImage: 'linear-gradient(90deg, var(--color-raw), var(--color-gold) 50%, var(--color-smackdown)) 1' }}>
        <div className="leading-none">
          <h1 className="display text-[20px] leading-none tracking-wide">
            <span className="text-slate-100">WWE</span>{' '}
            <span className="sheen">GM 2000</span>
          </h1>
          <p className="label text-[10px] text-slate-500 mt-1.5">
            {save
              ? <>Season <span className="text-gold">{save.season_year}</span>
                  {calendar?.active && <> · <span className="text-slate-300">{calendar.month_name}</span></>}
                  {' '}· seed {save.rng_seed}</>
              : 'No active save'}
          </p>
        </div>

        <div className="flex-1" />

        {save && calendar?.active && (
          <div className="flex items-center gap-2 mr-1 relative">
            <button
              onClick={() => setShowCal((v) => !v)}
              className="label text-[9px] text-slate-500 flex flex-col items-end leading-tight
                         hover:text-slate-300"
              title="Show the month calendar"
            >
              <span className="text-slate-300">{calendar.month_name} {calendar.season_year}</span>
              {calendar.ppv && <span className="text-gold">◆ {calendar.ppv}</span>}
            </button>
            <button
              onClick={() => nextMonth.mutate()}
              disabled={nextMonth.isPending}
              title="Advance the calendar one month"
              className="text-xs px-2.5 py-1.5 rounded border border-edge hover:border-gold/60 disabled:opacity-40"
            >
              {nextMonth.isPending ? '…' : 'Next month →'}
            </button>
            {showCal && (
              <div className="absolute top-full right-0 mt-2 w-[440px] z-50" onClick={(e) => e.stopPropagation()}>
                <CalendarView cal={calendar} />
              </div>
            )}
          </div>
        )}

        <button
          onClick={() => togglePhotos.mutate()}
          title={photosOn ? 'Images on — click for professional (no-image) mode' : 'Professional mode — click to show images'}
          className={`text-sm px-2 py-1.5 rounded border ${photosOn ? 'border-edge text-slate-500' : 'border-gold/60 text-gold'} hover:border-gold/60`}
        >
          {photosOn ? '🖼️' : '🚫'}
        </button>

        <button
          onClick={() => toggleSound.mutate()}
          title={soundOn ? 'Sound on — click to mute' : 'Sound off — click for bell & crowd'}
          className={`text-sm px-2 py-1.5 rounded border ${soundOn ? 'border-gold/60 text-gold' : 'border-edge text-slate-500'} hover:border-gold/60`}
        >
          {soundOn ? '🔔' : '🔇'}
        </button>

        <button
          onClick={() => start.mutate()}
          disabled={start.isPending}
          className="text-xs px-3 py-1.5 rounded border border-edge hover:border-gold/60 disabled:opacity-40"
          title="Wipes contracts, shows and sim progress. Keeps your rating edits."
        >
          {save ? 'Restart save' : 'New game'}
        </button>
      </header>

      {!save && tab !== 'images' && (
        <div className="px-6 py-2 bg-gold/10 border-b border-gold/30 text-xs text-gold">
          No active save — click <strong>New game</strong> to create brands, budgets and championships.
        </div>
      )}

      {store && !store.durable && (
        <div className="px-4 py-2 flex items-center gap-3 text-[12px]"
          style={{ background: 'rgba(255,43,78,0.14)', borderBottom: '1px solid rgba(255,43,78,0.35)' }}>
          <span className="label text-[10px] px-1.5 py-[3px] rounded bg-raw/25 text-blood shrink-0">
            NOT SAVING
          </span>
          <span className="text-slate-200">
            Nothing you do here is being kept — this host throws its filesystem away.{' '}
            <span className="text-slate-400">{store.durable_detail}</span>
          </span>
          <span className="ml-auto label text-[10px] text-slate-500 shrink-0">
            mode {store.mode}
          </span>
        </div>
      )}
      {store?.error && (
        <div className="px-4 py-2 text-[12px] text-blood"
          style={{ background: 'rgba(255,43,78,0.10)' }}>
          Save sync error: {store.error}
        </div>
      )}

      <div className="flex-1 flex min-h-0">
        <Nav tab={tab} onTab={setTab} brands={brands} pending={navBadges} />
        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">

      {tab === 'roster' && (
        <>
          <div className="px-6 py-2 flex gap-2 items-center border-b border-edge flex-wrap">
            {([['roster', 'Roster'], ['alumni', 'Alumni'], ['hof', 'Hall of Fame']] as const).map(([k, label]) => (
              <button
                key={k}
                onClick={() => setView(k)}
                className={`text-xs px-3 py-1.5 rounded transition-colors ${
                  view === k
                    ? k === 'hof' ? 'bg-gold text-black font-semibold' : 'bg-gold text-black font-semibold'
                    : 'text-slate-400 hover:text-slate-100 hover:bg-panel'
                }`}
              >
                {k === 'hof' && '★ '}{label}
                <span className={view === k ? 'ml-1.5 opacity-70' : 'ml-1.5 text-slate-600'}>{counts[k]}</span>
              </button>
            ))}

            {view === 'roster' && (
              <>
                <span className="w-px h-5 bg-edge mx-1" />
                {(['all', 'free', 'signed'] as const).map((k) => (
                  <button
                    key={k}
                    onClick={() => setStatus(k)}
                    className={`label text-[10px] px-2.5 py-1.5 rounded transition-colors ${
                      status === k ? 'bg-edge text-slate-100' : 'text-slate-500 hover:text-slate-200'
                    }`}
                  >
                    {k === 'all' ? 'Any status' : k === 'free' ? 'Undrafted' : 'Signed'}
                  </button>
                ))}
                {brands.map((b) => (
                  <button
                    key={b.brand_id}
                    onClick={() => setBrandFilter((f) => (f === b.brand_id ? 'all' : b.brand_id))}
                    className="label text-[10px] px-2.5 py-1.5 rounded transition-colors"
                    style={brandFilter === b.brand_id
                      ? { background: b.colour, color: '#000' }
                      : { color: b.colour }}
                  >
                    {b.name}
                  </button>
                ))}
              </>
            )}

            <div className="flex-1" />

            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search any ring name…"
              className="bg-panel border border-edge rounded px-3 py-1.5 text-sm w-56
                         placeholder:text-slate-600 focus:outline-none focus:border-gold/60"
            />
          </div>

          {view === 'roster' && draftClasses.length > 1 && (
            <div className="px-6 py-1.5 flex gap-1.5 items-center border-b border-edge flex-wrap">
              <span className="label text-[9px] text-slate-600 mr-1">Draft class</span>
              <button onClick={() => setClassFilter('all')}
                className={`label text-[10px] px-2 py-1 rounded ${classFilter === 'all' ? 'bg-edge text-slate-100' : 'text-slate-500 hover:text-slate-200'}`}>
                All
              </button>
              {draftClasses.map((yr) => (
                <button key={yr} onClick={() => setClassFilter(yr)}
                  className={`label text-[10px] px-2 py-1 rounded ${classFilter === yr ? 'bg-gold text-black' : 'text-slate-500 hover:text-slate-200'}`}>
                  {yr}
                  <span className={classFilter === yr ? 'ml-1 opacity-70' : 'ml-1 text-slate-600'}>
                    {roster.filter((r) => bucketOf(r) === 'roster' && r.draft_class === yr).length}
                  </span>
                </button>
              ))}
            </div>
          )}

          <div className="flex-1 flex min-h-0">
            <main ref={scrollRef} className="flex-1 overflow-auto">
              {isLoading && <p className="p-6 text-sm text-slate-500">Loading roster…</p>}
              {error && (
                <div className="p-6">
                  <p className="text-sm text-blood mb-1">Could not reach the API.</p>
                  <p className="text-xs text-slate-500">
                    It should be on <code className="text-slate-300">http://localhost:8010</code>. {String(error)}
                  </p>
                </div>
              )}

              {!isLoading && !error && view === 'hof' && rows.length === 0 && (
                <div className="p-8 max-w-lg">
                  <h2 className="display text-[22px] mb-2">★ Hall of Fame</h2>
                  <p className="text-sm text-slate-400 leading-relaxed">
                    Empty for now — the legends are yours to choose. Open any wrestler and
                    hit <strong className="text-gold">Induct into Hall of Fame</strong> to enshrine her here.
                  </p>
                </div>
              )}
              {!isLoading && !error && view === 'alumni' && rows.length === 0 && (
                <div className="p-8 max-w-lg">
                  <h2 className="display text-[22px] mb-2">Alumni</h2>
                  <p className="text-sm text-slate-400 leading-relaxed">
                    Nobody here yet. When a contract expires and isn't renewed, she moves
                    here automatically — released wrestlers land here too.
                  </p>
                </div>
              )}

              {!isLoading && !error && rows.length > 0 && view === 'hof' && (
                <div className="p-6 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
                  {rows.map((r) => (
                    <button key={r.id} onClick={() => setSelectedId(r.id)}
                      className="card p-4 text-left pop-in relative overflow-hidden champ-glow hover:border-gold/60 transition-colors">
                      <div className="flex items-center gap-3">
                        <Avatar row={r} width={54} />
                        <div className="min-w-0">
                          <div className="display text-[18px] leading-tight text-gold truncate">★ {r.name}</div>
                          <div className="text-[11px] text-slate-500 truncate">
                            {r.promotions.join(' · ')}
                          </div>
                          <div className="text-[11px] text-slate-400 mt-1">
                            {r.game_titles.length} title reign{r.game_titles.length !== 1 ? 's' : ''} · {r.accolades.length} accolade{r.accolades.length !== 1 ? 's' : ''}
                          </div>
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              )}

              {!isLoading && !error && rows.length > 0 && view !== 'hof' && (
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-canvas border-b border-edge">
                    <tr>
                      {COLUMNS.map((c) => (
                        <th
                          key={`${c.key}-${c.label}`}
                          onClick={c.sortable === false ? undefined : () => toggleSort(c.key)}
                          title={c.hint}
                          className={`label text-[10px] text-slate-500 px-3 py-3 select-none
                                      ${c.sortable === false ? '' : 'cursor-pointer hover:text-slate-200'}
                                      ${c.numeric ? 'text-right' : 'text-left'}`}
                        >
                          {c.label}
                          {c.sortable !== false && sort === c.key
                            && <span className="ml-1 text-gold">{asc ? '▲' : '▼'}</span>}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {firstRow > 0 && (
                      <tr aria-hidden style={{ height: firstRow * ROW_H }} />
                    )}
                    {visibleRows.map((r, vi) => {
                      // The true position in the list, not in the window — this
                      // is the rank number shown beside the name.
                      const i = firstRow + vi
                      const bc = brands.find((b) => b.brand_id === r.contract?.brand_id)?.colour
                      const champ = r.game_titles.filter((t) => !t.lost_on)
                      const atRisk = r.promises.some((p) => !p.delivered)
                      const roleTag = r.role === 'manager' ? 'Manager' : r.role === 'both' ? 'Wrestler + Manager' : 'Wrestler'
                      return (
                        <tr
                          key={r.id}
                          onClick={() => setSelectedId(r.id)}
                          className={`border-b border-edge-soft cursor-pointer row-hover
                                      ${selectedId === r.id ? 'bg-gold/10' : ''}`}
                          style={selectedId === r.id
                            ? { boxShadow: 'inset 3px 0 0 var(--color-gold)' }
                            : bc ? { boxShadow: `inset 3px 0 0 ${bc}` } : undefined}
                        >
                          <td className="px-3 py-2">
                            <div className="flex items-center gap-3">
                              <span className="stat text-[11px] text-slate-600 w-5 text-right shrink-0">{i + 1}</span>
                              <Avatar row={r} width={34} />
                              <div className="min-w-0">
                                <div className="font-semibold text-[15px] flex items-center gap-1.5 truncate">
                                  {r.name}
                                  {r.hall_of_fame && <span className="text-gold" title="Hall of Fame">★</span>}
                                  {champ.length > 0 && <span title={champ.map((t) => t.name).join(', ')}>👑</span>}
                                  {r.contract && <BrandChip brand={r.contract.brand_id} colour={bc} />}
                                  {r.sim.injured_until && <Pill tone="red">inj</Pill>}
                                  {atRisk && <Pill tone="gold" >promise</Pill>}
                                  {r.streak >= 3 && <Pill tone="green">🔥 W{r.streak}</Pill>}
                                  {r.streak <= -3 && <Pill tone="red">L{-r.streak}</Pill>}
                                </div>
                                <div className="text-[11px] text-slate-500 truncate flex items-center gap-1.5">
                                  {r.nickname && <span className="text-gold/80 italic truncate max-w-[130px]">“{r.nickname}”</span>}
                                  <span>{roleTag}</span>
                                  <span className="text-slate-600">· ’{String(r.draft_class).slice(2)}</span>
                                  {r.contract
                                    ? <span className="text-slate-400">· {money(r.contract.annual_value)}/yr</span>
                                    : r.alumni
                                      ? <span>· former talent</span>
                                      : <span>· undrafted</span>}
                                  {r.sim.matches > 0 && <span>· {r.sim.matches} sim</span>}
                                </div>
                              </div>
                            </div>
                          </td>
                          <td className="px-3 py-2 text-right stat text-[15px] text-slate-400">
                            {ageLabel(r.age, r.age_precision)}
                          </td>
                          {/* Silhouette before the digits. Scanning 370 rows by
                              shape is faster than reading five columns of them. */}
                          <td className="pl-1 pr-0 py-2">
                            <PentagonGlyph
                              values={valuesOf(r)}
                              size={24}
                              title={`${r.name}: ${CATEGORIES.map((c) => `${c.label} ${r[c.key]}`).join(', ')}`}
                              colour={r.contract?.brand_id === 'RAW' ? 'var(--color-raw)'
                                : r.contract?.brand_id === 'SMACKDOWN' ? 'var(--color-smackdown)'
                                : 'var(--color-gold)'}
                            />
                          </td>
                          <StatCell v={r.wrestling} edited={r.edited.wrestling} swing={r.record_swing} />
                          <StatCell v={r.achievements} title={r.achievement_reasons.join(' · ') || 'Nothing won yet in this save'} />
                          <StatCell v={r.popularity} edited={r.edited.popularity} />
                          <StatCell v={r.looks} edited={r.edited.looks} />
                          <StatCell v={r.personal} edited={r.edited.personal} />
                          <td className="px-3 py-2 text-right">
                            <span className={`stat text-[15px] ${r.sim.morale >= 66 ? 'text-emerald-300'
                              : r.sim.morale <= 34 ? 'text-blood' : 'text-slate-400'}`}>
                              {r.sim.morale}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-right"><OverallBadge v={r.overall} /></td>
                          <td className="px-3 py-2 text-right stat text-[15px] text-slate-300">{money(r.value)}</td>
                        </tr>
                      )
                    })}
                    {lastRow < rows.length && (
                      <tr aria-hidden style={{ height: (rows.length - lastRow) * ROW_H }} />
                    )}
                  </tbody>
                </table>
              )}

              {!isLoading && !error && rows.length === 0 && view === 'roster' && (
                <p className="p-6 text-sm text-slate-500">No wrestlers match those filters.</p>
              )}
            </main>

            {selected && (
              <WrestlerPanel row={selected} brands={brands} onClose={() => setSelectedId(null)} />
            )}
          </div>
        </>
      )}

      {tab === 'home' && <HomeTab onGoto={(t) => setTab(t as Tab)} />}
      {tab === 'rate' && <RateTab roster={roster} />}
      {tab === 'cards' && <CardsTab roster={roster} />}
      {tab === 'rivalries' && <RivalriesTab roster={roster} />}
      {tab === 'draft' && <DraftTab roster={roster} />}
      {tab === 'freeagents' && <FreeAgentsTab roster={roster} />}
      {tab === 'raw' && <BrandTab brandId="RAW" roster={roster} />}
      {tab === 'smackdown' && <BrandTab brandId="SMACKDOWN" roster={roster} />}
      {tab === 'stables' && <StablesTab roster={roster} />}
      {tab === 'trades' && <TradesTab roster={roster} />}
      {tab === 'titles' && <TitlesTab />}
      {tab === 'rankings' && <RankingsTab roster={roster} />}
      {tab === 'progression' && <ProgressionTab roster={roster} />}
      {tab === 'league' && <BrandsTab roster={roster} />}
      {tab === 'shows' && <ShowsTab roster={roster} />}
      {tab === 'images' && <ImagesTab />}

      <footer className="border-t border-edge px-6 py-2 text-[11px] text-slate-600 shrink-0">
        {tab === 'roster' && <>{rows.length} shown · </>}
        Each category is out of 20, five summing to 100 · Achievements counts only
        what she has won in THIS save · Wrestling shifts with her win/loss record
        · Looks and Personal are yours · ✎ marks a hand-edited value
      </footer>
        </div>
      </div>
    </div>
  )
}

function ImagesTab() {
  const qc = useQueryClient()
  const { data: st } = useQuery({ queryKey: ['imgstatus'], queryFn: fetchImageStatus })
  const { data: logos } = useQuery({ queryKey: ['logos'], queryFn: fetchLogos })
  const [result, setResult] = useState<any>(null)
  const [folder, setFolder] = useState('')

  const scan = useMutation({
    mutationFn: scanImages,
    onSuccess: (r) => { setResult(r); qc.invalidateQueries({ queryKey: ['roster'] }); qc.invalidateQueries({ queryKey: ['imgstatus'] }) },
    onError: (e: Error) => setResult({ error: e.message }),
  })
  const drive = useMutation({
    mutationFn: () => syncDrive(folder || undefined),
    onSuccess: (r) => { setResult(r); qc.invalidateQueries({ queryKey: ['roster'] }) },
    onError: (e: Error) => setResult({ error: e.message }),
  })

  const logoKeys = new Set(logos?.keys ?? [])
  const LOGO_KEYS = ['raw', 'smackdown', 'world', 'secondary', 'tag', 'cruiserweight', 'hardcore', 'manager']

  return (
    <div className="p-6 overflow-auto space-y-5 max-w-3xl">
      <section className="bg-panel border border-edge rounded p-4">
        <h3 className="font-semibold mb-1">Logos &amp; belts <span className="text-xs font-normal text-slate-500">— optional</span></h3>
        <p className="text-xs text-slate-400 mb-3 leading-relaxed">
          The app draws its own emblems for every belt, brand and PPV. To use your own art instead,
          drop image files (<code className="text-slate-300">.svg .png .webp .jpg</code>) into the logos folder,
          named by key — e.g. <code className="text-slate-300">raw.png</code>, <code className="text-slate-300">world.png</code>,
          <code className="text-slate-300"> wrestlemania.png</code>. Nothing is downloaded for you.
        </p>
        <code className="block text-[11px] text-gold bg-canvas rounded px-2 py-1.5 mb-3 break-all">
          {logos?.root ?? '…'}
        </code>
        <div className="flex flex-wrap gap-1.5">
          {LOGO_KEYS.map((k) => (
            <span key={k} className={`label text-[9px] px-2 py-1 rounded ${
              logoKeys.has(k) ? 'bg-emerald-400/15 text-emerald-300' : 'bg-edge text-slate-500'}`}>
              {logoKeys.has(k) ? '✓ ' : ''}{k}
            </span>
          ))}
        </div>
      </section>

      <section className="bg-panel border border-edge rounded p-4">
        <h3 className="font-semibold mb-1">Local drop folder</h3>
        <p className="text-xs text-slate-400 mb-3 leading-relaxed">
          Drop images into the inbox and press scan. Files are matched on any ring
          name plus a year, so <code className="text-slate-300">Miss Congeniality 1999.jpg</code>{' '}
          files correctly against Lita. Explicit form <code className="text-slate-300">356.2000.jpg</code>{' '}
          always works.
        </p>
        <code className="block text-[11px] text-gold bg-canvas rounded px-2 py-1.5 mb-3 break-all">
          {st?.inbox ?? '…'}
        </code>
        <button
          onClick={() => scan.mutate()}
          disabled={scan.isPending}
          className="text-xs px-3 py-1.5 rounded bg-gold text-black font-semibold disabled:opacity-40"
        >
          {scan.isPending ? 'Scanning…' : 'Scan inbox'}
        </button>
      </section>

      <section className="bg-panel border border-edge rounded p-4">
        <h3 className="font-semibold mb-1">
          Google Drive
          <span className={`ml-2 text-xs font-normal ${st?.drive_ready ? 'text-emerald-400' : 'text-orange-400'}`}>
            {st?.drive_ready ? 'ready' : `not configured — ${st?.drive_detail}`}
          </span>
        </h3>
        <div className="flex gap-2 my-3">
          <input
            value={folder}
            onChange={(e) => setFolder(e.target.value)}
            placeholder="Drive folder ID (or set GM2000_DRIVE_FOLDER_ID)"
            className="flex-1 bg-canvas border border-edge rounded px-2 py-1.5 text-xs
                       placeholder:text-slate-600 focus:outline-none focus:border-gold/60"
          />
          <button
            onClick={() => drive.mutate()}
            disabled={drive.isPending}
            className="text-xs px-3 py-1.5 rounded border border-edge hover:border-gold/60 disabled:opacity-40"
          >
            {drive.isPending ? 'Syncing…' : 'Sync'}
          </button>
        </div>
        {st?.setup && (
          <pre className="text-[10px] text-slate-500 whitespace-pre-wrap leading-relaxed
                          bg-canvas rounded p-3 overflow-x-auto">{st.setup}</pre>
        )}
      </section>

      {result && (
        <section className="bg-panel border border-edge rounded p-4">
          <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-2">Last run</h3>
          <pre className="text-[11px] text-slate-300 whitespace-pre-wrap overflow-x-auto">
            {JSON.stringify(result, null, 2)}
          </pre>
        </section>
      )}
    </div>
  )
}
