import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { applicationsApi } from '../api/client'
import type { Application, PipelineBoard } from '../api/client'

const COLUMNS: { key: string; label: string; color: string }[] = [
  { key: 'researching', label: 'Researching', color: 'bg-gray-100 border-gray-300' },
  { key: 'applied', label: 'Applied', color: 'bg-blue-50 border-blue-300' },
  { key: 'interviewing', label: 'Interviewing', color: 'bg-yellow-50 border-yellow-300' },
  { key: 'offered', label: 'Offered', color: 'bg-green-50 border-green-300' },
  { key: 'rejected', label: 'Rejected', color: 'bg-red-50 border-red-300' },
]

function ScoreBadge({ score }: { score?: number }) {
  if (score == null) return null
  const pct = Math.round(score * 100)
  const color = pct >= 80 ? 'bg-green-100 text-green-800' : pct >= 60 ? 'bg-yellow-100 text-yellow-800' : 'bg-red-100 text-red-800'
  return <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${color}`}>{pct}%</span>
}

function ApplicationCard({ app, onMove }: { app: Application; onMove: (id: number, status: string) => void }) {
  const [showMenu, setShowMenu] = useState(false)
  const otherStatuses = COLUMNS.map(c => c.key).filter(s => s !== app.status)

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-3 shadow-sm hover:shadow-md transition-shadow cursor-pointer">
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

      <div className="mt-2 flex items-center justify-between">
        <span className="text-xs text-gray-400">{app.source ?? 'manual'}</span>
        <div className="relative">
          <button
            onClick={() => setShowMenu(!showMenu)}
            className="text-gray-400 hover:text-gray-600 text-xs px-2 py-0.5 rounded border border-gray-200 hover:border-gray-300"
          >
            Move →
          </button>
          {showMenu && (
            <div className="absolute right-0 top-6 bg-white border border-gray-200 rounded shadow-lg z-10 min-w-32">
              {otherStatuses.map(s => (
                <button
                  key={s}
                  onClick={() => { onMove(app.id, s); setShowMenu(false) }}
                  className="block w-full text-left px-3 py-1.5 text-xs hover:bg-gray-50 capitalize"
                >
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
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

export default function PipelineBoard() {
  const queryClient = useQueryClient()
  const [showAdd, setShowAdd] = useState(false)

  const { data: board, isLoading } = useQuery<PipelineBoard>({
    queryKey: ['kanban'],
    queryFn: () => applicationsApi.kanban().then(r => r.data),
  })

  const moveMutation = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) =>
      applicationsApi.move(id, status),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['kanban'] }),
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
                  {apps.map(app => (
                    <ApplicationCard
                      key={app.id}
                      app={app}
                      onMove={(id, status) => moveMutation.mutate({ id, status })}
                    />
                  ))}
                  {apps.length === 0 && (
                    <p className="text-center text-gray-400 text-xs py-8">No applications</p>
                  )}
                </div>
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
