import { useState } from 'react'
import type { ArticleFacts } from '../types'
import { campColor, campLabel } from '../types'

interface Props {
  facts: ArticleFacts[]
}

function ArticleDigestCard({ f }: { f: ArticleFacts }) {
  const [expanded, setExpanded] = useState(false)

  const date = f.published_at
    ? new Date(f.published_at).toLocaleString('zh-CN', {
        month: 'numeric', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
      })
    : null

  const who = f.facts.who?.slice(0, 3).join('、')
  const nums = f.facts.numbers?.slice(0, 2).join(' · ')
  const where = f.facts.where

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      {/* Meta row */}
      <div className="flex items-center gap-2 mb-2">
        <span className={`inline-flex items-center text-xs px-1.5 py-0.5 rounded border font-medium ${campColor(f.bias_tag)}`}>
          {campLabel(f.bias_tag)}
        </span>
        <span className="text-xs text-gray-500">{f.source_name}</span>
        {date && <span className="text-xs text-gray-400 ml-auto">{date}</span>}
      </div>

      {/* Title */}
      <a
        href={f.article_url}
        target="_blank"
        rel="noopener noreferrer"
        className="block text-sm font-semibold text-gray-800 hover:text-blue-600 leading-snug mb-2"
      >
        {f.title}
      </a>

      {/* Tags row */}
      {(where || who || nums) && (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-gray-400 mb-2">
          {where && <span>📍 {where}</span>}
          {who && <span>👤 {who}</span>}
          {nums && <span>🔢 {nums}</span>}
        </div>
      )}

      {/* Action */}
      {f.facts.action && (
        <p className="text-sm text-gray-700 leading-relaxed mb-1">{f.facts.action}</p>
      )}

      {/* Context */}
      {f.facts.context && (
        <p className="text-xs text-gray-400 italic leading-relaxed mb-2">{f.facts.context}</p>
      )}

      {/* Key quotes toggle */}
      {f.facts.key_quotes && f.facts.key_quotes.length > 0 && (
        <div>
          <button
            onClick={() => setExpanded(v => !v)}
            className="text-xs text-blue-500 hover:text-blue-700 transition-colors"
          >
            {expanded ? '▲ 收起引言' : `▼ 查看引言（${f.facts.key_quotes.length} 条）`}
          </button>
          {expanded && (
            <ul className="mt-2 space-y-1">
              {f.facts.key_quotes.map((q, i) => (
                <li key={i} className="text-xs text-gray-600 border-l-2 border-blue-200 pl-2 italic leading-relaxed">
                  {q}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

export function ArticleDigestList({ facts }: Props) {
  if (!facts || facts.length === 0) return null

  return (
    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">📄 各方报道摘要</h2>
      <div className="space-y-3">
        {facts.map((f, i) => (
          <ArticleDigestCard key={i} f={f} />
        ))}
      </div>
    </section>
  )
}
