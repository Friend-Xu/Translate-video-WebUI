import { useEffect, useRef, useCallback, useState } from 'react'
import type { LogEntry } from '../types'

export type ConnectionState = 'connected' | 'reconnecting' | 'closed'

let _sseId = 1000000
function sseNextId(): number { return _sseId++ }

export function useSSE(
  jobId: string | null,
  onLog: (entry: LogEntry) => void,
  onDone: (status: string) => void,
  onClear?: () => void,
  apiBase: string = '/api/pipeline',
) {
  const sourceRef = useRef<EventSource | null>(null)
  const [connectionState, setConnectionState] = useState<ConnectionState>('closed')

  // Keep latest callbacks in refs to avoid rebuilding EventSource
  const onLogRef = useRef(onLog)
  const onDoneRef = useRef(onDone)
  const onClearRef = useRef(onClear)
  onLogRef.current = onLog
  onDoneRef.current = onDone
  onClearRef.current = onClear

  const disconnect = useCallback(() => {
    sourceRef.current?.close()
    sourceRef.current = null
    setConnectionState('closed')
  }, [])

  useEffect(() => {
    if (!jobId) {
      setConnectionState('closed')
      return
    }

    onClearRef.current?.()

    const es = new EventSource(`${apiBase}/${jobId}/logs`)
    sourceRef.current = es

    es.onopen = () => setConnectionState('connected')

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        const raw: string = data.message || ''
        const match = raw.match(/^\[(\w+)\s*\]\s*(.*)/)
        let level = (match?.[1] || 'INFO') as LogEntry['level']
        let message = match?.[2] || raw
        if (message.includes('[STAGE]')) {
          level = 'STAGE'
          message = message.replace('[STAGE] ', '')
        }
        const timestamp = data.ts || new Date().toLocaleTimeString()
        onLogRef.current({ _id: sseNextId(), level, message, timestamp })
      } catch {
        onLogRef.current({ _id: sseNextId(), level: 'INFO', message: event.data, timestamp: new Date().toLocaleTimeString() })
      }
    }

    es.addEventListener('done', (event) => {
      try {
        const data = JSON.parse((event as MessageEvent).data)
        onDoneRef.current(data.status)
      } catch {
        onDoneRef.current('completed')
      }
      disconnect()
    })

    es.onerror = () => {
      disconnect()
    }

    return disconnect
  }, [jobId, apiBase, disconnect])

  return { connectionState }
}
