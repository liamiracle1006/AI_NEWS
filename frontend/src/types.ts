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
  published_at?: string | null
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

export interface NarrativeNode {
  date_range: string
  main_event: string
  camp_reactions: Record<string, string>
  significance: string | null
}

export interface CampFirstSeen {
  bias_tag: string
  source_name: string
  first_date: string
  lag_hours: number
}

export interface WeeklyExtras {
  story_arc: NarrativeNode[]
  camp_first_seen: CampFirstSeen[]
  daily_counts: Record<string, number>
}

export interface AnalysisResult {
  facts_bundle: ArticleFacts[]
  cross: CrossReferenceResult
  entities: EntityTrackingResult | null
  weekly?: WeeklyExtras | null
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
  'us-liberal': 'bg-indigo-100 text-indigo-800 border-indigo-200',
  'us-conservative': 'bg-amber-100 text-amber-800 border-amber-200',
  'middle-east': 'bg-green-100 text-green-800 border-green-200',
  'russia-state': 'bg-orange-100 text-orange-800 border-orange-200',
  'china-state': 'bg-red-100 text-red-800 border-red-200',
  'china-nationalist': 'bg-rose-100 text-rose-800 border-rose-200',
  'overseas-chinese': 'bg-purple-100 text-purple-800 border-purple-200',
  'china-hk': 'bg-teal-100 text-teal-800 border-teal-200',
}

export const CAMP_LABELS: Record<string, string> = {
  'western-wire': '西方通讯社',
  'western-uk': '英国视角',
  'us-liberal': '美国主流',
  'us-conservative': '美国保守',
  'middle-east': '中东视角',
  'russia-state': '俄方官方',
  'china-state': '中国官方',
  'china-nationalist': '中国民族主义',
  'overseas-chinese': '海外中文',
  'china-hk': '香港视角',
}

export function campLabel(tag: string): string {
  return CAMP_LABELS[tag] ?? tag
}

export function campColor(tag: string): string {
  return CAMP_COLORS[tag] ?? 'bg-gray-100 text-gray-800 border-gray-200'
}
