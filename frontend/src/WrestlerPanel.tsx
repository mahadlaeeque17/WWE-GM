import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import Gallery from './Gallery'
import {
  saveOverride, clearOverride, extendContract, releaseContract,
  removeWrestler, aiPromo, imageUrl, renameWrestler, aiScouting,
  setTags, clearHoldout, PERSONALITIES, fetchPersonalities, addAccolade, removeAccolade,
  fetchAccoladeKinds, saveBio, ageLabel, money, moneyFull, prettyDate, CAT_MAX, OVERALL_MAX, ROLE_LABEL,
  type RosterRow, type BrandFinance,
} from './api'
import { AlignChip } from './ui'
import { usePhotos } from './prefs'

const CATEGORIES = [
  ['experience', 'Experience', 'Earned in the sim — not real life'],
  ['charisma', 'Charisma', 'Promo skill and likeability'],
  ['popularity', 'Popularity', 'Star power and draw'],
  ['looks', 'Looks', 'Placeholder — cagematch has no looks data'],
] as const

type CatKey = typeof CATEGORIES[number][0]

export default function WrestlerPanel({
  row, brands, onClose,
}: { row: RosterRow; brands: BrandFinance[]; onClose: () => void }) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState<Record<CatKey | 'age', number | null>>({
    experience: row.experience, charisma: row.charisma,
    popularity: row.popularity, looks: row.looks, age: row.age,
  })
  const [years, setYears] = useState(2)
  const [err, setErr] = useState<string | null>(null)

  // Re-seed the editor when a different wrestler is selected, otherwise the
  // previous wrestler's numbers linger in the inputs.
  useEffect(() => {
    setDraft({
      experience: row.experience, charisma: row.charisma,
      popularity: row.popularity, looks: row.looks, age: row.age,
    })
    setTouched(new Set())
    setErr(null)
  }, [row.id])

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['roster'] })
    qc.invalidateQueries({ queryKey: ['brands'] })
  }

  // Which fields this editing session actually touched. Only these get written
  // as overrides — persisting all four every time would freeze the three you
  // never touched at today's derived value, so retuning a formula later would
  // silently skip this wrestler.
  const [touched, setTouched] = useState<Set<CatKey | 'age'>>(new Set())

  const set = (key: CatKey | 'age', v: number | null) => {
    setDraft((d) => ({ ...d, [key]: v }))
    setTouched((t) => new Set(t).add(key))
  }

  const save = useMutation({
    mutationFn: () => {
      // Keep fields already overridden from a previous session, or saving a new
      // edit would wipe them.
      const keep = (k: CatKey | 'age') => touched.has(k) || row.edited[k]
      return saveOverride(row.id, {
        experience: keep('experience') ? draft.experience : null,
        charisma: keep('charisma') ? draft.charisma : null,
        popularity: keep('popularity') ? draft.popularity : null,
        looks: keep('looks') ? draft.looks : null,
        age_at_reset: keep('age') ? draft.age : null,
      })
    },
    onSuccess: () => { setTouched(new Set()); invalidate() },
    onError: (e: Error) => setErr(e.message),
  })

  const reset = useMutation({
    mutationFn: () => clearOverride(row.id),
    onSuccess: invalidate,
    onError: (e: Error) => setErr(e.message),
  })

  const extend = useMutation({
    mutationFn: () => extendContract(row.id, years),
    onSuccess: () => { setErr(null); invalidate() },
    onError: (e: Error) => setErr(e.message),
  })

  const release = useMutation({
    mutationFn: () => releaseContract(row.id),
    onSuccess: () => { setErr(null); invalidate() },
    onError: (e: Error) => setErr(e.message),
  })

  const [confirmRemove, setConfirmRemove] = useState(false)

  const remove = useMutation({
    mutationFn: () => removeWrestler(row.id),
    onSuccess: () => { setErr(null); setConfirmRemove(false); onClose(); invalidate() },
    onError: (e: Error) => setErr(e.message),
  })

  const { data: personalities = [] } = useQuery({ queryKey: ['personalities'], queryFn: fetchPersonalities })
  const personalityEffect = personalities.find((p) => p.key === row.personality)?.effect

  const hofAccolade = row.accolades.find((a) => a.kind === 'hall_of_fame')
  const hof = useMutation({
    mutationFn: () => hofAccolade ? removeAccolade(hofAccolade.id) : addAccolade(row.id, 'hall_of_fame'),
    onSuccess: () => { setErr(null); invalidate() },
    onError: (e: Error) => setErr(e.message),
  })

  const { data: accoladeKinds = [] } = useQuery({ queryKey: ['accoladeKinds'], queryFn: fetchAccoladeKinds })
  const [awardKind, setAwardKind] = useState('')
  const award = useMutation({
    mutationFn: () => addAccolade(row.id, awardKind),
    onSuccess: () => { setErr(null); setAwardKind(''); invalidate() },
    onError: (e: Error) => setErr(e.message),
  })
  const unaward = useMutation({
    mutationFn: (id: number) => removeAccolade(id),
    onSuccess: () => { setErr(null); invalidate() },
    onError: (e: Error) => setErr(e.message),
  })
  // Manual awards you hand out (Playboy cover, Babe/Rookie of the Year, …), minus
  // the Hall of Fame, which has its own button.
  const manualKinds = accoladeKinds.filter((k) => k.source === 'manual' && k.kind !== 'hall_of_fame')

  const [promo, setPromo] = useState<string | null>(null)
  const cutPromo = useMutation({
    mutationFn: () => aiPromo(row.id),
    onSuccess: (r) => { setErr(null); setPromo(r.promo) },
    onError: (e: Error) => setErr(e.message),
  })

  const [nick, setNick] = useState(row.nickname ?? '')
  const [bioDraft, setBioDraft] = useState(row.bio ?? '')
  useEffect(() => { setNick(row.nickname ?? ''); setBioDraft(row.bio ?? '') }, [row.id, row.nickname, row.bio])
  const bio = useMutation({
    mutationFn: () => saveBio(row.id, nick.trim() || null, bioDraft.trim() || null),
    onSuccess: () => { setErr(null); invalidate() },
    onError: (e: Error) => setErr(e.message),
  })

  const [nameDraft, setNameDraft] = useState(row.name)
  useEffect(() => { setNameDraft(row.name) }, [row.id, row.name])
  const rename = useMutation({
    mutationFn: (n: string | null) => renameWrestler(row.id, n),
    onSuccess: () => { setErr(null); invalidate() },
    onError: (e: Error) => setErr(e.message),
  })

  const [scout, setScout] = useState<{ nickname: string | null; report: string; also_known_as: string[] } | null>(null)
  const scouting = useMutation({
    mutationFn: () => aiScouting(row.id),
    onSuccess: (r) => { setErr(null); setScout(r) },
    onError: (e: Error) => setErr(e.message),
  })

  const tags = useMutation({
    mutationFn: (body: Parameters<typeof setTags>[1]) => setTags(row.id, body),
    onSuccess: () => { setErr(null); invalidate() },
    onError: (e: Error) => setErr(e.message),
  })
  const unHoldout = useMutation({
    mutationFn: (brand: string) => clearHoldout(row.id, brand),
    onSuccess: () => { setErr(null); invalidate() },
    onError: (e: Error) => setErr(e.message),
  })

  const dirty = CATEGORIES.some(([k]) => draft[k] !== row[k]) || draft.age !== row.age
  const anyEdited = Object.values(row.edited).some(Boolean)

  const [imgYear, setImgYear] = useState<number | null>(null)  // image id, not year
  // Same precedence as the row avatars: newest dated shot, else the year-0
  // default. Year 0 sorts first, so it must not be picked just by being last.
  const photos = usePhotos()
  const profileImg = row.images.find((i) => i.is_profile) ?? row.images[0]
  const shown = photos ? (row.images.find((i) => i.id === imgYear) ?? profileImg) : undefined

  return (
    <aside className="w-[440px] shrink-0 border-l border-edge bg-panel overflow-y-auto">
      {/* Hero portrait. object-contain, so the whole image is always visible —
          a cropped face is worse than a little letterboxing. */}
      <div className="relative">
        {shown ? (
          <div className="relative h-[330px] bg-canvas overflow-hidden">
            {/* A blurred, darkened copy of the same shot fills the frame so the
                sharp `contain` image on top is never cropped and never floats
                in dead space. */}
            <img
              src={imageUrl(shown.id)}
              alt=""
              aria-hidden="true"
              className="absolute inset-0 w-full h-full object-cover scale-125 blur-2xl opacity-45"
            />
            <img
              src={imageUrl(shown.id)}
              alt={row.name}
              className="relative w-full h-full object-contain"
            />
            <div className="absolute inset-0 scrim pointer-events-none" />
            {row.images.length > 1 && (
              <div className="absolute top-2 left-2 flex gap-1">
                {row.images.map((i) => (
                  <button
                    key={i.id}
                    onClick={() => setImgYear(i.id)}
                    className={`label text-[9px] px-1.5 py-1 rounded backdrop-blur-sm ${
                      i.id === shown.id ? 'bg-gold text-black' : 'bg-black/50 text-slate-300 hover:text-white'
                    }`}
                  >
                    {i.year ?? '—'}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="h-[110px] bg-gradient-to-b from-raised to-panel" />
        )}

        <button
          onClick={onClose}
          className="absolute top-2 right-2 w-7 h-7 grid place-items-center rounded-full
                     bg-black/60 backdrop-blur-sm text-slate-300 hover:text-white hover:bg-black/80"
        >
          ×
        </button>

        <div className={`px-5 ${shown ? '-mt-12 relative' : 'pt-4'} pb-3`}>
          <h2 className="display text-[27px] leading-none text-white"
              style={{ textShadow: '0 2px 14px rgba(0,0,0,0.85)' }}>
            {row.name}
          </h2>
          {row.nickname && (
            <p className="text-[13px] italic text-gold mt-1" style={{ textShadow: '0 2px 10px rgba(0,0,0,0.9)' }}>
              “{row.nickname}”
            </p>
          )}
          <p className="label text-[10px] text-slate-400 mt-1.5 flex items-center gap-1.5 flex-wrap">
            <AlignChip alignment={row.alignment} />
            {row.hall_of_fame && <span className="text-gold">★ HOF</span>}
            <span>{ROLE_LABEL[row.role]}
            {row.style ? ` · ${row.style}` : ''}
            {row.age !== null && ` · age ${ageLabel(row.age, row.age_precision)}`}</span>
          </p>
        </div>
      </div>

      <div className="px-5 py-4">
        {err && (
          <p className="text-xs text-blood bg-blood/10 border border-blood/30 rounded px-3 py-2 mb-4">
            {err}
          </p>
        )}

        {/* -------- rename (display only; canonical name kept for ID) -------- */}
        <section className="mb-4">
          <label className="label text-[10px] text-slate-500">Ring name</label>
          <div className="flex gap-1.5 mt-1">
            <input value={nameDraft} onChange={(e) => setNameDraft(e.target.value)}
              className="flex-1 bg-canvas border border-edge rounded px-2 py-1.5 text-sm
                         focus:outline-none focus:border-gold/60" />
            <button onClick={() => rename.mutate(nameDraft.trim() || null)}
              disabled={rename.isPending || nameDraft === row.name}
              className="text-xs px-3 rounded bg-gold text-black font-semibold disabled:opacity-30">
              Rename
            </button>
            {row.edited.name && (
              <button onClick={() => rename.mutate(null)} title="revert to original"
                className="text-xs px-2 rounded border border-edge text-slate-400 hover:text-slate-100">↺</button>
            )}
          </div>
          {row.name !== row.canonical_name && (
            <p className="text-[10px] text-slate-600 mt-1">
              stored for ID as <span className="text-slate-400">{row.canonical_name}</span>
            </p>
          )}
        </section>

        {/* -------- nickname & bio -------- */}
        <section className="mb-4">
          <label className="label text-[10px] text-slate-500">Nickname</label>
          <input value={nick} onChange={(e) => setNick(e.target.value)}
            placeholder="e.g. The Queen of Extreme"
            className="mt-1 w-full bg-canvas border border-edge rounded px-2 py-1.5 text-sm
                       focus:outline-none focus:border-gold/60" />
          <label className="label text-[10px] text-slate-500 mt-2 block">Bio</label>
          <textarea value={bioDraft} onChange={(e) => setBioDraft(e.target.value)} rows={3}
            placeholder="A couple of sentences on her career…"
            className="mt-1 w-full bg-canvas border border-edge rounded px-2 py-1.5 text-[13px] leading-snug
                       focus:outline-none focus:border-gold/60 resize-y" />
          <button onClick={() => bio.mutate()}
            disabled={bio.isPending || (nick === (row.nickname ?? '') && bioDraft === (row.bio ?? ''))}
            className="mt-1.5 text-xs px-3 py-1 rounded bg-gold text-black font-semibold disabled:opacity-30">
            {bio.isPending ? 'Saving…' : 'Save bio'}
          </button>
        </section>

        {/* -------- booking / persona -------- */}
        <section className="mb-5 card p-4 space-y-3">
          <h3 className="text-xs uppercase tracking-wider text-slate-500">Booking</h3>

          {/* alignment */}
          <div className="flex items-center justify-between">
            <span className="label text-[10px] text-slate-500">Alignment</span>
            <div className="flex gap-1">
              {(['face', 'heel'] as const).map((al) => (
                <button key={al} onClick={() => tags.mutate({ alignment: al })}
                  className={`text-[11px] px-2.5 py-1 rounded ${
                    row.alignment === al
                      ? al === 'face' ? 'bg-emerald-400/20 text-emerald-300' : 'bg-raw/20 text-raw'
                      : 'text-slate-500 hover:text-slate-200'}`}>
                  {al === 'face' ? 'Face' : 'Heel'}
                </button>
              ))}
            </div>
          </div>

          {/* personality */}
          <div className="flex items-center justify-between">
            <span className="label text-[10px] text-slate-500">Personality</span>
            <select value={PERSONALITIES[row.personality] ? row.personality : 'ambitious'}
              onChange={(e) => tags.mutate({ personality: e.target.value })}
              className="bg-canvas border border-edge rounded px-2 py-1 text-xs">
              {Object.entries(PERSONALITIES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
          {personalityEffect && (
            <p className="text-[10px] text-slate-500 leading-snug border-l-2 border-gold/40 pl-2 -mt-1">
              {personalityEffect}
            </p>
          )}

          {/* draft class */}
          <div className="flex items-center justify-between">
            <span className="label text-[10px] text-slate-500">Draft class</span>
            <select value={row.draft_class}
              onChange={(e) => tags.mutate({ draft_class: Number(e.target.value) })}
              className="bg-canvas border border-edge rounded px-2 py-1 text-xs tnum">
              {Array.from({ length: 2026 - 2000 + 1 }, (_, i) => 2000 + i).map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
          </div>

          {/* season role choice — only for BOTH */}
          {row.role === 'both' && (
            <div className="flex items-center justify-between">
              <span className="label text-[10px] text-slate-500">This season's draft</span>
              <select value={row.season_role ?? ''}
                onChange={(e) => tags.mutate({ season_role: e.target.value || null })}
                className="bg-canvas border border-edge rounded px-2 py-1 text-xs">
                <option value="">Either pool</option>
                <option value="wrestler">Wrestler draft only</option>
                <option value="manager">Manager draft only</option>
              </select>
            </div>
          )}

          {/* holdouts */}
          {row.holdout_brands.length > 0 && (
            <div className="text-[11px] text-orange-400 border-t border-edge-soft pt-2">
              Holding out from {row.holdout_brands.join(', ')} this year.
              {row.holdout_brands.map((b) => (
                <button key={b} onClick={() => unHoldout.mutate(b)}
                  className="ml-2 px-2 py-0.5 rounded border border-edge text-slate-300 hover:text-white">
                  reopen {b}
                </button>
              ))}
            </div>
          )}
        </section>

        {/* -------- valuation -------- */}
        <section className="mb-5 card p-4">
          <div className="flex items-end justify-between">
            <div>
              <div className="label text-[9px] text-slate-500">Overall</div>
              <div className="flex items-baseline gap-1">
                <span className="display text-[42px] leading-none sheen">{row.overall}</span>
                <span className="stat text-slate-600 text-sm">/{OVERALL_MAX}</span>
              </div>
            </div>
            <div className="text-right">
              <div className="label text-[9px] text-slate-500">Asking price</div>
              <div className="stat text-[26px] leading-none text-emerald-300">{moneyFull(row.value)}</div>
            </div>
          </div>
          <div className="mt-3 pt-3 border-t border-edge-soft text-[11px] text-slate-500 leading-snug">
            Four categories, each out of {CAT_MAX}. Age {ageLabel(row.age, row.age_precision)} applies a{' '}
            <span className={row.age_multiplier >= 1 ? 'text-emerald-400 font-semibold' : 'text-raw font-semibold'}>
              ×{row.age_multiplier.toFixed(2)}
            </span>{' '}
            {row.age_multiplier >= 1 ? 'youth premium' : 'veteran discount'}.
          </div>
        </section>

        {/* -------- editable ratings -------- */}
        <section className="mb-5">
          <div className="flex justify-between items-center mb-2">
            <h3 className="text-xs uppercase tracking-wider text-slate-500">Ratings</h3>
            {anyEdited && (
              <button
                onClick={() => reset.mutate()}
                className="text-[11px] text-slate-500 hover:text-blood"
              >
                revert all to derived
              </button>
            )}
          </div>

          {CATEGORIES.map(([key, label, hint]) => (
            <div key={key} className="mb-3">
              <div className="flex justify-between text-xs mb-1">
                <span className="label text-[10px] text-slate-400">
                  {label}
                  {row.edited[key] && <span className="ml-1.5 text-gold" title="hand-edited">✎</span>}
                </span>
                <span className="tnum">
                  <input
                    type="number" min={0} max={CAT_MAX}
                    value={draft[key] ?? 0}
                    onChange={(e) => set(key, Number(e.target.value))}
                    className="w-12 bg-canvas border border-edge rounded px-1.5 py-0.5 text-right tnum
                               focus:outline-none focus:border-gold/60"
                  />
                  <span className="text-slate-600 text-[11px]">/{CAT_MAX}</span>
                </span>
              </div>
              <input
                type="range" min={0} max={CAT_MAX}
                value={draft[key] ?? 0}
                onChange={(e) => set(key, Number(e.target.value))}
                className="w-full accent-[var(--color-gold)]"
              />
              <p className="text-[10px] text-slate-600 mt-0.5">{hint}</p>
            </div>
          ))}

          <div className="flex justify-between text-xs mb-1 mt-4">
            <span className="text-slate-400">
              Age on 1 Jan 2000
              {row.edited.age && <span className="ml-1.5 text-gold">✎</span>}
              {row.age_precision !== 'exact' && (
                <span className="ml-1.5 text-slate-600">({row.age_precision.replace('_', ' ')})</span>
              )}
            </span>
            <input
              type="number" min={0} max={120}
              value={draft.age ?? ''}
              onChange={(e) => set('age', e.target.value === '' ? null : Number(e.target.value))}
              className="w-14 bg-canvas border border-edge rounded px-1.5 py-0.5 text-right tnum
                         focus:outline-none focus:border-gold/60"
            />
          </div>

          <button
            disabled={!dirty || save.isPending}
            onClick={() => save.mutate()}
            className="w-full mt-3 py-1.5 rounded text-sm font-semibold transition-colors
                       disabled:opacity-30 disabled:cursor-not-allowed
                       bg-gold text-black hover:bg-gold/85"
          >
            {save.isPending ? 'Saving…' : dirty ? 'Save ratings' : 'No changes'}
          </button>
        </section>

        {/* -------- contract -------- */}
        <section className="mb-5">
          <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-2">Contract</h3>
          {row.contract ? (
            <div className="text-sm">
              <p>
                <span
                  className="font-semibold px-1.5 py-0.5 rounded text-xs"
                  style={{
                    background: `${brands.find((b) => b.brand_id === row.contract!.brand_id)?.colour}33`,
                    color: brands.find((b) => b.brand_id === row.contract!.brand_id)?.colour,
                  }}
                >
                  {row.contract.brand_id}
                </span>
                <span className="text-slate-400"> {moneyFull(row.contract.annual_value)}/yr</span>
              </p>
              <p className="text-xs text-slate-500 mt-1">
                {row.contract.start_year}–{row.contract.end_year} ({row.contract.years} yr
                {row.contract.origin === 'extension' && <span className="text-gold"> · extension</span>})
              </p>

              {row.contract.years > 1 && row.contract.origin !== 'extension' ? (
                <div className="flex items-center gap-2 mt-2">
                  <select
                    value={years}
                    onChange={(e) => setYears(Number(e.target.value))}
                    className="bg-canvas border border-edge rounded px-2 py-1 text-xs"
                  >
                    {[1, 2, 3, 4, 5].map((y) => <option key={y} value={y}>{y} yr</option>)}
                  </select>
                  <button
                    onClick={() => extend.mutate()}
                    disabled={extend.isPending}
                    className="text-xs px-2.5 py-1 rounded border border-edge hover:border-gold/60 disabled:opacity-30"
                  >
                    Extend from {row.contract.end_year + 1}
                  </button>
                </div>
              ) : (
                <p className="text-[11px] text-orange-400 mt-2">
                  {row.contract.origin === 'extension'
                    ? 'An extension cannot itself be extended.'
                    : 'One-year contracts cannot be extended.'}
                </p>
              )}

              <button
                onClick={() => release.mutate()}
                className="mt-2 text-xs px-2.5 py-1 rounded border border-blood/50 text-blood hover:bg-blood/10"
              >
                Release
              </button>

              {row.promises.length > 0 && (
                <div className="mt-3 pt-3 border-t border-edge-soft">
                  <div className="label text-[9px] text-slate-500 mb-1.5">Promises this season</div>
                  <div className="space-y-1">
                    {row.promises.map((p) => (
                      <div key={p.perk} className="flex items-center gap-2 text-[11px]">
                        <span className={p.delivered ? 'text-emerald-400' : 'text-orange-400'}>
                          {p.delivered ? '✓' : '⚠'}
                        </span>
                        <span className="text-slate-300">{p.label}</span>
                        <span className="text-slate-600 ml-auto">{p.detail}</span>
                      </div>
                    ))}
                  </div>
                  <p className="text-[10px] text-slate-600 mt-1.5 leading-snug">
                    Broken promises cost her morale at the season rollover.
                  </p>
                </div>
              )}
            </div>
          ) : (
            <div>
              <p className="text-sm text-slate-400">
                Not on a roster · asking {moneyFull(row.value)}/yr
              </p>
              <p className="text-[11px] text-slate-600 mt-1.5 leading-snug">
                Contracts are only handed out in the <strong className="text-slate-400">Draft</strong> tab —
                there is no free agency.
              </p>
            </div>
          )}
        </section>

        {/* -------- sim record -------- */}
        <section className="mb-5">
          <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-2">This save</h3>
          <div className="grid grid-cols-4 gap-2 text-center">
            <Cell label="Matches" v={row.sim.matches} />
            <Cell label="W–L" v={`${row.sim.wins}–${row.sim.losses}`} />
            <Cell label="Momentum" v={row.sim.momentum} />
            <Cell
              label="Morale"
              v={<span className={row.sim.morale >= 66 ? 'text-emerald-300'
                : row.sim.morale <= 34 ? 'text-blood' : undefined}>{row.sim.morale}</span>}
            />
          </div>
          <div className="grid grid-cols-3 gap-2 text-center mt-2">
            <Cell label="Career $" v={moneyFull(row.career_earnings)} />
            <Cell label="PPVs" v={row.ppv_appearances} />
            <Cell label="Fatigue" v={`${row.sim.fatigue}`} />
          </div>
          {row.sim.injured_until && (
            <p className="text-xs text-blood mt-2">Injured until {row.sim.injured_until}</p>
          )}
          <button
            onClick={() => cutPromo.mutate()} disabled={cutPromo.isPending}
            className="mt-3 text-xs px-3 py-1.5 rounded border border-gold/40 text-gold hover:bg-gold/10 disabled:opacity-40"
          >
            {cutPromo.isPending ? 'On the mic…' : '🤖 Cut a promo (AI)'}
          </button>
          {promo && (
            <p className="text-[13px] text-slate-200 bg-canvas border border-edge rounded p-3 mt-2 leading-relaxed whitespace-pre-line">
              {promo}
            </p>
          )}
        </section>

        {/* -------- history -------- */}
        <section className="mb-5 text-sm space-y-1">
          <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-2">Real career</h3>
          {row.birthday && (
            <Line label="Born">{prettyDate(row.birthday)}{row.birthplace ? ` — ${row.birthplace}` : ''}</Line>
          )}
          <Line label="Promos">
            {row.promotions.join(' · ')}
            {row.history.first_year && ` (${row.history.first_year}–${row.history.last_year})`}
          </Line>
          <Line label="Record">
            <span className="tnum">{row.history.wins}–{row.history.losses}</span>
            <span className="text-slate-500"> in {row.history.matches} recorded</span>
          </Line>
          <Line label="Cagematch">
            {row.rating
              ? <><span className="text-gold font-semibold">{row.rating}</span>{' '}
                  <span className="text-slate-500">from {row.votes} fan votes</span></>
              : <span className="text-slate-500">unrated</span>}
          </Line>
        </section>

        {/* -------- stables -------- */}
        {(row.stables?.tag_teams.length > 0 || row.stables?.factions.length > 0) && (
          <section className="mb-5">
            <h3 className="label text-[10px] text-slate-500 mb-2">Stables</h3>
            <div className="flex flex-wrap gap-1.5">
              {row.stables.tag_teams.map((t) => (
                <span key={`t${t.id}`} className="label text-[9px] px-2 py-1 rounded bg-edge text-slate-200">
                  🤝 {t.name}
                </span>
              ))}
              {row.stables.factions.map((f) => (
                <span key={`f${f.id}`} className="label text-[9px] px-2 py-1 rounded bg-gold/15 text-gold">
                  {f.is_leader ? '★ ' : ''}{f.name}
                </span>
              ))}
            </div>
          </section>
        )}

        {/* -------- scouting (Groq) + nicknames -------- */}
        <section className="mb-5">
          <div className="flex items-center justify-between mb-2">
            <h3 className="label text-[10px] text-slate-500">Scouting report</h3>
            <button onClick={() => scouting.mutate()} disabled={scouting.isPending}
              className="text-[11px] px-2 py-1 rounded border border-gold/40 text-gold hover:bg-gold/10 disabled:opacity-40">
              {scouting.isPending ? 'Scouting…' : scout ? '↻ regenerate' : '🤖 generate (AI)'}
            </button>
          </div>
          {scout ? (
            <div className="text-[13px] text-slate-300 bg-canvas border border-edge rounded p-3 space-y-1.5">
              {scout.nickname && <p className="text-gold font-semibold">“{scout.nickname}”</p>}
              <p className="leading-relaxed">{scout.report}</p>
              {scout.also_known_as.length > 0 && (
                <p className="text-[11px] text-slate-500">a.k.a. {scout.also_known_as.join(' · ')}</p>
              )}
            </div>
          ) : (
            <p className="text-[11px] text-slate-600">
              The AI writes a career blurb + nickname from her rating, votes and history.
            </p>
          )}
        </section>

        {row.ring_names.length > 1 && (
          <section className="mb-5">
            <h3 className="label text-[10px] text-slate-500 mb-2">Ring names</h3>
            <div className="flex flex-wrap gap-1.5">
              {row.ring_names.map((n) => (
                <span key={n} className="text-xs px-2 py-1 rounded bg-edge text-slate-300">{n}</span>
              ))}
            </div>
          </section>
        )}

        {/* -------- gallery -------- */}
        {photos && (
          <section className="mb-5">
            <h3 className="label text-[10px] text-slate-500 mb-2">Images</h3>
            <Gallery wrestlerId={row.id} />
          </section>
        )}

        {/* -------- accolades + hall of fame -------- */}
        <section className="mb-5">
          <div className="flex items-center justify-between mb-2">
            <h3 className="label text-[10px] text-slate-500">Accolades & titles</h3>
            <button
              onClick={() => hof.mutate()}
              disabled={hof.isPending}
              className={`label text-[10px] px-2.5 py-1 rounded border disabled:opacity-40 ${
                row.hall_of_fame
                  ? 'border-gold/60 bg-gold/10 text-gold'
                  : 'border-edge text-slate-400 hover:border-gold/60 hover:text-gold'}`}
              title="The Hall of Fame is yours to curate"
            >
              {row.hall_of_fame ? '★ Remove from Hall of Fame' : '★ Induct into Hall of Fame'}
            </button>
          </div>
          {(row.accolades.length > 0 || row.game_titles.length > 0) ? (
            <div className="flex flex-wrap gap-1.5">
              {row.game_titles.map((t, i) => (
                <span key={`t${i}`} className="label text-[9px] px-2 py-1 rounded bg-gold/15 text-gold">
                  {t.short_name ?? t.name}{!t.lost_on && ' ●'}
                </span>
              ))}
              {row.accolades.map((a) => (
                <button key={a.id} onClick={() => unaward.mutate(a.id)}
                  title="click to remove"
                  className="label text-[9px] px-2 py-1 rounded bg-edge text-slate-300 hover:bg-blood/20 hover:text-blood">
                  {a.label}{a.season_year ? ` ${a.season_year}` : ''} ✕
                </button>
              ))}
            </div>
          ) : (
            <p className="text-[11px] text-slate-600">No titles or awards yet this save.</p>
          )}

          {/* award a manual accolade — pays a bonus */}
          <div className="flex items-center gap-1.5 mt-2">
            <select value={awardKind} onChange={(e) => setAwardKind(e.target.value)}
              className="flex-1 bg-canvas border border-edge rounded px-2 py-1 text-[11px]">
              <option value="">Give an award…</option>
              {manualKinds.map((k) => (
                <option key={k.kind} value={k.kind}>
                  {k.label}{k.bonus ? ` (+${money(k.bonus)})` : ''}
                </option>
              ))}
            </select>
            <button onClick={() => award.mutate()} disabled={!awardKind || award.isPending}
              className="text-[11px] px-2.5 py-1 rounded bg-gold text-black font-semibold disabled:opacity-30">
              Award
            </button>
          </div>
          <p className="text-[10px] text-slate-600 mt-1 leading-snug">
            Awards and title wins pay a one-time cash bonus and a morale lift — real money on top of the salary cap.
          </p>
        </section>

        {/* -------- remove from game (permanent) -------- */}
        <section className="pt-4 border-t border-edge-soft">
          {confirmRemove ? (
            <div>
              <p className="text-xs text-slate-300 mb-2">
                Permanently delete <strong>{row.name}</strong> from the game?
              </p>
              <p className="text-[11px] text-blood mb-2 leading-snug">
                This cannot be undone. She is erased from the roster, every brand, the
                draft pool and her sim history, and can never be re-added.
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => remove.mutate()}
                  disabled={remove.isPending}
                  className="label text-[11px] px-3 py-1.5 rounded bg-raw text-white
                             hover:brightness-110 disabled:opacity-40"
                >
                  {remove.isPending ? 'Deleting…' : 'Delete permanently'}
                </button>
                <button
                  onClick={() => setConfirmRemove(false)}
                  className="label text-[11px] px-3 py-1.5 rounded border border-edge text-slate-400 hover:text-slate-100"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setConfirmRemove(true)}
              className="label text-[11px] px-3 py-1.5 rounded border border-edge
                         text-slate-500 hover:border-raw/60 hover:text-raw"
            >
              Delete from game
            </button>
          )}
        </section>
      </div>
    </aside>
  )
}

function Cell({ label, v }: { label: string; v: React.ReactNode }) {
  return (
    <div className="card py-2">
      <div className="stat text-lg leading-none text-slate-100">{v}</div>
      <div className="label text-[8px] text-slate-500 mt-1">{label}</div>
    </div>
  )
}

function Line({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2">
      <span className="text-slate-500 w-16 shrink-0">{label}</span>
      <span className="text-slate-200">{children}</span>
    </div>
  )
}
