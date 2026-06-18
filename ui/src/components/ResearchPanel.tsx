import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ProfileData, StoredJobsResponse, StoredJob, ScoreRow } from '../api/client'
import api, { researchApi, applicationsApi } from '../api/client'

export type FeedbackEntry = { relevance: 'relevant' | 'not_relevant'; reason?: string }
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

export function StoredJobCard({ job, feedback, onFeedback, onArchive, onSave, onRescore, readOnly = false, selected = false, onToggleSelect, rescoring = false }: {
  job: StoredJob
  feedback?: FeedbackEntry
  onFeedback: (url: string, title: string, company: string, rel: 'relevant' | 'not_relevant', reason?: string) => void
  onArchive: (id: number) => void
  onSave?: (job: StoredJob) => void
  onRescore: (id: number) => void
  readOnly?: boolean
  selected?: boolean
  onToggleSelect?: (id: number) => void
  rescoring?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [pickingReason, setPickingReason] = useState(false)
  const industries = parseJsonArray(job.inferred_industries)
  const keywords   = parseJsonArray(job.key_keywords)
  const reasons    = parseJsonArray(job.reasons)
  const risks      = parseJsonArray(job.risks)
  const breakdown: ScoreRow[] = job.scoring_breakdown ? JSON.parse(job.scoring_breakdown) : []

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
    if (saved || !onSave) return
    onSave(job)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const postedLabel = job.posted_at
    ? new Date(job.posted_at).toLocaleDateString('en-SG', { day: 'numeric', month: 'short', year: 'numeric' })
    : null

  return (
    <div className={`border rounded-lg p-4 space-y-2 transition-colors ${selected ? 'border-indigo-400 bg-indigo-50' : borderCls}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2 min-w-0">
          {onToggleSelect && (
            <input
              type="checkbox"
              checked={selected}
              onChange={() => onToggleSelect(job.id)}
              onClick={e => e.stopPropagation()}
              className="mt-1 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 shrink-0 cursor-pointer"
              aria-label={`Select ${job.title}`}
            />
          )}
          <div className="min-w-0">
          <p className="font-medium text-gray-900 truncate">{job.title}</p>
          <p className="text-sm text-gray-500">
            {job.company}
            {postedLabel && <span className="ml-2 text-xs text-gray-400">· {postedLabel}</span>}
          </p>
          {feedback?.relevance === 'not_relevant' && feedback.reason && (
            <p className="text-xs text-red-500 mt-0.5">👎 {feedback.reason}</p>
          )}
          {job.scored_by_model && (
            <p className="text-xs text-gray-400 mt-0.5">scored by {job.scored_by_model}</p>
          )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {!!job.scored && job.fit_score !== null
            ? <FitBadge score={job.fit_score} />
            : !rescoring && !job.rescoring && job.score_error
            ? <span className="text-xs text-red-400 italic" title={job.score_error}>
                ⚠ Not yet scored
              </span>
            : !rescoring && !job.rescoring
            ? <span className="text-xs text-gray-400 italic">Scoring…</span>
            : null
          }
          {!readOnly && <button title="Relevant" disabled={saving} onClick={handleThumbUp}
            className={`text-base leading-none px-1.5 py-0.5 rounded transition-colors ${
              feedback?.relevance === 'relevant' ? 'bg-green-200 text-green-700' : 'hover:bg-green-100 text-gray-400 hover:text-green-600'
            } disabled:opacity-40`}>👍</button>}
          {!readOnly && <button title="Not relevant" disabled={saving} onClick={handleThumbDown}
            className={`text-base leading-none px-1.5 py-0.5 rounded transition-colors ${
              feedback?.relevance === 'not_relevant' ? 'bg-red-200 text-red-600' : pickingReason ? 'bg-red-100 text-red-500' : 'hover:bg-red-100 text-gray-400 hover:text-red-500'
            } disabled:opacity-40`}>👎</button>}
          {onSave && <button
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
          </button>}
          {!readOnly && <button
            title="Archive job"
            onClick={() => onArchive(job.id)}
            className="text-gray-300 hover:text-gray-500 hover:bg-gray-100 rounded p-0.5 transition-colors leading-none"
            aria-label="Archive job"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
              <path d="M2 3a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3Z" />
              <path fillRule="evenodd" d="M3 7h14v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7Zm5 3a1 1 0 0 0 0 2h4a1 1 0 1 0 0-2H8Z" clipRule="evenodd" />
            </svg>
          </button>}
          {!readOnly && (!!job.scored || !!job.score_error || rescoring) && (
            <button
              title="Re-score"
              onClick={() => onRescore(job.id)}
              disabled={rescoring}
              className={`rounded p-0.5 transition-colors leading-none ${
                rescoring
                  ? 'text-indigo-300 cursor-not-allowed'
                  : 'text-gray-300 hover:text-indigo-500 hover:bg-indigo-50'
              }`}
              aria-label="Re-score"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className={`w-4 h-4 ${rescoring ? 'animate-spin' : ''}`}>
                <path fillRule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.389Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0v2.43l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z" clipRule="evenodd" />
              </svg>
            </button>
          )}
        </div>
      </div>
      {(rescoring || job.rescoring) && (
        <p className="text-xs text-indigo-400 italic animate-pulse mt-1">Rescoring…</p>
      )}
      {!readOnly && !rescoring && !job.rescoring && job.score_error && job.fit_score !== null && (
        <p className="text-xs text-amber-600 mt-1" title={job.score_error}>
          ⚠ Last rescore failed — previous score shown.{' '}
          <button className="underline" onClick={() => onRescore(job.id)}>Try again</button>
        </p>
      )}
      {!readOnly && !rescoring && !job.rescoring && job.score_error && job.fit_score === null && (
        <p className="text-xs text-red-500 mt-1" title={job.score_error}>
          ⚠ Scoring failed —{' '}
          <button className="underline" onClick={() => onRescore(job.id)}>try again</button>
        </p>
      )}

      {pickingReason && (
        <div className="pt-1">
          <p className="text-xs text-gray-500 mb-1.5">Why not relevant?</p>
          <div className="flex gap-2">
            <input
              id={`reason-input-${job.id}`}
              list={`reason-list-${job.id}`}
              placeholder="Select or type a reason…"
              autoFocus
              className="text-xs border border-red-300 rounded-lg px-3 py-1.5 flex-1 focus:outline-none focus:ring-2 focus:ring-red-300 bg-white"
              onKeyDown={e => {
                if (e.key === 'Enter') {
                  const val = (e.target as HTMLInputElement).value.trim()
                  if (val) handleReasonSelect(val)
                }
                if (e.key === 'Escape') setPickingReason(false)
              }}
              onChange={e => {
                const val = e.target.value.trim()
                if (NOT_RELEVANT_REASONS.includes(val)) handleReasonSelect(val)
              }}
            />
            <datalist id={`reason-list-${job.id}`}>
              {NOT_RELEVANT_REASONS.map(r => <option key={r} value={r} />)}
            </datalist>
            <button
              onClick={() => setPickingReason(false)}
              className="text-xs text-gray-400 hover:text-gray-600 px-2"
              aria-label="Cancel"
            >✕</button>
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
                        <th className="text-left py-1 px-2 font-medium border border-gray-200 w-24">Category</th>
                        <th className="text-left py-1 px-2 font-medium border border-gray-200">JD Requirement</th>
                        <th className="text-left py-1 px-2 font-medium border border-gray-200">Your Profile</th>
                        <th className="text-left py-1 px-2 font-medium border border-gray-200 w-28">Match</th>
                      </tr>
                    </thead>
                    <tbody>
                      {breakdown.map((row, i) => {
                        const matchCls =
                          row.match.startsWith('✅') ? 'text-green-700 font-semibold' :
                          row.match.startsWith('⚠') ? 'text-amber-600 font-semibold' :
                          'text-red-600 font-semibold'
                        return (
                          <tr key={i} className="even:bg-gray-50">
                            <td className="py-1 px-2 border border-gray-200 text-gray-500 whitespace-nowrap">{row.category}</td>
                            <td className="py-1 px-2 border border-gray-200 text-gray-700">{row.requirement}</td>
                            <td className="py-1 px-2 border border-gray-200 text-gray-600">{row.your_profile}</td>
                            <td className={`py-1 px-2 border border-gray-200 ${matchCls}`}>{row.match}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {job.recommendation && (
                <div className="rounded-md border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm text-indigo-900">
                  <p className="text-xs font-semibold text-indigo-500 uppercase tracking-wide mb-1">Recommendation</p>
                  {job.recommendation}
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
  const [rescoringIds, setRescoringIds] = useState<Set<number>>(new Set())
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  const params = new URLSearchParams({
    page: String(page),
    per_page: String(STORED_PAGE_SIZE),
    ...(filterRole ? { role: filterRole } : {}),
    ...(filterDays > 0 ? { days: String(filterDays) } : {}),
    ...(filterScore > 0 ? { min_score: String(filterScore) } : {}),
  })

  const { data, isLoading } = useQuery<StoredJobsResponse>({
    queryKey: ['stored-jobs', page, filterRole, filterDays, filterScore],
    queryFn: () => api.get<StoredJobsResponse>(`/research/jobs?${params}`).then(r => r.data),
    refetchInterval: false,
  })

  // Role options come from the user's target titles in their profile
  const roleOptions = [...titles].sort()

  const archiveMutation = useMutation({
    mutationFn: (id: number) => researchApi.archiveJob(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['stored-jobs'] }),
  })

  const bulkArchiveMutation = useMutation({
    mutationFn: (ids: number[]) => researchApi.bulkArchiveJobs(ids),
    onSuccess: () => {
      setSelectedIds(new Set())
      queryClient.invalidateQueries({ queryKey: ['stored-jobs'] })
    },
  })

  const saveMutation = useMutation({
    mutationFn: (job: StoredJob) => applicationsApi.create({
      company_name:   job.company,
      role_title:     job.title,
      source_url:     job.url,
      status:         'selected',
      job_posting_id: job.id,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['stored-jobs'] })
      queryClient.invalidateQueries({ queryKey: ['selected-jobs'] })
      queryClient.invalidateQueries({ queryKey: ['kanban'] })
    },
  })

  const rescoreMutation = useMutation({
    mutationFn: (id: number) => researchApi.rescoreJob(id).then(r => ({ id, job: r.data })),
    onMutate: (id) => {
      setRescoringIds(prev => new Set([...prev, id]))
    },
    onSuccess: ({ id, job }) => {
      setRescoringIds(prev => { const next = new Set(prev); next.delete(id); return next })
      queryClient.setQueryData<StoredJobsResponse>(
        ['stored-jobs', page, filterRole, filterDays, filterScore],
        old => old
          ? { ...old, jobs: old.jobs.map(j => j.id === id ? { ...j, ...job } : j) }
          : old
      )
    },
    onError: (_err, id) => {
      setRescoringIds(prev => { const next = new Set(prev); next.delete(id); return next })
    },
  })

  const bulkRescoreMutation = useMutation({
    mutationFn: (ids: number[]) => researchApi.bulkRescoreJobs(ids).then(r => ({ ids, jobs: r.data.jobs })),
    onMutate: (ids) => {
      setRescoringIds(prev => new Set([...prev, ...ids]))
    },
    onSuccess: ({ ids, jobs }) => {
      setRescoringIds(prev => { const next = new Set(prev); ids.forEach(id => next.delete(id)); return next })
      setSelectedIds(new Set())
      const jobMap = Object.fromEntries(jobs.map(j => [j.id, j]))
      queryClient.setQueryData<StoredJobsResponse>(
        ['stored-jobs', page, filterRole, filterDays, filterScore],
        old => old
          ? { ...old, jobs: old.jobs.map(j => jobMap[j.id] ? { ...j, ...jobMap[j.id] } : j) }
          : old
      )
    },
    onError: (_err, ids) => {
      setRescoringIds(prev => { const next = new Set(prev); ids.forEach(id => next.delete(id)); return next })
    },
  })

  const [confirmRescoreAll, setConfirmRescoreAll] = useState(false)

  const { data: scoringUsage } = useQuery<{ jobs_scored_today: number; daily_limit: number; remaining: number }>({
    queryKey: ['scoring-usage'],
    queryFn: () => api.get('/scoring/usage').then(r => r.data),
    refetchInterval: 60_000,
  })

  const rescoreAllMutation = useMutation({
    mutationFn: () => researchApi.rescoreAllJobs(),
    onSuccess: () => {
      setConfirmRescoreAll(false)
      queryClient.invalidateQueries({ queryKey: ['stored-jobs'] })
    },
    onError: () => setConfirmRescoreAll(false),
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

  const visibleJobs = data?.jobs ?? []

  // Clear selection when page or filters change
  useEffect(() => { setSelectedIds(new Set()) }, [page, filterRole, filterDays, filterScore])

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      {/* ── Daily scoring limit banner ── */}
      {scoringUsage && scoringUsage.remaining === 0 && (
        <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-xl px-5 py-4">
          <span className="text-amber-500 text-lg leading-none mt-0.5">⚠</span>
          <div>
            <p className="text-sm font-semibold text-amber-800">Daily scoring limit reached</p>
            <p className="text-xs text-amber-700 mt-0.5">
              You've used all {scoringUsage.daily_limit} job scorings for today. Scoring resumes automatically tomorrow.
            </p>
          </div>
        </div>
      )}

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
          <div className="flex items-center gap-3">
            {visibleJobs.length > 0 && (
              <input
                type="checkbox"
                checked={selectedIds.size === visibleJobs.length}
                ref={el => { if (el) el.indeterminate = selectedIds.size > 0 && selectedIds.size < visibleJobs.length }}
                onChange={() => {
                  if (selectedIds.size === visibleJobs.length) {
                    setSelectedIds(new Set())
                  } else {
                    setSelectedIds(new Set(visibleJobs.map(j => j.id)))
                  }
                }}
                className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                aria-label="Select all jobs"
              />
            )}
            <h3 className="text-sm font-semibold text-gray-800">
              Latest Jobs
              {data && (
                <span className="ml-2 text-xs font-normal text-gray-400">
                  {`${data.total} total`}
                </span>
              )}
            </h3>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setConfirmRescoreAll(true)}
              disabled={!data?.total || confirmRescoreAll || rescoreAllMutation.isPending || rescoringIds.size > 0 || bulkRescoreMutation.isPending}
              className="text-xs bg-white border border-gray-300 text-gray-600 px-3 py-1.5 rounded-lg hover:bg-gray-50 disabled:opacity-40 transition-colors"
              title="Rescore all jobs for your profile"
            >
              {rescoreAllMutation.isPending ? '↻ Rescoring all…' : '↻ Rescore All'}
            </button>
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="text-xs bg-white border border-gray-300 text-gray-600 px-3 py-1.5 rounded-lg hover:bg-gray-50 disabled:opacity-40 transition-colors"
            >
              {refreshing ? 'Scraping…' : '↻ Refresh'}
            </button>
          </div>
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
                onClick={() => { setFilterScore(f.min); setPage(1) }}
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

        {/* Rescore All confirmation */}
        {confirmRescoreAll && (
          <div className="flex items-center justify-between gap-3 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
            <p className="text-sm text-amber-800">
              Rescore all <strong>{data?.total ?? 0}</strong> job{(data?.total ?? 0) !== 1 ? 's' : ''}? This may take a few minutes.
            </p>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => rescoreAllMutation.mutate()}
                disabled={rescoreAllMutation.isPending}
                className="text-xs bg-amber-600 hover:bg-amber-700 text-white px-3 py-1.5 rounded-lg disabled:opacity-50 transition-colors font-medium"
              >
                {rescoreAllMutation.isPending ? 'Rescoring…' : 'Yes, rescore all'}
              </button>
              <button
                onClick={() => setConfirmRescoreAll(false)}
                disabled={rescoreAllMutation.isPending}
                className="text-xs text-gray-500 hover:text-gray-700 px-2 py-1.5 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Job list */}
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="h-20 bg-gray-100 rounded-lg animate-pulse" />
            ))}
          </div>
        ) : !data || data.jobs.length === 0 ? (
          <div className="text-center py-10 text-sm text-gray-400">
            {filterRole || filterDays > 0 || filterScore > 0 ? (
              <p>No jobs match the selected filters.</p>
            ) : (
              <>
                <p>No jobs matching your industry.</p>
                <p className="mt-1">New jobs are scored and classified automatically — check back shortly, or click <strong>↻ Refresh</strong> to scrape now.</p>
              </>
            )}
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
                rescoring={rescoringIds.has(job.id) || !!job.rescoring}
                selected={selectedIds.has(job.id)}
                onToggleSelect={id => setSelectedIds(prev => {
                  const next = new Set(prev)
                  if (next.has(id)) { next.delete(id) } else { next.add(id) }
                  return next
                })}
              />
            ))}
          </div>
        )}

        {/* Floating bulk action bar */}
        {selectedIds.size > 0 && (
          <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 bg-gray-900 text-white px-5 py-3 rounded-2xl shadow-2xl">
            <span className="text-sm font-medium text-gray-200">
              {selectedIds.size} job{selectedIds.size > 1 ? 's' : ''} selected
            </span>
            <div className="w-px h-4 bg-gray-600" />
            <button
              onClick={() => setSelectedIds(new Set())}
              className="text-xs text-gray-400 hover:text-white transition-colors px-1"
            >
              Clear
            </button>
            <button
              onClick={() => bulkArchiveMutation.mutate(Array.from(selectedIds))}
              disabled={bulkArchiveMutation.isPending || bulkRescoreMutation.isPending}
              className="text-xs bg-red-500 hover:bg-red-600 text-white px-3 py-1.5 rounded-lg disabled:opacity-40 transition-colors"
            >
              {bulkArchiveMutation.isPending ? 'Archiving…' : 'Archive'}
            </button>
            <button
              onClick={() => bulkRescoreMutation.mutate(Array.from(selectedIds))}
              disabled={selectedIds.size < 2 || bulkRescoreMutation.isPending || bulkArchiveMutation.isPending}
              title={selectedIds.size < 2 ? 'Select at least 2 jobs to rescore' : `Rescore ${selectedIds.size} jobs in one call`}
              className="text-xs bg-indigo-500 hover:bg-indigo-600 text-white px-3 py-1.5 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className={`w-3.5 h-3.5 ${bulkRescoreMutation.isPending ? 'animate-spin' : ''}`}>
                <path fillRule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.389Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0v2.43l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z" clipRule="evenodd" />
              </svg>
              {bulkRescoreMutation.isPending ? 'Rescoring…' : 'Rescore'}
            </button>
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
