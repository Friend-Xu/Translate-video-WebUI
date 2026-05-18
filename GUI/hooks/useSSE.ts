import { useEffect, useRef, useCallback } from 'react'
import type { LogEntry } from '../types'

export function useSSE(
  jobId: string | null,
  onLog: (entry: LogEntry) => void,
  onDone: (status: string) => void,
  onClear?: () => void,
) {
  const sourceRef = useRef<EventSource | null>(null)

  const disconnect = useCallback(() => {
    sourceRef.current?.close()
    sourceRef.current = null
  }, [])

  useEffect(() => {
    if (!jobId) return

    onClear?.()

    const es = new EventSource(`/api/pipeline/${jobId}/logs`)
    sourceRef.current = es

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        const raw: string = data.message || ''
        const match = raw.match(/^\[(\w+)\]\s*(.*)/)
        let level = (match?.[1] || 'INFO') as LogEntry['level']
        let message = match?.[2] || raw
        if (message.includes('[STAGE]')) {
          level = 'STAGE'
          message = message.replace('[STAGE] ', '')
        }
        const timestamp = new Date().toLocaleTimeString()
        onLog({ level, message, timestamp })
      } catch {
        onLog({ level: 'INFO', message: event.data, timestamp: new Date().toLocaleTimeString() })
      }
    }

    es.addEventListener('done', (event) => {
      try {
        const data = JSON.parse(event.data)
        onDone(data.status)
      } catch {
        onDone('completed')
      }
      disconnect()
    })

    es.onerror = () => {
      // Let EventSource auto-reconnect; disconnect only via 'done' event.
      // Calling disconnect() here defeats the browser's built-in retry,
      // permanently losing logs after a transient connection drop.
    }

    return disconnect
  }, [jobId, onLog, onDone, disconnect])
}
