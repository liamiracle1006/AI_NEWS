import { useState } from 'react'

interface Props {
  onSubmit: (keyword: string, maxArticles: number, trackPeople: boolean) => void
  loading: boolean
}

export function AnalyzeForm({ onSubmit, loading }: Props) {
  const [keyword, setKeyword] = useState('')
  const [maxArticles, setMaxArticles] = useState(10)
  const [trackPeople, setTrackPeople] = useState(true)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (keyword.trim()) onSubmit(keyword.trim(), maxArticles, trackPeople)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          关键词（用 | 分隔同义词）
        </label>
        <input
          type="text"
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          placeholder="例：加沙|Gaza  /  乌克兰|Ukraine|Kyiv"
          className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          disabled={loading}
        />
      </div>

      <div className="flex items-center gap-6">
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-600">最多文章数</label>
          <input
            type="number"
            min={3}
            max={20}
            value={maxArticles}
            onChange={e => setMaxArticles(Number(e.target.value))}
            className="w-16 border border-gray-300 rounded px-2 py-1 text-sm text-center"
            disabled={loading}
          />
        </div>

        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input
            type="checkbox"
            checked={trackPeople}
            onChange={e => setTrackPeople(e.target.checked)}
            disabled={loading}
            className="rounded"
          />
          追踪人物
        </label>
      </div>

      <button
        type="submit"
        disabled={loading || !keyword.trim()}
        className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 text-white font-medium py-2.5 rounded-lg transition-colors"
      >
        {loading ? '分析中...' : '开始分析'}
      </button>
    </form>
  )
}
