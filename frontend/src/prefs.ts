import { useQuery } from '@tanstack/react-query'
import { fetchSettings } from './api'

/**
 * Whether portraits / logo images should render. Off = "professional mode":
 * every photo and user-supplied logo is replaced by initials / vector / text,
 * so the app is clean to show in a work setting. Defaults to ON.
 */
export function usePhotos(): boolean {
  const { data } = useQuery({ queryKey: ['settings'], queryFn: fetchSettings, staleTime: 30_000 })
  return data?.photos !== 'off'
}
