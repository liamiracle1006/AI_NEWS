import { useState } from 'react'
import type { Divergence } from '../types'
import { CampBadge } from './CampBadge'

interface Props {
  divergence: Divergence
  index: number
}

export function DivergenceCard({ divergence, index }: Props) {
  const [open, setOpen] = useState(false)

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-50 transition-colors"
      >
        <span className="text-sm font-medium text-gray-800">
          分歧 {index}：{divergence.point}
        </span>
        <span className="text-gray-400 text-xs ml-2">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-3 border-t border-gray-100 pt-3">
          <div className="space-y-2">
            {Object.entries(divergence.camp_claims).map(([tag, claim]) => (
              <div key={tag} className="flex gap-2 text-sm">
                <CampBadge tag={tag} />
                <span className="text-gray-700 flex-1">{claim}</span>
              </div>
            ))}
          </div>
          {divergence.observation && (
            <div className="bg-amber-50 border border-amber-200 rounded p-3 text-sm text-amber-800">
              📝 {divergence.observation}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
