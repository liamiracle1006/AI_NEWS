import type { ProgressEvent } from '../types'

interface Props {
  events: ProgressEvent[]
}

export function ProgressBar({ events }: Props) {
  const latest = events[events.length - 1]
  if (!latest) return null

  const isError = latest.step === 'error'
  const isDone = latest.step === 'done'

  // Parse "事实提取 3/8 篇..." to get extraction progress
  let pct = isError || isDone ? 100 : 20
  if (latest.step === 'extracting') {
    const m = latest.message.match(/(\d+)\/(\d+)/)
    if (m) {
      pct = 20 + Math.round((parseInt(m[1]) / parseInt(m[2])) * 60)
    } else {
      pct = latest.message.includes('交叉') ? 85 : latest.message.includes('人物') ? 93 : 30
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex justify-between text-xs text-gray-500">
        <span className="truncate max-w-[85%]">{latest.message}</span>
        <span>{pct}%</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2">
        <div
          className={`h-2 rounded-full transition-all duration-300 ${isError ? 'bg-red-500' : 'bg-blue-500'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
