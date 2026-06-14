import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAgentStream } from '../hooks/useAgentStream'
import type { ResumeOutput } from '../api/client'
import api from '../api/client'
import AgentPanel from './AgentPanel'

const SECTION_COLORS: Record<string, string> = {
  summary:    'bg-purple-50 text-purple-700',
  experience: 'bg-blue-50 text-blue-700',
  skills:     'bg-green-50 text-green-700',
  education:  'bg-yellow-50 text-yellow-700',
}

export default function ResumePanel() {
  const [jdText, setJdText] = useState('')

  const { data: profile } = useQuery({
    queryKey: ['profile'],
    queryFn: () => api.get<{ resume_text: string | null }>('/profile').then((r) => r.data),
  })

  const { status, chunks, result, meta, error, run, reset } =
    useAgentStream<ResumeOutput>({ endpoint: '/agents/resume' })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    // resume_text omitted — backend loads it from DB automatically
    run({ jd_text: jdText })
  }

  const hasResume = !!profile?.resume_text

  const form = (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* Resume source indicator */}
      <div className={`rounded-lg px-4 py-3 text-sm flex items-center gap-2 ${
        hasResume
          ? 'bg-green-50 border border-green-200 text-green-700'
          : 'bg-amber-50 border border-amber-200 text-amber-700'
      }`}>
        {hasResume ? (
          <>✓ Using your saved resume ({profile!.resume_text!.trim().split(/\s+/).length} words)</>
        ) : (
          <>⚠ No resume saved — go to <strong>Profile</strong> tab to upload your resume first</>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Target job description</label>
        <textarea
          value={jdText}
          onChange={(e) => setJdText(e.target.value)}
          rows={7}
          placeholder="Paste the job description here…"
          required
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 resize-none"
        />
      </div>
      <button
        type="submit"
        disabled={!hasResume}
        className="bg-indigo-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        Optimise resume
      </button>
    </form>
  )

  const resultNode = result ? (
    <div className="space-y-5">
      <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-1">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">LinkedIn Headline</p>
        <p className="text-gray-900 font-medium">{result.headline}</p>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-3">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          Resume Edits ({result.resume_edits.length})
        </p>
        {result.resume_edits.map((edit, i) => (
          <div key={i} className="space-y-1 border-l-2 border-indigo-200 pl-3">
            <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${SECTION_COLORS[edit.section] ?? 'bg-gray-100 text-gray-600'}`}>
              {edit.section}
            </span>
            <p className="text-sm text-red-600 line-through opacity-70">{edit.original}</p>
            <p className="text-sm text-green-700">{edit.suggested}</p>
          </div>
        ))}
      </div>

      <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-3">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">LinkedIn About Options</p>
        {result.about_options.map((opt, i) => (
          <div key={i} className="bg-gray-50 rounded-lg p-3 text-sm text-gray-700">
            <span className="font-medium text-gray-400 mr-2">Option {i + 1}</span>{opt}
          </div>
        ))}
      </div>

      <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-2">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Suggested Skills Order</p>
        <div className="flex flex-wrap gap-2">
          {result.skills_reorder.map((skill, i) => (
            <span key={skill} className="text-xs bg-indigo-50 text-indigo-700 px-2.5 py-1 rounded-full">
              {i + 1}. {skill}
            </span>
          ))}
        </div>
      </div>

      {result.suggested_metrics[0] !== 'N/A' && (
        <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-2">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Metrics to Highlight</p>
          <ul className="space-y-1">
            {result.suggested_metrics.map((m, i) => (
              <li key={i} className="text-sm text-gray-700">→ {m}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  ) : null

  return (
    <AgentPanel
      title="Resume & LinkedIn Optimiser"
      description="Tailor your saved resume for a specific role."
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
