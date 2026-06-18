import { useQuery } from '@tanstack/react-query'
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


export default function PipelineBoard({ onNavigate }: { onNavigate: (tab: Tab) => void }) {
  const { data: board, isLoading } = useQuery<PipelineBoard>({
    queryKey: ['kanban'],
    queryFn: () => applicationsApi.kanban().then(r => r.data),
  })

  if (isLoading) return (
    <div className="flex items-center justify-center h-64 text-gray-400">Loading pipeline...</div>
  )

  const totalApps = board ? Object.values(board).reduce((sum, apps) => sum + apps.length, 0) : 0

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Job Pipeline</h1>
        <p className="text-sm text-gray-500 mt-1">{totalApps} applications tracked</p>
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

    </div>
  )
}
