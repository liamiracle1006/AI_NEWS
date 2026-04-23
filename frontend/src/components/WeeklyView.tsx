import type { WeeklyExtras } from '../types'
import { campLabel, campColor } from '../types'

interface Props {
  weekly: WeeklyExtras
}

export function WeeklyView({ weekly }: Props) {
  const { story_arc, camp_first_seen, daily_counts } = weekly

  const maxCount = Math.max(1, ...Object.values(daily_counts))

  return (
    <div className="space-y-4">
      {/* Coverage Momentum */}
      {Object.keys(daily_counts).length > 0 && (
        <section className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-800 mb-4">📈 报道热度趋势</h2>
          <div className="flex items-end gap-2 h-24">
            {Object.entries(daily_counts).map(([day, count]) => (
              <div key={day} className="flex-1 flex flex-col items-center gap-1">
                <span className="text-xs text-gray-500 font-medium">{count}</span>
                <div
                  className="w-full bg-blue-400 rounded-t transition-all"
                  style={{ height: `${Math.round((count / maxCount) * 72)}px` }}
                />
                <span className="text-xs text-gray-400 whitespace-nowrap">
                  {day.slice(5).replace('-', '/')}
                </span>
              </div>
            ))}
          </div>
          <p className="text-xs text-gray-400 mt-2">
            峰值日：
            {Object.entries(daily_counts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? '—'}
            （{maxCount} 篇）
          </p>
        </section>
      )}

      {/* Story Arc */}
      {story_arc.length > 0 && (
        <section className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-800 mb-5">🕰️ 叙事时间线</h2>
          <div className="relative">
            {/* Vertical spine */}
            <div className="absolute left-3 top-2 bottom-2 w-0.5 bg-gray-200" />
            <div className="space-y-6">
              {story_arc.map((node, i) => (
                <div key={i} className="pl-10 relative">
                  {/* Dot */}
                  <div className="absolute left-1.5 top-1 w-3 h-3 rounded-full bg-blue-500 border-2 border-white shadow" />
                  <div className="text-xs font-semibold text-blue-600 mb-1">{node.date_range}</div>
                  <p className="text-sm font-medium text-gray-800 mb-2">{node.main_event}</p>
                  {node.significance && (
                    <p className="text-xs text-gray-400 italic mb-2">💡 {node.significance}</p>
                  )}
                  {Object.keys(node.camp_reactions).length > 0 && (
                    <div className="space-y-1.5">
                      {Object.entries(node.camp_reactions).map(([tag, reaction]) => (
                        <div key={tag} className="flex gap-2 text-xs">
                          <span className={`shrink-0 inline-flex items-center px-1.5 py-0.5 rounded border font-medium ${campColor(tag)}`}>
                            {campLabel(tag)}
                          </span>
                          <span className="text-gray-600 leading-relaxed">{reaction}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* Info Lag */}
      {camp_first_seen.length > 1 && (
        <section className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-800 mb-1">⏱️ 信息响应速度</h2>
          <p className="text-xs text-gray-400 mb-4">各阵营首次报道本话题的时间，以最早报道者为基准</p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left py-2 pr-4 text-xs font-medium text-gray-500">阵营</th>
                  <th className="text-left py-2 pr-4 text-xs font-medium text-gray-500">来源</th>
                  <th className="text-left py-2 pr-4 text-xs font-medium text-gray-500">首次日期</th>
                  <th className="text-left py-2 text-xs font-medium text-gray-500">滞后</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {camp_first_seen.map((c, i) => (
                  <tr key={i} className="hover:bg-gray-50 transition-colors">
                    <td className="py-2 pr-4">
                      <span className={`inline-flex items-center text-xs px-1.5 py-0.5 rounded border font-medium ${campColor(c.bias_tag)}`}>
                        {campLabel(c.bias_tag)}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-xs text-gray-600">{c.source_name}</td>
                    <td className="py-2 pr-4 text-xs text-gray-600">{c.first_date}</td>
                    <td className="py-2">
                      {c.lag_hours === 0 ? (
                        <span className="text-xs font-medium text-green-600">最早</span>
                      ) : c.lag_hours > 72 ? (
                        <span className="text-xs font-medium text-red-600">+{c.lag_hours.toFixed(0)}h 明显滞后</span>
                      ) : (
                        <span className="text-xs text-gray-500">+{c.lag_hours.toFixed(0)}h</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {camp_first_seen.some(c => c.lag_hours > 72) && (
            <p className="text-xs text-orange-600 mt-3">
              ⚠️ 滞后超过 72 小时可能表明存在议程压制或信息管控。
            </p>
          )}
        </section>
      )}
    </div>
  )
}
