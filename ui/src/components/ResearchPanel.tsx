import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { ProfileData, StoredJobsResponse, StoredJob } from '../api/client'
import api from '../api/client'

type FeedbackMap = Record<string, 'relevant' | 'not_relevant'>

const STORED_PAGE_SIZE = 10
const STORED_DATE_OPTIONS = [
  { label: 'All time', days: 0 },
  { label: 'Today', days: 1 },
  { label: 'Last 7 days', days: 7 },
  { label: 'Last 30 days', days: 30 },
]

function FitBadge({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color =
    pct >= 80 ? 'bg-green-100 text-green-800' :
    pct >= 60 ? 'bg-yellow-100 text-yellow-800' :
                'bg-red-100 text-red-800'
  return <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${color}`}>{pct}%</span>
}

function parseJsonArray(val: string | null | undefined): string[] {
  if (!val) return []
  try { return JSON.parse(val) } catch { return [] }
}

function StoredJobCard({ job, feedback, onFeedback }: {
  job: StoredJob
  feedback?: 'relevant' | 'not_relevant'
  onFeedback: (url: string, title: string, company: string, rel: 'relevant' | 'not_relevant') => void
}) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const industries = parseJsonArray(job.inferred_industries)
  const keywords   = parseJsonArray(job.key_keywords)
  const reasons    = parseJsonArray(job.reasons)
  const risks      = parseJsonArray(job.risks)

  const borderCls =
    feedback === 'relevant'     ? 'border-green-400 bg-green-50' :
    feedback === 'not_relevant' ? 'border-red-300 bg-red-50 opacity-70' :
    'border-gray-200'

  const handleFeedback = async (rel: 'relevant' | 'not_relevant') => {
    if (saving) return
    setSaving(true)
    try {
      await api.post('/research/feedback', {
        job_url: job.url, job_title: job.title, company: job.company, relevance: rel,
      })
      onFeedback(job.url, job.title, job.company, rel)
    } finally {
      setSaving(false)
    }
  }

  const postedLabel = job.posted_at
    ? new Date(job.posted_at).toLocaleDateString('en-SG', { day: 'numeric', month: 'short', year: 'numeric' })
    : null

  return (
    <div className={`border rounded-lg p-4 space-y-2 transition-colors ${borderCls}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium text-gray-900 truncate">{job.title}</p>
          <p className="text-sm text-gray-500">
            {job.company}
            {postedLabel && <span className="ml-2 text-xs text-gray-400">· {postedLabel}</span>}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {!!job.scored && job.fit_score !== null
            ? <FitBadge score={job.fit_score} />
            : <span className="text-xs text-gray-400 italic">Scoring…</span>
          }
          <button title="Relevant" disabled={saving} onClick={() => handleFeedback('relevant')}
            className={`text-base leading-none px-1.5 py-0.5 rounded transition-colors ${
              feedback === 'relevant' ? 'bg-green-200 text-green-700' : 'hover:bg-green-100 text-gray-400 hover:text-green-600'
            } disabled:opacity-40`}>👍</button>
          <button title="Not relevant" disabled={saving} onClick={() => handleFeedback('not_relevant')}
            className={`text-base leading-none px-1.5 py-0.5 rounded transition-colors ${
              feedback === 'not_relevant' ? 'bg-red-200 text-red-600' : 'hover:bg-red-100 text-gray-400 hover:text-red-500'
            } disabled:opacity-40`}>👎</button>
        </div>
      </div>

      {industries.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {industries.map(ind => (
            <span key={ind} className="text-xs bg-teal-50 text-teal-700 border border-teal-200 px-2 py-0.5 rounded-full">{ind}</span>
          ))}
        </div>
      )}

      {keywords.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {keywords.map(kw => (
            <span key={kw} className="text-xs bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded">{kw}</span>
          ))}
        </div>
      )}

      {!!job.scored && (reasons.length > 0 || risks.length > 0) && (
        <>
          <button onClick={() => setOpen(v => !v)} className="text-xs text-gray-400 hover:text-gray-600">
            {open ? 'Hide details ▲' : 'Show details ▼'}
          </button>
          {open && (
            <div className="grid grid-cols-2 gap-3 pt-2 text-sm">
              <div>
                <p className="font-medium text-green-700 mb-1">Reasons</p>
                <ul className="space-y-0.5">
                  {reasons.map((r, i) => <li key={i} className="text-gray-600">✓ {r}</li>)}
                </ul>
              </div>
              <div>
                <p className="font-medium text-red-600 mb-1">Risks</p>
                <ul className="space-y-0.5">
                  {risks.map((r, i) => <li key={i} className="text-gray-600">⚠ {r}</li>)}
                </ul>
              </div>
            </div>
          )}
        </>
      )}

      {job.url && (
        <a href={job.url} target="_blank" rel="noopener noreferrer"
          className="text-xs text-indigo-500 hover:underline block">
          View posting →
        </a>
      )}
    </div>
  )
}

