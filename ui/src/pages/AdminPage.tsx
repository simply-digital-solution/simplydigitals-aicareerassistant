import { useState } from 'react'
import { useQuery, useMutation, useQueryClient, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import adminApi from '../api/adminApi'
import type { AdminUser, DailyCount, DailyTokens, UserTokenDay, AgentRunStats } from '../api/adminApi'

const ADMIN_EMAIL = 'pandiri.vasu@gmail.com'

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 60_000 } } })

// ---------------------------------------------------------------------------
// Access gate
// ---------------------------------------------------------------------------

function useAdminEmail(): string | null {
  try { return localStorage.getItem('user_email') } catch { return null }
}

// ---------------------------------------------------------------------------
// Tiny bar-chart component
// ---------------------------------------------------------------------------

function BarChart({ data, valueKey, label }: {
  data: Record<string, unknown>[]
  valueKey: string
  label: string
}) {
  if (!data.length) return <p className="text-xs text-gray-400 py-4 text-center">No data for this period.</p>
  const max = Math.max(...data.map(d => Number(d[valueKey]) || 0), 1)
  return (
    <div className="space-y-1">
      {data.map((d, i) => {
        const val = Number(d[valueKey]) || 0
        const pct = Math.round((val / max) * 100)
        return (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span className="w-24 text-gray-500 shrink-0 tabular-nums">{String(d.date)}</span>
            <div className="flex-1 bg-gray-100 rounded-full h-4 overflow-hidden">
              <div className="h-4 bg-indigo-500 rounded-full transition-all" style={{ width: `${pct}%` }} />
            </div>
            <span className="w-12 text-right text-gray-700 font-medium tabular-nums">{val}</span>
          </div>
        )
      })}
      <p className="text-xs text-gray-400 pt-1">{label}</p>
    </div>
  )
}

function DualBarChart({ data }: { data: DailyTokens[] }) {
  if (!data.length) return <p className="text-xs text-gray-400 py-4 text-center">No data for this period.</p>
  const maxVal = Math.max(...data.flatMap(d => [d.input_tokens, d.output_tokens]), 1)
  return (
    <div className="space-y-1.5">
      {data.map((d, i) => (
        <div key={i} className="text-xs">
          <span className="text-gray-500 block mb-0.5">{d.date}</span>
          <div className="flex items-center gap-1.5 mb-0.5">
            <span className="w-10 text-indigo-500 shrink-0">in</span>
            <div className="flex-1 bg-gray-100 rounded-full h-3 overflow-hidden">
              <div className="h-3 bg-indigo-400 rounded-full" style={{ width: `${Math.round((d.input_tokens / maxVal) * 100)}%` }} />
            </div>
            <span className="w-16 text-right tabular-nums text-gray-700">{d.input_tokens.toLocaleString()}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-10 text-emerald-500 shrink-0">out</span>
            <div className="flex-1 bg-gray-100 rounded-full h-3 overflow-hidden">
              <div className="h-3 bg-emerald-400 rounded-full" style={{ width: `${Math.round((d.output_tokens / maxVal) * 100)}%` }} />
            </div>
            <span className="w-16 text-right tabular-nums text-gray-700">{d.output_tokens.toLocaleString()}</span>
          </div>
        </div>
      ))}
    </div>
  )
}

