import { useQuery } from '@tanstack/react-query'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { statsApi } from '../api/client'
import type { DayStat, MonthStat } from '../api/client'

const BLUE   = '#1F5C9E'
const GREEN  = '#16a34a'
const AMBER  = '#d97706'
const PURPLE = '#7c3aed'
const TEAL   = '#0d9488'

function shortDate(iso: string) {
  const d = new Date(iso + 'T00:00:00')
  return `${d.getDate()}/${d.getMonth() + 1}`
}

function shortMonth(ym: string) {
  const [y, m] = ym.split('-')
  return new Date(Number(y), Number(m) - 1).toLocaleString('default', { month: 'short', year: '2-digit' })
}

interface ChartCardProps {
  title: string
  subtitle: string
  color: string
  data: DayStat[]
  dataKey?: string
  labelFn?: (v: string) => string
}

function ChartCard({ title, subtitle, color, data, dataKey = 'date', labelFn = shortDate }: ChartCardProps) {
  const total = data.reduce((s, d) => s + d.count, 0)
  // Show every 5th label to avoid crowding
  const tickFormatter = (v: string, i: number) => i % 5 === 0 ? labelFn(v) : ''

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 flex flex-col gap-2">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-semibold text-gray-800">{title}</p>
          <p className="text-xs text-gray-500">{subtitle}</p>
        </div>
        <span
          className="text-2xl font-bold"
          style={{ color }}
        >
          {total}
        </span>
      </div>
      <ResponsiveContainer width="100%" height={140}>
        <BarChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f0f0f0" />
          <XAxis
            dataKey={dataKey}
            tickFormatter={tickFormatter}
            tick={{ fontSize: 10, fill: '#9ca3af' }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fontSize: 10, fill: '#9ca3af' }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            formatter={(v) => [v, 'Count']}
            labelFormatter={(v) => labelFn(String(v))}
            contentStyle={{ fontSize: 12, borderRadius: 6 }}
          />
          <Bar dataKey="count" fill={color} radius={[3, 3, 0, 0]} maxBarSize={24} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

interface MonthChartCardProps {
  title: string
  subtitle: string
  color: string
  data: MonthStat[]
}

function MonthChartCard({ title, subtitle, color, data }: MonthChartCardProps) {
  const total = data.reduce((s, d) => s + d.count, 0)
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 flex flex-col gap-2">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-semibold text-gray-800">{title}</p>
          <p className="text-xs text-gray-500">{subtitle}</p>
        </div>
        <span className="text-2xl font-bold" style={{ color }}>{total}</span>
      </div>
      <ResponsiveContainer width="100%" height={140}>
        <BarChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f0f0f0" />
          <XAxis
            dataKey="month"
            tickFormatter={shortMonth}
            tick={{ fontSize: 11, fill: '#9ca3af' }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fontSize: 10, fill: '#9ca3af' }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            formatter={(v) => [v, 'Count']}
            labelFormatter={(v) => shortMonth(String(v))}
            contentStyle={{ fontSize: 12, borderRadius: 6 }}
          />
          <Bar dataKey="count" fill={color} radius={[3, 3, 0, 0]} maxBarSize={48} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function StatsPanel() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['stats-dashboard'],
    queryFn: () => statsApi.dashboard().then(r => r.data),
    staleTime: 5 * 60 * 1000,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400 text-sm">
        Loading stats…
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="flex items-center justify-center h-64 text-red-500 text-sm">
        Failed to load stats. Please try again.
      </div>
    )
  }

  return (
    <div className="p-6 max-w-5xl mx-auto flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900">Activity Dashboard</h2>
        <p className="text-sm text-gray-500 mt-0.5">Last 30 days · interviews shown by month</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <ChartCard
          title="Jobs Scored by AI"
          subtitle="Daily count of jobs scored in last 30 days"
          color={BLUE}
          data={data.scored_by_day}
        />
        <ChartCard
          title="Jobs Fit for Profile"
          subtitle="Fit score ≥ 70% · last 30 days"
          color={GREEN}
          data={data.fit_by_day}
        />
        <ChartCard
          title="Jobs Selected"
          subtitle="Added to pipeline per day · last 30 days"
          color={AMBER}
          data={data.selected_by_day}
        />
        <ChartCard
          title="Jobs Applied"
          subtitle="Applications submitted per day · last 30 days"
          color={PURPLE}
          data={data.applied_by_day}
        />
      </div>

      <MonthChartCard
        title="Interview Calls"
        subtitle="Jobs moved to Interviewing status · last 3 months"
        color={TEAL}
        data={data.interviews_by_month}
      />
    </div>
  )
}
