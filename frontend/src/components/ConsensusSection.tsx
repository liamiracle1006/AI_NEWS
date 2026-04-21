interface Props {
  facts: string[]
}

export function ConsensusSection({ facts }: Props) {
  return (
    <section className="bg-white rounded-xl border border-gray-200 p-6">
      <h2 className="text-lg font-semibold text-gray-800 mb-4 flex items-center gap-2">
        🤝 共识事实
        <span className="text-xs font-normal text-gray-400 ml-1">跨阵营承认，可信度较高</span>
      </h2>
      {facts.length === 0 ? (
        <p className="text-sm text-gray-400 italic">本轮分析未识别出跨阵营共识。</p>
      ) : (
        <ul className="space-y-2">
          {facts.map((f, i) => (
            <li key={i} className="flex gap-3 text-sm text-gray-700">
              <span className="text-green-500 mt-0.5 shrink-0">✓</span>
              <span>{f}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
