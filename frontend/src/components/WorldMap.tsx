import { useMemo, useState } from 'react'
import {
  ComposableMap,
  Geographies,
  Geography,
  ZoomableGroup,
} from 'react-simple-maps'

const GEO_URL = '/world-110m.json'

// Countries that should be treated as part of another country
// (political sensitivity + TopoJSON has them as separate polygons)
const REDIRECT: Record<string, string> = {
  Taiwan: 'China',
  'N. Cyprus': 'Cyprus',
}

// Chinese display names for countries shown in the panel header
const ZH_NAMES: Record<string, string> = {
  'United States of America': '美国',
  China: '中国',
  Russia: '俄罗斯',
  Ukraine: '乌克兰',
  Israel: '以色列',
  Palestine: '巴勒斯坦',
  Germany: '德国',
  France: '法国',
  'United Kingdom': '英国',
  Japan: '日本',
  'South Korea': '韩国',
  'North Korea': '朝鲜',
  India: '印度',
  Pakistan: '巴基斯坦',
  Iran: '伊朗',
  'Saudi Arabia': '沙特阿拉伯',
  Turkey: '土耳其',
  Syria: '叙利亚',
  Iraq: '伊拉克',
  Lebanon: '黎巴嫩',
  Egypt: '埃及',
  Libya: '利比亚',
  Yemen: '也门',
  Jordan: '约旦',
  Qatar: '卡塔尔',
  'United Arab Emirates': '阿联酋',
  Sudan: '苏丹',
  Ethiopia: '埃塞俄比亚',
  Nigeria: '尼日利亚',
  Somalia: '索马里',
  'South Africa': '南非',
  Kenya: '肯尼亚',
  Mali: '马里',
  Niger: '尼日尔',
  'Dem. Rep. Congo': '刚果（金）',
  Congo: '刚果（布）',
  Australia: '澳大利亚',
  Brazil: '巴西',
  Argentina: '阿根廷',
  Mexico: '墨西哥',
  Canada: '加拿大',
  Venezuela: '委内瑞拉',
  Cuba: '古巴',
  Colombia: '哥伦比亚',
  Chile: '智利',
  Vietnam: '越南',
  Philippines: '菲律宾',
  Indonesia: '印度尼西亚',
  Myanmar: '缅甸',
  Thailand: '泰国',
  Malaysia: '马来西亚',
  Kazakhstan: '哈萨克斯坦',
  Afghanistan: '阿富汗',
  Bangladesh: '孟加拉国',
  Poland: '波兰',
  Italy: '意大利',
  Spain: '西班牙',
  Sweden: '瑞典',
  Finland: '芬兰',
  Romania: '罗马尼亚',
  Hungary: '匈牙利',
  Serbia: '塞尔维亚',
  Belarus: '白俄罗斯',
  Georgia: '格鲁吉亚',
  Armenia: '亚美尼亚',
  Azerbaijan: '阿塞拜疆',
  'New Zealand': '新西兰',
  Netherlands: '荷兰',
  Switzerland: '瑞士',
}

function heatColor(count: number, max: number): string {
  if (count === 0 || max === 0) return '#d1fae5' // green-100
  const ratio = Math.min(count / Math.max(max, 1), 1)
  // green → yellow → red
  if (ratio < 0.5) {
    const t = ratio * 2
    const r = Math.round(209 + (253 - 209) * t)
    const g = Math.round(250 + (224 - 250) * t)
    const b = Math.round(133 + (71 - 133) * t)
    return `rgb(${r},${g},${b})`
  } else {
    const t = (ratio - 0.5) * 2
    const r = Math.round(253 + (239 - 253) * t)
    const g = Math.round(224 + (68 - 224) * t)
    const b = Math.round(71 + (68 - 71) * t)
    return `rgb(${r},${g},${b})`
  }
}

interface Props {
  heatData: Record<string, number>
  onCountryClick: (name: string, zhName: string) => void
  loading: boolean
}

export function WorldMap({ heatData, onCountryClick, loading }: Props) {
  const [tooltip, setTooltip] = useState<{ name: string; count: number; x: number; y: number } | null>(null)

  const max = useMemo(() => Math.max(0, ...Object.values(heatData)), [heatData])

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-100">
        <span className="text-sm font-semibold text-gray-700">🗺️ 全球新闻热度</span>
        {loading && (
          <span className="text-xs text-gray-400 animate-pulse">加载中...</span>
        )}
        {!loading && max > 0 && (
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <span className="inline-block w-3 h-3 rounded-sm bg-[#d1fae5]" />冷
            <span className="inline-block w-3 h-3 rounded-sm bg-[#fde047]" />
            <span className="inline-block w-3 h-3 rounded-sm bg-[#ef4444]" />热
          </div>
        )}
      </div>

      <div className="relative" style={{ height: 320 }}>
        <ComposableMap
          projectionConfig={{ scale: 147, center: [10, 10] }}
          style={{ width: '100%', height: '100%' }}
        >
          <ZoomableGroup zoom={1} minZoom={1} maxZoom={4}>
            <Geographies geography={GEO_URL}>
              {({ geographies }) =>
                geographies.map((geo) => {
                  const rawName: string = geo.properties.name ?? ''
                  const name = REDIRECT[rawName] ?? rawName
                  const count = heatData[name] ?? 0
                  const fill = heatColor(count, max)

                  return (
                    <Geography
                      key={geo.rsmKey}
                      geography={geo}
                      fill={fill}
                      stroke="#ffffff"
                      strokeWidth={0.5}
                      style={{
                        default: { outline: 'none' },
                        hover: { outline: 'none', opacity: 0.8, cursor: 'pointer' },
                        pressed: { outline: 'none' },
                      }}
                      onMouseEnter={(e) => {
                        setTooltip({
                          name,
                          count,
                          x: e.clientX,
                          y: e.clientY,
                        })
                      }}
                      onMouseLeave={() => setTooltip(null)}
                      onClick={() => {
                        onCountryClick(name, ZH_NAMES[name] ?? name)
                      }}
                    />
                  )
                })
              }
            </Geographies>
          </ZoomableGroup>
        </ComposableMap>

        {tooltip && (
          <div
            className="fixed z-50 bg-gray-900 text-white text-xs px-2 py-1 rounded pointer-events-none"
            style={{ left: tooltip.x + 12, top: tooltip.y - 28 }}
          >
            {ZH_NAMES[tooltip.name] ?? tooltip.name}
            {tooltip.count > 0 && ` · ${tooltip.count} 篇`}
          </div>
        )}
      </div>
    </div>
  )
}
