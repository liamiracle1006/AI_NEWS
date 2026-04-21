import type { SourceRef } from '../types'
import { CampBadge } from './CampBadge'

interface Props {
  sources: SourceRef[]
}

export function SourceList({ sources }: Props) {
  return (
    <section className="bg-white rounded-xl border border-gray-200 p-6">
      <h2 className="text-lg font-semibold text-gray-800 mb-4">🔗 原文链接</h2>
      <ul className="space-y-2">
        {sources.map((s, i) => (
          <li key={i} className="flex items-start gap-2 text-sm">
            <CampBadge tag={s.bias_tag} />
            <a
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 hover:underline flex-1 leading-snug"
            >
              {s.title}
            </a>
            <span className="text-gray-400 text-xs shrink-0">{s.source_name}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
