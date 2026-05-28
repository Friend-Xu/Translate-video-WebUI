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

    onClear?.()

    const es = new EventSource(`${apiBase}/${jobId}/logs`)
    sourceRef.current = es

    es.onopen = () => {
      setConnectionState('connected')
    }

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
        onLog({ _id: sseNextId(), level, message, timestamp })
      } catch {
        onLog({ _id: sseNextId(), level: 'INFO', message: event.data, timestamp: new Date().toLocaleTimeString() })
      }
    }

    es.addEventListener('done', (event) => {
      try {
        const data = JSON.parse((event as MessageEvent).data)
        onDone(data.status)
      } catch {
        onDone('completed')
      }
      disconnect()
    })

    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        setConnectionState('closed')
      } else {
        setConnectionState('reconnecting')
      }
    }

    return disconnect
  }, [jobId, onLog, onDone, disconnect])

  return { connectionState }
}
