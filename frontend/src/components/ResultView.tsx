import type { AnalysisResult } from '../types'
import { campLabel } from '../types'
import { ConsensusSection } from './ConsensusSection'
import { DivergenceCard } from './DivergenceCard'
import { EntityCard } from './EntityCard'
import { GapSection } from './GapSection'
import { SourceList } from './SourceList'
import { WeeklyView } from './WeeklyView'

interface Props {
  result: AnalysisResult
}

export function ResultView({ result }: Props) {
  const { cross, entities } = result
  const camps = [...new Set(result.facts_bundle.map(f => f.bias_tag))]

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4">
        <h2 className="font-semibold text-blue-900 text-base mb-1">{cross.topic}</h2>
        <p className="text-xs text-blue-600">
          命中 {result.facts_bundle.length} 篇 · 覆盖{' '}
          {camps.map(c => campLabel(c)).join('、')}
        </p>
      </div>

      <ConsensusSection facts={cross.consensus_facts} />

      {/* Divergences */}
      <section className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-800 mb-4">⚔️ 叙事分歧</h2>
        {cross.divergences.length === 0 ? (
          <p className="text-sm text-gray-400 italic">本轮分析未识别出显著分歧。</p>
        ) : (
          <div className="space-y-2">
            {cross.divergences.map((d, i) => (
              <DivergenceCard key={i} divergence={d} index={i + 1} />
            ))}
          </div>
        )}
      </section>

      <GapSection gaps={cross.suspicious_gaps} />

      {/* Entities */}
      {entities && entities.entities.length > 0 && (
        <section className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-800 mb-4">👤 人物状态速览</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {entities.entities.map((e, i) => (
              <EntityCard key={i} entity={e} />
            ))}
          </div>
        </section>
      )}

      <SourceList sources={cross.sources_covered} />

      {result.weekly && (
        <WeeklyView weekly={result.weekly} />
      )}
    </div>
  )
}
