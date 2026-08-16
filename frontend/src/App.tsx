import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom'
import { Database, Cpu, Plus, Sparkles, Trash2 } from 'lucide-react'
import { api, type Dataset } from './api'
import { StatusDot } from './ui'

export function useDatasets() {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const refresh = async () => {
    try {
      setDatasets(await api.datasets())
      setError('')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    refresh()
  }, [])
  return { datasets, loading, error, refresh }
}

function Wordmark() {
  return (
    <div className="px-4 pt-5 pb-4">
      <div className="flex items-center gap-2.5">
        <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden>
          <rect width="32" height="32" rx="7" fill="#0f1620" stroke="#22303f" />
          <path d="M8 21 L16 8 L24 21 Z" fill="none" stroke="#ff8a3d" strokeWidth="2.4" strokeLinejoin="round" />
          <path d="M11.5 21h9" stroke="#6ab7e8" strokeWidth="2.4" strokeLinecap="round" />
        </svg>
        <div className="leading-none">
          <div className="font-[family-name:var(--font-display)] text-[15px] font-extrabold tracking-[-0.02em]">
            Insight<span className="text-amber">Forge</span>
          </div>
          <div className="eyebrow mt-1">raw data → answers</div>
        </div>
      </div>
    </div>
  )
}

export default function App() {
  const { datasets, refresh } = useDatasets()
  const [health, setHealth] = useState<any>(null)
  const nav = useNavigate()
  const loc = useLocation()
  const { id } = useParams()

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ ok: false }))
  }, [])

  // datasets that are still being processed need polling, nothing else does
  useEffect(() => {
    const busy = datasets.some((d) => d.status === 'etl' || d.status === 'indexing')
    if (!busy) return
    const t = setInterval(refresh, 1500)
    return () => clearInterval(t)
  }, [datasets, refresh])

  useEffect(() => {
    refresh()
  }, [loc.pathname])

  const remove = async (d: Dataset, e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (!confirm(`Delete "${d.name}"? The Postgres table and its knowledge base go with it.`)) return
    await api.remove(d.id)
    if (loc.pathname.includes(d.id)) nav('/')
    refresh()
  }

  return (
    <div className="relative z-10 flex h-full">
      <aside className="flex w-[200px] shrink-0 sm:w-[254px] flex-col border-r border-line-soft bg-ink-950/70 backdrop-blur">
        <Wordmark />
        <div className="px-3">
          <button className="btn btn-hot w-full justify-center" onClick={() => nav('/')}>
            <Plus size={15} /> New dataset
          </button>
        </div>

        <div className="mt-5 px-4 flex items-center justify-between">
          <span className="eyebrow">Datasets</span>
          <span className="num text-[11px] text-fg-3">{datasets.length}</span>
        </div>

        <nav className="mt-2 flex-1 overflow-y-auto px-2 pb-3">
          {datasets.length === 0 && (
            <p className="px-2 py-3 text-[12.5px] text-fg-3">Nothing loaded yet. Start with a file or a paste.</p>
          )}
          {datasets.map((d) => (
            <NavLink
              key={d.id}
              to={`/data/${d.id}`}
              className={({ isActive }) =>
                `group relative block rounded-[10px] px-3 py-2.5 mb-1 border transition-colors ${
                  isActive || id === d.id
                    ? 'border-[#3a2a1c] bg-[#1a1410]'
                    : 'border-transparent hover:bg-ink-850 hover:border-line-soft'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && <span className="absolute left-0 top-2.5 bottom-2.5 w-[2px] rounded-full bg-amber" />}
                  <div className="flex items-center gap-2">
                    <span className="truncate text-[13px] font-medium">{d.name}</span>
                    <button
                      onClick={(e) => remove(d, e)}
                      title="Delete dataset"
                      className="ml-auto opacity-0 transition-opacity group-hover:opacity-100 text-fg-3 hover:text-bad"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                  <div className="mt-1 flex items-center gap-2.5">
                    <StatusDot status={d.status} />
                    <span className="num text-[11px] text-fg-3">
                      {d.row_count.toLocaleString()} × {d.column_count}
                    </span>
                  </div>
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-line-soft px-4 py-3 space-y-1.5">
          <div className="flex items-center gap-2 text-[11.5px] text-fg-3">
            <Database size={12} className={health?.postgres?.ok ? 'text-good' : 'text-bad'} />
            <span className="truncate">
              {health?.postgres?.ok ? `${health.postgres.database} @ ${health.postgres.host}` : 'Postgres offline'}
            </span>
          </div>
          <div className="flex items-center gap-2 text-[11.5px] text-fg-3">
            <Cpu size={12} className={health?.llm?.key_configured ? 'text-good' : 'text-warn'} />
            <span className="truncate">
              {health?.llm?.key_configured ? health.llm.model : 'Groq key missing'}
            </span>
          </div>
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto">
        <Outlet context={{ datasets, refresh }} />
      </main>
    </div>
  )
}

/** The signature element: the five stations a dataset moves through. */
export function StationRail({ status, datasetId }: { status: string; datasetId?: string }) {
  const stations = ['Ingest', 'Transform', 'Profile', 'Index', 'Ask']
  const reached =
    status === 'error' ? 1 : status === 'etl' ? 1 : status === 'indexing' ? 3 : status === 'ready' ? 5 : 0
  const nav = useNavigate()
  return (
    <div className="flex items-center gap-0 overflow-x-auto">
      {stations.map((s, i) => {
        const done = i < reached
        const active = i === reached - 1
        const last = i === stations.length - 1
        return (
          <div key={s} className="flex items-center shrink-0">
            <button
              disabled={!last || status !== 'ready'}
              onClick={() => last && datasetId && nav(`/ask/${datasetId}`)}
              className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11.5px] transition-colors ${
                done
                  ? 'border-[#4a3320] bg-[#1c1410] text-amber'
                  : 'border-line bg-ink-850 text-fg-3'
              } ${last && status === 'ready' ? 'cursor-pointer hover:border-amber' : ''}`}
            >
              {last && status === 'ready' ? <Sparkles size={11} /> : <span className={`h-1.5 w-1.5 rounded-full ${done ? 'bg-amber' : 'bg-[#2c3a4a]'} ${active && status !== 'ready' ? 'pulse-dot' : ''}`} />}
              {s}
            </button>
            {!last && (
              <span className="relative h-[2px] w-7 bg-[#1e2a37] overflow-hidden">
                <span
                  className={`absolute inset-0 ${i < reached - 1 ? 'bg-gradient-to-r from-amber to-amber-deep' : ''} ${
                    i === reached - 1 && status !== 'ready' && status !== 'error' ? 'sweep' : ''
                  }`}
                />
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}
