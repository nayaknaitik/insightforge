import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  BarChart3,
  Check,
  Copy,
  Database,
  Download,
  Layers,
  ListTree,
  MessageSquare,
  Play,
  RefreshCw,
  Table2,
  Workflow,
} from 'lucide-react'
import { api, type Chart, type Column, type Dataset, type EtlRun, type Table } from '../api'
import { StationRail } from '../App'
import { ChartCard } from '../Chart'
import { DataTable, ErrorNote, Eyebrow, SectionHead, Spinner, Stat, StatusDot, TYPE_TONE } from '../ui'

type Tab = 'pipeline' | 'schema' | 'data' | 'explore' | 'knowledge' | 'powerbi'

const TABS: [Tab, string, any][] = [
  ['pipeline', 'Pipeline', Workflow],
  ['schema', 'Schema & profile', ListTree],
  ['data', 'Data', Table2],
  ['explore', 'Explore', BarChart3],
  ['knowledge', 'Knowledge base', Layers],
  ['powerbi', 'Power BI', Database],
]

export default function DatasetPage() {
  const { id = '' } = useParams()
  const [tab, setTab] = useState<Tab>('pipeline')
  const [data, setData] = useState<{
    dataset: Dataset
    columns: Column[]
    etl_runs: EtlRun[]
    chunks: Record<string, number>
    chunk_count: number
  } | null>(null)
  const [error, setError] = useState('')

  const load = () => api.dataset(id).then(setData).catch((e) => setError(e.message))

  useEffect(() => {
    setData(null)
    setError('')
    load()
  }, [id])

  useEffect(() => {
    if (!data || data.dataset.status === 'ready' || data.dataset.status === 'error') return
    const t = setInterval(load, 1200)
    return () => clearInterval(t)
  }, [data?.dataset.status, id])

  if (error) return <div className="p-8"><ErrorNote>{error}</ErrorNote></div>
  if (!data) return <div className="p-8"><Spinner label="Loading dataset…" /></div>

  const d = data.dataset

  return (
    <div className="mx-auto max-w-[1180px] px-8 py-8">
      <header className="mb-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <Eyebrow>{d.source_kind === 'upload' ? `from ${d.source_name}` : `from ${d.source_name || d.source_kind}`}</Eyebrow>
            <h1 className="mt-1 font-[family-name:var(--font-display)] text-[30px] font-extrabold tracking-[-0.03em]">
              {d.name}
            </h1>
            {d.description && <p className="mt-1 text-[13.5px] text-fg-2">{d.description}</p>}
          </div>
          <div className="flex items-center gap-2">
            <StatusDot status={d.status} />
            <Link to={`/ask/${d.id}`} className="btn btn-hot">
              <MessageSquare size={14} /> Ask this data
            </Link>
          </div>
        </div>

        <div className="mt-5">
          <StationRail status={d.status} datasetId={d.id} />
        </div>

        {d.status === 'error' && (
          <div className="mt-4">
            <ErrorNote>{d.error}</ErrorNote>
          </div>
        )}
      </header>

      <div className="mb-6 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
        <Stat value={d.row_count.toLocaleString()} label="rows in postgres" />
        <Stat value={d.column_count} label="typed columns" />
        <Stat value={d.quality_score} unit="%" label="cells populated" tone={d.quality_score > 95 ? undefined : 'hot'} />
        <Stat value={data.chunk_count.toLocaleString()} label="knowledge chunks" tone="cool" />
      </div>

      <nav className="mb-5 flex flex-wrap gap-1.5 border-b border-line-soft pb-3">
        {TABS.map(([t, label, Icon]) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`btn ${tab === t ? 'border-amber/60 bg-[#1c1410] text-amber' : 'border-transparent bg-transparent'}`}
          >
            <Icon size={14} /> {label}
          </button>
        ))}
      </nav>

      {tab === 'pipeline' && <Pipeline runs={data.etl_runs} table={d.table_name} chunks={data.chunks} />}
      {tab === 'schema' && <Schema columns={data.columns} rows={d.row_count} />}
      {tab === 'data' && <Preview id={id} />}
      {tab === 'explore' && <Explore id={id} columns={data.columns} table={d.table_name} />}
      {tab === 'knowledge' && <Knowledge id={id} chunks={data.chunks} onReindex={load} />}
      {tab === 'powerbi' && <PowerBI id={id} />}
    </div>
  )
}

