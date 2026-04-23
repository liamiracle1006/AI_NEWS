import { ResponsiveSankey } from '@nivo/sankey'
import type { WeeklyExtras, AttentionPeriod } from '../types'
import { campLabel, campColor } from '../types'

interface Props {
  weekly: WeeklyExtras
}

// Fixed theme colors for consistent Sankey node coloring
const THEME_COLORS: Record<string, string> = {
  '军事行动': '#ef4444',
  '外交斡旋': '#3b82f6',
  '经济制裁': '#f59e0b',
  '人道主义': '#10b981',
  '政治局势': '#8b5cf6',
  '法律司法': '#6b7280',
  '其他':     '#d1d5db',
}

const PERIOD_COLORS = ['#0ea5e9', '#7c3aed', '#0d9488', '#dc2626', '#d97706']

function buildSankeyData(periods: AttentionPeriod[]) {
  const periodSet = new Set(periods.map(p => p.label))
  const themeSet = new Set(periods.flatMap(p => Object.keys(p.themes)))
  const nodes = [
    ...Array.from(periodSet).map(id => ({ id })),
    ...Array.from(themeSet).map(id => ({ id })),
  ]
  const links = periods.flatMap(p =>
    Object.entries(p.themes)
      .filter(([, v]) => v > 0)
      .map(([theme, value]) => ({ source: p.label, target: theme, value }))
  )
  return { nodes, links }
}

export function WeeklyView({ weekly }: Props) {
  const { story_arc, camp_first_seen, daily_counts, attention_shift, narrative_elasticity } = weekly
  const maxCount = Math.max(1, ...Object.values(daily_counts))

  return (
    <div className="space-y-4">
      {/* ── Coverage Momentum ── */}
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

      {/* ── Attention Shift Sankey ── */}
      {attention_shift.length > 0 && (
        <section className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-800 mb-1">🌊 议题聚光灯转移</h2>
          <p className="text-xs text-gray-400 mb-4">
            左侧为时间段，右侧为主题，流量宽度代表文章数量
          </p>
          <div style={{ height: 260 }}>
            <ResponsiveSankey
              data={buildSankeyData(attention_shift)}
              margin={{ top: 10, right: 120, bottom: 10, left: 120 }}
              align="justify"
              colors={(node) =>
                THEME_COLORS[node.id] ??
                PERIOD_COLORS[
                  attention_shift.findIndex(p => p.label === node.id) % PERIOD_COLORS.length
                ] ??
                '#94a3b8'
              }
              nodeOpacity={0.9}
              nodeHoverOpacity={1}
              nodeThickness={20}
              nodeSpacing={14}
              nodeBorderWidth={0}
              nodeBorderRadius={3}
              linkOpacity={0.35}
              linkHoverOpacity={0.7}
              linkContract={2}
              enableLinkGradient={true}
              labelPosition="outside"
              labelPadding={12}
              labelTextColor={{ from: 'color', modifiers: [['darker', 1.2]] }}
              animate={true}
            />
          </div>
          {/* Legend */}
          <div className="flex flex-wrap gap-2 mt-3">
            {Object.entries(THEME_COLORS)
              .filter(([theme]) =>
                attention_shift.some(p => theme in p.themes)
              )
              .map(([theme, color]) => (
                <span key={theme} className="flex items-center gap-1 text-xs text-gray-600">
                  <span className="w-2.5 h-2.5 rounded-sm inline-block" style={{ background: color }} />
                  {theme}
                </span>
              ))}
          </div>
        </section>
      )}

      {/* ── Story Arc ── */}
      {story_arc.length > 0 && (
        <section className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-800 mb-5">🕰️ 叙事时间线</h2>
          <div className="relative">
            <div className="absolute left-3 top-2 bottom-2 w-0.5 bg-gray-200" />
            <div className="space-y-6">
              {story_arc.map((node, i) => (
                <div key={i} className="pl-10 relative">
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

      {/* ── Narrative Elasticity ── */}
      {narrative_elasticity.length > 0 && (
        <section className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-800 mb-1">🎯 叙事弹性分析</h2>
          <p className="text-xs text-gray-400 mb-4">各阵营在本周内是否调整了叙事框架</p>
          <div className="space-y-3">
            {narrative_elasticity.map((e, i) => (
              <div
                key={i}
                className={`rounded-lg border p-4 ${
                  e.shifted
                    ? 'border-orange-200 bg-orange-50'
                    : 'border-gray-100 bg-gray-50'
                }`}
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className={`inline-flex items-center text-xs px-1.5 py-0.5 rounded border font-medium ${campColor(e.bias_tag)}`}>
                    {campLabel(e.bias_tag)}
                  </span>
                  {e.shifted ? (
                    <span className="text-xs font-semibold text-orange-600">⚡ 立场转向</span>
                  ) : (
                    <span className="text-xs text-gray-400">→ 立场稳定</span>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <div className="text-gray-400 mb-0.5 font-medium">前期</div>
                    <div className="text-gray-700 leading-relaxed">{e.early_stance}</div>
                  </div>
                  <div>
                    <div className="text-gray-400 mb-0.5 font-medium">后期</div>
                    <div className={`leading-relaxed ${e.shifted ? 'text-orange-700 font-medium' : 'text-gray-700'}`}>
                      {e.late_stance}
                    </div>
                  </div>
                </div>
                {e.shifted && e.shift_description && (
                  <p className="text-xs text-orange-600 mt-2 italic">
                    📌 {e.shift_description}
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ── Info Lag ── */}
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
                        <span className="text-xs font-semibold text-green-600">最早</span>
                      ) : c.lag_hours > 72 ? (
                        <span className="text-xs font-semibold text-red-600">+{c.lag_hours.toFixed(0)}h 明显滞后</span>
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
