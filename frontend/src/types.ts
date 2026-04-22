export interface ExtractedFact {
  when: string | null
  where: string | null
  who: string[]
  action: string | null
  numbers: string[]
  context: string | null
  key_quotes: string[]
  source_claims_verbatim: string[]
}

export interface ArticleFacts {
  article_url: string
  source_name: string
  bias_tag: string
  title: string
  facts: ExtractedFact
}

export interface Divergence {
  point: string
  camp_claims: Record<string, string>
  observation: string | null
}

export interface SourceRef {
  source_name: string
  bias_tag: string
  url: string
  title: string
}

export interface CrossReferenceResult {
  topic: string
  generated_at: string
  sources_covered: SourceRef[]
  consensus_facts: string[]
  divergences: Divergence[]
  suspicious_gaps: string[]
}

export interface EntityEvent {
  canonical_name: string
  aliases: string[]
  position: string | null
  action_or_status: string
  status_change: string | null
  per_source_framing: Record<string, string>
  sources: string[]
}

export interface EntityTrackingResult {
  topic: string
  generated_at: string
  entities: EntityEvent[]
}

export interface AnalysisResult {
  facts_bundle: ArticleFacts[]
  cross: CrossReferenceResult
  entities: EntityTrackingResult | null
}

export interface BriefMeta {
  id: string
  topic: string
  generated_at: string
  filename: string
  article_count: number
  has_data: boolean
}

export interface ProgressEvent {
  step: 'fetching' | 'extracting' | 'done' | 'error'
  message: string
}

export interface MapArticle {
  title: string
  url: string
  source_name: string
  bias_tag: string
  summary: string
  published_at: string | null
}

// Camp colors
export const CAMP_COLORS: Record<string, string> = {
  'western-wire': 'bg-blue-100 text-blue-800 border-blue-200',
  'western-uk': 'bg-sky-100 text-sky-800 border-sky-200',
  'middle-east': 'bg-green-100 text-green-800 border-green-200',
  'russia-state': 'bg-orange-100 text-orange-800 border-orange-200',
  'china-state': 'bg-red-100 text-red-800 border-red-200',
  'china-nationalist': 'bg-rose-100 text-rose-800 border-rose-200',
  'overseas-chinese': 'bg-purple-100 text-purple-800 border-purple-200',
}

export const CAMP_LABELS: Record<string, string> = {
  'western-wire': '西方通讯社',
  'western-uk': '英国视角',
  'middle-east': '中东视角',
  'russia-state': '俄方官方',
  'china-state': '中国官方',
  'china-nationalist': '中国民族主义',
  'overseas-chinese': '海外中文',
}

export function campLabel(tag: string): string {
  return CAMP_LABELS[tag] ?? tag
}

export function campColor(tag: string): string {
  return CAMP_COLORS[tag] ?? 'bg-gray-100 text-gray-800 border-gray-200'
}
