import { CAT_MAX, imageUrl, starsFor, type RosterRow } from './api'
import { usePhotos } from './prefs'

/** Match star rating — 0-5 with half stars, Meltzer-style. */
export function Stars({ quality, size = 13 }: { quality: number | null; size?: number }) {
  const s = starsFor(quality)
  const full = Math.floor(s)
  const half = s - full >= 0.5
  return (
    <span className="inline-flex items-center gap-[1px] text-gold" style={{ fontSize: size }}
      title={`${s} stars`}>
      {[0, 1, 2, 3, 4].map((i) => (
        i < full
          ? <span key={i}>★</span>
          : i === full && half
            ? <span key={i} style={{ opacity: 0.5 }}>★</span>
            : <span key={i} className="text-slate-700">☆</span>
      ))}
      <span className="ml-1 stat text-[11px] text-slate-400">{s.toFixed(1)}</span>
    </span>
  )
}

/** Face/heel chip. */
export function AlignChip({ alignment }: { alignment: 'face' | 'heel' }) {
  const face = alignment === 'face'
  return (
    <span className="label text-[9px] px-1.5 py-[2px] rounded"
      style={{ background: face ? 'rgba(52,211,153,0.15)' : 'rgba(179,32,54,0.18)',
               color: face ? '#34d399' : '#f87171' }}>
      {face ? 'FACE' : 'HEEL'}
    </span>
  )
}

/**
 * Portrait thumbnail. Deliberately 3:4 rather than square — the source images
 * are ~2:3, so a square frame with `contain` would letterbox them into a thin
 * strip. Never crops; see `.portrait` in index.css.
 */
export function Avatar({
  row, width = 36, year,
}: { row: RosterRow; width?: number; year?: number }) {
  const height = Math.round(width * 4 / 3)
  const photos = usePhotos()
  // The profile image is whichever one you picked in the gallery; a requested
  // year wins over it, and the first image is the last resort.
  const profile = row.images.find((i) => i.is_profile) ?? row.images[0]
  const pick = year ? row.images.find((i) => i.year === year) ?? profile : profile

  if (!photos || !pick) {
    // Initials beat a broken-image icon, and most of the roster has no photo.
    const initials = row.name.split(/\s+/).slice(0, 2).map((w) => w[0]).join('')
    return (
      <div
        className="rounded shrink-0 grid place-items-center border border-edge bg-raised text-slate-600 label"
        style={{ width, height, fontSize: width * 0.36 }}
      >
        {initials}
      </div>
    )
  }
  return (
    <img
      src={imageUrl(pick.id)}
      alt=""
      loading="lazy"
      className="rounded shrink-0 portrait border border-edge"
      style={{ width, height }}
    />
  )
}

/** Colour a category by how close it is to the 25 cap. */
export function catTone(v: number): string {
  const p = v / CAT_MAX
  if (p >= 0.88) return 'text-emerald-300'
  if (p >= 0.7) return 'text-gold'
  if (p >= 0.45) return 'text-slate-200'
  return 'text-slate-500'
}

/**
 * A category value with a thin fill bar underneath — reads at a glance.
 *
 * `swing` marks a value that is not purely stored: Wrestling carries a live
 * adjustment from her win/loss record, and showing it as `17 ⁺²` rather than
 * just `17` is the difference between a number you trust and a number you
 * assume is a typo when it moves on its own.
 *
 * `title` is for a computed category that owes the reader an explanation —
 * Achievements hangs its reasons ("2× world titles · a Rumble") off the hover.
 */
export function StatCell({ v, edited = false, swing = 0, title }: {
  v: number; edited?: boolean; swing?: number; title?: string
}) {
  const hot = Math.abs(swing) >= 0.5
  return (
    <td className="px-2 py-2 text-right align-middle" title={title}>
      <div className={`stat text-[15px] leading-none ${catTone(v)}`}>
        {v}
        {hot && (
          <span className={`text-[9px] align-super ml-0.5 ${swing > 0 ? 'text-emerald-400' : 'text-blood'}`}>
            {swing > 0 ? '▲' : '▼'}
          </span>
        )}
        {edited && <span className="text-gold text-[9px] align-super ml-0.5">✎</span>}
      </div>
      <div className="h-[3px] mt-1.5 rounded-full bg-edge-soft overflow-hidden ml-auto w-9">
        <div
          className="h-full rounded-full bg-current opacity-70"
          style={{ width: `${(v / CAT_MAX) * 100}%` }}
        />
      </div>
    </td>
  )
}

/** Overall, sized and toned by how good it is. */
export function OverallBadge({ v, colour }: { v: number; colour?: string }) {
  const tone = v >= 70 ? 'text-emerald-300' : v >= 55 ? 'text-gold' : v >= 40 ? 'text-slate-200' : 'text-slate-500'
  return (
    <span className={`stat text-2xl leading-none ${colour ? '' : tone}`} style={colour ? { color: colour } : undefined}>
      {v}
    </span>
  )
}

export function BrandChip({ brand, colour }: { brand: string; colour?: string }) {
  const short = brand === 'SMACKDOWN' ? 'SD' : 'RAW'
  return (
    <span
      className="label text-[9px] px-1.5 py-[3px] rounded"
      style={{
        background: `${colour ?? '#666'}22`,
        color: colour ?? '#999',
        boxShadow: `inset 0 0 0 1px ${colour ?? '#666'}55`,
      }}
    >
      {short}
    </span>
  )
}

export function Pill({
  children, tone = 'slate',
}: { children: React.ReactNode; tone?: 'slate' | 'gold' | 'red' | 'green' }) {
  const tones = {
    slate: 'bg-edge text-slate-300',
    gold: 'bg-gold/15 text-gold',
    red: 'bg-raw/15 text-raw',
    green: 'bg-emerald-400/15 text-emerald-300',
  }
  return <span className={`label text-[9px] px-1.5 py-[3px] rounded ${tones[tone]}`}>{children}</span>
}

/** Section heading used across tabs. */
export function SectionTitle({ children, accent }: { children: React.ReactNode; accent?: string }) {
  return (
    <h3 className="label text-[11px] text-slate-500 mb-2 flex items-center gap-2">
      <span className="w-1 h-3 rounded-full" style={{ background: accent ?? 'var(--color-gold)' }} />
      {children}
    </h3>
  )
}