/* ------------------------------------------------------------------ tabs -- */

function Pipeline({ runs, table, chunks }: { runs: EtlRun[]; table: string; chunks: Record<string, number> }) {
  const run = runs[0]
  if (!run) return <Spinner label="Waiting for the first run…" />
  return (
    <div className="grid gap-5 lg:grid-cols-[1.25fr_1fr]">
      <section>
        <SectionHead
          title="What happened to your data"
          sub="Every transformation is recorded. Nothing is changed silently."
        />
        <ol className="relative border-l border-line pl-6">
          {run.steps.map((s, i) => (
            <li key={i} className="relative pb-5 last:pb-0 rise" style={{ animationDelay: `${i * 45}ms` }}>
              <span className="absolute -left-[29px] top-1 h-2.5 w-2.5 rounded-full border-2 border-ink-900 bg-amber" />
              <div className="flex items-baseline gap-2">
                <span className="font-[family-name:var(--font-display)] text-[14px] font-semibold">{s.title}</span>
                {s.metric !== null && <span className="chip num">{s.metric.toLocaleString()}</span>}
              </div>
              <p className="mt-0.5 text-[13px] text-fg-2">{s.detail}</p>
            </li>
          ))}
        </ol>
        {run.error && (
          <div className="mt-4">
            <ErrorNote>{run.error}</ErrorNote>
          </div>
        )}
      </section>

      <section className="space-y-4">
        <div className="panel p-4">
          <SectionHead title="Load result" />
          <dl className="space-y-2 text-[13px]">
            <Row k="Postgres table" v={<code className="num text-meter">data.&quot;{table}&quot;</code>} />
            <Row k="Rows in" v={<span className="num">{run.rows_in.toLocaleString()}</span>} />
            <Row k="Rows kept" v={<span className="num">{run.rows_out.toLocaleString()}</span>} />
            <Row
              k="Rows dropped"
              v={<span className="num text-amber">{(run.rows_in - run.rows_out).toLocaleString()}</span>}
            />
            <Row k="Run status" v={<span className={run.status === 'success' ? 'text-good' : 'text-bad'}>{run.status}</span>} />
          </dl>
        </div>
        <div className="panel p-4">
          <SectionHead title="Retrieval index" sub="What the assistant can search over." />
          <dl className="space-y-2 text-[13px]">
            {Object.entries(chunks).length === 0 && <p className="text-fg-3">Indexing…</p>}
            {Object.entries(chunks).map(([k, n]) => (
              <Row key={k} k={LABELS[k] ?? k} v={<span className="num">{n.toLocaleString()}</span>} />
            ))}
          </dl>
        </div>
      </section>
    </div>
  )
}

const LABELS: Record<string, string> = {
  overview: 'Dataset card',
  schema: 'Schema card',
  column: 'Column profiles',
  rows: 'Row narratives',
  insight: 'Pre-computed insights',
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line-soft pb-1.5 last:border-0">
      <dt className="text-fg-3">{k}</dt>
      <dd className="text-right">{v}</dd>
    </div>
  )
}

