import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  ArrowUp,
  BookOpen,
  ChevronDown,
  Database,
  MessageSquarePlus,
  Search,
  Sigma,
  Terminal,
} from 'lucide-react'
import { api, type ChatReply, type Dataset } from '../api'
import { ChartCard } from '../Chart'
import { DataTable, ErrorNote, Eyebrow, Spinner, StatusDot } from '../ui'

type Msg =
  | { role: 'user'; content: string }
  | ({ role: 'assistant'; content: string } & Partial<ChatReply>)

const TOOL_ICON: Record<string, any> = {
  run_sql: Terminal,
  search_data: Search,
  analyze: Sigma,
  make_chart: Database,
  model: BookOpen,
}

export default function Ask() {
  const { id = '' } = useParams()
  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [convId, setConvId] = useState<string | undefined>()
  const [convs, setConvs] = useState<any[]>([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [ideas, setIdeas] = useState<string[]>([])
  const [keyMissing, setKeyMissing] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.health().then((h) => setKeyMissing(!h?.llm?.key_configured)).catch(() => {})
  }, [])

  useEffect(() => {
    api.dataset(id).then((d) => setDataset(d.dataset)).catch((e) => setError(e.message))
    api.suggestions(id).then((r) => setIdeas(r.questions)).catch(() => {})
    api.conversations(id).then(setConvs).catch(() => {})
    setMsgs([])
    setConvId(undefined)
  }, [id])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [msgs, busy])

  const openConversation = async (cid: string) => {
    const rows = await api.messages(cid)
    setConvId(cid)
    setMsgs(
      rows.map((m: any) =>
        m.role === 'user' ? { role: 'user', content: m.content } : { role: 'assistant', content: m.content, ...(m.meta ?? {}) },
      ),
    )
  }

  const send = async (text?: string) => {
    const question = (text ?? q).trim()
    if (!question || busy) return
    setQ('')
    setError('')
    setMsgs((m) => [...m, { role: 'user', content: question }])
    setBusy(true)
    try {
      const r = await api.chat({ dataset_id: id, question, conversation_id: convId })
      setConvId(r.conversation_id)
      setMsgs((m) => [...m, { role: 'assistant', content: r.answer, ...r }])
      api.conversations(id).then(setConvs).catch(() => {})
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 border-b border-line-soft bg-ink-900/85 px-8 py-4 backdrop-blur">
          <div className="mx-auto flex max-w-[880px] items-center gap-3">
            <div className="min-w-0">
              <Eyebrow>Station 05 — Ask</Eyebrow>
              <h1 className="truncate font-[family-name:var(--font-display)] text-[19px] font-bold tracking-[-0.02em]">
                {dataset?.name ?? 'Loading…'}
              </h1>
            </div>
            {dataset && (
              <div className="ml-auto flex items-center gap-3">
                <span className="num hidden text-[11.5px] text-fg-3 sm:inline">
                  {dataset.row_count.toLocaleString()} rows · {dataset.column_count} cols
                </span>
                <StatusDot status={dataset.status} />
                <Link to={`/data/${id}`} className="btn">
                  Workbench
                </Link>
                <button
                  className="btn"
                  onClick={() => {
                    setConvId(undefined)
                    setMsgs([])
                  }}
                  title="Start a new conversation"
                >
                  <MessageSquarePlus size={14} />
                </button>
              </div>
            )}
          </div>
        </header>

        <div className="flex-1 px-8 py-7">
          <div className="mx-auto max-w-[880px] space-y-6">
            {msgs.length === 0 && (
              <div className="rise">
                <h2 className="font-[family-name:var(--font-display)] text-[26px] font-extrabold tracking-[-0.03em]">
                  Ask anything about <span className="text-amber">{dataset?.name}</span>.
                </h2>
                <p className="mt-2 max-w-[62ch] text-[14px] text-fg-2">
                  Answers come from your own rows. The assistant writes SQL against the loaded table, runs statistics,
                  and cites the parts of the data it read. Every number is traceable.
                </p>
                <div className="mt-5 grid gap-2 sm:grid-cols-2">
                  {ideas.map((s) => (
                    <button
                      key={s}
                      onClick={() => send(s)}
                      className="panel px-4 py-3 text-left text-[13px] text-fg-2 transition-colors hover:border-amber/50 hover:text-fg"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {msgs.map((m, i) => (m.role === 'user' ? <UserMsg key={i} text={m.content} /> : <Answer key={i} m={m} />))}

            {busy && (
              <div className="panel flex items-center gap-3 px-4 py-3">
                <span className="h-1.5 w-1.5 rounded-full bg-amber pulse-dot" />
                <Spinner label="Reading your data, writing SQL, checking the numbers…" />
              </div>
            )}
            {error && <ErrorNote>{error}</ErrorNote>}
            <div ref={endRef} />
          </div>
        </div>

        <div className="sticky bottom-0 border-t border-line-soft bg-ink-900/90 px-8 py-4 backdrop-blur">
          {keyMissing && (
            <div className="mx-auto mb-3 max-w-[880px] rounded-[10px] border border-[#5a4520] bg-[#241c0f] px-3.5 py-2.5 text-[12.5px] text-[#f0d9a8]">
              Add your Groq key to <code className="num">backend/.env</code> as{' '}
              <code className="num">GROQ_API_KEY=gsk_…</code> and restart the API. Everything else on this
              dataset already works.
            </div>
          )}
          <div className="mx-auto flex max-w-[880px] items-end gap-2">
            <textarea
              className="field resize-none py-2.5"
              rows={1}
              placeholder="Ask a question about this dataset…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send()
                }
              }}
            />
            <button className="btn btn-hot h-[38px]" onClick={() => send()} disabled={busy || !q.trim()}>
              <ArrowUp size={15} />
            </button>
          </div>
        </div>
      </div>

      <aside className="hidden w-[220px] shrink-0 border-l border-line-soft px-3 py-5 xl:block">
        <div className="eyebrow mb-2 px-1">Conversations</div>
        {convs.length === 0 && <p className="px-1 text-[12.5px] text-fg-3">No history yet.</p>}
        {convs.map((c) => (
          <button
            key={c.id}
            onClick={() => openConversation(c.id)}
            className={`mb-1 block w-full truncate rounded-[9px] px-2.5 py-2 text-left text-[12.5px] transition-colors ${
              convId === c.id ? 'bg-[#1a1410] text-amber' : 'text-fg-2 hover:bg-ink-850'
            }`}
            title={c.title}
          >
            {c.title}
          </button>
        ))}
      </aside>
    </div>
  )
}

function UserMsg({ text }: { text: string }) {
  return (
    <div className="flex justify-end rise">
      <div className="max-w-[80%] rounded-[13px] rounded-br-[4px] border border-[#3a2a1c] bg-[#1a1410] px-4 py-2.5 text-[13.5px]">
        {text}
      </div>
    </div>
  )
}

function Answer({ m }: { m: Msg & { role: 'assistant' } }) {
  const [openSteps, setOpenSteps] = useState(false)
  const [openCites, setOpenCites] = useState(false)
  const steps = m.steps ?? []
  const cites = m.citations ?? []

  return (
    <article className="rise space-y-3">
      {steps.length > 0 && (
        <div className="panel overflow-hidden">
          <button
            onClick={() => setOpenSteps((v) => !v)}
            className="flex w-full items-center gap-2 px-4 py-2.5 text-left"
          >
            <span className="eyebrow">How this was answered</span>
            <span className="num text-[11px] text-fg-3">{steps.length} steps</span>
            <ChevronDown size={14} className={`ml-auto text-fg-3 transition-transform ${openSteps ? 'rotate-180' : ''}`} />
          </button>
          <div className={openSteps ? 'block' : 'hidden'}>
            <ol className="space-y-2 border-t border-line-soft px-4 py-3">
              {steps.map((s, i) => {
                const Icon = TOOL_ICON[s.tool] ?? Sigma
                return (
                  <li key={i} className="flex gap-2.5 text-[12.5px]">
                    <Icon size={13} className={`mt-0.5 shrink-0 ${s.ok === false ? 'text-bad' : 'text-meter'}`} />
                    <div className="min-w-0">
                      <span className="num text-fg-3">{s.tool}</span>
                      <p className="text-fg-2">{s.detail}</p>
                      {s.sql && (
                        <pre className="mt-1 overflow-x-auto rounded-[8px] border border-line bg-ink-950 px-3 py-2 font-[family-name:var(--font-mono)] text-[11.5px] text-[#cfe3f2]">
                          {s.sql}
                        </pre>
                      )}
                    </div>
                  </li>
                )
              })}
            </ol>
          </div>
        </div>
      )}

      <div className="prose-forge">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
      </div>

      {(m.charts ?? []).length > 0 && (
        <div className={m.charts!.length > 1 ? 'grid gap-3 lg:grid-cols-2' : ''}>
          {m.charts!.map((c, i) => (
            <ChartCard key={i} spec={c} height={m.charts!.length > 1 ? 250 : 300} />
          ))}
        </div>
      )}

      {(m.tables ?? []).slice(0, 3).map((t, i) => (
        <div key={i}>
          {t.title && <div className="eyebrow mb-1.5">{t.title}</div>}
          <DataTable columns={t.columns} rows={t.rows} max={100} dense />
        </div>
      ))}

      {cites.length > 0 && (
        <div>
          <button onClick={() => setOpenCites((v) => !v)} className="flex items-center gap-1.5 text-[11.5px] text-fg-3 hover:text-fg-2">
            <BookOpen size={12} />
            {cites.length} pieces of your data were read
            <ChevronDown size={12} className={openCites ? 'rotate-180' : ''} />
          </button>
          {openCites && (
            <div className="mt-2 space-y-1.5">
              {cites.map((c, i) => (
                <div key={i} className="rounded-[9px] border border-line bg-ink-950 px-3 py-2">
                  <div className="mb-1 flex items-center gap-2">
                    <span className="chip">{c.kind}</span>
                    <span className="num text-[11px] text-fg-3">{c.ref}</span>
                  </div>
                  <p className="whitespace-pre-wrap text-[12px] text-fg-3">{c.excerpt}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {m.model && <div className="num text-[10.5px] text-fg-3">answered by {m.model} on groq</div>}
    </article>
  )
}
