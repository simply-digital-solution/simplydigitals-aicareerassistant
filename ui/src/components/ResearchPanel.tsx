import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ProfileData, StoredJobsResponse, StoredJob, ScoreCategory } from '../api/client'
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
const SCORE_FILTERS = [
  { label: 'All',  min: 0    },
  { label: '50%+', min: 0.50 },
  { label: '60%+', min: 0.60 },
  { label: '70%+', min: 0.70 },
  { label: '80%+', min: 0.80 },
]
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

function StoredJobCard({ job, feedback, onFeedback, onArchive, onSave, onRescore }: {
  job: StoredJob
  feedback?: FeedbackEntry
  onFeedback: (url: string, title: string, company: string, rel: 'relevant' | 'not_relevant', reason?: string) => void
  onArchive: (id: number) => void
  onSave: (job: StoredJob) => void
  onRescore: (id: number) => void
}) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [pickingReason, setPickingReason] = useState(false)
  const industries = parseJsonArray(job.inferred_industries)
  const keywords   = parseJsonArray(job.key_keywords)
  const reasons    = parseJsonArray(job.reasons)
  const risks      = parseJsonArray(job.risks)
  const breakdown: ScoreCategory[] = job.scoring_breakdown ? JSON.parse(job.scoring_breakdown) : []

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
            : job.score_error
            ? <span className="text-xs text-red-400 italic" title={job.score_error}>⚠ Score failed</span>
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
          {(!!job.scored || !!job.score_error) && (
            <button
              title="Re-score"
              onClick={() => onRescore(job.id)}
              className="text-gray-300 hover:text-indigo-500 hover:bg-indigo-50 rounded p-0.5 transition-colors leading-none"
              aria-label="Re-score"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                <path fillRule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.389Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0v2.43l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z" clipRule="evenodd" />
              </svg>
            </button>
          )}
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

      {!!job.scored && (reasons.length > 0 || risks.length > 0 || breakdown.length > 0) && (
        <>
          <button onClick={() => setOpen(v => !v)} className="text-xs text-gray-400 hover:text-gray-600">
            {open ? 'Hide details ▲' : 'Show details ▼'}
          </button>
          {open && (
            <div className="space-y-3 pt-2">
              {(reasons.length > 0 || risks.length > 0) && (
                <div className="grid grid-cols-2 gap-3 text-sm">
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

              {breakdown.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Score Breakdown</p>
                  <table className="w-full text-xs border-collapse">
                    <thead>
                      <tr className="bg-gray-50 text-gray-500">
                        <th className="text-left py-1 px-2 font-medium border border-gray-200 w-1/4">Category</th>
                        <th className="text-left py-1 px-2 font-medium border border-gray-200 w-5/12">JD Requires</th>
                        <th className="text-left py-1 px-2 font-medium border border-gray-200 w-5/12">Your Profile</th>
                        <th className="text-center py-1 px-2 font-medium border border-gray-200 w-12">Score</th>
                      </tr>
                    </thead>
                    <tbody>
                      {breakdown.map((row) => {
                        const scoreCls =
                          row.score >= 8 ? 'text-green-700 font-semibold' :
                          row.score >= 5 ? 'text-amber-600 font-semibold' :
                          'text-red-600 font-semibold'
                        return (
                          <tr key={row.category} className="even:bg-gray-50">
                            <td className="py-1 px-2 border border-gray-200 text-gray-700">{row.category}</td>
                            <td className="py-1 px-2 border border-gray-200 text-gray-600">{row.jd_experience}</td>
                            <td className="py-1 px-2 border border-gray-200 text-gray-600">{row.your_profile}</td>
                            <td className={`py-1 px-2 border border-gray-200 text-center ${scoreCls}`}>{row.score}/10</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
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

function RoleCombobox({ value, onChange, options }: {
  value: string
  onChange: (v: string) => void
  options: string[]
}) {
  const [inputValue, setInputValue] = useState(value)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Sync external clear (value reset to '')
  useEffect(() => { if (value === '') setInputValue('') }, [value])

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Debounce: fire onChange 300ms after the user stops typing
  useEffect(() => {
    const t = setTimeout(() => onChange(inputValue), 300)
    return () => clearTimeout(t)
  }, [inputValue])  // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = options.filter(o => o.toLowerCase().includes(inputValue.toLowerCase()))

  return (
    <div ref={ref} className="relative">
      <div className="flex items-center border border-gray-300 rounded-lg overflow-hidden focus-within:ring-2 focus-within:ring-indigo-400">
        <input
          type="text"
          value={inputValue}
          placeholder="All roles"
          aria-label="Filter stored jobs by role"
          onChange={e => { setInputValue(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)}
          className="text-sm px-3 py-1.5 outline-none w-44 bg-white"
        />
        {inputValue && (
          <button
            onClick={() => { setInputValue(''); onChange(''); setOpen(false) }}
            className="pr-2 text-gray-400 hover:text-gray-600 text-base leading-none"
            aria-label="Clear role filter"
          >×</button>
        )}
      </div>
      {open && filtered.length > 0 && (
        <ul className="absolute z-20 top-full mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
          {filtered.map(o => (
            <li key={o}>
              <button
                onMouseDown={e => e.preventDefault()}
                onClick={() => { setInputValue(o); onChange(o); setOpen(false) }}
                className="w-full text-left text-sm px-3 py-1.5 hover:bg-indigo-50 hover:text-indigo-700"
              >
                {o}
              </button>
            </li>
          ))}
        </ul>
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
  const [filterScore, setFilterScore] = useState(0)
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

  // Role options come from the user's target titles in their profile
  const roleOptions = [...titles].sort()

  const archiveMutation = useMutation({
    mutationFn: (id: number) => researchApi.archiveJob(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['stored-jobs'] }),
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

  const rescoreMutation = useMutation({
    mutationFn: (id: number) => researchApi.rescoreJob(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['stored-jobs'] }),
  })

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await api.post('/research/scrape', {})
      await queryClient.invalidateQueries({ queryKey: ['stored-jobs'] })
    } finally {
      setRefreshing(false)
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / STORED_PAGE_SIZE)) : 1

  // Client-side score filter — unscored jobs always shown
  const visibleJobs = (data?.jobs ?? []).filter(job =>
    filterScore === 0 || !job.scored || job.fit_score === null || job.fit_score >= filterScore
  )

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
            {data && (
              <span className="ml-2 text-xs font-normal text-gray-400">
                {filterScore > 0
                  ? `${visibleJobs.length} of ${data.total} total`
                  : `${data.total} total`}
              </span>
            )}
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
          <RoleCombobox
            value={filterRole}
            onChange={v => { setFilterRole(v); setPage(1) }}
            options={roleOptions}
          />

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

          <div role="group" aria-label="Filter by fit score" className="flex items-center rounded-lg border border-gray-300 overflow-hidden">
            {SCORE_FILTERS.map(f => (
              <button
                key={f.min}
                onClick={() => setFilterScore(f.min)}
                aria-pressed={filterScore === f.min}
                className={`text-xs px-3 py-1.5 border-r border-gray-300 last:border-r-0 transition-colors ${
                  filterScore === f.min
                    ? 'bg-indigo-600 text-white'
                    : 'bg-white text-gray-600 hover:bg-gray-50'
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
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
        ) : visibleJobs.length === 0 ? (
          <div className="text-center py-10 text-sm text-gray-400">
            <p>No jobs match the selected score filter.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {visibleJobs.map(job => (
              <StoredJobCard
                key={job.id}
                job={job}
                feedback={feedbackMap[job.url]}
                onFeedback={handleFeedback}
                onArchive={(id) => archiveMutation.mutate(id)}
                onSave={(j) => saveMutation.mutate(j)}
                onRescore={(id) => rescoreMutation.mutate(id)}
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
