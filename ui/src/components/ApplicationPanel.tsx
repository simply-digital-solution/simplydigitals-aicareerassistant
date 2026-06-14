import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAgentStream } from '../hooks/useAgentStream'
import type { ApplicationOutput } from '../api/client'
import api from '../api/client'
import AgentPanel from './AgentPanel'

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button onClick={copy} className="text-xs text-indigo-500 hover:underline">
      {copied ? 'Copied!' : 'Copy'}
    </button>
  )
}

export default function ApplicationPanel() {
  const [jdText, setJdText] = useState('')

  const { data: profile } = useQuery({
    queryKey: ['profile'],
    queryFn: () => api.get<{ resume_text: string | null }>('/profile').then((r) => r.data),
  })

  const { status, chunks, result, meta, error, run, reset } =
    useAgentStream<ApplicationOutput>({ endpoint: '/agents/application' })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    run({ jd_text: jdText })
  }

  const hasResume = !!profile?.resume_text

  const form = (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className={`rounded-lg px-4 py-3 text-sm flex items-center gap-2 ${
        hasResume
          ? 'bg-green-50 border border-green-200 text-green-700'
          : 'bg-amber-50 border border-amber-200 text-amber-700'
      }`}>
        {hasResume ? (
          <>✓ Using your saved resume</>
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
        Draft application
      </button>
    </form>
  )

  const resultNode = result ? (
    <div className="space-y-5">
      <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-2">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Cover Letter</p>
          <CopyButton text={result.cover_letter} />
        </div>
        <p className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">{result.cover_letter}</p>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-2">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">LinkedIn Note</p>
          <CopyButton text={result.linkedin_note} />
        </div>
        <p className="text-sm text-gray-700">{result.linkedin_note}</p>
        <p className="text-xs text-gray-400">{result.linkedin_note.length} / 300 chars</p>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-2">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">CV Tailoring Notes</p>
        <ul className="space-y-1.5">
          {result.cv_tailor_notes.map((note, i) => (
            <li key={i} className="text-sm text-gray-700 flex gap-2">
              <span className="text-indigo-400 shrink-0">→</span>{note}
            </li>
          ))}
        </ul>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-2">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Key Match Points</p>
        <ul className="space-y-1">
          {result.key_match_points.map((pt, i) => (
            <li key={i} className="text-sm text-gray-700">✓ {pt}</li>
          ))}
        </ul>
      </div>
    </div>
  ) : null

  return (
    <AgentPanel
      title="Application Drafts"
      description="Write a tailored cover letter using your saved resume."
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
