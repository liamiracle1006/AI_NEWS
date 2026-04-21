interface Props {
  gaps: string[]
}

export function GapSection({ gaps }: Props) {
  if (gaps.length === 0) return null

  return (
    <section className="bg-white rounded-xl border border-gray-200 p-6">
      <h2 className="text-lg font-semibold text-gray-800 mb-1 flex items-center gap-2">
        🕳️ 可疑缺口
      </h2>
      <p className="text-xs text-gray-400 mb-4">仅单一阵营提及、但若属实对立阵营理应跟进的信息点</p>
      <ul className="space-y-2">
        {gaps.map((g, i) => (
          <li key={i} className="flex gap-3 text-sm text-gray-700">
            <span className="text-amber-500 mt-0.5 shrink-0">⚠</span>
            <span>{g}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
