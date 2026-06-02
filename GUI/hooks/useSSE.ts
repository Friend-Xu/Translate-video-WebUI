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
  apiBase: string = '/api/core/pipeline',
  onEvent?: (type: string, payload: Record<string, unknown>) => void,
) {
  const sourceRef = useRef<EventSource | null>(null)
  const [connectionState, setConnectionState] = useState<ConnectionState>('closed')

  // Keep latest callbacks in refs to avoid rebuilding EventSource
  const onLogRef = useRef(onLog)
  const onDoneRef = useRef(onDone)
  const onClearRef = useRef(onClear)
  onLogRef.current = onLog
  onDoneRef.current = onDone
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

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
        // Pass structured event fields to parent via onEvent callback
        if (data.event && onEventRef.current) {
          onEventRef.current(data.event as string, {
            type: data.event as string,
            stage: data.stage || '',
            stage_label: data.stage_label || '',
            current_item: data.current_item ?? 0,
            total_items: data.total_items ?? 0,
            percent: data.percent ?? 0,
            message: data.message || '',
          })
        }
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
