import { useQuery } from '@tanstack/react-query'
import { researchApi } from '../api/client'
import { StoredJobCard } from './ResearchPanel'
import TailoredResumePanel from './TailoredResumePanel'

export default function AppliedJobsPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ['applied-jobs'],
    queryFn: () => researchApi.getAppliedJobs().then(r => r.data),
  })

  const jobs = data?.jobs ?? []

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-4">
      <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-800">
            Applied Jobs
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
            <p>No applied jobs yet.</p>
            <p className="mt-1">Mark jobs as applied from the <strong>Selected</strong> tab.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {jobs.map(job => (
              <div key={job.id}>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <StoredJobCard
                      job={job}
                      readOnly
                      onFeedback={() => {}}
                      onArchive={() => {}}
                      onRescore={() => {}}
                    />
                  </div>
                  <div className="pt-2 shrink-0">
                    <span
                      className="text-xs text-gray-400 border border-gray-200 px-2.5 py-1 rounded-md font-medium"
                      aria-label="Job marked as applied"
                    >
                      ✓ Applied
                    </span>
                  </div>
                </div>
                <TailoredResumePanel jobId={job.id} company={job.company} readOnly />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
