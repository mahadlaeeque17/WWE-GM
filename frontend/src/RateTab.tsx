/**
 * The rating sheet — one screen for grinding through 370 wrestlers.
 *
 * WHY THIS EXISTS. Two of the five categories are the GM's outright: Looks and
 * Personal. The roster arrives with Personal on a neutral placeholder for
 * everyone and Looks untouched for most, and the only way to set them was to
 * open a side panel per wrestler. Three hundred and seventy times.
 *
 * So this is built as a KEYBOARD GRID, not a list of forms:
 *
 *   arrows / tab   move between cells
 *   digits         type a value straight in
 *   Enter          commit and drop to the next wrestler in the same column
 *   0-9 then move  the common case — a number and an arrow, no mouse
 *
 * Edits are held locally and saved in ONE request. That is not laziness: on a
 * stateless host every write pushes the whole database to Blob storage, so
 * per-cell saving would upload the same file hundreds of times.
 *
 * ACHIEVEMENTS IS ABSENT. It is computed from what she has won, so there is no
 * cell to type in — the column shows it read-only, because you still want to see
 * it while judging the rest.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  saveRatingsBulk, fetchRatingProgress, CAT_MAX,
  type EditableStat, type RatingEdit, type RosterRow,
} from './api'
import { Avatar, catTone } from './ui'
import { PentagonGlyph } from './Pentagon'

/**
 * Columns of the grid, in the order you tab through them.
 *
 * The first two are ROLE-DEPENDENT. A wrestler is rated on Wrestling and
 * Popularity; a manager on Mic and Influence, because those are the questions
 * worth asking about someone whose job is talking and getting a client over. Same
 * two cells, same keyboard path — the key each one writes to depends on the row.
 */
const COLS: {
  wrestler: EditableStat; manager: EditableStat; label: string; hint: string
}[] = [
  { wrestler: 'wrestling', manager: 'mic', label: 'WRS·MIC',
    hint: 'Wrestlers: in-ring ability (the base — her record moves the shown value). Managers: mic work' },
  { wrestler: 'popularity', manager: 'influence', label: 'POP·INF',
    hint: 'Wrestlers: star power. Managers: how much she elevates her client' },
  { wrestler: 'looks', manager: 'looks', label: 'LKS', hint: 'Yours' },
  { wrestler: 'personal', manager: 'personal', label: 'PER', hint: 'Yours alone' },
]

/** Which key this column writes to for this wrestler. */
const keyFor = (col: typeof COLS[number], role: string): EditableStat =>
  role === 'manager' ? col.manager : col.wrestler

type Filter = 'all' | 'unrated' | 'signed'

