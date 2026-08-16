import type { ReactNode } from 'react'
import { AlertTriangle, Loader2 } from 'lucide-react'

export function Eyebrow({ children }: { children: ReactNode }) {
  return <div className="eyebrow">{children}</div>
}

export function SectionHead({ title, sub, right }: { title: string; sub?: string; right?: ReactNode }) {
  return (
    <div className="flex items-end justify-between gap-4 mb-3">
      <div>
        <h2 className="font-[family-name:var(--font-display)] text-[17px] font-semibold tracking-[-0.01em]">
          {title}
        </h2>
        {sub && <p className="text-[12.5px] text-fg-3 mt-0.5">{sub}</p>}
      </div>
      {right}
    </div>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-fg-3 text-[13px]">
      <Loader2 size={14} className="animate-spin" />
      {label}
    </div>
  )
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <div className="flex gap-2.5 rounded-[10px] border border-[#5a2a26] bg-[#2a1512] px-3.5 py-3 text-[13px] text-[#ffc9be]">
      <AlertTriangle size={15} className="mt-0.5 shrink-0 text-bad" />
      <div className="min-w-0 break-words">{children}</div>
    </div>
  )
}

export function StatusDot({ status }: { status: string }) {
  const map: Record<string, [string, string]> = {
    ready: ['bg-good', 'Ready'],
    indexing: ['bg-meter', 'Indexing'],
    etl: ['bg-amber', 'Transforming'],
    pending: ['bg-fg-3', 'Queued'],
    error: ['bg-bad', 'Failed'],
  }
  const [color, label] = map[status] ?? ['bg-fg-3', status]
  const live = status === 'indexing' || status === 'etl'
  return (
    <span className="inline-flex items-center gap-1.5 text-[11.5px] text-fg-2">
      <span className={`h-1.5 w-1.5 rounded-full ${color} ${live ? 'pulse-dot' : ''}`} />
      {label}
    </span>
  )
}

/** A stat readout. Number first, label second — never the other way round. */
export function Stat({ value, label, unit, tone }: { value: ReactNode; label: string; unit?: string; tone?: 'hot' | 'cool' }) {
  const color = tone === 'hot' ? 'text-amber' : tone === 'cool' ? 'text-meter' : 'text-fg'
  return (
    <div className="panel px-4 py-3">
      <div className={`num text-[22px] leading-tight font-semibold ${color}`}>
        {value}
        {unit && <span className="text-[13px] text-fg-3 ml-0.5">{unit}</span>}
      </div>
      <div className="eyebrow mt-1">{label}</div>
    </div>
  )
}

const fmtCell = (v: any) => {
  if (v === null || v === undefined) return null
  if (typeof v === 'number') {
    const abs = Math.abs(v)
    if (Number.isInteger(v)) return v.toLocaleString()
    return abs >= 1000 ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(Number(v.toFixed(4)))
  }
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  // midnight timestamps are dates — don't make the reader parse "T00:00:00"
  return String(v).replace(/^(\d{4}-\d{2}-\d{2})T00:00:00(\.0+)?$/, '$1')
}

/** Tabular data always sits on a plate: warm, high-contrast, tabular numerals. */
export function DataTable({
  columns,
  rows,
  max = 400,
  dense,
}: {
  columns: string[]
  rows: any[][]
  max?: number
  dense?: boolean
}) {
  if (!columns?.length) return <p className="text-[13px] text-fg-3">No columns returned.</p>
  const shown = rows.slice(0, max)
  const pad = dense ? 'px-2.5 py-1' : 'px-3 py-1.5'
  return (
    <div className="plate overflow-hidden">
      <div className="overflow-auto max-h-[460px]">
        <table className="w-full border-collapse text-[12.5px]">
          <thead className="sticky top-0 z-10">
            <tr className="bg-plate-2">
              {columns.map((c) => (
                <th
                  key={c}
                  className={`${pad} text-left font-medium text-plate-ink/70 border-b border-plate-line whitespace-nowrap font-[family-name:var(--font-mono)] text-[11px] uppercase tracking-[0.07em]`}
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={i} className={i % 2 ? 'bg-black/[0.025]' : ''}>
                {r.map((v, j) => {
                  const s = fmtCell(v)
                  return (
                    <td
                      key={j}
                      className={`${pad} border-b border-plate-line/60 whitespace-nowrap ${
                        typeof v === 'number' ? 'num text-right tabular-nums' : ''
                      }`}
                    >
                      {s === null ? <span className="text-plate-mute italic">null</span> : s}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > shown.length && (
        <div className="border-t border-plate-line bg-plate-2 px-3 py-1.5 text-[11.5px] text-plate-mute">
          Showing {shown.length.toLocaleString()} of {rows.length.toLocaleString()} rows.
        </div>
      )}
    </div>
  )
}

export function Empty({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div className="panel flex flex-col items-center gap-3 px-6 py-14 text-center">
      <div className="h-9 w-9 rounded-[10px] border border-line bg-ink-800 grid place-items-center">
        <span className="text-amber text-[15px]">◆</span>
      </div>
      <div>
        <p className="font-[family-name:var(--font-display)] text-[15px] font-semibold">{title}</p>
        <p className="mt-1 max-w-[46ch] text-[13px] text-fg-3">{body}</p>
      </div>
      {action}
    </div>
  )
}

export const TYPE_TONE: Record<string, string> = {
  integer: 'text-s2',
  numeric: 'text-s2',
  datetime: 'text-s4',
  categorical: 'text-s3',
  boolean: 'text-s6',
  identifier: 'text-fg-3',
  text: 'text-fg-2',
}
