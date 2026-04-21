import { campColor, campLabel } from '../types'

export function CampBadge({ tag }: { tag: string }) {
  return (
    <span className={`inline-block text-xs font-medium px-2 py-0.5 rounded border ${campColor(tag)}`}>
      {campLabel(tag)}
    </span>
  )
}