function AgentRunChart({ data }: { data: AgentRunStats[] }) {
  if (!data.length) return <p className="text-xs text-gray-400 py-4 text-center">No data for this period.</p>
  const maxVal = Math.max(...data.flatMap(d => [d.complete, d.failed]), 1)
  return (
    <div className="space-y-1.5">
      {data.map((d, i) => (
        <div key={i} className="text-xs">
          <span className="text-gray-500 block mb-0.5">{d.date}</span>
          <div className="flex items-center gap-1.5 mb-0.5">
            <span className="w-12 text-green-600 shrink-0">ok</span>
            <div className="flex-1 bg-gray-100 rounded-full h-3 overflow-hidden">
              <div className="h-3 bg-green-400 rounded-full" style={{ width: `${Math.round((d.complete / maxVal) * 100)}%` }} />
            </div>
            <span className="w-8 text-right tabular-nums">{d.complete}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-12 text-red-500 shrink-0">fail</span>
            <div className="flex-1 bg-gray-100 rounded-full h-3 overflow-hidden">
              <div className="h-3 bg-red-400 rounded-full" style={{ width: `${Math.round((d.failed / maxVal) * 100)}%` }} />
            </div>
            <span className="w-8 text-right tabular-nums">{d.failed}</span>
          </div>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Stat card
// ---------------------------------------------------------------------------

function StatCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5">
      <h3 className="text-sm font-semibold text-gray-800 mb-4">{title}</h3>
      {children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// User management table
// ---------------------------------------------------------------------------

function UserTable() {
  const qc = useQueryClient()
  const { data: users = [], isLoading } = useQuery({
    queryKey: ['admin-users'],
    queryFn: () => adminApi.listUsers().then(r => r.data),
  })

  const activate = useMutation({
    mutationFn: (id: number) => adminApi.activateUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
  })
  const suspend = useMutation({
    mutationFn: (id: number) => adminApi.suspendUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
  })

  if (isLoading) return <p className="text-sm text-gray-400">Loading users…</p>

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-gray-200 text-left">
            <th className="py-2 pr-4 text-gray-500 font-medium">Email</th>
            <th className="py-2 pr-4 text-gray-500 font-medium">Joined</th>
            <th className="py-2 pr-4 text-gray-500 font-medium">Last active</th>
            <th className="py-2 pr-4 text-gray-500 font-medium text-right">LLM calls</th>
            <th className="py-2 pr-4 text-gray-500 font-medium text-right">Jobs</th>
            <th className="py-2 text-gray-500 font-medium">Status</th>
            <th className="py-2 text-gray-500 font-medium">Action</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u: AdminUser) => (
            <tr key={u.id} className="border-b border-gray-100 hover:bg-gray-50">
              <td className="py-2 pr-4 font-medium text-gray-900">{u.email}</td>
              <td className="py-2 pr-4 text-gray-500">{u.created_at.slice(0, 10)}</td>
              <td className="py-2 pr-4 text-gray-500">{u.last_active ? u.last_active.slice(0, 10) : '—'}</td>
              <td className="py-2 pr-4 text-right tabular-nums">{u.total_llm_requests}</td>
              <td className="py-2 pr-4 text-right tabular-nums">{u.total_jobs}</td>
              <td className="py-2 pr-4">
                {u.scoring_suspended
                  ? <span className="inline-block px-2 py-0.5 rounded-full bg-red-50 text-red-600 font-medium">Suspended</span>
                  : <span className="inline-block px-2 py-0.5 rounded-full bg-green-50 text-green-700 font-medium">Active</span>
                }
              </td>
              <td className="py-2">
                {u.scoring_suspended ? (
                  <button
                    onClick={() => activate.mutate(u.id)}
                    disabled={activate.isPending}
                    className="text-xs border border-green-300 text-green-700 px-2.5 py-1 rounded-lg hover:bg-green-50 disabled:opacity-40 transition-colors"
                  >
                    Activate
                  </button>
                ) : (
                  <button
                    onClick={() => suspend.mutate(u.id)}
                    disabled={suspend.isPending}
                    className="text-xs border border-red-300 text-red-600 px-2.5 py-1 rounded-lg hover:bg-red-50 disabled:opacity-40 transition-colors"
                  >
                    Suspend
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {users.length === 0 && <p className="text-sm text-gray-400 pt-4 text-center">No users found.</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Per-user token table
// ---------------------------------------------------------------------------

function UserTokenTable({ days }: { days: number }) {
  const { data = [], isLoading } = useQuery({
    queryKey: ['admin-llm-per-user', days],
    queryFn: () => adminApi.llmPerUser(days).then(r => r.data),
  })

  if (isLoading) return <p className="text-sm text-gray-400">Loading…</p>
  if (!data.length) return <p className="text-xs text-gray-400 py-4 text-center">No data for this period.</p>

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-gray-200 text-left">
            <th className="py-2 pr-4 text-gray-500 font-medium">Date</th>
            <th className="py-2 pr-4 text-gray-500 font-medium">User</th>
            <th className="py-2 pr-4 text-gray-500 font-medium text-right">Requests</th>
            <th className="py-2 pr-4 text-gray-500 font-medium text-right">Input tokens</th>
            <th className="py-2 text-gray-500 font-medium text-right">Output tokens</th>
          </tr>
        </thead>
        <tbody>
          {(data as UserTokenDay[]).map((r, i) => (
            <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
              <td className="py-2 pr-4 text-gray-500">{r.date}</td>
              <td className="py-2 pr-4 font-medium text-gray-900 max-w-[200px] truncate">{r.email}</td>
              <td className="py-2 pr-4 text-right tabular-nums">{r.requests}</td>
              <td className="py-2 pr-4 text-right tabular-nums">{r.input_tokens.toLocaleString()}</td>
              <td className="py-2 text-right tabular-nums">{r.output_tokens.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main dashboard
// ---------------------------------------------------------------------------

function AdminDashboard() {
  const [days, setDays] = useState(30)

  const { data: usersActive = [] } = useQuery({
    queryKey: ['admin-users-active', days],
    queryFn: () => adminApi.usersActive(days).then(r => r.data),
  })
  const { data: llmTokens = [] } = useQuery({
    queryKey: ['admin-llm-tokens', days],
    queryFn: () => adminApi.llmTokens(days).then(r => r.data),
  })
  const { data: jobsScraped = [] } = useQuery({
    queryKey: ['admin-jobs-scraped', days],
    queryFn: () => adminApi.jobsScraped(days).then(r => r.data),
  })
  const { data: agentRuns = [] } = useQuery({
    queryKey: ['admin-agent-runs', days],
    queryFn: () => adminApi.agentRuns(days).then(r => r.data),
  })
  const { data: scoring = [] } = useQuery({
    queryKey: ['admin-scoring', days],
    queryFn: () => adminApi.scoring(days).then(r => r.data),
  })

  const totalIn = (llmTokens as DailyTokens[]).reduce((s, d) => s + d.input_tokens, 0)
  const totalOut = (llmTokens as DailyTokens[]).reduce((s, d) => s + d.output_tokens, 0)
  const totalJobs = (jobsScraped as DailyCount[]).reduce((s, d) => s + d.count, 0)
  const totalActive = new Set((usersActive as DailyCount[]).map(() => 0)).size  // placeholder — real: distinct users
  const peakActive = Math.max(...(usersActive as DailyCount[]).map(d => d.count), 0)

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-8 py-4 flex items-center justify-between sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center">
            <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>
          <div>
            <h1 className="text-base font-bold text-gray-900">Admin Dashboard</h1>
            <p className="text-xs text-gray-400">AI Career Assistant</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <label className="text-xs text-gray-500">Period:</label>
          <select
            value={days}
            onChange={e => setDays(Number(e.target.value))}
            className="text-xs border border-gray-300 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-400"
          >
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-8 py-6 space-y-6">

        {/* KPI summary row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Peak daily active users', value: peakActive },
            { label: 'Total input tokens', value: totalIn.toLocaleString() },
            { label: 'Total output tokens', value: totalOut.toLocaleString() },
            { label: 'Jobs scraped', value: totalJobs },
          ].map(kpi => (
            <div key={kpi.label} className="bg-white border border-gray-200 rounded-xl p-4">
              <p className="text-xs text-gray-400 mb-1">{kpi.label}</p>
              <p className="text-2xl font-bold text-gray-900">{kpi.value}</p>
            </div>
          ))}
        </div>

        {/* Charts — top row */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <StatCard title="1 · Active users per day">
            <BarChart
              data={usersActive as Record<string, unknown>[]}
              valueKey="count"
              label="Distinct users with at least one LLM call"
            />
          </StatCard>

          <StatCard title="2 · LLM tokens per day (input / output)">
            <DualBarChart data={llmTokens as DailyTokens[]} />
          </StatCard>
        </div>

        {/* Charts — second row */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <StatCard title="3 · New jobs scraped per day">
            <BarChart
              data={jobsScraped as Record<string, unknown>[]}
              valueKey="count"
              label="Across all users"
            />
          </StatCard>

          <StatCard title="7 · Agent run success / failure">
            <AgentRunChart data={agentRuns as AgentRunStats[]} />
          </StatCard>

          <StatCard title="8 · Jobs scored per day">
            <BarChart
              data={scoring as Record<string, unknown>[]}
              valueKey="jobs_scored"
              label="From daily_scoring_usage"
            />
          </StatCard>
        </div>

        {/* Per-user tables */}
        <StatCard title="4 & 5 · LLM requests + tokens per user per day">
          <UserTokenTable days={days} />
        </StatCard>

        {/* User management */}
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-gray-800 mb-4">6 · User management</h3>
          <UserTable />
        </div>

      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Access gate wrapper
// ---------------------------------------------------------------------------

export default function AdminPage() {
  const email = useAdminEmail()

  if (email !== ADMIN_EMAIL) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="bg-white border border-gray-200 rounded-2xl shadow-sm p-10 text-center max-w-sm">
          <div className="w-12 h-12 rounded-full bg-red-50 flex items-center justify-center mx-auto mb-4">
            <svg className="w-6 h-6 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
            </svg>
          </div>
          <h2 className="text-lg font-bold text-gray-900 mb-2">Access denied</h2>
          <p className="text-sm text-gray-500 mb-6">
            This page is restricted to administrators.<br />
            Sign in as <span className="font-medium text-gray-700">{ADMIN_EMAIL}</span> to continue.
          </p>
          <a
            href="/"
            className="inline-block text-sm bg-indigo-600 text-white px-5 py-2 rounded-lg hover:bg-indigo-700 transition-colors"
          >
            Go to app
          </a>
        </div>
      </div>
    )
  }

  return (
    <QueryClientProvider client={qc}>
      <AdminDashboard />
    </QueryClientProvider>
  )
}
