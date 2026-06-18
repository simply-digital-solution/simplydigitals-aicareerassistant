import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { applicationsApi } from '../api/client'
import type { Application, PipelineBoard } from '../api/client'
import type { Tab } from '../App'

const LANE_LIMIT = 4

const COLUMNS: { key: string; label: string; color: string; tab: Tab }[] = [
  { key: 'selected',     label: 'Selected',     color: 'bg-gray-100 border-gray-300',   tab: 'Selected' },
  { key: 'applied',      label: 'Applied',       color: 'bg-blue-50 border-blue-300',    tab: 'Applied' },
  { key: 'interviewing', label: 'Interviewing',  color: 'bg-yellow-50 border-yellow-300', tab: 'Pipeline' },
  { key: 'offered',      label: 'Offered',       color: 'bg-green-50 border-green-300',  tab: 'Pipeline' },
  { key: 'rejected',     label: 'Rejected',      color: 'bg-red-50 border-red-300',      tab: 'Pipeline' },
]

function ScoreBadge({ score }: { score?: number }) {
  if (score == null) return null
  const pct = Math.round(score * 100)
  const color = pct >= 80 ? 'bg-green-100 text-green-800' : pct >= 60 ? 'bg-yellow-100 text-yellow-800' : 'bg-red-100 text-red-800'
  return <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${color}`}>{pct}%</span>
}

function ApplicationCard({ app }: { app: Application }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-3 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-semibold text-gray-900 text-sm truncate">{app.company_name}</p>
          <p className="text-gray-500 text-xs truncate">{app.role_title}</p>
        </div>
        <ScoreBadge score={app.fit_score ?? undefined} />
      </div>

      {app.deadline && (
        <p className="text-xs text-orange-600 mt-1">Due: {app.deadline}</p>
      )}
    </div>
  )
}

function AddApplicationModal({ onClose, onAdd }: { onClose: () => void; onAdd: (data: Partial<Application>) => void }) {
  const [form, setForm] = useState({ company_name: '', role_title: '', source_url: '', notes: '' })

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
        <h2 className="text-lg font-semibold mb-4">Add Application</h2>
        <div className="space-y-3">
          <input
            placeholder="Company name *"
            value={form.company_name}
            onChange={e => setForm(f => ({ ...f, company_name: e.target.value }))}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
          <input
            placeholder="Role title *"
            value={form.role_title}
            onChange={e => setForm(f => ({ ...f, role_title: e.target.value }))}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
          <input
            placeholder="Job URL (optional)"
            value={form.source_url}
            onChange={e => setForm(f => ({ ...f, source_url: e.target.value }))}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
          <textarea
            placeholder="Notes (optional)"
            value={form.notes}
            onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
            rows={2}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
        <div className="flex gap-2 mt-4">
          <button onClick={onClose} className="flex-1 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50">Cancel</button>
          <button
            onClick={() => { if (form.company_name && form.role_title) { onAdd(form); onClose() } }}
            className="flex-1 py-2 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-700"
          >
            Add
          </button>
        </div>
      </div>
    </div>
  )
}

export default function PipelineBoard({ onNavigate }: { onNavigate: (tab: Tab) => void }) {
  const queryClient = useQueryClient()
  const [showAdd, setShowAdd] = useState(false)

  const { data: board, isLoading } = useQuery<PipelineBoard>({
    queryKey: ['kanban'],
    queryFn: () => applicationsApi.kanban().then(r => r.data),
  })

  const addMutation = useMutation({
    mutationFn: (data: Partial<Application>) => applicationsApi.create(data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['kanban'] }),
  })

  if (isLoading) return (
    <div className="flex items-center justify-center h-64 text-gray-400">Loading pipeline...</div>
  )

  const totalApps = board ? Object.values(board).reduce((sum, apps) => sum + apps.length, 0) : 0

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Job Pipeline</h1>
          <p className="text-sm text-gray-500 mt-1">{totalApps} applications tracked</p>
        </div>
        <button
          onClick={() => setShowAdd(true)}
          className="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
        >
          + Add Application
        </button>
      </div>

      <div className="flex gap-4 overflow-x-auto pb-4">
        {COLUMNS.map(col => {
          const apps = board?.[col.key] ?? []
          const visible = apps.slice(0, LANE_LIMIT)
          const overflow = apps.length - visible.length
          return (
            <div key={col.key} className="shrink-0 w-64">
              <div className={`rounded-xl border-2 ${col.color} p-3 min-h-96`}>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="font-semibold text-sm text-gray-700 capitalize">{col.label}</h3>
                  <span className="bg-white text-gray-600 text-xs font-medium px-2 py-0.5 rounded-full border border-gray-200">
                    {apps.length}
                  </span>
                </div>
                <div className="space-y-2">
                  {visible.map(app => (
                    <ApplicationCard key={app.id} app={app} />
                  ))}
                  {apps.length === 0 && (
                    <p className="text-center text-gray-400 text-xs py-8">No applications</p>
                  )}
                </div>
                {overflow > 0 && (
                  <button
                    onClick={() => onNavigate(col.tab)}
                    className="mt-3 w-full text-xs text-indigo-600 hover:text-indigo-800 font-medium py-1.5 rounded-lg hover:bg-indigo-50 transition-colors"
                  >
                    View all ({apps.length})
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {showAdd && (
        <AddApplicationModal
          onClose={() => setShowAdd(false)}
          onAdd={(data) => addMutation.mutate(data)}
        />
      )}
    </div>
  )
}
