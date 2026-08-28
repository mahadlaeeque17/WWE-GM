/**
 * The five ratings as a shape.
 *
 * WHY A PENTAGON. Five categories is exactly the count a radar chart is good at,
 * and the shape carries information the five numbers do not: Trish Stratus and
 * Meiko Satomura both sit in the fifties and look nothing alike — one a wide flat
 * kite, the other a single spike. Two sizes, one component:
 *
 *   full   on the wrestler panel, with axis labels and gridlines
 *   glyph  ~22px in a roster row, no text, so a table of 370 becomes scannable
 *          by silhouette rather than by reading four columns of digits
 *
 * Achievements is drawn in gold on top of the wrestler's own colour, because it
 * is the one axis that is earned in the save rather than set — it should read as
 * a different KIND of number, not just another point.
 */
import { CAT_MAX, CATEGORIES, type RosterRow } from './api'

const AXES = CATEGORIES.map((c) => c.full)
const ACH_INDEX = CATEGORIES.findIndex((c) => c.key === 'achievements')

/**
 * Axis labels for a row, which depend on her ROLE. A manager's two performance
 * axes are Mic and Influence, not Wrestling and Popularity — the shape means
 * nothing if it is labelled with stats she is not scored on.
 */
const LABEL_FOR: Record<string, string> = {
  wrestling: 'WRS', popularity: 'POP', mic: 'MIC', influence: 'INF',
  achievements: 'ACH', looks: 'LKS', personal: 'PER',
}

export function labelsOf(row: RosterRow): string[] {
  const [a, b] = row.performance_pair ?? ['wrestling', 'popularity']
  return CATEGORIES.map((c, i) =>
    i === 0 ? LABEL_FOR[a] : i === 2 ? LABEL_FOR[b] : c.label)
}

/** Point up, then clockwise, so Wrestling sits at the apex. */
function point(i: number, radius: number, cx: number, cy: number) {
  const a = -Math.PI / 2 + (i * 2 * Math.PI) / AXES.length
  return [cx + Math.cos(a) * radius, cy + Math.sin(a) * radius] as const
}

function polygon(vals: number[], r: number, cx: number, cy: number) {
  return vals
    .map((v, i) => {
      // A floor of 0.35 keeps a zero from collapsing the shape onto the centre,
      // which would make a 0 and a 1 look identical.
      const [x, y] = point(i, (Math.max(v, 0.35) / CAT_MAX) * r, cx, cy)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

export function valuesOf(row: RosterRow): number[] {
  // Slots 0 and 2 are role-dependent; the other three are the same for everyone.
  const [a, b] = row.performance_pair ?? ['wrestling', 'popularity']
  return CATEGORIES.map((c, i) => {
    const key = i === 0 ? a : i === 2 ? b : c.key
    return (row[key] as number) ?? 0
  })
}

/** The small one — a silhouette for a table row. No text, no gridlines. */
export function PentagonGlyph({
  values, size = 22, colour = 'currentColor', title,
}: { values: number[]; size?: number; colour?: string; title?: string }) {
  const c = size / 2
  const r = c - 1.5
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}
         aria-hidden={title ? undefined : true} role={title ? 'img' : undefined}>
      {title && <title>{title}</title>}
      <polygon points={polygon(AXES.map(() => CAT_MAX), r, c, c)}
               fill="none" stroke="var(--color-edge-soft)" strokeWidth={1} />
      <polygon points={polygon(values, r, c, c)}
               fill={colour} fillOpacity={0.28} stroke={colour} strokeWidth={1.2}
               strokeLinejoin="round" />
    </svg>
  )
}

/** The big one — labelled axes, rings at 5/10/15/20, and a marker per point. */
export default function Pentagon({
  values, size = 250, colour = 'var(--color-gold)', reasons = [], labels,
}: {
  values: number[]; size?: number; colour?: string; reasons?: string[]
  /** Override the axis labels — a manager's two differ. See labelsOf. */
  labels?: string[]
}) {
  // Room for the labels, which sit outside the outer ring.
  const pad = 42
  const c = size / 2
  const r = c - pad

  return (
    <svg width="100%" viewBox={`0 0 ${size} ${size}`} style={{ maxWidth: size }}
         role="img" aria-label={AXES.map((a, i) => `${a} ${values[i]}`).join(', ')}>
      {[5, 10, 15, 20].map((step) => (
        <polygon key={step} points={polygon(AXES.map(() => step), r, c, c)}
                 fill="none"
                 stroke={step === CAT_MAX ? 'var(--color-edge)' : 'var(--color-edge-soft)'}
                 strokeWidth={step === CAT_MAX ? 1.2 : 1} />
      ))}

      {AXES.map((axis, i) => {
        const [x, y] = point(i, r, c, c)
        const [lx, ly] = point(i, r + 20, c, c)
        const isAch = i === ACH_INDEX
        return (
          <g key={axis}>
            <line x1={c} y1={c} x2={x.toFixed(1)} y2={y.toFixed(1)}
                  stroke="var(--color-edge-soft)" strokeWidth={1} />
            <text
              x={lx.toFixed(1)} y={ly.toFixed(1)}
              textAnchor={lx > c + 6 ? 'start' : lx < c - 6 ? 'end' : 'middle'}
              dominantBaseline={ly < c ? 'auto' : 'hanging'}
              className="label"
              fill={isAch ? 'var(--color-gold)' : 'var(--color-slate-400, #94a3b8)'}
              style={{ fontSize: 9.5 }}
            >
              {(labels ?? CATEGORIES.map((c) => c.label))[i]} {values[i]}
            </text>
          </g>
        )
      })}

      <polygon points={polygon(values, r, c, c)}
               fill={colour} fillOpacity={0.18} stroke={colour}
               strokeWidth={2} strokeLinejoin="round" />

      {values.map((v, i) => {
        const [x, y] = point(i, (Math.max(v, 0.35) / CAT_MAX) * r, c, c)
        const isAch = i === ACH_INDEX
        return (
          <circle key={i} cx={x.toFixed(1)} cy={y.toFixed(1)} r={isAch ? 3.4 : 2.8}
                  fill={isAch && v > 0 ? 'var(--color-gold)' : colour}>
            {isAch && reasons.length > 0 && <title>{reasons.join(' · ')}</title>}
          </circle>
        )
      })}
    </svg>
  )
}
