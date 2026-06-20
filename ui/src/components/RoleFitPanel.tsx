import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { RoleFitOutput, RoleSuggestion, ProfileData } from '../api/client'
import api from '../api/client'

const TIER_STYLES: Record<string, { badge: string; border: string; label: string }> = {
  strong:   { badge: 'bg-green-100 text-green-800',   border: 'border-green-200',  label: 'Strong fit'   },
  stretch:  { badge: 'bg-yellow-100 text-yellow-800', border: 'border-yellow-200', label: 'Stretch fit'  },
  adjacent: { badge: 'bg-blue-100 text-blue-700',     border: 'border-blue-200',   label: 'Adjacent fit' },
}

function RoleCard({
  role,
  onSearch,
  onSave,
  saved,
}: {
  role: RoleSuggestion
  onSearch: (q: string) => void
  onSave: (title: string) => void
  saved: boolean
}) {
  const style = TIER_STYLES[role.tier] ?? TIER_STYLES.adjacent
  return (
    <div className={`bg-white border ${style.border} rounded-xl p-4 space-y-3`}>
      <div className="flex items-start justify-between gap-3">
        <p className="font-semibold text-gray-900">{role.title}</p>
        <span className={`text-xs font-medium px-2.5 py-1 rounded-full shrink-0 ${style.badge}`}>
          {style.label}
        </span>
      </div>

      <div>
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Why you fit</p>
        <ul className="space-y-0.5">
          {role.reasons.map((r, i) => (
            <li key={i} className="text-sm text-gray-700 flex gap-2">
              <span className="text-green-500 shrink-0">✓</span>{r}
            </li>
          ))}
        </ul>
      </div>

      {role.gaps.length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Gaps to address</p>
          <ul className="space-y-0.5">
            {role.gaps.map((g, i) => (
              <li key={i} className="text-sm text-gray-600 flex gap-2">
                <span className="text-amber-400 shrink-0">△</span>{g}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={() => onSave(role.title)}
          disabled={saved}
          className={`flex-1 text-sm py-1.5 rounded-lg border transition-colors ${
            saved
              ? 'border-green-300 text-green-600 bg-green-50 cursor-default'
              : 'border-gray-300 text-gray-700 hover:bg-gray-50'
          }`}
        >
          {saved ? '✓ Saved to profile' : '+ Save to profile'}
        </button>
        <button
          onClick={() => onSearch(role.search_query)}
          className="flex-1 text-sm bg-indigo-600 text-white py-1.5 rounded-lg hover:bg-indigo-700 transition-colors"
        >
          Search jobs →
        </button>
      </div>
    </div>
  )
}

export default function RoleFitPanel({ onSearchRole }: { onSearchRole?: (query: string) => void }) {
  const qc = useQueryClient()
  const [result, setResult] = useState<RoleFitOutput | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [savedRoles, setSavedRoles] = useState<Set<string>>(new Set())

  const { data: profile } = useQuery({
    queryKey: ['profile'],
    queryFn: () => api.get<ProfileData>('/profile').then((r) => r.data),
  })

  const saveRoleToProfile = async (title: string) => {
    const existing: string[] = profile?.target_titles
      ? JSON.parse(profile.target_titles).catch?.(() => []) ?? JSON.parse(profile.target_titles)
      : []
    if (existing.includes(title)) {
      setSavedRoles(prev => new Set(prev).add(title))
      return
    }
    const updated = [...existing, title]
    await api.patch('/profile', { target_titles: JSON.stringify(updated) })
    qc.invalidateQueries({ queryKey: ['profile'] })
    setSavedRoles(prev => new Set(prev).add(title))
  }

  const hasResume = !!profile?.resume_text

  const analyse = async () => {
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const { data } = await api.post<RoleFitOutput>('/profile/suggest-roles')
      setResult(data)
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Something went wrong. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const tiers = ['strong', 'stretch', 'adjacent'] as const

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-gray-900">Role Fit Advisor</h2>
        <p className="text-sm text-gray-500 mt-1">
          Analyses your resume and identifies the best-fit roles — no extra input needed.
        </p>
      </div>

      {/* Resume status + trigger */}
      <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
        <div className={`rounded-lg px-4 py-3 text-sm flex items-center gap-2 ${
          hasResume
            ? 'bg-green-50 border border-green-200 text-green-700'
            : 'bg-amber-50 border border-amber-200 text-amber-700'
        }`}>
          {hasResume
            ? <>✓ Resume loaded — ready to analyse</>
            : <>⚠ No resume saved — go to <strong>Profile</strong> tab to upload your resume first</>}
        </div>

        <button
          onClick={analyse}
          disabled={!hasResume || loading}
          className="bg-indigo-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? 'Analysing…' : 'Analyse my profile'}
        </button>

        {error && <p className="text-sm text-red-600">{error}</p>}
      </div>

      {/* Results */}
      {result && (
        <div className="space-y-6">
          {/* Candidate summary */}
          <div className="bg-indigo-50 border border-indigo-200 rounded-xl p-4 space-y-3">
            <p className="text-sm text-indigo-900 leading-relaxed">{result.candidate_summary}</p>
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-xs font-semibold text-indigo-600 uppercase tracking-wide">
                Seniority: {result.seniority_level}
              </span>
              <div className="flex flex-wrap gap-1.5">
                {result.core_skills.map((skill) => (
                  <span key={skill} className="text-xs bg-white border border-indigo-200 text-indigo-700 px-2 py-0.5 rounded-full">
                    {skill}
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* Roles by tier */}
          {tiers.map((tier) => {
            const roles = result.roles.filter((r) => r.tier === tier)
            if (roles.length === 0) return null
            const style = TIER_STYLES[tier]
            return (
              <div key={tier} className="space-y-3">
                <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
                  {style.label} ({roles.length})
                </h3>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {roles.map((role, i) => (
                    <RoleCard
                      key={i}
                      role={role}
                      onSearch={(q) => onSearchRole?.(q)}
                      onSave={saveRoleToProfile}
                      saved={savedRoles.has(role.title)}
                    />
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
