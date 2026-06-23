import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { researchApi, agentsApi, applicationsApi, authApi } from '../api/client'
import type { InterviewingJob, InterviewPack, InterviewPackResult } from '../api/client'
import { StoredJobCard } from './ResearchPanel'
import TailoredResumePanel from './TailoredResumePanel'

type StatusFilter = 'interviewing' | 'offered' | 'rejected' | 'all'

const STATUS_BADGE: Record<string, string> = {
  interviewing: 'bg-blue-50 text-blue-700 border-blue-200',
  offered: 'bg-green-50 text-green-700 border-green-200',
  rejected: 'bg-red-50 text-red-600 border-red-200',
}

const STATUS_LABEL: Record<string, string> = {
  interviewing: 'Interviewing',
  offered: 'Offered',
  rejected: 'Rejected',
}

function StarQuestionsView({ pack }: { pack: InterviewPack }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="mt-3 border border-indigo-100 rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-indigo-50 hover:bg-indigo-100 text-sm font-medium text-indigo-800 transition-colors"
      >
        Interview Pack
        <span className="text-indigo-400 text-xs">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="p-4 space-y-4 bg-white">
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">2-Minute Pitch</p>
            <p className="text-sm text-gray-700 whitespace-pre-wrap bg-gray-50 rounded p-3">{pack.pitch}</p>
          </div>
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
              STAR Questions ({pack.star_questions.length})
            </p>
            <div className="space-y-3">
              {pack.star_questions.map((q, i) => (
                <StarQuestionCard key={i} index={i + 1} q={q} />
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function StarQuestionCard({ index, q }: { index: number; q: InterviewPack['star_questions'][0] }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-2 px-3 py-2.5 bg-gray-50 hover:bg-gray-100 text-sm text-gray-700 transition-colors text-left"
      >
        <span className="text-indigo-400 font-semibold shrink-0">{index}.</span>
        <span className="font-medium">{q.q}</span>
        <span className="ml-auto text-gray-400 text-xs shrink-0">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="p-3 space-y-2 text-sm">
          {(['situation', 'task', 'action', 'result'] as const).map(key => (
            <div key={key}>
              <span className="font-semibold capitalize text-gray-600">{key}: </span>
              <span className="text-gray-700">{q[key]}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function PackDriveLinks({ fileId, link }: { fileId: string | null; link: string | null }) {
  if (!fileId && !link) return null
  return (
    <div className="flex items-center gap-3 mt-1">
      {fileId && (
        <a
          href={`https://drive.google.com/uc?export=download&id=${fileId}`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-green-600 hover:text-green-800 font-medium"
          aria-label="Download interview pack from Google Drive"
        >
          ↓ Interview Pack
        </a>
      )}
      {link && (
        <a
          href={link}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-blue-600 hover:text-blue-800 font-medium"
          aria-label="Open interview pack in Google Drive"
        >
          ↗ Interview Pack in Drive
        </a>
      )}
    </div>
  )
}

function InterviewJobCard({ job, driveConnected }: { job: InterviewingJob; driveConnected: boolean }) {
  const qc = useQueryClient()
  const [generating, setGenerating] = useState(false)
  const [driveError, setDriveError] = useState<string | null>(null)
  const [movingTo, setMovingTo] = useState<string | null>(null)
  const isTerminal = job.application_status === 'offered' || job.application_status === 'rejected'

  // Persistent Drive links come from job row (survive page refresh)
  const packFileId = job.pack_drive_file_id
  const packLink = job.pack_drive_link

  const { data: pack } = useQuery({
    queryKey: ['interview-pack', job.application_id],
    queryFn: () => agentsApi.getInterviewPack(job.application_id).then(r => r.data),
    enabled: job.has_interview_pack,
    retry: false,
  })

  const handleGeneratePack = async () => {
    setGenerating(true)
    setDriveError(null)
    try {
      const res = await agentsApi.generateInterviewPack(job.application_id)
      if (res.data.drive_error) setDriveError(res.data.drive_error)
      qc.invalidateQueries({ queryKey: ['interview-pack', job.application_id] })
      qc.invalidateQueries({ queryKey: ['interviewing-jobs'] })
    } finally {
      setGenerating(false)
    }
  }

  const handleMove = async (status: 'offered' | 'rejected') => {
    setMovingTo(status)
    try {
      await applicationsApi.move(job.application_id, status)
      qc.invalidateQueries({ queryKey: ['interviewing-jobs'] })
      qc.invalidateQueries({ queryKey: ['pipeline'] })
    } finally {
      setMovingTo(null)
    }
  }

  return (
    <div>
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
        <span
          className={`mt-2 shrink-0 text-xs border px-2.5 py-1 rounded-md font-medium ${STATUS_BADGE[job.application_status]}`}
        >
          {STATUS_LABEL[job.application_status]}
        </span>
      </div>

      {!isTerminal && (
        <div className="flex items-center gap-2 mt-2">
          <span className="text-xs text-gray-400">Move to:</span>
          <button
            type="button"
            onClick={() => handleMove('offered')}
            disabled={!!movingTo}
            className="text-xs border border-green-600 text-green-700 px-2.5 py-0.5 rounded font-medium hover:bg-green-50 disabled:opacity-50 transition-colors"
          >
            {movingTo === 'offered' ? 'Moving…' : 'Offered'}
          </button>
          <button
            type="button"
            onClick={() => handleMove('rejected')}
            disabled={!!movingTo}
            className="text-xs border border-red-400 text-red-500 px-2.5 py-0.5 rounded font-medium hover:bg-red-50 disabled:opacity-50 transition-colors"
          >
            {movingTo === 'rejected' ? 'Moving…' : 'Rejected'}
          </button>
        </div>
      )}

      <TailoredResumePanel jobId={job.id} company={job.company} readOnly />

      {/* Interview Pack */}
      {pack ? (
        <>
          <StarQuestionsView pack={pack} />
          <PackDriveLinks fileId={packFileId} link={packLink} />
        </>
      ) : (
        <div className="mt-3 space-y-1">
          {!driveConnected ? (
            <p className="text-xs text-amber-600" role="status">
              Connect Drive to save interview questionnaire — connect Google Drive first.
            </p>
          ) : packFileId ? (
            // Pack already uploaded to Drive (content cleared from DB)
            <PackDriveLinks fileId={packFileId} link={packLink} />
          ) : (
            <>
              <button
                type="button"
                onClick={handleGeneratePack}
                disabled={generating}
                className="text-xs bg-indigo-600 text-white px-3 py-1.5 rounded-md font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              >
                {generating ? 'Generating pack…' : '✦ Interview Questions'}
              </button>
              {generating && (
                <p className="text-xs text-gray-400">This takes ~15 seconds…</p>
              )}
              {driveError && (
                <p className="text-xs text-red-500">Drive upload failed: {driveError}</p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

const FILTER_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'interviewing', label: 'Interviewing' },
  { value: 'offered', label: 'Offered' },
  { value: 'rejected', label: 'Rejected' },
]

export default function InterviewJobsPanel() {
  const [filter, setFilter] = useState<StatusFilter>('interviewing')

  const { data, isLoading } = useQuery({
    queryKey: ['interviewing-jobs'],
    queryFn: () => researchApi.getInterviewingJobs().then(r => r.data),
  })

  const { data: driveStatus } = useQuery({
    queryKey: ['drive-status'],
    queryFn: () => authApi.googleStatus().then(r => r.data),
    staleTime: 60_000,
  })
  const driveConnected = driveStatus?.connected ?? false

  const allJobs = data?.jobs ?? []
  const jobs = filter === 'all' ? allJobs : allJobs.filter(j => j.application_status === filter)

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-4">
      <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <h3 className="text-sm font-semibold text-gray-800">
            Interview Pipeline
            {data && (
              <span className="ml-2 text-xs font-normal text-gray-400">{data.total} total</span>
            )}
          </h3>
          <div className="flex gap-1">
            {FILTER_OPTIONS.map(opt => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setFilter(opt.value)}
                className={`text-xs px-3 py-1.5 rounded-md font-medium transition-colors ${
                  filter === opt.value
                    ? 'bg-indigo-600 text-white'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {opt.label}
                {opt.value !== 'all' && data && (
                  <span className="ml-1 opacity-70">
                    ({allJobs.filter(j => j.application_status === opt.value).length})
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>

        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="h-20 bg-gray-100 rounded-lg animate-pulse" />
            ))}
          </div>
        ) : jobs.length === 0 ? (
          <div className="text-center py-10 text-sm text-gray-400">
            <p>No jobs in this stage.</p>
            {filter === 'interviewing' && (
              <p className="mt-1">Use <strong>Interview Scheduled</strong> on the Applied tab to move jobs here.</p>
            )}
          </div>
        ) : (
          <div className="space-y-6 divide-y divide-gray-100">
            {jobs.map(job => (
              <div key={job.id} className="pt-4 first:pt-0">
                <InterviewJobCard job={job} driveConnected={driveConnected} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
