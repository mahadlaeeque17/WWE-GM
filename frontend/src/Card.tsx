/**
 * The player card — the FIFA idea, drawn in this game's own palette.
 *
 * WHAT THE FACE TELLS YOU, in the order your eye gets to it:
 *
 *   the frame colour   her tier, so you know roughly where she sits before you
 *                      read a single number
 *   the big number     overall, 0-100
 *   under it           style and role, where the reference card puts a position
 *   the five stats     out of 99, because that is what a card is. The stored
 *                      values are out of 20 — see attributes.to99 for why the
 *                      conversion lives at the display edge and nowhere else
 *   the ribbon         what that season earned her, if anything
 *
 * A MANAGER'S CARD IS DIFFERENT, and it should be. MIC and INF sit where WRS and
 * POP sit on a wrestler's, exactly as a goalkeeper card swaps its stat names, and
 * the frame is tinted differently so the two never get confused at a glance.
 */
import type { PlayerCard } from './api'

/**
 * Tier palettes. Deliberately NOT FIFA's metals — this game is gold-on-near-black
 * already, so a literal bronze/silver would fight the app. These are the same
 * hues at four temperatures.
 */
const TIERS: Record<string, { edge: string; wash: string; ink: string; label: string }> = {
  elite: { edge: '#e9d5ff', wash: 'rgba(192,132,252,0.16)', ink: '#f3e8ff', label: 'Elite' },
  gold: { edge: '#ffc83d', wash: 'rgba(255,200,61,0.14)', ink: '#ffe9a8', label: 'Gold' },
  silver: { edge: '#b8c4d6', wash: 'rgba(184,196,214,0.10)', ink: '#dfe7f2', label: 'Silver' },
  bronze: { edge: '#c8853d', wash: 'rgba(200,133,61,0.10)', ink: '#e8c9a6', label: 'Bronze' },
}

const SIZES = {
  sm: { w: 132, ovr: 26, name: 10, stat: 9, pad: 8 },
  md: { w: 186, ovr: 38, name: 12, stat: 11, pad: 11 },
  lg: { w: 240, ovr: 50, name: 14, stat: 13, pad: 14 },
}

export default function Card({
  card, size = 'md', portrait, onClick,
}: {
  card: PlayerCard
  size?: keyof typeof SIZES
  /** Optional portrait URL. The card works without one — most of the roster has none. */
  portrait?: string | null
  onClick?: () => void
}) {
  const t = TIERS[card.tier] ?? TIERS.bronze
  const s = SIZES[size]
  const isManager = card.role === 'manager'
  // A signed wrestler's card carries her brand; a free agent gets the tier alone.
  const brand = card.brand_id === 'RAW' ? 'var(--color-raw)'
    : card.brand_id === 'SMACKDOWN' ? 'var(--color-smackdown)' : null

  const Tag = onClick ? 'button' : 'div'

  return (
    <Tag
      onClick={onClick}
      className={`relative block text-left rounded-lg overflow-hidden shrink-0
                  ${onClick ? 'cursor-pointer hover:-translate-y-0.5 transition-transform' : ''}`}
      style={{
        width: s.w,
        // Two borders' worth of information in one: the tier sets the ring, the
        // brand tints the ground behind it.
        border: `1.5px solid ${t.edge}`,
        background: `linear-gradient(160deg, ${t.wash}, rgba(5,7,13,0.9) 55%),
                     ${brand ? `linear-gradient(200deg, ${brand}33, transparent 60%),` : ''}
                     var(--color-panel)`,
        boxShadow: `0 0 0 1px rgba(0,0,0,0.5), 0 6px 18px rgba(0,0,0,0.45)`,
      }}
    >
      {/* --------------------------------------------------- overall + identity */}
      <div className="flex" style={{ padding: s.pad, paddingBottom: 0 }}>
        <div className="shrink-0" style={{ minWidth: s.ovr * 1.5 }}>
          <div className="display leading-none" style={{ fontSize: s.ovr, color: t.ink }}>
            {card.overall}
          </div>
          <div className="label mt-0.5" style={{ fontSize: s.stat - 1, color: t.edge }}>
            {isManager ? 'MGR' : (card.style || 'WRESTLER').split(',')[0].slice(0, 10)}
          </div>
          {card.record && (
            <div className="stat text-slate-400" style={{ fontSize: s.stat }}>
              {card.record}
            </div>
          )}
        </div>

        {portrait ? (
          <img
            src={portrait} alt=""
            className="ml-auto object-cover object-top rounded"
            style={{ width: s.w * 0.44, height: s.w * 0.52 }}
          />
        ) : (
          <div className="ml-auto flex items-end justify-center"
               style={{ width: s.w * 0.44, height: s.w * 0.52 }}>
            <span className="display text-slate-700" style={{ fontSize: s.ovr * 1.2 }}>
              {card.name.split(' ').map((p) => p[0]).join('').slice(0, 2)}
            </span>
          </div>
        )}
      </div>

      {/* ------------------------------------------------------------ the name */}
      <div style={{ padding: `4px ${s.pad}px 0` }}>
        <div className="display truncate" style={{ fontSize: s.name + 2, color: t.ink }}>
          {card.name}
        </div>
        <div className="h-px my-1" style={{ background: `${t.edge}55` }} />
      </div>

      {/* ----------------------------------------------------------- the stats */}
      <div className="grid grid-cols-3 gap-x-1 gap-y-0.5"
           style={{ padding: `2px ${s.pad}px ${s.pad}px` }}>
        {card.stats.map((st) => (
          <div key={st.key} className="flex items-baseline gap-1 min-w-0">
            <span className="stat tabular-nums" style={{ fontSize: s.stat + 2, color: t.ink }}>
              {st.v99}
            </span>
            <span className="label truncate" style={{ fontSize: s.stat - 2, color: `${t.edge}bb` }}>
              {st.label}
            </span>
          </div>
        ))}
      </div>

      {/* --------------------------------------------------------- season + ribbon */}
      <div className="flex items-center gap-1.5 px-2 py-1"
           style={{ background: `${t.edge}1f`, borderTop: `1px solid ${t.edge}33` }}>
        <span className="label" style={{ fontSize: s.stat - 2, color: t.edge }}>
          {card.season_year}{card.live ? ' · live' : ''}
        </span>
        {card.special && (
          <span className="label truncate ml-auto" style={{ fontSize: s.stat - 2, color: t.ink }}
                title={card.special}>
            ★ {card.special}
          </span>
        )}
      </div>
    </Tag>
  )
}

export { TIERS as CARD_TIERS }