export default function RateTab({ roster }: { roster: RosterRow[] }) {
  const qc = useQueryClient()
  const [edits, setEdits] = useState<Record<number, Partial<Record<EditableStat, number>>>>({})
  const [filter, setFilter] = useState<Filter>('unrated')
  const [search, setSearch] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const gridRef = useRef<HTMLTableSectionElement>(null)

  const { data: progress } = useQuery({
    queryKey: ['rating-progress'], queryFn: fetchRatingProgress, staleTime: 5_000,
  })

  const rows = useMemo(() => {
    const term = search.trim().toLowerCase()
    return roster
      .filter((r) => !r.removed)
      // "Unrated" means Personal has never been set — the honest definition of
      // work outstanding, since every wrestler starts with a placeholder there.
      .filter((r) => filter === 'all'
        || (filter === 'unrated' && !r.edited.personal)
        || (filter === 'signed' && !!r.contract))
      .filter((r) => !term || r.name.toLowerCase().includes(term)
        || r.ring_names.some((n) => n.toLowerCase().includes(term)))
      .sort((a, b) => b.overall - a.overall)
  }, [roster, filter, search])

  const dirtyCount = Object.values(edits).reduce((n, e) => n + Object.keys(e).length, 0)

  const value = (r: RosterRow, key: EditableStat): number => {
    const e = edits[r.id]?.[key]
    if (e !== undefined) return e
    // Wrestling's cell edits the BASE. Showing the swung value here would mean
    // typing nothing and still saving a different number than was displayed.
    return key === 'wrestling' ? r.wrestling_base : ((r[key] as number) ?? 10)
  }

  const set = (id: number, key: EditableStat, v: number) => {
    const clamped = Math.max(0, Math.min(CAT_MAX, v))
    setEdits((d) => ({ ...d, [id]: { ...d[id], [key]: clamped } }))
  }

  const save = useMutation({
    mutationFn: () => {
      const payload: RatingEdit[] = Object.entries(edits).map(([id, e]) => ({
        wrestler_id: Number(id), ...e,
      }))
      return saveRatingsBulk(payload)
    },
    onSuccess: () => {
      setEdits({})
      setErr(null)
      qc.invalidateQueries({ queryKey: ['roster'] })
      qc.invalidateQueries({ queryKey: ['rating-progress'] })
      qc.invalidateQueries({ queryKey: ['brands'] })
    },
    onError: (e: Error) => setErr(e.message),
  })

  // Ctrl/Cmd+S saves, because with a grid this size you will want to bank
  // progress without reaching for the mouse.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        if (dirtyCount) save.mutate()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [dirtyCount])

  /** Arrow / Enter navigation across the grid of inputs. */
  const move = (rowIdx: number, colIdx: number, dRow: number, dCol: number) => {
    const nextRow = Math.max(0, Math.min(rows.length - 1, rowIdx + dRow))
    const nextCol = Math.max(0, Math.min(COLS.length - 1, colIdx + dCol))
    const sel = `input[data-cell="${nextRow}-${nextCol}"]`
    const el = gridRef.current?.querySelector<HTMLInputElement>(sel)
    if (el) { el.focus(); el.select() }
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>, ri: number, ci: number) => {
    const el = e.currentTarget
    if (e.key === 'ArrowDown' || e.key === 'Enter') { e.preventDefault(); move(ri, ci, 1, 0) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); move(ri, ci, -1, 0) }
    // Only leave the cell once the caret is already at the edge, so a left/right
    // press still moves through the digits first. This is why the cells are
    // type=text: a number input reports selectionStart as null, so both of these
    // comparisons were false forever and sideways navigation never worked.
    else if (e.key === 'ArrowRight' && el.selectionStart === el.value.length) {
      e.preventDefault(); move(ri, ci, 0, 1)
    } else if (e.key === 'ArrowLeft' && el.selectionStart === 0) {
      e.preventDefault(); move(ri, ci, 0, -1)
    }
  }

  const jumpToNextUnrated = () => {
    const idx = rows.findIndex((r) => !r.edited.personal && !edits[r.id]?.personal)
    if (idx < 0) return
    const el = gridRef.current?.querySelector<HTMLInputElement>(`input[data-cell="${idx}-3"]`)
    el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    el?.focus(); el?.select()
  }

  const pct = progress ? Math.round(((progress.total - progress.personal_todo) / progress.total) * 100) : 0

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* ------------------------------------------------------------- header */}
      <div className="px-4 py-3 border-b border-edge flex flex-wrap items-center gap-3">
        <div>
          <h2 className="display text-lg leading-none">Rating sheet</h2>
          <p className="text-[11px] text-slate-500 mt-1">
            Arrows to move · type a number · Enter drops down a row · Ctrl+S saves
          </p>
        </div>

        {progress && (
          <div className="flex items-center gap-2.5">
            <div className="w-36 h-1.5 rounded-full bg-edge-soft overflow-hidden">
              <div className="h-full rounded-full bg-gold transition-all" style={{ width: `${pct}%` }} />
            </div>
            <span className="stat text-[13px] text-slate-300">{pct}%</span>
            <span className="text-[11px] text-slate-500">
              {progress.personal_todo} of {progress.total} still on the default Personal
              {progress.looks_todo > 0 && <> · {progress.looks_todo} Looks untouched</>}
            </span>
          </div>
        )}

        <div className="ml-auto flex items-center gap-2">
          <input
            value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search…"
            className="bg-canvas border border-edge rounded px-2 py-1 text-xs w-40
                       focus:outline-none focus:border-gold/60"
          />
          {(['unrated', 'signed', 'all'] as Filter[]).map((f) => (
            <button
              key={f} onClick={() => setFilter(f)}
              className={`label text-[10px] px-2.5 py-1 rounded border transition-colors
                ${filter === f ? 'border-gold text-gold bg-gold/10'
                  : 'border-edge text-slate-500 hover:text-slate-200'}`}
            >
              {f}
            </button>
          ))}
          <button
            onClick={jumpToNextUnrated}
            className="label text-[10px] px-2.5 py-1 rounded border border-edge
                       text-slate-400 hover:text-gold hover:border-gold/50"
          >
            next unrated ↓
          </button>
          <button
            onClick={() => save.mutate()}
            disabled={!dirtyCount || save.isPending}
            className={`label text-[10px] px-3 py-1.5 rounded transition-colors
              ${dirtyCount ? 'bg-gold text-canvas hover:bg-gold/85'
                : 'bg-raised text-slate-600 cursor-not-allowed'}`}
          >
            {save.isPending ? 'Saving…' : dirtyCount ? `Save ${dirtyCount}` : 'Saved'}
          </button>
        </div>
      </div>

      {err && (
        <div className="px-4 py-2 text-xs text-blood border-b border-edge-soft">{err}</div>
      )}

      {/* --------------------------------------------------------------- grid */}
      <div className="flex-1 overflow-auto">
        <table className="w-full text-sm border-separate border-spacing-0">
          <thead className="sticky top-0 bg-panel z-10">
            <tr>
              <th className="label text-[10px] text-left px-3 py-2 border-b border-edge">Wrestler</th>
              <th className="label text-[10px] px-1 py-2 border-b border-edge" title="The five ratings as a shape" />
              <th className="label text-[10px] text-right px-2 py-2 border-b border-edge"
                  title="Achievements — earned in this save, not set here">ACH</th>
              {COLS.map((c) => (
                <th key={c.label} title={c.hint}
                    className="label text-[10px] text-right px-2 py-2 border-b border-edge">
                  {c.label}
                </th>
              ))}
              <th className="label text-[10px] text-right px-3 py-2 border-b border-edge">OVR</th>
            </tr>
          </thead>
          <tbody ref={gridRef}>
            {rows.map((r, ri) => {
              // The overall as it WOULD be with the pending edits applied, so the
              // number moves as you type rather than after you save.
              const isMgr = r.role === 'manager'
              const perfA = keyFor(COLS[0], r.role)
              const perfB = keyFor(COLS[1], r.role)
              // The overall as it WOULD be with the pending edits applied. For a
              // wrestler the shown Wrestling includes her record swing, so the
              // base is swapped out for the swung value; a manager has no swing.
              const live = (isMgr ? value(r, perfA) : r.wrestling)
                + r.achievements + value(r, perfB)
                + value(r, 'looks') + value(r, 'personal')
              const pendingVals = [
                isMgr ? value(r, perfA) : r.wrestling, r.achievements,
                value(r, perfB), value(r, 'looks'), value(r, 'personal'),
              ]
              const untouched = !r.edited.personal && edits[r.id]?.personal === undefined
              return (
                <tr key={r.id}
                    className={`border-b border-edge-soft hover:bg-raised/40
                                ${untouched ? '' : 'opacity-95'}`}>
                  <td className="px-3 py-1.5">
                    <div className="flex items-center gap-2 min-w-0">
                      <Avatar row={r} width={24} />
                      <span className="truncate max-w-[220px]">{r.name}</span>
                      {isMgr && (
                        <span className="label text-[9px] text-smackdown shrink-0"
                              title="Rated on Mic and Influence, not Wrestling and Popularity">
                          mgr
                        </span>
                      )}
                      {untouched && (
                        <span className="label text-[9px] text-slate-600 shrink-0"
                              title="Personal has never been set for her">
                          default
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-1 py-1.5">
                    <PentagonGlyph values={pendingVals} size={22}
                                   colour={untouched ? 'var(--color-edge)' : 'var(--color-gold)'} />
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <span className={`stat text-[13px] ${r.achievements ? 'text-gold' : 'text-slate-700'}`}
                          title={r.achievement_reasons.join(' · ') || 'Nothing won yet in this save'}>
                      {r.achievements}
                    </span>
                  </td>
                  {COLS.map((c, ci) => {
                    const ck = keyFor(c, r.role)
                    const v = value(r, ck)
                    const dirty = edits[r.id]?.[ck] !== undefined
                    return (
                      <td key={c.label} className="px-1 py-1">
                        <input
                          data-cell={`${ri}-${ci}`}
                          // NOT type=number. Two reasons, both of which bite in a
                          // grid this size: a number input has no caret position
                          // to read, so sideways arrow navigation is impossible;
                          // and a stray scroll over a focused one silently
                          // changes the rating under the cursor.
                          type="text" inputMode="numeric"
                          aria-label={`${ck} for ${r.name}`}
                          title={isMgr ? `${ck} (manager)` : ck}
                          value={v}
                          onChange={(e) => {
                            const digits = e.target.value.replace(/\D/g, '')
                            set(r.id, ck, digits === '' ? 0 : Number(digits))
                          }}
                          onKeyDown={(e) => onKeyDown(e, ri, ci)}
                          onFocus={(e) => e.currentTarget.select()}
                          className={`w-12 text-right tnum text-[13px] rounded px-1.5 py-0.5
                                      bg-canvas border focus:outline-none focus:border-gold
                                      ${dirty ? 'border-gold/70 text-gold'
                                        : `border-edge ${catTone(v)}`}`}
                        />
                      </td>
                    )
                  })}
                  <td className="px-3 py-1.5 text-right stat text-[15px] text-slate-300">{live}</td>
                </tr>
              )
            })}
          </tbody>
        </table>

        {rows.length === 0 && (
          <p className="p-6 text-sm text-slate-500">
            {filter === 'unrated'
              ? 'Every wrestler has a Personal rating. That is the whole roster done.'
              : 'Nobody matches those filters.'}
          </p>
        )}
      </div>

      <div className="border-t border-edge px-4 py-2 text-[11px] text-slate-600">
        {rows.length} shown · Achievements is earned in the save, not set here ·
        Wrestling edits the base, and her win/loss record moves what the roster
        shows · a <span className="text-smackdown">mgr</span> row is rated on Mic
        and Influence instead
        {dirtyCount > 0 && (
          <span className="text-gold"> · {dirtyCount} unsaved</span>
        )}
      </div>
    </div>
  )
}
