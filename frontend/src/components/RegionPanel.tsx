import { campColor, campLabel } from '../types'
import type { ArticleFacts } from '../types'

interface Props {
  countryName: string       // English name (GEO_KEYWORDS key)
  countryZh: string         // Chinese display name
  articles: ArticleFacts[]  // all articles from latest analysis; we filter here
  heatCount: number         // raw mention count from /api/map/heat
  open: boolean
  onClose: () => void
}

// Keywords used to match articles to a country (simplified subset for filtering)
// Full matching is done backend-side; here we just filter the already-loaded bundle.
function articleMatchesCountry(article: ArticleFacts, countryName: string): boolean {
  const name = countryName.toLowerCase()
  // Check where field
  const where = (article.facts.where ?? '').toLowerCase()
  if (where.includes(name)) return true
  // Check title
  if (article.title.toLowerCase().includes(name)) return true
  // Check action
  const action = (article.facts.action ?? '').toLowerCase()
  if (action.includes(name)) return true
  return false
}

export function RegionPanel({ countryName, countryZh, articles, heatCount, open, onClose }: Props) {
  if (!open) return null

  const related = articles.filter((a) => articleMatchesCountry(a, countryName))

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/30 z-20" onClick={onClose} />

      {/* Slide-in panel */}
      <div className="fixed top-0 right-0 h-full w-96 bg-white shadow-xl z-30 flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <div>
            <h2 className="font-semibold text-gray-800">
              📍 {countryZh || countryName}
            </h2>
            {heatCount > 0 && (
              <p className="text-xs text-gray-400 mt-0.5">
                近期 RSS 命中 <span className="font-medium text-gray-600">{heatCount}</span> 篇相关报道
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
          >
            ×
          </button>
        </div>

        {/* Article list */}
        <div className="flex-1 overflow-y-auto divide-y divide-gray-100">
          {related.length === 0 ? (
            <div className="px-4 py-12 text-center text-sm text-gray-400">
              当前分析结果中暂无与该地区直接相关的文章。
              <br />
              <span className="text-xs mt-1 block">尝试搜索该地区相关关键词以获取详细报道。</span>
            </div>
          ) : (
            related.map((a, i) => (
              <div key={i} className="px-4 py-3 hover:bg-gray-50 transition-colors">
                {/* Source badge */}
                <span
                  className={`inline-flex items-center text-xs px-1.5 py-0.5 rounded border font-medium mb-1.5 ${campColor(a.bias_tag)}`}
                >
                  {campLabel(a.bias_tag)}
                </span>

                {/* Title */}
                <a
                  href={a.article_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block text-sm font-medium text-gray-800 hover:text-blue-600 leading-snug mb-1"
                >
                  {a.title}
                </a>

                {/* Action summary */}
                {a.facts.action && (
                  <p className="text-xs text-gray-500 line-clamp-2">{a.facts.action}</p>
                )}
              </div>
            ))
          )}
        </div>

        {/* Footer hint */}
        <div className="px-4 py-3 border-t border-gray-100 text-xs text-gray-400">
          热力数据来自全局 RSS 抓取（每 10 分钟刷新）；文章列表来自当前搜索结果。
        </div>
      </div>
    </>
  )
}
