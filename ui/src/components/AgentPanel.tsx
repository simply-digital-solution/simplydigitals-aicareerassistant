/**
 * Shared shell for all agent panels.
 * Renders: title, a form (slot), a streaming output area, and a result slot.
 */
import type { StreamStatus } from '../hooks/useAgentStream'

interface Props {
  title: string
  description: string
  status: StreamStatus
  chunks: string
  error: string | null
  meta: Record<string, unknown> | null
  onReset: () => void
  form: React.ReactNode
  result: React.ReactNode
}

export default function AgentPanel({
  title,
  description,
  status,
  chunks,
  error,
  meta,
  onReset,
  form,
  result,
}: Props) {
  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-gray-900">{title}</h2>
        <p className="text-sm text-gray-500 mt-1">{description}</p>
      </div>

      {/* Input form — hidden once streaming starts */}
      {status === 'idle' && <div className="bg-white rounded-xl border border-gray-200 p-5">{form}</div>}

      {/* Streaming progress */}
      {status === 'streaming' && (
        <div className="bg-white rounded-xl border border-indigo-200 p-5 space-y-3">
          <div className="flex items-center gap-2 text-sm font-medium text-indigo-700">
            <span className="animate-pulse w-2 h-2 rounded-full bg-indigo-500 inline-block" />
            Thinking…
          </div>
          {chunks && (
            <pre className="text-xs text-gray-600 whitespace-pre-wrap font-mono max-h-48 overflow-y-auto bg-gray-50 rounded p-3">
              {chunks}
            </pre>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-start justify-between gap-4">
          <p className="text-sm text-red-700">{error}</p>
          <button onClick={onReset} className="text-xs text-red-500 hover:underline shrink-0">
            Try again
          </button>
        </div>
      )}

      {/* Result */}
      {status === 'done' && result && (
        <div className="space-y-4">
          {result}
          <div className="flex items-center justify-between">
            {meta && (
              <p className="text-xs text-gray-400">
                {meta.model as string} · {meta.output_tokens as number} tokens ·{' '}
                ${(meta.cost_usd as number).toFixed(4)}
              </p>
            )}
            <button
              onClick={onReset}
              className="text-xs text-indigo-500 hover:underline ml-auto"
            >
              Run again
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
