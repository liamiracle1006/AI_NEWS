import type { AnalysisResult, BriefMeta, ProgressEvent } from './types'

export async function startAnalyze(
  keyword: string,
  maxArticles: number,
  trackPeople: boolean,
): Promise<{ jobId: string; expandedKeyword: string }> {
  const res = await fetch('/api/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keyword, max_articles: maxArticles, track_people: trackPeople, auto_synonyms: true }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail ?? 'Failed to start analysis')
  }
  const data = await res.json()
  return { jobId: data.job_id as string, expandedKeyword: data.expanded_keyword as string }
}

export async function fetchResult(jobId: string): Promise<AnalysisResult> {
  const res = await fetch(`/api/analyze/${jobId}/result`)
  if (!res.ok) throw new Error('Failed to fetch result')
  return res.json()
}

export async function fetchBriefs(): Promise<BriefMeta[]> {
  const res = await fetch('/api/briefs')
  if (!res.ok) throw new Error('Failed to fetch briefs')
  return res.json()
}

export async function fetchBriefContent(id: string): Promise<string> {
  const res = await fetch(`/api/briefs/${id}`)
  if (!res.ok) throw new Error('Brief not found')
  const data = await res.json()
  return data.content as string
}

export async function fetchBriefData(id: string): Promise<import('./types').AnalysisResult> {
  const res = await fetch(`/api/briefs/${id}/data`)
  if (!res.ok) throw new Error('Brief data not found')
  return res.json()
}

export function subscribeToProgress(
  jobId: string,
  onEvent: (e: ProgressEvent) => void,
  onDone: () => void,
): () => void {
  const es = new EventSource(`/api/analyze/${jobId}/stream`)
  es.onmessage = (e) => {
    const data = JSON.parse(e.data) as ProgressEvent
    onEvent(data)
    if (data.step === 'done' || data.step === 'error') {
      es.close()
      onDone()
    }
  }
  es.onerror = () => {
    es.close()
    onDone()
  }
  return () => es.close()
}
