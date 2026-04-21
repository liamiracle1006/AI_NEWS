import { useEffect, useState } from 'react'
import { fetchBriefs, fetchBriefData } from '../api'
import type { AnalysisResult, BriefMeta } from '../types'

interface Props {
  open: boolean
  onClose: () => void
  onLoad: (result: AnalysisResult, topic: string) => void
}

export function HistoryPanel({ open, onClose, onLoad }: Props) {
  const [briefs, setBriefs] = useState<BriefMeta[]>([])
  const [loadingId, setLoadingId] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      fetchBriefs().then(setBriefs).catch(() => setBriefs([]))
    }
  }, [open])

  const handleLoad = async (brief: BriefMeta) => {
    if (!brief.has_data) return
    setLoadingId(brief.id)
    try {
      const data = await fetchBriefData(brief.id)
      onLoad(data, brief.topic)
      onClose()
    } catch {
      // silently fail — user sees no result
    } finally {
      setLoadingId(null)
    }
  }

  if (!open) return null

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/30 z-20"
        onClick={onClose}
      />

      {/* Slide-in panel */}
      <div className="fixed top-0 right-0 h-full w-80 bg-white shadow-xl z-30 flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <h2 className="font-semibold text-gray-800">历史记录</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
          >
            ×
          </button>
        </div>

        <div className="flex-1 overflow-y-auto divide-y divide-gray-100">
          {briefs.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-12">暂无历史记录</p>
          ) : (
            briefs.map(b => {
              const date = b.generated_at
                ? new Date(b.generated_at).toLocaleString('zh-CN', {
                    month: 'numeric', day: 'numeric',
                    hour: '2-digit', minute: '2-digit',
                  })
                : '—'
              const topicDisplay = b.topic.replace(/\|/g, ' / ')

              return (
                <button
                  key={b.id}
                  onClick={() => handleLoad(b)}
                  disabled={!b.has_data || loadingId === b.id}
                  className="w-full text-left px-4 py-3 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <div className="text-sm font-medium text-gray-800 truncate">{topicDisplay}</div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-xs text-gray-400">{date}</span>
                    {b.article_count > 0 && (
                      <span className="text-xs text-gray-400">· {b.article_count} 篇</span>
                    )}
                    {!b.has_data && (
                      <span className="text-xs text-amber-500">仅 Markdown</span>
                    )}
                  </div>
                  {loadingId === b.id && (
                    <span className="text-xs text-blue-500 mt-1 block">加载中...</span>
                  )}
                </button>
              )
            })
          )}
        </div>
      </div>
    </>
  )
}
