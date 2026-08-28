/**
 * The card collection — every season's set, side by side.
 *
 * This is the "each year" half of the request. A card is minted for every signed
 * wrestler when a season ends and then never moves, so scrolling back through the
 * years is scrolling back through the actual save: who was elite in 2003, who
 * broke through in 2007, whose gold card has a champion's ribbon on it.
 *
 * The current season shows a MINT button rather than cards, because the season
 * has not finished. Minting early is allowed — you may want to look — and can be
 * re-cut with overwrite if a rating was wrong.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchCardSeasons, fetchSeasonCards, mintCards, fetchHealth, imageUrl,
  type RosterRow,
} from './api'
import Card from './Card'

type Filter = 'all' | 'special' | 'elite'

export default function CardsTab({ roster }: { roster: RosterRow[] }) {
  const qc = useQueryClient()
  const [season, setSeason] = useState<number | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [err, setErr] = useState<string | null>(null)

  const { data: health } = useQuery({ queryKey: ['health'], queryFn: fetchHealth })
  const { data: seasons = [] } = useQuery({
    queryKey: ['card-seasons'], queryFn: fetchCardSeasons,
  })

  const current = health?.save?.season_year ?? null
  // Default to the newest season that actually has cards, else the live one.
  const showing = season ?? seasons[0]?.season_year ?? current

  const { data: cards = [], isLoading } = useQuery({
    queryKey: ['season-cards', showing],
    queryFn: () => fetchSeasonCards(showing!, 400),
    enabled: showing != null,
  })

  const mint = useMutation({
    mutationFn: (overwrite: boolean) => mintCards(showing ?? undefined, overwrite),
    onSuccess: () => {
      setErr(null)
      qc.invalidateQueries({ queryKey: ['card-seasons'] })
      qc.invalidateQueries({ queryKey: ['season-cards'] })
    },
    onError: (e: Error) => setErr(e.message),
  })

  const portraitOf = (id: number) => {
    const r = roster.find((w) => w.id === id)
    return r?.profile_image_id ? imageUrl(r.profile_image_id) : null
  }

  const shown = cards.filter((c) =>
    filter === 'all' || (filter === 'special' && c.special)
    || (filter === 'elite' && (c.tier === 'elite' || c.tier === 'gold')))

  const counts = seasons.find((s) => s.season_year === showing)

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="px-4 py-3 border-b border-edge flex flex-wrap items-center gap-3">
        <div>
          <h2 className="display text-lg leading-none">Cards</h2>
          <p className="text-[11px] text-slate-500 mt-1">
            One per signed wrestler per season, frozen when the year ends.
            Managers are rated on Mic and Influence, not Wrestling and Popularity.
          </p>
        </div>

        <div className="flex items-center gap-1 flex-wrap">
          {seasons.map((s) => (
            <button
              key={s.season_year} onClick={() => setSeason(s.season_year)}
              title={`${s.cards} cards, ${s.specials} with a ribbon`}
              className={`label text-[10px] px-2 py-1 rounded border transition-colors
                ${showing === s.season_year ? 'border-gold text-gold bg-gold/10'
                  : 'border-edge text-slate-500 hover:text-slate-200'}`}
            >
              {s.season_year}
            </button>
          ))}
          {current != null && !seasons.some((s) => s.season_year === current) && (
            <button
              onClick={() => setSeason(current)}
              className={`label text-[10px] px-2 py-1 rounded border transition-colors
                ${showing === current ? 'border-gold text-gold bg-gold/10'
                  : 'border-edge border-dashed text-slate-500 hover:text-slate-200'}`}
              title="This season has not been minted yet"
            >
              {current} · live
            </button>
          )}
        </div>

        <div className="ml-auto flex items-center gap-2">
          {(['all', 'special', 'elite'] as Filter[]).map((f) => (
            <button
              key={f} onClick={() => setFilter(f)}
              className={`label text-[10px] px-2 py-1 rounded border transition-colors
                ${filter === f ? 'border-gold text-gold bg-gold/10'
                  : 'border-edge text-slate-500 hover:text-slate-200'}`}
            >
              {f}
            </button>
          ))}
          <button
            onClick={() => mint.mutate(false)}
            disabled={mint.isPending}
            className="label text-[10px] px-3 py-1.5 rounded bg-gold text-canvas hover:bg-gold/85"
          >
            {mint.isPending ? 'Printing…' : `Mint ${showing ?? ''}`}
          </button>
          {counts && counts.cards > 0 && (
            <button
              onClick={() => mint.mutate(true)}
              disabled={mint.isPending}
              className="label text-[10px] px-2 py-1.5 rounded border border-edge
                         text-slate-500 hover:text-blood hover:border-blood/50"
              title="Re-cut this season's cards from today's ratings. Only useful after fixing a rating."
            >
              re-cut
            </button>
          )}
        </div>
      </div>

      {err && <div className="px-4 py-2 text-xs text-blood">{err}</div>}

      <div className="flex-1 overflow-auto p-4">
        {isLoading && <p className="text-xs text-slate-500">Fetching the set…</p>}

        {!isLoading && cards.length === 0 && (
          <div className="max-w-[520px]">
            <p className="text-sm text-slate-400 mb-2">No cards for {showing} yet.</p>
            <p className="text-xs text-slate-500">
              Cards are minted automatically when a season ends. To see this
              season's set early, press <strong className="text-gold">Mint</strong> —
              it prints one for every wrestler currently under contract. Nobody
              signed means nothing to print, so run the draft first.
            </p>
          </div>
        )}

        {shown.length > 0 && (
          <>
            <div className="flex flex-wrap gap-3">
              {shown.map((c) => (
                <Card key={`${c.wrestler_id}-${c.season_year}`} card={c} size="md"
                      portrait={portraitOf(c.wrestler_id)} />
              ))}
            </div>
            <p className="text-[11px] text-slate-600 mt-4">
              {shown.length} of {cards.length} shown
              {counts ? ` · ${counts.specials} with a ribbon` : ''}
            </p>
          </>
        )}

        {cards.length > 0 && shown.length === 0 && (
          <p className="text-xs text-slate-500">
            No {filter} cards in {showing}.
          </p>
        )}
      </div>
    </div>
  )
}
