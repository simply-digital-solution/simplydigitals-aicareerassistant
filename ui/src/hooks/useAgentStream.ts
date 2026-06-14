import { useState, useRef, useCallback } from 'react'

export type StreamStatus = 'idle' | 'streaming' | 'done' | 'error'

interface UseAgentStreamOptions<T> {
  endpoint: string
  onResult?: (result: T) => void
}

interface UseAgentStreamReturn<T> {
  status: StreamStatus
  chunks: string
  result: T | null
  meta: Record<string, unknown> | null
  error: string | null
  run: (body: unknown) => Promise<void>
  reset: () => void
}

export function useAgentStream<T>({
  endpoint,
  onResult,
}: UseAgentStreamOptions<T>): UseAgentStreamReturn<T> {
  const [status, setStatus] = useState<StreamStatus>('idle')
  const [chunks, setChunks] = useState('')
  const [result, setResult] = useState<T | null>(null)
  const [meta, setMeta] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const reset = useCallback(() => {
    abortRef.current?.abort()
    setStatus('idle')
    setChunks('')
    setResult(null)
    setMeta(null)
    setError(null)
  }, [])

  const run = useCallback(
    async (body: unknown) => {
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      setStatus('streaming')
      setChunks('')
      setResult(null)
      setMeta(null)
      setError(null)

      const email = localStorage.getItem('user_email')

      try {
        const resp = await fetch(`/api/v1${endpoint}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(email ? { 'X-User-Email': email } : {}),
          },
          body: JSON.stringify(body),
          signal: controller.signal,
        })

        if (!resp.ok) {
          const text = await resp.text()
          throw new Error(text || `HTTP ${resp.status}`)
        }

        const reader = resp.body!.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''

          for (const line of lines) {
            if (line.startsWith('event: ')) {
              // event type on this line, data on next — handled below
            } else if (line.startsWith('data: ')) {
              // Find the event type from the last "event:" line in this block
              const eventLine = lines[lines.indexOf(line) - 1] ?? ''
              const eventType = eventLine.startsWith('event: ')
                ? eventLine.slice(7).trim()
                : 'message'

              const raw = line.slice(6)
              try {
                const parsed = JSON.parse(raw)
                if (eventType === 'chunk') {
                  setChunks((prev) => prev + (parsed.text ?? ''))
                } else if (eventType === 'result') {
                  setResult(parsed as T)
                  onResult?.(parsed as T)
                } else if (eventType === 'meta') {
                  setMeta(parsed)
                } else if (eventType === 'error') {
                  setError(parsed.error ?? 'Agent error')
                }
              } catch {
                // non-JSON data line — skip
              }
            }
          }
        }

        setStatus('done')
      } catch (err: unknown) {
        if (err instanceof Error && err.name === 'AbortError') return
        const isConnectionError = err instanceof TypeError && (
          err.message === 'Failed to fetch' ||
          err.message.includes('NetworkError') ||
          err.message.includes('net::ERR')
        )
        setError(isConnectionError
          ? 'Cannot connect to server. Make sure the backend is running.'
          : err instanceof Error ? err.message : 'Unknown error')
        setStatus('error')
      }
    },
    [endpoint, onResult],
  )

  return { status, chunks, result, meta, error, run, reset }
}
