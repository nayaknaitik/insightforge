import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ClipboardPaste, FileUp, Grid3x3, Plus, Upload, X } from 'lucide-react'
import { api } from '../api'
import { ErrorNote, Eyebrow, Spinner } from '../ui'

const SAMPLE = `region,product,units,unit_price,order_date
North,Widget A,120,19.99,2024-03-04
South,Widget B,,24.50,2024-03-06
North,Widget A,86,19.99,2024-04-11
East,Gizmo,45,132.00,2024-04-19`

type Mode = 'file' | 'paste' | 'grid'

export default function Ingest() {
  const nav = useNavigate()
  const [mode, setMode] = useState<Mode>('file')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const [file, setFile] = useState<File | null>(null)
  const [drag, setDrag] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const [text, setText] = useState('')
  const [cols, setCols] = useState<string[]>(['region', 'product', 'units', 'order_date'])
  const [rows, setRows] = useState<string[][]>([
    ['North', 'Widget A', '120', '2024-03-04'],
    ['South', 'Widget B', '86', '2024-03-06'],
    ['', '', '', ''],
  ])

  const go = async (fn: () => Promise<any>, label: string) => {
    setError('')
    setBusy(label)
    try {
      const res = await fn()
      nav(`/data/${res.id}`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy('')
    }
  }

  const submit = () => {
    if (mode === 'file') {
      if (!file) return setError('Choose a file first.')
      return go(() => api.upload(file, name, description), 'Reading, cleaning and loading your file…')
    }
    if (mode === 'paste') {
      if (!text.trim()) return setError('Paste some CSV, TSV or JSON first.')
      return go(
        () => api.manual({ name: name || 'Pasted dataset', description, text }),
        'Parsing and loading the pasted data…',
      )
    }
    const filled = rows.filter((r) => r.some((c) => c.trim() !== ''))
    if (!filled.length) return setError('Fill in at least one row.')
    return go(
      () => api.manual({ name: name || 'Typed dataset', description, columns: cols, rows: filled }),
      'Loading the rows you typed…',
    )
  }

  const setCell = (r: number, c: number, v: string) =>
    setRows((prev) => prev.map((row, i) => (i === r ? row.map((cell, j) => (j === c ? v : cell)) : row)))

  return (
    <div className="mx-auto max-w-[1080px] px-8 py-10">
      {/* hero: the thesis of the product, told with the product's own artefacts */}
      <header className="mb-10">
        <Eyebrow>Station 01 — Ingest</Eyebrow>
        <h1 className="mt-2 font-[family-name:var(--font-display)] text-[42px] font-extrabold leading-[1.04] tracking-[-0.035em]">
          Hand it over raw.
          <br />
          <span className="text-amber">Take it back answered.</span>
        </h1>
        <p className="mt-3 max-w-[58ch] text-[14.5px] text-fg-2">
          Drop in a spreadsheet, a paste, or rows you type by hand. InsightForge cleans it, types it, loads it into
          Postgres, publishes it to Power BI, indexes it for retrieval, and then answers questions about it.
        </p>

        <div className="mt-7 grid gap-3 md:grid-cols-[1fr_auto_1fr] items-center">
          <div className="rounded-[12px] border border-line bg-ink-950 p-4">
            <div className="eyebrow mb-2">What you have</div>
            <pre className="overflow-x-auto font-[family-name:var(--font-mono)] text-[11.5px] leading-[1.7] text-fg-3">
{`Region , Product ,Units, Order Date
 north  ,Widget A, 120 , 03/04/2024
South   ,Widget B,  N/A, 2024-03-06
        ,        ,     ,
South   ,Widget B,  N/A, 2024-03-06`}
            </pre>
          </div>

          <div className="flex flex-col items-center gap-1.5 px-2">
            <span className="hidden h-[2px] w-16 bg-gradient-to-r from-amber to-amber-deep md:block" />
            <span className="eyebrow text-amber">ELT</span>
            <span className="text-[10.5px] text-fg-3">clean · type · load</span>
          </div>

          <div className="plate p-4">
            <div className="mb-2 font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-[0.16em] text-plate-mute">
              What you get
            </div>
            <table className="w-full border-collapse text-[11.5px]">
              <thead>
                <tr className="text-plate-mute">
                  {['region', 'product', 'units', 'order_date'].map((h) => (
                    <th key={h} className="border-b border-plate-line py-1 pr-3 text-left font-[family-name:var(--font-mono)] font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="num">
                <tr>
                  <td className="py-1 pr-3">north</td><td className="pr-3">Widget A</td><td className="pr-3 text-right">120</td><td>2024-03-04</td>
                </tr>
                <tr>
                  <td className="py-1 pr-3">South</td><td className="pr-3">Widget B</td><td className="pr-3 text-right italic text-plate-mute">null</td><td>2024-03-06</td>
                </tr>
              </tbody>
            </table>
            <div className="mt-2 flex flex-wrap gap-1.5 text-[10.5px] text-plate-mute">
              <span className="rounded-full bg-plate-2 px-2 py-0.5">1 blank row dropped</span>
              <span className="rounded-full bg-plate-2 px-2 py-0.5">1 duplicate removed</span>
              <span className="rounded-full bg-plate-2 px-2 py-0.5">4 types inferred</span>
            </div>
          </div>
        </div>
      </header>

      <section className="panel p-5">
        <div className="mb-5 flex flex-wrap items-center gap-1.5">
          {(
            [
              ['file', 'Upload a file', FileUp],
              ['paste', 'Paste data', ClipboardPaste],
              ['grid', 'Type it in', Grid3x3],
            ] as const
          ).map(([m, label, Icon]) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`btn ${mode === m ? 'border-amber/60 bg-[#1c1410] text-amber' : ''}`}
            >
              <Icon size={14} /> {label}
            </button>
          ))}
        </div>

        <div className="mb-5 grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="eyebrow">Dataset name</span>
            <input
              className="field mt-1.5"
              placeholder="Q1 orders, gym members, sensor log…"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="eyebrow">What is it? (helps the assistant)</span>
            <input
              className="field mt-1.5"
              placeholder="One order per row, exported from Shopify"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
        </div>

        {mode === 'file' && (
          <div
            onDragOver={(e) => {
              e.preventDefault()
              setDrag(true)
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDrag(false)
              const f = e.dataTransfer.files?.[0]
              if (f) {
                setFile(f)
                if (!name) setName(f.name.replace(/\.[^.]+$/, ''))
              }
            }}
            className={`grid place-items-center rounded-[12px] border-2 border-dashed px-6 py-12 text-center transition-colors ${
              drag ? 'border-amber bg-[#1a1310]' : 'border-line bg-ink-950'
            }`}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.tsv,.txt,.json,.xlsx,.xls,.xlsm"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) {
                  setFile(f)
                  if (!name) setName(f.name.replace(/\.[^.]+$/, ''))
                }
              }}
            />
            <Upload size={22} className="mb-3 text-amber" />
            {file ? (
              <div className="flex items-center gap-2">
                <span className="num text-[13.5px]">{file.name}</span>
                <span className="chip">{(file.size / 1024).toFixed(0)} KB</span>
                <button className="text-fg-3 hover:text-bad" onClick={() => setFile(null)} title="Remove file">
                  <X size={14} />
                </button>
              </div>
            ) : (
              <>
                <p className="text-[14px] font-medium">Drop a CSV, TSV, JSON or Excel file here</p>
                <p className="mt-1 text-[12.5px] text-fg-3">Up to 50 MB and 200,000 rows.</p>
              </>
            )}
            <button className="btn mt-4" onClick={() => fileRef.current?.click()}>
              Choose a file
            </button>
          </div>
        )}

        {mode === 'paste' && (
          <div>
            <textarea
              className="field font-[family-name:var(--font-mono)] text-[12.5px]"
              rows={12}
              placeholder="Paste CSV, TSV or a JSON array of objects…"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <button className="mt-2 text-[12px] text-meter hover:underline" onClick={() => setText(SAMPLE)}>
              Fill in an example
            </button>
          </div>
        )}

        {mode === 'grid' && (
          <div className="rounded-[12px] border border-line bg-ink-950 p-3">
            <div className="overflow-x-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr>
                    {cols.map((c, j) => (
                      <th key={j} className="p-1">
                        <input
                          className="field font-[family-name:var(--font-mono)] text-[12px]"
                          value={c}
                          onChange={(e) => setCols(cols.map((x, i) => (i === j ? e.target.value : x)))}
                        />
                      </th>
                    ))}
                    <th className="w-8" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <tr key={i}>
                      {row.map((cell, j) => (
                        <td key={j} className="p-1">
                          <input
                            className="field text-[12.5px]"
                            value={cell}
                            onChange={(e) => setCell(i, j, e.target.value)}
                          />
                        </td>
                      ))}
                      <td className="p-1 text-center">
                        <button
                          className="text-fg-3 hover:text-bad"
                          onClick={() => setRows(rows.filter((_, k) => k !== i))}
                          title="Remove row"
                        >
                          <X size={13} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-2 flex gap-2">
              <button className="btn" onClick={() => setRows([...rows, cols.map(() => '')])}>
                <Plus size={13} /> Row
              </button>
              <button
                className="btn"
                onClick={() => {
                  setCols([...cols, `column_${cols.length + 1}`])
                  setRows(rows.map((r) => [...r, '']))
                }}
              >
                <Plus size={13} /> Column
              </button>
            </div>
          </div>
        )}

        {error && (
          <div className="mt-4">
            <ErrorNote>{error}</ErrorNote>
          </div>
        )}

        <div className="mt-5 flex items-center gap-3">
          <button className="btn btn-hot" onClick={submit} disabled={!!busy}>
            {busy ? 'Working…' : 'Run the pipeline'}
          </button>
          {busy && <Spinner label={busy} />}
        </div>
      </section>
    </div>
  )
}
