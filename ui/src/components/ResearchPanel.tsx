import { useState, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAgentStream } from '../hooks/useAgentStream'
import type { ResearchOutput, JobOpportunity, ProfileData } from '../api/client'
import api from '../api/client'
import AgentPanel from './AgentPanel'
import TagInput from './profile/TagInput'

type FeedbackMap = Record<string, 'relevant' | 'not_relevant'>

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

const inputCls = "w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
const selectCls = inputCls

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

  // Search fields — pre-filled from profile, overridable per-search
  const [location, setLocation] = useState('')
  const [remotePref, setRemotePref] = useState('any')
  const [employmentType, setEmploymentType] = useState('any')
  const [salaryFloor, setSalaryFloor] = useState('')
  const [salaryCurrency, setSalaryCurrency] = useState('USD')
  const [excludedCompanies, setExcludedCompanies] = useState('')
  const [profileLoaded, setProfileLoaded] = useState(false)

  const [manualJd, setManualJd] = useState('')
  const [showManual, setShowManual] = useState(false)

  // Pre-fill from profile once loaded
  useEffect(() => {
    if (profile && !profileLoaded) {
      setTitles(parseJsonArray(profile.target_titles))
      setIndustries(parseJsonArray(profile.target_industries))
      const locations = parseJsonArray(profile.target_locations)
      if (locations.length > 0) setLocation(locations[0])
      if (profile.remote_preference) setRemotePref(profile.remote_preference)
      if (profile.employment_type) setEmploymentType(profile.employment_type)
      if (profile.salary_floor) setSalaryFloor(String(profile.salary_floor))
      if (profile.salary_currency) setSalaryCurrency(profile.salary_currency)
      const excluded = parseJsonArray(profile.excluded_companies)
      if (excluded.length > 0) setExcludedCompanies(excluded.join(', '))
      setProfileLoaded(true)
    }
  }, [profile, profileLoaded])

  const { status, chunks, result, meta, error, run, reset } =
    useAgentStream<ResearchOutput>({ endpoint: '/agents/research' })

  const buildFilters = () => ({
    ...(titles.length > 0 ? { target_titles: titles } : {}),
    ...(industries.length > 0 ? { target_industries: industries } : {}),
    ...(location ? { location } : {}),
    ...(remotePref !== 'any' ? { remote_preference: remotePref } : {}),
    ...(employmentType !== 'any' ? { employment_type: employmentType } : {}),
    ...(salaryFloor ? { salary_floor: parseInt(salaryFloor), salary_currency: salaryCurrency } : {}),
    ...(excludedCompanies ? { excluded_companies: excludedCompanies.split(',').map(s => s.trim()).filter(Boolean) } : {}),
  })

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    run({ ...buildFilters() })
  }

  const handleManual = (e: React.FormEvent) => {
    e.preventDefault()
    run({ job_postings: [{ title: 'Role', company: '', url: '', description: manualJd }] })
  }

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
          <TagInput
            tags={titles}
            onChange={handleTitles}
            placeholder="e.g. Product Manager"
          />
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

      <form onSubmit={handleSearch} className="space-y-4">

        {/* Location */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Location <span className="text-red-500">*</span>
          </label>
          <input value={location} onChange={e => setLocation(e.target.value)}
            placeholder="e.g. Singapore, Remote" required className={inputCls} />
        </div>

        {/* Row 2: remote + employment */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Remote preference</label>
            <select value={remotePref} onChange={e => setRemotePref(e.target.value)} className={selectCls}>
              <option value="any">Any</option>
              <option value="remote">Remote only</option>
              <option value="hybrid">Hybrid</option>
              <option value="onsite">Onsite only</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Employment type</label>
            <select value={employmentType} onChange={e => setEmploymentType(e.target.value)} className={selectCls}>
              <option value="any">Any</option>
              <option value="full_time">Full-time</option>
              <option value="contract">Contract</option>
            </select>
          </div>
        </div>

        {/* Row 3: salary + skills */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Minimum salary</label>
            <div className="flex gap-2">
              <select value={salaryCurrency} onChange={e => setSalaryCurrency(e.target.value)}
                className="border border-gray-300 rounded-lg px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 w-24">
                <option>USD</option>
                <option>SGD</option>
                <option>GBP</option>
                <option>EUR</option>
                <option>AUD</option>
                <option>INR</option>
              </select>
              <input type="number" min={0} value={salaryFloor} onChange={e => setSalaryFloor(e.target.value)}
                placeholder="120000" className={inputCls} />
            </div>
          </div>
        </div>

        {/* Row 4: excluded companies */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Exclude companies</label>
          <input value={excludedCompanies} onChange={e => setExcludedCompanies(e.target.value)}
            placeholder="Company A, Company B" className={inputCls} />
        </div>

        <div className="flex items-center gap-3">
          <button type="submit" disabled={!location.trim()}
            className="bg-indigo-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
            Search
          </button>
          <button type="button" onClick={() => setShowManual(v => !v)}
            className="text-sm text-gray-500 hover:text-gray-700 underline">
            {showManual ? 'Hide manual paste' : 'Or paste a specific job description'}
          </button>
        </div>
      </form>

      {showManual && (
        <form onSubmit={handleManual} className="border-t border-gray-100 pt-4 space-y-3">
          <p className="text-xs text-gray-500">Paste a single job description to score it against your profile.</p>
          <textarea value={manualJd} onChange={e => setManualJd(e.target.value)}
            rows={5} placeholder="Paste job description here…" required
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 resize-none" />
          <button type="submit"
            className="bg-gray-700 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-800 transition-colors">
            Score this job
          </button>
        </form>
      )}
    </div>
  )

  const topOpportunities = result
    ? [...result.opportunities].sort((a, b) => b.fit_score - a.fit_score).slice(0, 10)
    : []

  const resultNode = result ? (
    <div className="space-y-3">
      <p className="text-sm font-medium text-gray-700">
        Top {topOpportunities.length} opportunit{topOpportunities.length === 1 ? 'y' : 'ies'} — rate each to refine future searches
      </p>
      {topOpportunities.map((opp, i) => (
        <OpportunityCard
          key={i}
          opp={opp}
          feedback={opp.link ? feedbackMap[opp.link] : undefined}
          onFeedback={handleFeedback}
        />
      ))}
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