function Schema({ columns, rows }: { columns: Column[]; rows: number }) {
  return (
    <div>
      <SectionHead title="Columns" sub="Types were inferred from the values, then enforced in Postgres." />
      <div className="grid gap-2.5 md:grid-cols-2">
        {columns.map((c) => {
          const s = c.stats ?? {}
          const fill = 100 - (s.null_pct ?? 0)
          return (
            <article key={c.name} className="panel p-4">
              <div className="flex items-baseline justify-between gap-3">
                <h3 className="num text-[13.5px] font-semibold">{c.name}</h3>
                <span className={`eyebrow ${TYPE_TONE[c.semantic_type] ?? ''}`}>{c.semantic_type}</span>
              </div>
              {c.original_name !== c.name && (
                <p className="mt-0.5 text-[11.5px] text-fg-3">renamed from “{c.original_name}”</p>
              )}

              <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-ink-700">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-amber to-amber-deep"
                  style={{ width: `${fill}%` }}
                />
              </div>
              <div className="mt-1.5 flex justify-between text-[11.5px] text-fg-3">
                <span className="num">{fill.toFixed(1)}% populated</span>
                <span className="num">{c.distinct_count.toLocaleString()} distinct</span>
              </div>

              {(s.mean !== undefined && s.mean !== null) && (
                <div className="mt-3 grid grid-cols-4 gap-2 text-[11.5px]">
                  {[
                    ['min', s.mn],
                    ['median', s.med],
                    ['mean', s.mean],
                    ['max', s.mx],
                  ].map(([k, v]) => (
                    <div key={k as string}>
                      <div className="eyebrow">{k as string}</div>
                      <div className="num mt-0.5 text-fg">{fmtNum(v)}</div>
                    </div>
                  ))}
                </div>
              )}

              {s.min && s.max && c.semantic_type === 'datetime' && (
                <p className="num mt-3 text-[12px] text-fg-2">
                  {String(s.min).slice(0, 10)} → {String(s.max).slice(0, 10)}
                </p>
              )}

              {s.top_values?.length > 0 && (
                <div className="mt-3 space-y-1">
                  {s.top_values.slice(0, 4).map((t: any) => (
                    <div key={String(t.value)} className="flex items-center gap-2 text-[12px]">
                      <span className="w-28 truncate text-fg-2" title={String(t.value)}>
                        {String(t.value)}
                      </span>
                      <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-700">
                        <span className="block h-full rounded-full bg-meter" style={{ width: `${(100 * t.count) / rows}%` }} />
                      </span>
                      <span className="num w-12 text-right text-fg-3">{t.count.toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              )}
            </article>
          )
        })}
      </div>
    </div>
  )
}

const fmtNum = (v: any) =>
  v === null || v === undefined
    ? '—'
    : Math.abs(Number(v)) >= 1000
      ? Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 })
      : String(Number(Number(v).toFixed(3)))

function Preview({ id }: { id: string }) {
  const [page, setPage] = useState(0)
  const [t, setT] = useState<Table | null>(null)
  const [err, setErr] = useState('')
  const size = 50
  useEffect(() => {
    api.preview(id, size, page * size).then(setT).catch((e) => setErr(e.message))
  }, [id, page])
  if (err) return <ErrorNote>{err}</ErrorNote>
  if (!t) return <Spinner label="Reading rows…" />
  return (
    <div>
      <SectionHead
        title="Loaded rows"
        sub="Straight out of Postgres — the typed table, not the original file."
        right={
          <div className="flex items-center gap-2">
            <button className="btn" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
              Previous
            </button>
            <span className="num text-[12px] text-fg-3">rows {page * size + 1}–{page * size + t.rows.length}</span>
            <button className="btn" disabled={t.rows.length < size} onClick={() => setPage((p) => p + 1)}>
              Next
            </button>
          </div>
        }
      />
      <DataTable columns={t.columns} rows={t.rows} />
    </div>
  )
}

function Explore({ id, columns, table }: { id: string; columns: Column[]; table: string }) {
  const [charts, setCharts] = useState<Chart[] | null>(null)
  const [sql, setSql] = useState(`SELECT * FROM data."${table}" LIMIT 20`)
  const [result, setResult] = useState<(Table & { row_count: number }) | null>(null)
  const [sqlErr, setSqlErr] = useState('')
  const [running, setRunning] = useState(false)

  const picks = useMemo(() => {
    const nums = columns.filter((c) => ['integer', 'numeric'].includes(c.semantic_type))
    const cats = columns.filter((c) => ['categorical', 'boolean'].includes(c.semantic_type))
    const dates = columns.filter((c) => c.semantic_type === 'datetime')
    return { nums, cats, dates }
  }, [columns])

  useEffect(() => {
    let dead = false
    setCharts(null)
    const jobs: Promise<Chart | null>[] = []
    const { nums, cats, dates } = picks

    if (cats[0] && nums[0])
      jobs.push(
        api
          .analyze(id, { kind: 'group_summary', dimension: cats[0].name, measure: nums[0].name, agg: 'sum', top: 10 })
          .then((r) => toChart(`Total ${nums[0].name} by ${cats[0].name}`, 'bar', r))
          .catch(() => null),
      )
    if (dates[0] && nums[0])
      jobs.push(
        api
          .analyze(id, { kind: 'trend', date_column: dates[0].name, measure: nums[0].name, agg: 'sum', granularity: 'month' })
          .then((r) => toChart(`${nums[0].name} over time`, 'area', r))
          .catch(() => null),
      )
    if (nums[0])
      jobs.push(
        api
          .analyze(id, { kind: 'distribution', column: nums[0].name })
          .then((r) => toChart(`Distribution of ${nums[0].name}`, 'bar', r))
          .catch(() => null),
      )
    if (cats[1])
      jobs.push(
        api
          .analyze(id, { kind: 'group_summary', dimension: cats[1].name, agg: 'count', top: 8 })
          .then((r) => toChart(`Rows by ${cats[1].name}`, 'pie', r))
          .catch(() => null),
      )

    Promise.all(jobs).then((cs) => !dead && setCharts(cs.filter(Boolean) as Chart[]))
    return () => {
      dead = true
    }
  }, [id, picks])

  const run = async () => {
    setRunning(true)
    setSqlErr('')
    try {
      setResult(await api.query(id, sql))
    } catch (e: any) {
      setSqlErr(e.message)
      setResult(null)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="space-y-7">
      <section>
        <SectionHead title="Automatic views" sub="Generated from the shape of your columns — no configuration." />
        {charts === null ? (
          <Spinner label="Building charts…" />
        ) : charts.length === 0 ? (
          <p className="text-[13px] text-fg-3">
            No numeric or category columns to chart automatically. Use the SQL console below.
          </p>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {charts.map((c, i) => (
              <ChartCard key={i} spec={c} />
            ))}
          </div>
        )}
      </section>

      <section>
        <SectionHead
          title="SQL console"
          sub="Read-only. SELECT and WITH only, capped and timed out."
          right={
            <button className="btn btn-hot" onClick={run} disabled={running}>
              <Play size={13} /> {running ? 'Running…' : 'Run query'}
            </button>
          }
        />
        <textarea
          className="field font-[family-name:var(--font-mono)] text-[12.5px]"
          rows={4}
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') run()
          }}
        />
        <p className="mt-1 text-[11.5px] text-fg-3">⌘/Ctrl + Enter to run.</p>
        {sqlErr && (
          <div className="mt-3">
            <ErrorNote>{sqlErr}</ErrorNote>
          </div>
        )}
        {result && (
          <div className="mt-3">
            <DataTable columns={result.columns} rows={result.rows} />
          </div>
        )}
      </section>
    </div>
  )
}

function toChart(title: string, type: Chart['type'], r: any): Chart | null {
  if (!r?.columns || !r?.rows?.length) return null
  const [xi, yi] = [0, 1]
  const y = r.columns[yi]
  return {
    type,
    title,
    x: r.columns[xi],
    series: [y],
    data: r.rows.map((row: any[]) => ({ label: String(row[xi]), [y]: Number(row[yi]) })),
  }
}

function Knowledge({ id, chunks, onReindex }: { id: string; chunks: Record<string, number>; onReindex: () => void }) {
  const [kind, setKind] = useState('')
  const [items, setItems] = useState<{ id: number; kind: string; ref: string; content: string }[]>([])
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<any[] | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.chunks(id, kind).then(setItems).catch(() => setItems([]))
  }, [id, kind])

  const search = async () => {
    if (!q.trim()) return setHits(null)
    setBusy(true)
    try {
      setHits((await api.search(id, q)).matches)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <section className="panel p-4">
        <SectionHead
          title="Try retrieval"
          sub="This is exactly what the assistant sees before it answers."
          right={
            <button
              className="btn"
              onClick={async () => {
                setBusy(true)
                await api.reindex(id)
                onReindex()
                setBusy(false)
              }}
              disabled={busy}
            >
              <RefreshCw size={13} /> Rebuild index
            </button>
          }
        />
        <div className="flex gap-2">
          <input
            className="field"
            placeholder="e.g. which region sells the most?"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && search()}
          />
          <button className="btn btn-hot" onClick={search} disabled={busy}>
            Search
          </button>
        </div>
        {hits && (
          <div className="mt-4 space-y-2">
            {hits.length === 0 && <p className="text-[13px] text-fg-3">No matches.</p>}
            {hits.map((h, i) => (
              <div key={i} className="rounded-[10px] border border-line bg-ink-950 p-3">
                <div className="mb-1 flex items-center gap-2">
                  <span className="chip">{h.kind}</span>
                  <span className="num text-[11px] text-fg-3">{h.ref}</span>
                  <span className="num ml-auto text-[11px] text-meter">score {h.score?.toFixed?.(3)}</span>
                </div>
                <p className="whitespace-pre-wrap text-[12.5px] text-fg-2">{(h.content ?? h.excerpt ?? '').slice(0, 600)}</p>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <SectionHead title="Indexed chunks" sub="Your data, rewritten as searchable text." />
        <div className="mb-3 flex flex-wrap gap-1.5">
          <button className={`btn ${kind === '' ? 'border-amber/60 text-amber' : ''}`} onClick={() => setKind('')}>
            All
          </button>
          {Object.entries(chunks).map(([k, n]) => (
            <button
              key={k}
              className={`btn ${kind === k ? 'border-amber/60 text-amber' : ''}`}
              onClick={() => setKind(k)}
            >
              {LABELS[k] ?? k} <span className="num text-fg-3">{n}</span>
            </button>
          ))}
        </div>
        <div className="space-y-2">
          {items.map((c) => (
            <details key={c.id} className="panel px-4 py-3">
              <summary className="cursor-pointer list-none text-[13px]">
                <span className="chip mr-2">{c.kind}</span>
                <span className="num text-fg-3">{c.ref}</span>
                <span className="ml-2 text-fg-2">{c.content.slice(0, 90)}…</span>
              </summary>
              <p className="mt-2 whitespace-pre-wrap text-[12.5px] text-fg-2">{c.content}</p>
            </details>
          ))}
        </div>
      </section>
    </div>
  )
}

function PowerBI({ id }: { id: string }) {
  const [info, setInfo] = useState<any>(null)
  const [copied, setCopied] = useState('')
  useEffect(() => {
    api.powerbi(id).then(setInfo).catch(() => setInfo(null))
  }, [id])
  if (!info) return <Spinner label="Preparing connection details…" />
  const d = info.direct_query

  const copy = (k: string, v: string) => {
    navigator.clipboard.writeText(v)
    setCopied(k)
    setTimeout(() => setCopied(''), 1400)
  }

  const Field = ({ k, label, value }: { k: string; label: string; value: string }) => (
    <div className="flex items-center gap-3 border-b border-line-soft py-2 last:border-0">
      <span className="w-32 shrink-0 text-[12.5px] text-fg-3">{label}</span>
      <code className="num min-w-0 flex-1 truncate text-[12.5px] text-fg">{value}</code>
      <button className="btn px-2 py-1" onClick={() => copy(k, value)} title="Copy">
        {copied === k ? <Check size={13} className="text-good" /> : <Copy size={13} />}
      </button>
    </div>
  )

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <section className="panel p-5">
        <SectionHead title="Option A — live PostgreSQL connection" sub="Home ▸ Get Data ▸ PostgreSQL database." />
        <Field k="server" label="Server" value={d.server} />
        <Field k="db" label="Database" value={d.database} />
        <Field k="user" label="User" value={d.user} />
        <Field k="schema" label="Schema" value={d.schema} />
        <Field k="table" label="Table" value={d.table} />
        <Field k="native" label="Native query" value={d.native_query} />
        <p className="mt-3 text-[12.5px] text-fg-3">
          Pick <strong className="text-fg-2">Import</strong> for speed, or <strong className="text-fg-2">DirectQuery</strong> so the
          report refreshes whenever the table changes.
        </p>
      </section>

      <section className="space-y-4">
        <div className="panel p-5">
          <SectionHead title="Option B — one click" sub="Opens Power BI Desktop straight onto this table." />
          <a className="btn btn-hot" href={info.pbids} download>
            <Download size={14} /> Download .pbids file
          </a>
        </div>
        <div className="panel p-5">
          <SectionHead title="Option C — no database driver" sub="Home ▸ Get Data ▸ Web, then paste this URL." />
          <Field k="feed" label="JSON feed" value={info.web_feed} />
        </div>
        <div className="panel p-5">
          <SectionHead title="Option D — static export" sub="For Excel, Sheets, or an offline copy." />
          <a className="btn" href={info.csv} download>
            <Download size={14} /> Download CSV ({info.rows.toLocaleString()} rows)
          </a>
        </div>
      </section>
    </div>
  )
}
