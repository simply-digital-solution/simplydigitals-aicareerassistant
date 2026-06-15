import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ProfileData, StoredJobsResponse, StoredJob } from '../api/client'
import api, { researchApi, applicationsApi } from '../api/client'

type FeedbackEntry = { relevance: 'relevant' | 'not_relevant'; reason?: string }
type FeedbackMap = Record<string, FeedbackEntry>

const NOT_RELEVANT_REASONS = [
  'Wrong industry',
  'Wrong seniority',
  'Too junior / too senior',
  'Wrong location',
  'Already applied',
  'Company not a fit',
]

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

function StoredJobCard({ job, feedback, onFeedback, onArchive, onSave }: {
  job: StoredJob
  feedback?: FeedbackEntry
  onFeedback: (url: string, title: string, company: string, rel: 'relevant' | 'not_relevant', reason?: string) => void
  onArchive: (id: number) => void
  onSave: (job: StoredJob) => void
}) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [pickingReason, setPickingReason] = useState(false)
  const industries = parseJsonArray(job.inferred_industries)
  const keywords   = parseJsonArray(job.key_keywords)
  const reasons    = parseJsonArray(job.reasons)
  const risks      = parseJsonArray(job.risks)

  const borderCls =
    feedback?.relevance === 'relevant'     ? 'border-green-400 bg-green-50' :
    feedback?.relevance === 'not_relevant' ? 'border-red-300 bg-red-50 opacity-70' :
    'border-gray-200'

  const handleThumbUp = async () => {
    if (saving) return
    setSaving(true)
    setPickingReason(false)
    try {
      await api.post('/research/feedback', {
        job_url: job.url, job_title: job.title, company: job.company, relevance: 'relevant',
      })
      onFeedback(job.url, job.title, job.company, 'relevant')
    } finally {
      setSaving(false)
    }
  }

  const handleThumbDown = () => {
    if (saving || feedback?.relevance === 'not_relevant') return
    setPickingReason(true)
  }

  const handleReasonSelect = async (reason: string) => {
    setSaving(true)
    setPickingReason(false)
    try {
      await api.post('/research/feedback', {
        job_url: job.url, job_title: job.title, company: job.company,
        relevance: 'not_relevant', reason,
      })
      onFeedback(job.url, job.title, job.company, 'not_relevant', reason)
    } finally {
      setSaving(false)
    }
  }

  const handleSave = () => {
    if (saved) return
    onSave(job)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
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
          {feedback?.relevance === 'not_relevant' && feedback.reason && (
            <p className="text-xs text-red-500 mt-0.5">👎 {feedback.reason}</p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {!!job.scored && job.fit_score !== null
            ? <FitBadge score={job.fit_score} />
            : <span className="text-xs text-gray-400 italic">Scoring…</span>
          }
          <button title="Relevant" disabled={saving} onClick={handleThumbUp}
            className={`text-base leading-none px-1.5 py-0.5 rounded transition-colors ${
              feedback?.relevance === 'relevant' ? 'bg-green-200 text-green-700' : 'hover:bg-green-100 text-gray-400 hover:text-green-600'
            } disabled:opacity-40`}>👍</button>
          <button title="Not relevant" disabled={saving} onClick={handleThumbDown}
            className={`text-base leading-none px-1.5 py-0.5 rounded transition-colors ${
              feedback?.relevance === 'not_relevant' ? 'bg-red-200 text-red-600' : pickingReason ? 'bg-red-100 text-red-500' : 'hover:bg-red-100 text-gray-400 hover:text-red-500'
            } disabled:opacity-40`}>👎</button>
          <button
            title="Save to Selected"
            onClick={handleSave}
            disabled={saved}
            aria-label="Save to Selected"
            className={`rounded p-0.5 transition-colors leading-none ${
              saved
                ? 'text-indigo-500'
                : 'text-gray-300 hover:text-indigo-400 hover:bg-indigo-50'
            }`}
          >
            {saved
              ? (
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                  <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clipRule="evenodd" />
                </svg>
              )
              : (
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M17.593 3.322c1.1.128 1.907 1.077 1.907 2.185V21L12 17.25 4.5 21V5.507c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0 1 11.186 0Z" />
                </svg>
              )
            }
          </button>
          <button
            title="Archive job"
            onClick={() => onArchive(job.id)}
            className="text-gray-300 hover:text-gray-500 hover:bg-gray-100 rounded p-0.5 transition-colors leading-none"
            aria-label="Archive job"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
              <path d="M2 3a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3Z" />
              <path fillRule="evenodd" d="M3 7h14v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7Zm5 3a1 1 0 0 0 0 2h4a1 1 0 1 0 0-2H8Z" clipRule="evenodd" />
            </svg>
          </button>
        </div>
      </div>

      {pickingReason && (
        <div className="pt-1">
          <p className="text-xs text-gray-500 mb-1.5">Why not relevant?</p>
          <div className="flex flex-wrap gap-1.5">
            {NOT_RELEVANT_REASONS.map(r => (
              <button
                key={r}
                onClick={() => handleReasonSelect(r)}
                className="text-xs border border-red-300 text-red-600 bg-red-50 hover:bg-red-100 px-2.5 py-1 rounded-full transition-colors"
              >
                {r}
              </button>
            ))}
          </div>
        </div>
      )}

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
  const { data: savedFeedback } = useQuery<{ job_url: string; relevance: 'relevant' | 'not_relevant'; reason?: string }[]>({
    queryKey: ['research-feedback'],
    queryFn: () => api.get('/research/feedback').then(r => r.data.feedback ?? []),
  })
  const [localFeedback, setLocalFeedback] = useState<FeedbackMap>({})
  const feedbackMap: FeedbackMap = {
    ...(savedFeedback ?? []).reduce<FeedbackMap>((acc, f) => {
      acc[f.job_url] = { relevance: f.relevance, reason: f.reason }
      return acc
    }, {}),
    ...localFeedback,
  }
  const handleFeedback = (url: string, _title: string, _company: string, relevance: 'relevant' | 'not_relevant', reason?: string) => {
    setLocalFeedback(prev => ({ ...prev, [url]: { relevance, reason } }))
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

  const archiveMutation = useMutation({
    mutationFn: (id: number) => researchApi.archiveJob(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['stored-jobs'] })
      queryClient.invalidateQueries({ queryKey: ['stored-jobs-all-roles'] })
    },
  })

  const saveMutation = useMutation({
    mutationFn: (job: StoredJob) => applicationsApi.create({
      company_name: job.company,
      role_title:   job.title,
      source_url:   job.url,
      status:       'selected',
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['kanban'] }),
  })

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
                onArchive={(id) => archiveMutation.mutate(id)}
                onSave={(j) => saveMutation.mutate(j)}
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
