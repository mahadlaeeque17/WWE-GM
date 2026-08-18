import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchGallery, setProfileImage, deleteImage, imageUrl } from './api'

/**
 * Every image a wrestler has. Click one to make it her profile portrait — that
 * is the shot used on the roster row, the draft board and the panel hero.
 */
export default function Gallery({ wrestlerId }: { wrestlerId: number }) {
  const qc = useQueryClient()
  const { data: images = [], isLoading } = useQuery({
    queryKey: ['gallery', wrestlerId],
    queryFn: () => fetchGallery(wrestlerId),
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['gallery', wrestlerId] })
    qc.invalidateQueries({ queryKey: ['roster'] })
  }

  const pick = useMutation({
    mutationFn: (imageId: number) => setProfileImage(wrestlerId, imageId),
    onSuccess: invalidate,
  })
  const drop = useMutation({
    mutationFn: (imageId: number) => deleteImage(wrestlerId, imageId),
    onSuccess: invalidate,
  })

  if (isLoading) return <p className="text-xs text-slate-600">Loading gallery…</p>
  if (!images.length) {
    return (
      <p className="text-[11px] text-slate-600 leading-snug">
        No images yet. Drop files in your Drive folder named with her ID or any
        ring name, then hit <strong className="text-slate-400">Sync</strong> on
        the Images tab.
      </p>
    )
  }

  return (
    <div>
      <div className="grid grid-cols-3 gap-2">
        {images.map((img) => (
          <div key={img.id} className="relative group">
            <button
              onClick={() => pick.mutate(img.id)}
              title={img.is_profile ? 'Current profile picture' : 'Use as profile picture'}
              className={`block w-full rounded overflow-hidden border-2 transition-colors ${
                img.is_profile ? 'border-gold' : 'border-edge hover:border-gold/50'
              }`}
            >
              <img
                src={imageUrl(img.id)}
                alt={img.original_name ?? img.filename}
                loading="lazy"
                className="w-full h-24 portrait"
              />
            </button>

            {img.is_profile === 1 && (
              <span className="absolute top-1 left-1 label text-[8px] px-1 py-0.5 rounded bg-gold text-black">
                profile
              </span>
            )}
            {img.year ? (
              <span className="absolute bottom-1 left-1 label text-[8px] px-1 py-0.5 rounded bg-black/70 text-slate-200">
                {img.year}
              </span>
            ) : null}

            <button
              onClick={() => drop.mutate(img.id)}
              title="Delete this image"
              className="absolute top-1 right-1 w-5 h-5 grid place-items-center rounded-full
                         bg-black/70 text-slate-400 opacity-0 group-hover:opacity-100
                         hover:text-raw transition-opacity"
            >
              ×
            </button>
          </div>
        ))}
      </div>
      <p className="text-[10px] text-slate-600 mt-2">
        {images.length} image{images.length > 1 ? 's' : ''} · click one to set it as her profile
      </p>
    </div>
  )
}
