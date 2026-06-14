import { useState } from 'react'
import { useAgentStream } from '../hooks/useAgentStream'
import type { InterviewOutput, BehaviouralQuestion, TechnicalQuestion, StarExample } from '../api/client'
import AgentPanel from './AgentPanel'

function Accordion({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 text-sm font-medium text-gray-700 transition-colors"
      >
        {label}
        <span className="text-gray-400">{open ? '▲' : '▼'}</span>
      </button>
      {open && <div className="p-4">{children}</div>}
    </div>
  )
}

function BehaviouralCard({ q }: { q: BehaviouralQuestion }) {
  return (
    <Accordion label={q.q}>
      <p className="text-sm text-indigo-700 bg-indigo-50 rounded p-3">{q.guidance}</p>
    </Accordion>
  )
}

function TechnicalCard({ q }: { q: TechnicalQuestion }) {
  return (
    <Accordion label={q.q}>
      <p className="text-sm text-gray-700 whitespace-pre-wrap">{q.answer_outline}</p>
    </Accordion>
  )
}

function StarCard({ ex }: { ex: StarExample }) {
  return (
    <Accordion label={`STAR: ${ex.applicable_questions[0] ?? 'Example'}`}>
      <div className="space-y-2 text-sm">
        {(['situation', 'task', 'action', 'result'] as const).map((key) => (
          <div key={key}>
            <span className="font-semibold capitalize text-gray-600">{key}: </span>
            <span className="text-gray-700">{ex[key]}</span>
          </div>
        ))}
        {ex.applicable_questions.length > 1 && (
          <div className="mt-2">
            <p className="text-xs text-gray-500 font-medium">Also applies to:</p>
            <ul className="mt-1 space-y-0.5">
              {ex.applicable_questions.slice(1).map((q, i) => (
                <li key={i} className="text-xs text-gray-500">• {q}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Accordion>
  )
}

export default function InterviewPanel() {
  const [jdText, setJdText] = useState('')
  const [companyName, setCompanyName] = useState('')

  const { status, chunks, result, meta, error, run, reset } =
    useAgentStream<InterviewOutput>({ endpoint: '/agents/interview' })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    run({ jd_text: jdText, company_name: companyName })
  }

  const form = (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Company name</label>
        <input
          value={companyName}
          onChange={(e) => setCompanyName(e.target.value)}
          placeholder="e.g. Stripe"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Job description</label>
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
        className="bg-indigo-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
      >
        Prepare interview pack
      </button>
    </form>
  )

  const resultNode = result ? (
    <div className="space-y-6">
      {/* Behavioural */}
      <div className="space-y-2">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          Behavioural Questions ({result.behavioural.length})
        </p>
        {result.behavioural.map((q, i) => <BehaviouralCard key={i} q={q} />)}
      </div>

      {/* Technical */}
      <div className="space-y-2">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          Technical / Role Questions ({result.technical.length})
        </p>
        {result.technical.map((q, i) => <TechnicalCard key={i} q={q} />)}
      </div>

      {/* STAR examples */}
      <div className="space-y-2">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          STAR Examples ({result.star_examples.length})
        </p>
        {result.star_examples.map((ex, i) => <StarCard key={i} ex={ex} />)}
      </div>

      {/* Questions to ask */}
      <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-2">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          Questions to Ask the Interviewer
        </p>
        <ul className="space-y-2">
          {result.interviewer_questions.map((q, i) => (
            <li key={i} className="text-sm text-gray-700 flex gap-2">
              <span className="text-indigo-400 shrink-0 font-medium">{i + 1}.</span>
              {q}
            </li>
          ))}
        </ul>
      </div>
    </div>
  ) : null

  return (
    <AgentPanel
      title="Interview Coach"
      description="Prepare behavioural, technical, and STAR answers for a specific role."
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
