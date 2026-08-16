export type Dataset = {
  id: string
  name: string
  description: string
  source_kind: string
  source_name: string
  table_name: string
  status: 'pending' | 'etl' | 'indexing' | 'ready' | 'error'
  row_count: number
  column_count: number
  quality_score: number
  error: string | null
  created_at: string
  updated_at: string
  chunk_count?: number
}

export type Column = {
  name: string
  original_name: string
  position: number
  pg_type: string
  semantic_type: string
  null_count: number
  distinct_count: number
  stats: Record<string, any>
}

export type EtlStep = { title: string; detail: string; metric: number | null; at: string }
export type EtlRun = {
  id: number
  status: string
  rows_in: number
  rows_out: number
  steps: EtlStep[]
  error: string | null
  started_at: string
  finished_at: string | null
}

export type Table = { title?: string; columns: string[]; rows: any[][]; sql?: string }
export type Chart = {
  type: 'bar' | 'line' | 'area' | 'pie' | 'scatter'
  title: string
  x: string
  series: string[]
  data: Record<string, any>[]
}
export type Step = { tool: string; detail: string; ok?: boolean; sql?: string; rows?: number }
export type Citation = { kind: string; ref: string; excerpt: string; score: number }

export type ChatReply = {
  conversation_id: string
  answer: string
  steps: Step[]
  tables: Table[]
  charts: Chart[]
  sql: { sql: string; purpose: string; row_count: number }[]
  citations: Citation[]
  model: string
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init)
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      /* non-JSON error body */
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json() as Promise<T>
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  health: () => req<any>('/health'),
  datasets: () => req<Dataset[]>('/datasets'),
  dataset: (id: string) =>
    req<{
      dataset: Dataset
      columns: Column[]
      etl_runs: EtlRun[]
      chunks: Record<string, number>
      chunk_count: number
    }>(`/datasets/${id}`),
  preview: (id: string, limit = 50, offset = 0) =>
    req<Table>(`/datasets/${id}/preview?limit=${limit}&offset=${offset}`),
  upload: async (file: File, name: string, description: string) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('name', name)
    fd.append('description', description)
    const res = await fetch('/api/datasets/upload', { method: 'POST', body: fd })
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? 'Upload failed')
    return res.json()
  },
  manual: (body: unknown) => req<any>('/datasets/manual', json(body)),
  remove: (id: string) => req<any>(`/datasets/${id}`, { method: 'DELETE' }),
  reindex: (id: string) => req<{ chunks: number }>(`/datasets/${id}/reindex`, { method: 'POST' }),
  chunks: (id: string, kind = '', limit = 60) =>
    req<{ id: number; kind: string; ref: string; content: string }[]>(
      `/datasets/${id}/chunks?limit=${limit}${kind ? `&kind=${kind}` : ''}`,
    ),
  search: (id: string, query: string) =>
    req<{ matches: (Citation & { content: string })[] }>(`/datasets/${id}/search`, json({ query })),
  query: (id: string, sql: string) => req<Table & { row_count: number }>(`/datasets/${id}/query`, json({ sql })),
  analyze: (id: string, body: Record<string, unknown>) => req<any>(`/datasets/${id}/analyze`, json(body)),
  suggestions: (id: string) => req<{ questions: string[] }>(`/datasets/${id}/suggestions`),
  chat: (body: { dataset_id: string; question: string; conversation_id?: string }) =>
    req<ChatReply>('/chat', json(body)),
  conversations: (datasetId: string) => req<any[]>(`/conversations?dataset_id=${datasetId}`),
  messages: (id: string) => req<any[]>(`/conversations/${id}/messages`),
  deleteConversation: (id: string) => req<any>(`/conversations/${id}`, { method: 'DELETE' }),
  powerbi: (id: string) => req<any>(`/powerbi/${id}/connection`),
}
