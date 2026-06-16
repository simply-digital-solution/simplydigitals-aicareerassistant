import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api, { researchApi, applicationsApi } from '../api/client'
import type { StoredJob } from '../api/client'
import { StoredJobCard } from './ResearchPanel'
import type { FeedbackEntry } from './ResearchPanel'
import TailoredResumePanel from './TailoredResumePanel'

type FeedbackMap = Record<string, FeedbackEntry>

function MarkAppliedButton({ applicationId }: { applicationId: number }) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)

  const applyMutation = useMutation({
    mutationFn: () => applicationsApi.move(applicationId, 'applied'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['selected-jobs'] })
      queryClient.invalidateQueries({ queryKey: ['stored-jobs'] })
    },
  })

  if (confirming) {
    return (
      <span className="flex items-center gap-1.5">
        <span className="text-xs text-gray-500">Applied?</span>
        <button
          onClick={() => applyMutation.mutate()}
          disabled={applyMutation.isPending}
          className="text-xs bg-green-600 text-white px-2.5 py-1 rounded-md hover:bg-green-700 disabled:opacity-50 transition-colors font-medium"
          aria-label="Confirm mark as applied"
        >
          {applyMutation.isPending ? 'Saving…' : 'Yes'}
        </button>
        <button
          onClick={() => setConfirming(false)}
          className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
          aria-label="Cancel"
        >
          Cancel
        </button>
      </span>
    )
  }

  return (
    <button
      onClick={() => setConfirming(true)}
      className="text-xs border border-green-300 text-green-700 px-2.5 py-1 rounded-md hover:bg-green-50 transition-colors font-medium"
      aria-label="Mark job as applied"
    >
      ✓ Applied
    </button>
  )
}

export default function SelectedJobsPanel() {
  const queryClient = useQueryClient()
  const [localFeedback, setLocalFeedback] = useState<FeedbackMap>({})

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

  const [pendingRescore, setPendingRescore] = useState<Set<number>>(new Set())

  const archiveMutation = useMutation({
    mutationFn: (id: number) => researchApi.archiveJob(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['selected-jobs'] })
      queryClient.invalidateQueries({ queryKey: ['stored-jobs'] })
    },
  })

  const rescoreMutation = useMutation({
    mutationFn: (id: number) => researchApi.rescoreJob(id),
    onSuccess: (_data, id) => {
      setPendingRescore(prev => new Set([...prev, id]))
      queryClient.invalidateQueries({ queryKey: ['selected-jobs'] })
    },
  })

  const jobs: StoredJob[] = data?.jobs ?? []

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
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <StoredJobCard
                      job={job}
                      feedback={feedbackMap[job.url]}
                      onFeedback={handleFeedback}
                      onArchive={(id) => archiveMutation.mutate(id)}
                      onRescore={(id) => rescoreMutation.mutate(id)}
                    />
                  </div>
                  <div className="pt-2 shrink-0">
                    <MarkAppliedButton applicationId={(job as StoredJob & { application_id: number }).application_id} />
                  </div>
                </div>
                <TailoredResumePanel jobId={job.id} company={job.company} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
