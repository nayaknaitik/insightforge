import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { Chart as ChartSpec } from './api'

/** Validated categorical palette (see backend README): fixed order, never cycled. */
export const SERIES = ['#c4561e', '#1b6ec2', '#0e8f63', '#7a4fbf', '#c42b5c', '#a87400']
const GRID = '#ddd6c8'
const AXIS = '#6a7583'

const short = (v: any) => {
  if (typeof v !== 'number') return String(v ?? '')
  const a = Math.abs(v)
  if (a >= 1e9) return `${(v / 1e9).toFixed(1)}B`
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}k`
  return Number.isInteger(v) ? String(v) : String(Number(v.toFixed(2)))
}

const clip = (s: any, n = 18) => {
  const t = String(s ?? '')
  return t.length > n ? `${t.slice(0, n - 1)}…` : t
}

function TipBox({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-[9px] border border-[#cfc7b6] bg-[#fffdf8] px-3 py-2 shadow-lg">
      <div className="mb-1 font-[family-name:var(--font-mono)] text-[11px] uppercase tracking-[0.07em] text-plate-mute">
        {String(label ?? payload[0]?.name ?? '')}
      </div>
      {payload.map((p: any, i: number) => (
        <div key={i} className="flex items-center gap-2 text-[12.5px] text-plate-ink">
          <span className="h-2 w-2 rounded-[2px]" style={{ background: p.color ?? p.fill }} />
          <span className="text-plate-mute">{p.name}</span>
          <span className="num ml-auto font-medium tabular-nums">
            {typeof p.value === 'number' ? p.value.toLocaleString(undefined, { maximumFractionDigits: 3 }) : String(p.value)}
          </span>
        </div>
      ))}
    </div>
  )
}

const legendStyle = { fontSize: 12, fontFamily: 'IBM Plex Sans', color: '#4a545f', paddingTop: 6 }

export function ChartCard({ spec, height = 280 }: { spec: ChartSpec; height?: number }) {
  const { type, title, x, series, data } = spec
  const multi = series.length > 1
  const axis = { stroke: AXIS, fontSize: 11, tickLine: false, axisLine: { stroke: GRID } }

  const body = () => {
    switch (type) {
      case 'line':
      case 'area': {
        const C = type === 'line' ? LineChart : AreaChart
        return (
          <C data={data} margin={{ top: 6, right: 14, bottom: 4, left: 4 }}>
            <defs>
              {series.map((s, i) => (
                <linearGradient key={s} id={`fill-${i}-${title.replace(/\W/g, '')}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={SERIES[i % 6]} stopOpacity={0.32} />
                  <stop offset="100%" stopColor={SERIES[i % 6]} stopOpacity={0.03} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
            <XAxis dataKey="label" tickFormatter={(v) => clip(v, 12)} {...axis} />
            <YAxis tickFormatter={short} width={52} {...axis} />
            <Tooltip content={<TipBox />} cursor={{ stroke: '#b8b0a0', strokeWidth: 1 }} />
            {multi && <Legend wrapperStyle={legendStyle} iconType="plainline" iconSize={14} />}
            {series.map((s, i) =>
              type === 'line' ? (
                <Line isAnimationActive={false}
                  key={s}
                  type="monotone"
                  dataKey={s}
                  stroke={SERIES[i % 6]}
                  strokeWidth={2}
                  dot={data.length <= 40 ? { r: 2.5, strokeWidth: 0, fill: SERIES[i % 6] } : false}
                  activeDot={{ r: 4.5, stroke: '#f6f3ec', strokeWidth: 2 }}
                />
              ) : (
                <Area isAnimationActive={false}
                  key={s}
                  type="monotone"
                  dataKey={s}
                  stroke={SERIES[i % 6]}
                  strokeWidth={2}
                  fill={`url(#fill-${i}-${title.replace(/\W/g, '')})`}
                  activeDot={{ r: 4.5, stroke: '#f6f3ec', strokeWidth: 2 }}
                />
              ),
            )}
          </C>
        )
      }
      case 'pie': {
        const key = series[0]
        return (
          <PieChart>
            <Tooltip content={<TipBox />} />
            <Legend wrapperStyle={legendStyle} iconType="square" iconSize={9} />
            <Pie isAnimationActive={false}
              data={data.map((d) => ({ name: clip(d.label, 22), value: Number(d[key]) || 0 }))}
              dataKey="value"
              nameKey="name"
              innerRadius="52%"
              outerRadius="82%"
              paddingAngle={2}
              stroke="#f6f3ec"
              strokeWidth={2}
            >
              {data.map((_, i) => (
                <Cell key={i} fill={SERIES[i % 6]} />
              ))}
            </Pie>
          </PieChart>
        )
      }
      case 'scatter': {
        return (
          <ScatterChart margin={{ top: 8, right: 14, bottom: 4, left: 4 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="2 4" />
            <XAxis dataKey="label" name={x} tickFormatter={(v) => clip(v, 12)} {...axis} />
            <YAxis dataKey={series[0]} name={series[0]} tickFormatter={short} width={52} {...axis} />
            <Tooltip content={<TipBox />} cursor={{ strokeDasharray: '3 3' }} />
            {multi && <Legend wrapperStyle={legendStyle} iconType="circle" iconSize={9} />}
            {series.map((s, i) => (
              <Scatter isAnimationActive={false} key={s} name={s} data={data} dataKey={s} fill={SERIES[i % 6]} />
            ))}
          </ScatterChart>
        )
      }
      default: {
        return (
          <BarChart data={data} margin={{ top: 6, right: 14, bottom: 4, left: 4 }} barCategoryGap="22%" barGap={2}>
            <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
            <XAxis dataKey="label" tickFormatter={(v) => clip(v, 12)} interval={0} angle={data.length > 8 ? -25 : 0} textAnchor={data.length > 8 ? 'end' : 'middle'} height={data.length > 8 ? 58 : 30} {...axis} />
            <YAxis tickFormatter={short} width={52} {...axis} />
            <Tooltip content={<TipBox />} cursor={{ fill: 'rgba(0,0,0,0.04)' }} />
            {multi && <Legend wrapperStyle={legendStyle} iconType="square" iconSize={9} />}
            {series.map((s, i) => (
              <Bar isAnimationActive={false} key={s} dataKey={s} fill={SERIES[i % 6]} radius={[4, 4, 0, 0]} maxBarSize={46} />
            ))}
          </BarChart>
        )
      }
    }
  }

  return (
    <figure className="plate px-4 pt-3.5 pb-3 m-0">
      <figcaption className="mb-2">
        <span className="font-[family-name:var(--font-display)] text-[14px] font-semibold text-plate-ink">{title}</span>
        {!multi && <span className="ml-2 text-[11.5px] text-plate-mute">{series[0]}</span>}
      </figcaption>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          {body()}
        </ResponsiveContainer>
      </div>
    </figure>
  )
}
