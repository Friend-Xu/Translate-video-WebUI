import { useState, useCallback, useEffect, useRef } from 'react'
import { PipelineConfig, DEFAULT_CONFIG } from '../types'

const TRANSIENT_KEYS = new Set(['videoPath', 'outputPath', 'forceRetry', 'defaultVideoDir'])

function stripTransient(config: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(config)) {
    if (!TRANSIENT_KEYS.has(k)) out[k] = v
  }
  return out
}

/** Derive output dir from video path: {dir}/{name}_out/ */
function deriveOutputPath(videoPath: string): string {
  if (!videoPath) return ''
  const lastSlash = Math.max(videoPath.lastIndexOf('/'), videoPath.lastIndexOf('\\'))
  const dir = videoPath.substring(0, lastSlash)
  const file = videoPath.substring(lastSlash + 1)
  const dot = file.lastIndexOf('.')
  const name = dot > 0 ? file.substring(0, dot) : file
  return `${dir}/${name}_out`
}

export function useConfig() {
  const [config, setConfig] = useState<PipelineConfig>(DEFAULT_CONFIG)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Load system info + saved config on mount
  useEffect(() => {
    Promise.all([
      fetch('/api/system/info').then(r => r.ok ? r.json() : null),
      fetch('/api/config').then(r => r.ok ? r.json() : null),
    ]).then(([sysInfo, serverConfig]) => {
      setConfig(prev => {
        let next = { ...prev }
        if (sysInfo) {
          next.concurrency = sysInfo.recommendedConcurrency
          next.device = sysInfo.hasGpu ? 'cuda' : 'cpu'
          next.defaultVideoDir = sysInfo.defaultVideoDir
        }
        if (serverConfig) {
          next = { ...next, ...serverConfig }
        }
        next.videoPath = prev.videoPath
        next.outputPath = prev.outputPath
        next.forceRetry = false
        return next
      })
    }).catch(() => {})
  }, [])

  const updateConfig = useCallback(<K extends keyof PipelineConfig>(
    key: K,
    value: PipelineConfig[K]
  ) => {
    setConfig(prev => {
      const next = { ...prev, [key]: value }
      if (key === 'videoPath' && typeof value === 'string') {
        next.outputPath = deriveOutputPath(value)
      }

      // Debounced auto-save (skip transient fields)
      if (saveTimer.current) clearTimeout(saveTimer.current)
      saveTimer.current = setTimeout(() => {
        fetch('/api/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(stripTransient(next as unknown as Record<string, unknown>)),
        }).catch(() => {})
      }, 2000)

      return next
    })
  }, [])

  const resetConfig = useCallback(() => {
    setConfig(DEFAULT_CONFIG)
  }, [])

  return { config, updateConfig, resetConfig }
}
