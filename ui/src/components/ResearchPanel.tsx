import { useState, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAgentStream } from '../hooks/useAgentStream'
import type { ResearchOutput, JobOpportunity, ProfileData } from '../api/client'
import api from '../api/client'
import AgentPanel from './AgentPanel'
import TagInput from './profile/TagInput'

type FeedbackMap = Record<string, 'relevant' | 'not_relevant'>

const PAGE_SIZE = 10

const DATE_OPTIONS = [
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

function OpportunityCard({
  opp,
  feedback,
  onFeedback,
}: {
  opp: JobOpportunity
  feedback?: 'relevant' | 'not_relevant'
  onFeedback: (url: string, title: string, company: string, relevance: 'relevant' | 'not_relevant') => void
}) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)

  const borderCls =
    feedback === 'relevant' ? 'border-green-400 bg-green-50' :
    feedback === 'not_relevant' ? 'border-red-300 bg-red-50 opacity-70' :
    'border-gray-200'

  const handleFeedback = async (relevance: 'relevant' | 'not_relevant') => {
    if (!opp.link || saving) return
    setSaving(true)
    try {
      await api.post('/research/feedback', {
        job_url: opp.link,
        job_title: opp.role,
        company: opp.company,
        relevance,
      })
      onFeedback(opp.link, opp.role, opp.company, relevance)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={`border rounded-lg p-4 space-y-2 transition-colors ${borderCls}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium text-gray-900 truncate">{opp.role}</p>
          <p className="text-sm text-gray-500">{opp.company}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <FitBadge score={opp.fit_score} />
          <button
            title="Relevant"
            disabled={saving}
            onClick={() => handleFeedback('relevant')}
            className={`text-base leading-none px-1.5 py-0.5 rounded transition-colors ${
              feedback === 'relevant'
                ? 'bg-green-200 text-green-700'
                : 'hover:bg-green-100 text-gray-400 hover:text-green-600'
            } disabled:opacity-40`}
          >
            👍
          </button>
          <button
            title="Not relevant"
            disabled={saving}
            onClick={() => handleFeedback('not_relevant')}
            className={`text-base leading-none px-1.5 py-0.5 rounded transition-colors ${
              feedback === 'not_relevant'
                ? 'bg-red-200 text-red-600'
                : 'hover:bg-red-100 text-gray-400 hover:text-red-500'
            } disabled:opacity-40`}
          >
            👎
          </button>
        </div>
      </div>

      {opp.inferred_industries?.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {opp.inferred_industries.map((ind) => (
            <span key={ind} className="text-xs bg-teal-50 text-teal-700 border border-teal-200 px-2 py-0.5 rounded-full">
              {ind}
            </span>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-1">
        {opp.key_keywords.map((kw) => (
          <span key={kw} className="text-xs bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded">{kw}</span>
        ))}
      </div>

      <button onClick={() => setOpen(v => !v)} className="text-xs text-gray-400 hover:text-gray-600">
        {open ? 'Hide details ▲' : 'Show details ▼'}
      </button>

      {open && (
        <div className="grid grid-cols-2 gap-3 pt-2 text-sm">
          <div>
            <p className="font-medium text-green-700 mb-1">Reasons</p>
            <ul className="space-y-0.5">
              {opp.reasons.map((r, i) => <li key={i} className="text-gray-600">✓ {r}</li>)}
            </ul>
          </div>
          <div>
            <p className="font-medium text-red-600 mb-1">Risks</p>
            <ul className="space-y-0.5">
              {opp.risks.map((r, i) => <li key={i} className="text-gray-600">⚠ {r}</li>)}
            </ul>
          </div>
        </div>
      )}

      {opp.link && (
        <a href={opp.link} target="_blank" rel="noopener noreferrer"
          className="text-xs text-indigo-500 hover:underline block">
          View posting →
        </a>
      )}
    </div>
  )
}

function parseJsonArray(val: string | null | undefined): string[] {
  if (!val) return []
  try { return JSON.parse(val) } catch { return [] }
}

export default function ResearchPanel() {
  const queryClient = useQueryClient()

  const { data: profile } = useQuery<ProfileData>({
    queryKey: ['profile'],
    queryFn: () => api.get<ProfileData>('/profile').then(r => r.data),
  })

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

  // Target roles/industries — editable here, synced to profile on Save
  const [titles, setTitles] = useState<string[]>([])
  const [industries, setIndustries] = useState<string[]>([])
  const [targetsDirty, setTargetsDirty] = useState(false)
  const [targetsSaving, setTargetsSaving] = useState(false)
  const [profileLoaded, setProfileLoaded] = useState(false)

  const handleTitles = (next: string[]) => { setTitles(next); setTargetsDirty(true) }
  const handleIndustries = (next: string[]) => { setIndustries(next); setTargetsDirty(true) }

  const saveTargets = async () => {
    setTargetsSaving(true)
    try {
      await api.patch('/profile', {
        target_titles: JSON.stringify(titles),
        target_industries: JSON.stringify(industries),
      })
      setTargetsDirty(false)
      queryClient.invalidateQueries({ queryKey: ['profile'] })
    } finally {
      setTargetsSaving(false)
    }
  }

  useEffect(() => {
    if (profile && !profileLoaded) {
      setTitles(parseJsonArray(profile.target_titles))
      setIndustries(parseJsonArray(profile.target_industries))
      setProfileLoaded(true)
    }
  }, [profile, profileLoaded])

  // Manual JD paste
  const [manualJd, setManualJd] = useState('')
  const [showManual, setShowManual] = useState(false)

  const { status, chunks, result, meta, error, run, reset } =
    useAgentStream<ResearchOutput>({ endpoint: '/agents/research' })

  const handleSearch = () => run({})

  const handleManual = (e: React.FormEvent) => {
    e.preventDefault()
    run({ job_postings: [{ title: 'Role', company: '', url: '', description: manualJd }] })
  }

  // Result filters + pagination — applied client-side on the agent result
  const [filterRole, setFilterRole] = useState('')
  const [filterDays, setFilterDays] = useState(0)
  const [page, setPage] = useState(1)

  // Reset pagination when filters or result changes
  useEffect(() => { setPage(1) }, [filterRole, filterDays, result])

  const cutoff = filterDays > 0
    ? new Date(Date.now() - filterDays * 24 * 60 * 60 * 1000)
    : null

  const allOpportunities = result
    ? [...result.opportunities].sort((a, b) => {
        // Sort by posted_at DESC when available, otherwise keep agent order
        const da = (a as JobOpportunity & { posted_at?: string }).posted_at
        const db = (b as JobOpportunity & { posted_at?: string }).posted_at
        if (da && db) return new Date(db).getTime() - new Date(da).getTime()
        return 0
      })
    : []

  const filtered = allOpportunities.filter(opp => {
    if (filterRole && opp.role.toLowerCase() !== filterRole.toLowerCase()) return false
    if (cutoff) {
      const posted = (opp as JobOpportunity & { posted_at?: string }).posted_at
      if (posted && new Date(posted) < cutoff) return false
    }
    return true
  })

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const paginated = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const form = (
    <div className="space-y-5">
      {/* Target Roles + Industries — editable, synced to Profile */}
      <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-gray-700">Targeting</span>
          <button
            type="button"
            onClick={saveTargets}
            disabled={!targetsDirty || targetsSaving}
            className="text-xs bg-indigo-600 text-white px-3 py-1 rounded-lg hover:bg-indigo-700 disabled:opacity-40 transition-colors"
          >
            {targetsSaving ? 'Saving…' : 'Save'}
          </button>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Target Job Titles</label>
          <TagInput tags={titles} onChange={handleTitles} placeholder="e.g. Product Manager" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Target Industries</label>
          <TagInput
            tags={industries}
            onChange={handleIndustries}
            placeholder="e.g. Banking & Finance"
            colorCls="bg-purple-50 text-purple-700"
          />
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleSearch}
          className="bg-indigo-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
        >
          Search
        </button>
        <button
          type="button"
          onClick={() => setShowManual(v => !v)}
          className="text-sm text-gray-500 hover:text-gray-700 underline"
        >
          {showManual ? 'Hide manual paste' : 'Or paste a specific job description'}
        </button>
      </div>

      {showManual && (
        <form onSubmit={handleManual} className="border-t border-gray-100 pt-4 space-y-3">
          <p className="text-xs text-gray-500">Paste a single job description to score it against your profile.</p>
          <textarea
            value={manualJd}
            onChange={e => setManualJd(e.target.value)}
            rows={5}
            placeholder="Paste job description here…"
            required
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 resize-none"
          />
          <button type="submit"
            className="bg-gray-700 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-800 transition-colors">
            Score this job
          </button>
        </form>
      )}
    </div>
  )

  const resultNode = result ? (
    <div className="space-y-4">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3 pb-2 border-b border-gray-100">
        <select
          value={filterRole}
          onChange={e => setFilterRole(e.target.value)}
          className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-400"
          aria-label="Filter by role"
        >
          <option value="">All roles</option>
          {Array.from(new Set(allOpportunities.map(o => o.role))).map(r => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>

        <select
          value={filterDays}
          onChange={e => setFilterDays(Number(e.target.value))}
          className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-400"
          aria-label="Filter by date"
        >
          {DATE_OPTIONS.map(o => (
            <option key={o.days} value={o.days}>{o.label}</option>
          ))}
        </select>

        <span className="text-xs text-gray-400 ml-auto">
          {filtered.length} result{filtered.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Job cards */}
      {paginated.length === 0 ? (
        <p className="text-sm text-gray-500 text-center py-6">No results match the selected filters.</p>
      ) : (
        <div className="space-y-3">
          {paginated.map((opp, i) => (
            <OpportunityCard
              key={i}
              opp={opp}
              feedback={opp.link ? feedbackMap[opp.link] : undefined}
              onFeedback={handleFeedback}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-2">
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

      {/* Meta + reset */}
      <div className="flex items-center justify-between pt-1">
        {meta && (
          <p className="text-xs text-gray-400">
            {meta.model as string} · {meta.output_tokens as number} tokens · ${(meta.cost_usd as number).toFixed(4)}
          </p>
        )}
        <button onClick={reset} className="text-xs text-indigo-500 hover:underline ml-auto">
          Run again
        </button>
      </div>
    </div>
  ) : null

  return (
    <AgentPanel
      title="Job Research"
      description="Finds and scores job opportunities against your profile."
      status={status}
      chunks={chunks}
      error={error}
      meta={meta}
      onReset={reset}
      form={form}
      result={resultNode}
    />
  )
}
