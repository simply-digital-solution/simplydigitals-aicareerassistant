import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

interface GapItem {
  title: string
  required_skills: string[]
  have: string[]
  missing: string[]
  coverage: number
  last_updated: string | null
}

function CoverageBar({ coverage }: { coverage: number }) {
  const pct = Math.round(coverage * 100)
  const color =
    pct >= 80 ? 'bg-green-500' :
    pct >= 50 ? 'bg-yellow-400' :
                'bg-red-400'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-medium text-gray-500 w-8 text-right">{pct}%</span>
    </div>
  )
}

function GapCard({ gap, onRefresh }: { gap: GapItem; onRefresh: (title: string) => void }) {
  const [open, setOpen] = useState(false)
  const pct = Math.round(gap.coverage * 100)

  return (
    <div className="border border-gray-200 rounded-xl overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors text-left"
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm font-medium text-gray-900 truncate">{gap.title}</span>
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium shrink-0 ${
              pct >= 80 ? 'bg-green-100 text-green-700' :
              pct >= 50 ? 'bg-yellow-100 text-yellow-700' :
                          'bg-red-100 text-red-600'
            }`}>
              {gap.missing.length} missing
            </span>
          </div>
          <CoverageBar coverage={gap.coverage} />
        </div>
        <span className="text-gray-400 text-xs pl-3 shrink-0">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="border-t border-gray-100 px-4 py-3 space-y-3 bg-white">
          {gap.have.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-green-700 mb-1.5">You have</p>
              <div className="flex flex-wrap gap-1.5">
                {gap.have.map(s => (
                  <span key={s} className="text-xs bg-green-50 text-green-700 border border-green-200 px-2 py-0.5 rounded-md">
                    ✓ {s}
                  </span>
                ))}
              </div>
            </div>
          )}

          {gap.missing.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-red-600 mb-1.5">Missing</p>
              <div className="flex flex-wrap gap-1.5">
                {gap.missing.map(s => (
                  <span key={s} className="text-xs bg-red-50 text-red-600 border border-red-200 px-2 py-0.5 rounded-md">
                    ✗ {s}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="flex items-center justify-between pt-1">
            {gap.last_updated ? (
              <span className="text-xs text-gray-400">
                Based on job postings · {new Date(gap.last_updated).toLocaleDateString()}
              </span>
            ) : (
              <span className="text-xs text-gray-400">Based on LLM knowledge</span>
            )}
            <button
              type="button"
              onClick={e => { e.stopPropagation(); onRefresh(gap.title) }}
              className="text-xs text-indigo-500 hover:text-indigo-700 ml-auto"
            >
              Refresh
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default function SkillGapPanel() {
  const qc = useQueryClient()

  const { data, isLoading } = useQuery<{ gaps: GapItem[] }>({
    queryKey: ['skill-gaps'],
    queryFn: () => api.get('/profile/skill-gaps').then(r => r.data),
  })

  const refreshMutation = useMutation({
    mutationFn: (title: string) =>
      api.post<GapItem>('/profile/skill-gaps/refresh', { title }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['skill-gaps'] }),
  })

  const seedAllMutation = useMutation({
    mutationFn: () =>
      api.post<{ seeded: string[]; skipped: string[] }>('/profile/skill-gaps/seed-all'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['skill-gaps'] }),
  })

  const gaps = data?.gaps ?? []

  if (isLoading) {
    return (
      <div className="space-y-2 animate-pulse">
        {[1, 2, 3].map(i => <div key={i} className="h-14 bg-gray-100 rounded-xl" />)}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {/* Status messages */}
      {(refreshMutation.isPending || seedAllMutation.isPending) && (
        <p className="text-xs text-indigo-500 animate-pulse">
          {seedAllMutation.isPending ? 'Generating skill data for all titles…' : 'Refreshing skill data…'}
        </p>
      )}
      {refreshMutation.isError && (
        <p className="text-xs text-red-500">Refresh failed. Try again.</p>
      )}
      {seedAllMutation.isError && (
        <p className="text-xs text-red-500">Seed failed. Try again.</p>
      )}
      {seedAllMutation.isSuccess && seedAllMutation.data?.data.seeded.length === 0 && (
        <p className="text-xs text-gray-400">All titles already have skill data.</p>
      )}

      {gaps.length === 0 ? (
        <div className="space-y-3 py-2">
          <p className="text-sm text-gray-400">
            No skill gap data yet. Seed from LLM knowledge or run a Job Research search to derive skills from real job postings.
          </p>
          <button
            type="button"
            onClick={() => seedAllMutation.mutate()}
            disabled={seedAllMutation.isPending}
            className="text-xs bg-indigo-50 text-indigo-600 border border-indigo-200 px-3 py-1.5 rounded-lg hover:bg-indigo-100 disabled:opacity-50 transition-colors"
          >
            {seedAllMutation.isPending ? 'Generating…' : 'Seed All Titles'}
          </button>
        </div>
      ) : (
        <>
          {gaps.map(gap => (
            <GapCard
              key={gap.title}
              gap={gap}
              onRefresh={title => refreshMutation.mutate(title)}
            />
          ))}
          <button
            type="button"
            onClick={() => seedAllMutation.mutate()}
            disabled={seedAllMutation.isPending}
            className="text-xs text-gray-400 hover:text-indigo-500 disabled:opacity-50 transition-colors pt-1"
          >
            {seedAllMutation.isPending ? 'Generating…' : '+ Seed missing titles'}
          </button>
        </>
      )}
    </div>
  )
}
