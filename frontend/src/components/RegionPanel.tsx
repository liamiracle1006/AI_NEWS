import { useEffect, useState } from 'react'
import { fetchMapArticles } from '../api'
import { campColor, campLabel } from '../types'
import type { MapArticle } from '../types'

interface Props {
  countryName: string
  countryZh: string
  heatCount: number
  open: boolean
  onClose: () => void
  selectedDate?: string
  onAnalyze?: (keyword: string, weekMode?: boolean) => void
}

export function RegionPanel({ countryName, countryZh, heatCount, open, onClose, selectedDate, onAnalyze }: Props) {
  const [articles, setArticles] = useState<MapArticle[]>([])
  const [loading, setLoading] = useState(false)
  const [viewMode, setViewMode] = useState<'day' | 'week'>('day')

  const today = new Date().toISOString().slice(0, 10)
  const isToday = !selectedDate || selectedDate === today

  useEffect(() => {
    if (!open || !countryName) return
    setLoading(true)
    setArticles([])
    const weekMode = viewMode === 'week'
    fetchMapArticles(countryName, weekMode ? undefined : selectedDate, weekMode)
      .then(setArticles)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [open, countryName, selectedDate, viewMode])

  // Reset to day view when panel opens for a new country
  useEffect(() => {
    if (open) setViewMode('day')
  }, [countryName, open])

  const dateLabel = viewMode === 'week'
    ? '近 7 天'
    : isToday ? '今日' : selectedDate

  if (!open) return null

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-20" onClick={onClose} />

      <div className="fixed top-0 right-0 h-full w-96 bg-white shadow-xl z-30 flex flex-col">
        {/* Header */}
        <div className="px-4 py-3 border-b border-gray-200">
          <div className="flex items-center justify-between mb-2">
            <h2 className="font-semibold text-gray-800">
              📍 {countryZh || countryName}
            </h2>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
          </div>

          <div className="flex items-center justify-between">
            {/* Day / Week toggle */}
            <div className="flex rounded-lg border border-gray-200 overflow-hidden text-xs">
              <button
                onClick={() => setViewMode('day')}
                className={`px-3 py-1 transition-colors ${viewMode === 'day' ? 'bg-blue-600 text-white' : 'bg-white text-gray-500 hover:bg-gray-50'}`}
              >
                {isToday ? '今天' : selectedDate?.slice(5) ?? '当天'}
              </button>
              <button
                onClick={() => setViewMode('week')}
                className={`px-3 py-1 transition-colors ${viewMode === 'week' ? 'bg-blue-600 text-white' : 'bg-white text-gray-500 hover:bg-gray-50'}`}
              >
                本周
              </button>
            </div>

            {/* Analyze button */}
            {onAnalyze && isToday && (
              <button
                onClick={() => { onClose(); onAnalyze(countryName, viewMode === 'week') }}
                className="text-xs px-2.5 py-1 rounded bg-blue-600 text-white hover:bg-blue-700 transition-colors whitespace-nowrap"
              >
                {viewMode === 'week' ? '本周深度分析' : '深度分析'}
              </button>
            )}
          </div>

          {heatCount > 0 && (
            <p className="text-xs text-gray-400 mt-1.5">
              {dateLabel} RSS 命中 <span className="font-medium text-gray-600">{heatCount}</span> 篇相关报道
            </p>
          )}
        </div>

        {/* Article list */}
        <div className="flex-1 overflow-y-auto divide-y divide-gray-100">
          {loading && (
            <p className="text-sm text-gray-400 text-center py-12 animate-pulse">加载中...</p>
          )}

          {!loading && articles.length === 0 && (
            <div className="px-4 py-12 text-center text-sm text-gray-400">
              {dateLabel} 缓存中暂无与该地区相关的报道。
              {isToday && viewMode === 'day' && (
                <span className="text-xs mt-1 block">可切换至"本周"查看近期报道。</span>
              )}
            </div>
          )}

          {!loading && articles.map((a, i) => (
            <div key={i} className="px-4 py-3 hover:bg-gray-50 transition-colors">
              <div className="flex items-center gap-2 mb-1.5">
                <span className={`inline-flex items-center text-xs px-1.5 py-0.5 rounded border font-medium ${campColor(a.bias_tag)}`}>
                  {campLabel(a.bias_tag)}
                </span>
                {a.published_at && (
                  <span className="text-xs text-gray-400">
                    {new Date(a.published_at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                  </span>
                )}
              </div>

              <a
                href={a.url}
                target="_blank"
                rel="noopener noreferrer"
                className="block text-sm font-medium text-gray-800 hover:text-blue-600 leading-snug mb-1"
              >
                {a.title}
              </a>

              {a.summary && (
                <p className="text-xs text-gray-500 line-clamp-2">{a.summary}</p>
              )}
            </div>
          ))}
        </div>

        <div className="px-4 py-3 border-t border-gray-100 text-xs text-gray-400">
          {viewMode === 'week' ? '数据来自近 7 天 RSS 缓存' : isToday ? '数据来自今日 RSS 缓存 · 每天自动更新' : `数据来自 ${selectedDate} 缓存`}
        </div>
      </div>
    </>
  )
}
