import { useQuery } from '@tanstack/react-query'
import { fetchLogos, logoUrl } from './api'
import { usePhotos } from './prefs'

/**
 * Original, house-drawn emblems — no copyrighted brand art is bundled or fetched.
 * If the user drops their own file into data/logos (keyed by name), <Logo> shows
 * it instead of the SVG.
 */
export function useLogos() {
  const { data } = useQuery({ queryKey: ['logos'], queryFn: fetchLogos, staleTime: 60_000 })
  return new Set(data?.keys ?? [])
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '')

/** Renders a user-supplied override image for `keyName` if present, else `fallback`. */
export function Logo({
  keyName, fallback, size = 28, alt = '',
}: { keyName: string; fallback: React.ReactNode; size?: number; alt?: string }) {
  const logos = useLogos()
  const photos = usePhotos()
  const k = slug(keyName)
  // Professional mode hides user-supplied logo IMAGES too — fall back to the
  // neutral vector emblem.
  if (photos && logos.has(k)) {
    return <img src={logoUrl(k)} alt={alt} style={{ height: size, width: 'auto', maxWidth: size * 2.4 }}
      className="object-contain inline-block" />
  }
  return <>{fallback}</>
}

// ---------------------------------------------------------------- belt emblems

const TIER: Record<string, { a: string; b: string; edge: string }> = {
  world:         { a: '#ffe9a8', b: '#e8b93f', edge: '#8a6410' },
  secondary:     { a: '#e8edf5', b: '#aebacb', edge: '#5b6677' },
  tag:           { a: '#ffe9a8', b: '#d8a53a', edge: '#8a6410' },
  cruiserweight: { a: '#bff3ea', b: '#4fd1c5', edge: '#1f7a70' },
  hardcore:      { a: '#ffb3bd', b: '#e0223c', edge: '#7a0e1c' },
  manager:       { a: '#e6d4ff', b: '#a855f7', edge: '#5b2b8a' },
}

/** A championship belt plate, coloured by tier. Pure SVG, scales cleanly. */
export function BeltEmblem({ tier, size = 34 }: { tier: string; size?: number }) {
  const c = TIER[tier] ?? TIER.world
  const id = `belt-${tier}`
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
      <defs>
        <linearGradient id={`${id}-g`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={c.a} />
          <stop offset="0.5" stopColor={c.b} />
          <stop offset="1" stopColor={c.edge} />
        </linearGradient>
      </defs>
      {/* strap */}
      <rect x="1" y="19" width="46" height="10" rx="3" fill="#171d29" stroke="#232b3a" />
      {/* side plates */}
      <circle cx="8" cy="24" r="4.5" fill={`url(#${id}-g)`} stroke={c.edge} strokeWidth="0.8" />
      <circle cx="40" cy="24" r="4.5" fill={`url(#${id}-g)`} stroke={c.edge} strokeWidth="0.8" />
      {/* centre plate — a rounded shield */}
      <path d="M24 6 L38 12 L38 26 Q38 38 24 43 Q10 38 10 26 L10 12 Z"
        fill={`url(#${id}-g)`} stroke={c.edge} strokeWidth="1.4" />
      <path d="M24 6 L38 12 L38 26 Q38 38 24 43 Q10 38 10 26 L10 12 Z"
        fill="none" stroke="#ffffff" strokeOpacity="0.35" strokeWidth="0.6" transform="scale(0.86) translate(3.4,3.4)" />
      {/* a small star */}
      <path d="M24 16 l2.2 4.6 5 .5 -3.8 3.4 1.1 5 -4.5 -2.5 -4.5 2.5 1.1 -5 -3.8 -3.4 5 -.5 Z"
        fill="#0b0e15" fillOpacity="0.55" />
    </svg>
  )
}

// ---------------------------------------------------------------- brand crest

/** Raw / SmackDown crest — a shield with the brand mark. */
export function BrandCrest({ brand, size = 30 }: { brand: string; size?: number }) {
  const isRaw = brand === 'RAW'
  const col = isRaw ? '#e0223c' : '#3b82f6'
  const mark = isRaw ? 'R' : 'SD'
  const id = `crest-${brand}`
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true">
      <defs>
        <linearGradient id={`${id}-g`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={col} stopOpacity="0.95" />
          <stop offset="1" stopColor={col} stopOpacity="0.55" />
        </linearGradient>
      </defs>
      <path d="M20 2 L36 8 L36 22 Q36 34 20 39 Q4 34 4 22 L4 8 Z"
        fill={`url(#${id}-g)`} stroke={col} strokeWidth="1.5" />
      <text x="20" y="26" textAnchor="middle" fontFamily="Anton, sans-serif"
        fontSize={mark.length > 1 ? 13 : 18} fill="#0b0e15" style={{ letterSpacing: 0.5 }}>{mark}</text>
    </svg>
  )
}

// ---------------------------------------------------------------- ppv badge

/** A pay-per-view rosette. `finale` gives WrestleMania an extra ring. */
export function PPVBadge({ size = 30, finale = false }: { size?: number; finale?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true">
      <defs>
        <radialGradient id="ppv-g" cx="0.5" cy="0.4" r="0.7">
          <stop offset="0" stopColor="#fff6d8" />
          <stop offset="0.6" stopColor="#e8b93f" />
          <stop offset="1" stopColor="#8a6410" />
        </radialGradient>
      </defs>
      {finale && <circle cx="20" cy="20" r="18" fill="none" stroke="#e8b93f" strokeOpacity="0.5" strokeWidth="1" />}
      {/* rosette points */}
      {Array.from({ length: 12 }).map((_, i) => (
        <rect key={i} x="19" y="2" width="2" height="8" rx="1" fill="#e8b93f" fillOpacity="0.8"
          transform={`rotate(${i * 30} 20 20)`} />
      ))}
      <circle cx="20" cy="20" r="12" fill="url(#ppv-g)" stroke="#8a6410" strokeWidth="1" />
      <text x="20" y="25" textAnchor="middle" fontFamily="Anton, sans-serif" fontSize="14" fill="#0b0e15">◆</text>
    </svg>
  )
}
