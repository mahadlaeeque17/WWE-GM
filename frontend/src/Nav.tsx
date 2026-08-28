/**
 * The left rail.
 *
 * WHY IT REPLACED THE TAB STRIP. Fifteen tabs across the top wrapped onto a
 * second line at anything under a wide desktop, and a flat list of fifteen has
 * no shape — "Trades", "Titles" and "Rankings" sat side by side as though they
 * were the same kind of thing. Down the side they get room to be GROUPED, and
 * the grouping is the actual information: what you do with talent, what you do
 * with a brand, what you do on a show night, what happens at the end of a year.
 *
 * Collapsible to an icon rail, because on a laptop the roster table wants every
 * pixel it can get. The choice is remembered.
 */
import { useEffect, useState } from 'react'

export type Tab =
  | 'home' | 'roster' | 'rate' | 'draft' | 'freeagents'
  | 'raw' | 'smackdown' | 'stables' | 'trades' | 'league'
  | 'shows' | 'titles' | 'rankings' | 'progression' | 'images' | 'cards'
  | 'rivalries'

type Item = { key: Tab; label: string; icon: string; brand?: string; hint?: string }
type Group = { title: string; items: Item[] }

/**
 * Grouped by what you are trying to DO, not by which screen was built first.
 * Icons are single glyphs rather than an icon font — no dependency, and they
 * survive the collapsed rail where the label cannot.
 */
export const GROUPS: Group[] = [
  { title: '', items: [
    { key: 'home', label: 'Home', icon: '◆', hint: 'Approvals, champions, cap space, this week' },
  ]},
  { title: 'Talent', items: [
    { key: 'roster', label: 'Roster', icon: '☰', hint: 'Everyone, sortable by any rating' },
    { key: 'rate', label: 'Rate', icon: '✎', hint: 'Set Looks and Personal across the roster' },
    { key: 'cards', label: 'Cards', icon: '🂠', hint: "Every season's set of player cards" },
    { key: 'draft', label: 'Draft', icon: '⇩', hint: 'Build your brands' },
    { key: 'freeagents', label: 'Free Agents', icon: '✚', hint: 'Sign anyone unsigned' },
  ]},
  { title: 'Brands', items: [
    { key: 'raw', label: 'Raw', icon: '●', brand: 'RAW' },
    { key: 'smackdown', label: 'SmackDown', icon: '●', brand: 'SMACKDOWN' },
    { key: 'stables', label: 'Stables', icon: '⛓', hint: 'Tag teams and factions' },
    { key: 'trades', label: 'Trades', icon: '⇄' },
    { key: 'league', label: 'League', icon: '$', hint: 'Budgets, payroll, cap space' },
  ]},
  { title: 'Show night', items: [
    { key: 'shows', label: 'Shows', icon: '▶', hint: 'Book a card, run the Rumble' },
    { key: 'titles', label: 'Titles', icon: '♛', hint: 'Championships and lineage' },
    { key: 'rankings', label: 'Rankings', icon: '↑', hint: 'The Power 25 and contenders' },
    { key: 'rivalries', label: 'Rivalries', icon: '⚔', hint: "The save's feuds, ranked by more than meeting count" },
  ]},
  { title: 'Season', items: [
    { key: 'progression', label: 'Progression', icon: '↗', hint: 'Year-end rating changes to approve' },
    { key: 'images', label: 'Images', icon: '▣', hint: 'Portraits' },
  ]},
]

const STORAGE_KEY = 'gm2000.nav.collapsed'

export default function Nav({
  tab, onTab, brands, pending,
}: {
  tab: Tab
  onTab: (t: Tab) => void
  brands: { brand_id: string; colour?: string }[]
  /** Badge counts per tab — approvals waiting, ratings unset, and so on. */
  pending?: Partial<Record<Tab, number>>
}) {
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(STORAGE_KEY) === '1' } catch { return false }
  })
  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0') } catch { /* private mode */ }
  }, [collapsed])

  return (
    <nav
      // Width as an inline style, not a utility class. A flex item also needs
      // min-width:0 or `min-width:auto` quietly holds it at its content size and
      // the collapse does nothing — which is exactly what it did.
      className="shrink-0 border-r border-edge bg-panel/40 flex flex-col overflow-hidden"
      style={{
        width: collapsed ? 52 : 178,
        minWidth: 0,
        transition: 'width 150ms ease',
      }}
      aria-label="Sections"
    >
      <div className="flex-1 overflow-y-auto overflow-x-hidden py-2">
        {GROUPS.map((g, gi) => (
          <div key={g.title || gi} className={gi ? 'mt-3' : ''}>
            {g.title && !collapsed && (
              <div className="label text-[9px] text-slate-600 px-3 pb-1">{g.title}</div>
            )}
            {g.title && collapsed && <div className="mx-3 my-2 border-t border-edge-soft" />}

            {g.items.map((it) => {
              const colour = it.brand
                ? brands.find((b) => b.brand_id === it.brand)?.colour
                : undefined
              const active = tab === it.key
              const badge = pending?.[it.key]
              return (
                <button
                  key={it.key}
                  onClick={() => onTab(it.key)}
                  title={collapsed ? it.label : it.hint}
                  aria-current={active ? 'page' : undefined}
                  className={`w-full flex items-center gap-2.5 px-3 py-[7px] text-left
                              relative transition-colors group
                              ${active ? 'text-slate-50' : 'text-slate-400 hover:text-slate-100 hover:bg-raised/50'}`}
                  style={active
                    ? { background: colour ? `${colour}22` : 'rgba(255,200,61,0.10)' }
                    : undefined}
                >
                  {/* The active marker is a spine on the edge, not a filled pill —
                      a full-bleed highlight on fifteen items reads as noise. */}
                  <span
                    aria-hidden
                    className="absolute left-0 top-0 bottom-0 w-[2px] transition-colors"
                    style={{ background: active ? (colour || 'var(--color-gold)') : 'transparent' }}
                  />
                  <span
                    className="w-4 text-center text-[13px] shrink-0 leading-none"
                    style={{ color: active ? (colour || 'var(--color-gold)') : undefined }}
                  >
                    {it.icon}
                  </span>
                  {!collapsed && (
                    <span className="label text-[11px] truncate flex-1">{it.label}</span>
                  )}
                  {badge ? (
                    <span
                      className={`stat text-[10px] leading-none rounded-full bg-gold text-canvas
                                  ${collapsed ? 'absolute top-1 right-1 px-1' : 'px-1.5 py-[2px]'}`}
                      title={`${badge} waiting`}
                    >
                      {badge > 99 ? '99+' : badge}
                    </span>
                  ) : null}
                </button>
              )
            })}
          </div>
        ))}
      </div>

      <button
        onClick={() => setCollapsed((v) => !v)}
        className="border-t border-edge px-3 py-2 text-slate-600 hover:text-gold
                   label text-[10px] flex items-center gap-2"
        title={collapsed ? 'Expand the menu' : 'Collapse to icons'}
      >
        <span className="w-4 text-center leading-none">{collapsed ? '»' : '«'}</span>
        {!collapsed && <span>Collapse</span>}
      </button>
    </nav>
  )
}
