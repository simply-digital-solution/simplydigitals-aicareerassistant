import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { approvalsApi } from '../api/client'
import type { Draft } from '../api/client'

const GATE_COLORS: Record<string, string> = {
  hard:  'bg-red-100 text-red-700',
  soft:  'bg-yellow-100 text-yellow-700',
  auto:  'bg-green-100 text-green-700',
}

const TYPE_LABELS: Record<string, string> = {
  cover_letter:  'Cover Letter',
  resume_edit:   'Resume Edit',
  interview_q:   'Interview Prep',
}

function DraftCard({ draft }: { draft: Draft }) {
  const [editMode, setEditMode] = useState(false)
  const [editedContent, setEditedContent] = useState(draft.content)
  const qc = useQueryClient()

  const invalidate = () => qc.invalidateQueries({ queryKey: ['drafts'] })

  const approve = useMutation({
    mutationFn: () => approvalsApi.approve(draft.id),
    onSuccess: invalidate,
  })
  const editDraft = useMutation({
    mutationFn: () => approvalsApi.edit(draft.id, editedContent),
    onSuccess: () => { setEditMode(false); invalidate() },
  })
  const reject = useMutation({
    mutationFn: () => approvalsApi.reject(draft.id),
    onSuccess: invalidate,
  })

  const busy = approve.isPending || editDraft.isPending || reject.isPending

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-medium text-gray-900">
            {TYPE_LABELS[draft.draft_type] ?? draft.draft_type}
            {draft.company_name && (
              <span className="text-gray-500 font-normal"> — {draft.company_name}</span>
            )}
            {draft.role_title && (
              <span className="text-gray-400 text-sm font-normal"> ({draft.role_title})</span>
            )}
          </p>
          <p className="text-xs text-gray-400 mt-0.5">
            {new Date(draft.created_at).toLocaleDateString()}
          </p>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium shrink-0 ${GATE_COLORS[draft.gate_tier] ?? 'bg-gray-100 text-gray-600'}`}>
          {draft.gate_tier} gate
        </span>
      </div>

      {/* Content */}
      {editMode ? (
        <textarea
          value={editedContent}
          onChange={(e) => setEditedContent(e.target.value)}
          rows={8}
          className="w-full border border-indigo-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 resize-none"
        />
      ) : (
        <p className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto">
          {draft.content}
        </p>
      )}

      {/* Actions */}
      <div className="flex gap-2 pt-1">
        {editMode ? (
          <>
            <button
              onClick={() => editDraft.mutate()}
              disabled={busy}
              className="bg-indigo-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            >
              Save edit
            </button>
            <button
              onClick={() => { setEditMode(false); setEditedContent(draft.content) }}
              className="text-gray-500 hover:text-gray-700 px-3 py-1.5 text-xs"
            >
              Cancel
            </button>
          </>
        ) : (
          <>
            <button
              onClick={() => approve.mutate()}
              disabled={busy}
              className="bg-green-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-green-700 disabled:opacity-50 transition-colors"
            >
              ✓ Approve
            </button>
            <button
              onClick={() => setEditMode(true)}
              disabled={busy}
              className="bg-white border border-gray-300 text-gray-700 px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50 transition-colors"
            >
              Edit & approve
            </button>
            <button
              onClick={() => reject.mutate()}
              disabled={busy}
              className="text-red-500 hover:text-red-700 px-3 py-1.5 text-xs font-medium disabled:opacity-50"
            >
              Reject
            </button>
          </>
        )}
      </div>
    </div>
  )
}

export default function DraftsPanel() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['drafts'],
    queryFn: () => approvalsApi.pending().then((r) => r.data),
    refetchInterval: 15_000,
  })

  if (isLoading) {
    return (
      <div className="max-w-4xl mx-auto p-6">
        <div className="animate-pulse space-y-3">
          {[1, 2].map((i) => (
            <div key={i} className="h-40 bg-gray-100 rounded-xl" />
          ))}
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="max-w-4xl mx-auto p-6">
        <p className="text-sm text-red-600">Failed to load pending drafts.</p>
      </div>
    )
  }

  const drafts = data?.drafts ?? []

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-gray-900">Pending Drafts</h2>
          <p className="text-sm text-gray-500 mt-1">Review and approve agent-generated content before use.</p>
        </div>
        {drafts.length > 0 && (
          <span className="bg-indigo-600 text-white text-xs font-bold px-2.5 py-1 rounded-full">
            {drafts.length}
          </span>
        )}
      </div>

      {drafts.length === 0 ? (
        <div className="bg-white border border-gray-200 rounded-xl p-12 text-center">
          <p className="text-gray-400 text-sm">No pending drafts — all caught up.</p>
        </div>
      ) : (
        drafts.map((draft) => <DraftCard key={draft.id} draft={draft} />)
      )}
    </div>
  )
}
