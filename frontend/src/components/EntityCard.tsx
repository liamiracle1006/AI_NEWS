import type { EntityEvent } from '../types'
import { CampBadge } from './CampBadge'

interface Props {
  entity: EntityEvent
}

export function EntityCard({ entity }: Props) {
  return (
    <div className="border border-gray-200 rounded-lg p-4 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <span className="font-semibold text-gray-800">{entity.canonical_name}</span>
          {entity.position && (
            <span className="text-xs text-gray-500 ml-2">（{entity.position}）</span>
          )}
        </div>
        {entity.status_change && (
          <span className="text-xs bg-yellow-100 text-yellow-800 border border-yellow-200 px-2 py-0.5 rounded shrink-0">
            {entity.status_change}
          </span>
        )}
      </div>

      {entity.aliases.length > 0 && (
        <p className="text-xs text-gray-400">别名：{entity.aliases.join(' · ')}</p>
      )}

      <p className="text-sm text-gray-700">{entity.action_or_status}</p>

      {Object.keys(entity.per_source_framing).length > 0 && (
        <div className="space-y-1 pt-1 border-t border-gray-100">
          <p className="text-xs text-gray-400 font-medium">阵营差异</p>
          {Object.entries(entity.per_source_framing).map(([tag, framing]) => (
            <div key={tag} className="flex gap-2 text-xs">
              <CampBadge tag={tag} />
              <span className="text-gray-600 flex-1">{framing}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