export default function ResearchPanel() {
  const queryClient = useQueryClient()

  // Feedback — merge saved + optimistic local state
  const { data: savedFeedback } = useQuery<{ job_url: string; relevance: 'relevant' | 'not_relevant' }[]>({
    queryKey: ['research-feedback'],
    queryFn: () => api.get('/research/feedback').then(r => r.data.feedback ?? []),
  })
  const [localFeedback, setLocalFeedback] = useState<FeedbackMap>({})
  const feedbackMap: FeedbackMap = {
    ...(savedFeedback ?? []).reduce<FeedbackMap>((acc, f) => { acc[f.job_url] = f.relevance; return acc }, {}),
    ...localFeedback,
  }
  const handleFeedback = (url: string, _title: string, _company: string, relevance: 'relevant' | 'not_relevant') => {
    setLocalFeedback(prev => ({ ...prev, [url]: relevance }))
    queryClient.invalidateQueries({ queryKey: ['research-feedback'] })
  }

  const { data: profile } = useQuery<ProfileData>({
    queryKey: ['profile'],
    queryFn: () => api.get<ProfileData>('/profile').then(r => r.data),
  })
  const titles     = parseJsonArray(profile?.target_titles)
  const industries = parseJsonArray(profile?.target_industries)

  const [targetingOpen, setTargetingOpen] = useState(false)

  // Latest Jobs state
  const [page, setPage] = useState(1)
  const [filterRole, setFilterRole] = useState('')
  const [filterDays, setFilterDays] = useState(0)
  const [refreshing, setRefreshing] = useState(false)

  const params = new URLSearchParams({
    page: String(page),
    per_page: String(STORED_PAGE_SIZE),
    ...(filterRole ? { role: filterRole } : {}),
    ...(filterDays > 0 ? { days: String(filterDays) } : {}),
  })

  const { data, isLoading } = useQuery<StoredJobsResponse>({
    queryKey: ['stored-jobs', page, filterRole, filterDays],
    queryFn: () => api.get<StoredJobsResponse>(`/research/jobs?${params}`).then(r => r.data),
  })

  const { data: allRolesData } = useQuery<StoredJobsResponse>({
    queryKey: ['stored-jobs-all-roles'],
    queryFn: () => api.get<StoredJobsResponse>('/research/jobs?per_page=200').then(r => r.data),
  })
  const roleOptions = Array.from(new Set((allRolesData?.jobs ?? []).map(j => j.title))).sort()

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await api.post('/research/scrape', {})
      await queryClient.invalidateQueries({ queryKey: ['stored-jobs'] })
      await queryClient.invalidateQueries({ queryKey: ['stored-jobs-all-roles'] })
    } finally {
      setRefreshing(false)
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / STORED_PAGE_SIZE)) : 1

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      {/* ── Targeting (collapsible, read-only) ── */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <button
          type="button"
          onClick={() => setTargetingOpen(v => !v)}
          className="w-full flex items-center justify-between px-5 py-3 hover:bg-gray-50 transition-colors text-left"
          aria-expanded={targetingOpen}
        >
          <span className="text-sm font-semibold text-gray-800">
            Targeting <span className="ml-1 text-xs font-normal text-gray-400">{targetingOpen ? '▲' : '▼'}</span>
          </span>
          <a
            href="#profile"
            onClick={e => e.stopPropagation()}
            className="text-xs text-indigo-500 hover:underline"
          >
            Edit in Profile →
          </a>
        </button>
        {targetingOpen && (
          <div className="px-5 pb-4 space-y-3 border-t border-gray-100">
            <div className="pt-3">
              <p className="text-xs font-medium text-gray-500 mb-1">Job Titles</p>
              {titles.length === 0
                ? <p className="text-xs text-gray-400 italic">None set — <a href="#profile" className="underline">add in Profile</a></p>
                : <div className="flex flex-wrap gap-1">
                    {titles.map(t => <span key={t} className="text-xs bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded-md">{t}</span>)}
                  </div>
              }
            </div>
            <div>
              <p className="text-xs font-medium text-gray-500 mb-1">Industries</p>
              {industries.length === 0
                ? <p className="text-xs text-gray-400 italic">None set — <a href="#profile" className="underline">add in Profile</a></p>
                : <div className="flex flex-wrap gap-1">
                    {industries.map(i => <span key={i} className="text-xs bg-purple-50 text-purple-700 px-2 py-0.5 rounded-md">{i}</span>)}
                  </div>
              }
            </div>
          </div>
        )}
      </div>

      {/* ── Latest Jobs ── */}
      <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-800">
            Latest Jobs
            {data && <span className="ml-2 text-xs font-normal text-gray-400">{data.total} total</span>}
          </h3>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="text-xs bg-white border border-gray-300 text-gray-600 px-3 py-1.5 rounded-lg hover:bg-gray-50 disabled:opacity-40 transition-colors"
          >
            {refreshing ? 'Scraping…' : '↻ Refresh'}
          </button>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3">
          <select
            value={filterRole}
            onChange={e => { setFilterRole(e.target.value); setPage(1) }}
            className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-400"
            aria-label="Filter stored jobs by role"
          >
            <option value="">All roles</option>
            {roleOptions.map(r => <option key={r} value={r}>{r}</option>)}
          </select>

          <select
            value={filterDays}
            onChange={e => { setFilterDays(Number(e.target.value)); setPage(1) }}
            className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-400"
            aria-label="Filter stored jobs by date"
          >
            {STORED_DATE_OPTIONS.map(o => (
              <option key={o.days} value={o.days}>{o.label}</option>
            ))}
          </select>
        </div>

        {/* Job list */}
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="h-20 bg-gray-100 rounded-lg animate-pulse" />
            ))}
          </div>
        ) : !data || data.jobs.length === 0 ? (
          <div className="text-center py-10 text-sm text-gray-400">
            <p>No jobs yet.</p>
            <p className="mt-1">Click <strong>↻ Refresh</strong> to scrape now, or wait for the 07:00 daily run.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {data.jobs.map(job => (
              <StoredJobCard
                key={job.id}
                job={job}
                feedback={feedbackMap[job.url]}
                onFeedback={handleFeedback}
              />
            ))}
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between pt-1">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="text-sm px-3 py-1.5 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              ← Prev
            </button>
            <span className="text-xs text-gray-500">Page {page} of {totalPages}</span>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="text-sm px-3 py-1.5 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Next →
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
