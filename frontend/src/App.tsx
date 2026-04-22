import { useEffect, useState } from 'react'
import { AnalyzeForm } from './components/AnalyzeForm'
import { ProgressBar } from './components/ProgressBar'
import { ResultView } from './components/ResultView'
import { HistoryPanel } from './components/HistoryPanel'
import { WorldMap } from './components/WorldMap'
import { RegionPanel } from './components/RegionPanel'
import { startAnalyze, fetchResult, subscribeToProgress, fetchHeatData } from './api'
import type { AnalysisResult, ProgressEvent } from './types'

export default function App() {
  const [loading, setLoading] = useState(false)
  const [events, setEvents] = useState<ProgressEvent[]>([])
  const [expandedKeyword, setExpandedKeyword] = useState<string | null>(null)
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)

  // Map state
  const [heatData, setHeatData] = useState<Record<string, number>>({})
  const [heatLoading, setHeatLoading] = useState(true)
  const [selectedCountry, setSelectedCountry] = useState<{ name: string; zh: string } | null>(null)

  useEffect(() => {
    const refresh = () =>
      fetchHeatData()
        .then(setHeatData)
        .catch(() => {})
        .finally(() => setHeatLoading(false))

    refresh()
    // Re-poll every 2 minutes so map colors update after startup cache finishes
    const timer = setInterval(refresh, 120_000)
    return () => clearInterval(timer)
  }, [])

  const handleAnalyze = async (keyword: string, maxArticles: number, trackPeople: boolean) => {
    setLoading(true)
    setEvents([])
    setResult(null)
    setError(null)
    setExpandedKeyword(null)

    try {
      const { jobId, expandedKeyword: expanded } = await startAnalyze(keyword, maxArticles, trackPeople)
      setExpandedKeyword(expanded)

      let failed = false
      await new Promise<void>((resolve) => {
        subscribeToProgress(
          jobId,
          (e) => {
            setEvents(prev => [...prev, e])
            if (e.step === 'error') {
              setError(e.message)
              failed = true
            }
          },
          resolve,
        )
      })

      if (!failed) {
        const data = await fetchResult(jobId)
        setResult(data)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '分析失败，请重试。')
    } finally {
      setLoading(false)
    }
  }

  const handleHistoryLoad = (historicResult: AnalysisResult, topic: string) => {
    setResult(historicResult)
    setExpandedKeyword(topic)
    setError(null)
    setEvents([])
  }

  const articles = result?.facts_bundle ?? []

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-4xl mx-auto px-4 py-3 flex items-center justify-between">
          <span className="text-lg font-bold text-gray-800">🌐 AI News</span>
          <button
            onClick={() => setHistoryOpen(true)}
            className="text-sm text-gray-500 hover:text-blue-600 transition-colors flex items-center gap-1"
          >
            📋 历史记录
          </button>
        </div>
      </header>

      <HistoryPanel
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        onLoad={handleHistoryLoad}
      />

      <RegionPanel
        countryName={selectedCountry?.name ?? ''}
        countryZh={selectedCountry?.zh ?? ''}
        articles={articles}
        heatCount={selectedCountry ? (heatData[selectedCountry.name] ?? 0) : 0}
        open={selectedCountry !== null}
        onClose={() => setSelectedCountry(null)}
      />

      <main className="max-w-4xl mx-auto px-4 py-8 space-y-4">
        {/* World heatmap — always visible */}
        <WorldMap
          heatData={heatData}
          loading={heatLoading}
          onCountryClick={(name, zh) => setSelectedCountry({ name, zh })}
        />

        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h1 className="text-xl font-bold text-gray-800 mb-1">新闻叙事分析</h1>
          <p className="text-sm text-gray-500 mb-5">
            从西方、中东、俄方、中国等多个立场阵营抓取报道，提炼共识事实与叙事分歧
          </p>
          <AnalyzeForm onSubmit={handleAnalyze} loading={loading} />
        </div>

        {expandedKeyword && (
          <div className="text-xs text-gray-500 px-1">
            搜索关键词已扩展为：
            <span className="ml-1 font-mono bg-gray-100 px-2 py-0.5 rounded text-gray-700">
              {expandedKeyword}
            </span>
          </div>
        )}

        {loading && events.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <ProgressBar events={events} />
          </div>
        )}

        {error && !loading && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
            ❌ {error}
          </div>
        )}

        {result && !loading && <ResultView result={result} />}
      </main>
    </div>
  )
}
