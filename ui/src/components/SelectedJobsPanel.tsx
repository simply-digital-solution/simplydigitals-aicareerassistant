import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api, { researchApi } from '../api/client'
import type { StoredJob } from '../api/client'
import { StoredJobCard } from './ResearchPanel'
import type { FeedbackEntry } from './ResearchPanel'
import TailoredResumePanel from './TailoredResumePanel'

type FeedbackMap = Record<string, FeedbackEntry>

export default function SelectedJobsPanel() {
  const queryClient = useQueryClient()
  const [localFeedback, setLocalFeedback] = useState<FeedbackMap>({})
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [rescoringIds, setRescoringIds] = useState<Set<number>>(new Set())
  const [generatingIds, setGeneratingIds] = useState<Set<number>>(new Set())
  const [etaSeconds, setEtaSeconds] = useState(0)

  const { data: savedFeedback } = useQuery<{ job_url: string; relevance: 'relevant' | 'not_relevant'; reason?: string }[]>({
    queryKey: ['research-feedback'],
    queryFn: () => api.get('/research/feedback').then(r => r.data.feedback ?? []),
  })

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

  const { data, isLoading } = useQuery({
    queryKey: ['selected-jobs'],
    queryFn: () => researchApi.getSelectedJobs().then(r => r.data),
  })

  const archiveMutation = useMutation({
    mutationFn: (id: number) => researchApi.archiveJob(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['selected-jobs'] })
      queryClient.invalidateQueries({ queryKey: ['stored-jobs'] })
    },
  })

  const rescoreMutation = useMutation({
    mutationFn: (id: number) => researchApi.rescoreJob(id).then(r => ({ id, job: r.data })),
    onMutate: (id) => {
      setRescoringIds(prev => new Set([...prev, id]))
    },
    onSuccess: ({ id, job }) => {
      setRescoringIds(prev => { const next = new Set(prev); next.delete(id); return next })
      queryClient.setQueryData<{ total: number; jobs: StoredJob[] }>(
        ['selected-jobs'],
        old => old
          ? { ...old, jobs: old.jobs.map(j => j.id === id ? { ...j, ...job } : j) }
          : old
      )
    },
    onError: (_err, id) => {
      setRescoringIds(prev => { const next = new Set(prev); next.delete(id); return next })
    },
  })

  const bulkGenerateMutation = useMutation({
    mutationFn: (jobIds: number[]) => researchApi.bulkGenerateResumes(jobIds).then(r => ({ jobIds, results: r.data.results })),
    onMutate: (jobIds) => {
      setGeneratingIds(new Set(jobIds))
      // ETA: each job takes ~4s on average (rate limiter paces to 15 RPM)
      setEtaSeconds(jobIds.length * 4)
    },
    onSuccess: ({ jobIds, results }) => {
      // Invalidate each job's resume cache so TailoredResumePanel refetches
      for (const jid of jobIds) {
        if (results[jid]) {
          queryClient.invalidateQueries({ queryKey: ['generated-resume', jid] })
        }
      }
      setGeneratingIds(new Set())
      setSelectedIds(new Set())
      setEtaSeconds(0)
    },
    onError: () => {
      setGeneratingIds(new Set())
      setEtaSeconds(0)
    },
  })

  // Count down ETA every second while generating
  useEffect(() => {
    if (etaSeconds <= 0) return
    const t = setTimeout(() => setEtaSeconds(s => Math.max(0, s - 1)), 1000)
    return () => clearTimeout(t)
  }, [etaSeconds])

  const toggleSelected = (id: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const jobs: (StoredJob & { application_id: number })[] = data?.jobs ?? []
  const isGeneratingAny = generatingIds.size > 0

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-4">
      <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-800">
            Selected Jobs
            {data && (
              <span className="ml-2 text-xs font-normal text-gray-400">{data.total} total</span>
            )}
          </h3>
          {selectedIds.size > 0 && (
            <span className="text-xs text-gray-400">{selectedIds.size} selected</span>
          )}
        </div>

        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="h-20 bg-gray-100 rounded-lg animate-pulse" />
            ))}
          </div>
        ) : jobs.length === 0 ? (
          <div className="text-center py-10 text-sm text-gray-400">
            <p>No selected jobs yet.</p>
            <p className="mt-1">Save jobs from the <strong>Research</strong> tab using the bookmark icon.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {jobs.map(job => (
              <div key={job.id}>
                <div className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    checked={selectedIds.has(job.id)}
                    onChange={() => toggleSelected(job.id)}
                    disabled={isGeneratingAny}
                    className="mt-3 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 shrink-0 cursor-pointer disabled:cursor-not-allowed disabled:opacity-40"
                    aria-label={`Select ${job.title} at ${job.company}`}
                  />
                  <div className="flex-1 min-w-0">
                    <StoredJobCard
                      job={job}
                      feedback={feedbackMap[job.url]}
                      onFeedback={handleFeedback}
                      onArchive={(id) => archiveMutation.mutate(id)}
                      onRescore={(id) => rescoreMutation.mutate(id)}
                      rescoring={rescoringIds.has(job.id) || !!job.rescoring}
                    />
                  </div>
                </div>
                <TailoredResumePanel
                  jobId={job.id}
                  company={job.company}
                  jobUrl={job.url}
                  isGenerating={generatingIds.has(job.id)}
                  applicationId={job.application_id}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Floating action bar */}
      {(selectedIds.size > 0 || isGeneratingAny) && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50">
          <div className="flex items-center gap-3 bg-gray-900 text-white rounded-full px-5 py-2.5 shadow-xl text-sm font-medium">
            {isGeneratingAny ? (
              <span className="text-gray-300 text-xs">
                Generating {generatingIds.size} resume{generatingIds.size !== 1 ? 's' : ''}
                {etaSeconds > 0 ? ` — ~${etaSeconds}s remaining` : '…'}
              </span>
            ) : (
              <>
                <span className="text-gray-400 text-xs">{selectedIds.size} selected</span>
                <button
                  onClick={() => bulkGenerateMutation.mutate([...selectedIds])}
                  disabled={selectedIds.size === 0}
                  className="bg-indigo-500 hover:bg-indigo-400 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-full px-4 py-1 text-xs transition-colors"
                >
                  ✦ Generate Resumes
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
