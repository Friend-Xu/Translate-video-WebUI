import { useState, useCallback, useEffect } from 'react'
import { PipelineConfig, DEFAULT_CONFIG, type SystemInfo } from '../types'

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

  // Fetch system info once on mount to set intelligent defaults
  useEffect(() => {
    fetch('/api/system/info')
      .then(r => r.ok ? r.json() : null)
      .then((info: SystemInfo | null) => {
        if (!info) return
        setConfig(prev => ({
          ...prev,
          concurrency: info.recommendedConcurrency,
          device: info.hasGpu ? 'gpu' : 'cpu',
          defaultVideoDir: info.defaultVideoDir,
        }))
      })
      .catch(() => { /* server not ready, keep defaults */ })
  }, [])

  const updateConfig = useCallback(<K extends keyof PipelineConfig>(
    key: K,
    value: PipelineConfig[K]
  ) => {
    setConfig(prev => {
      const next = { ...prev, [key]: value }
      // Auto-derive output path when video changes
      if (key === 'videoPath' && typeof value === 'string') {
        next.outputPath = deriveOutputPath(value)
      }
      return next
    })
  }, [])

  const resetConfig = useCallback(() => {
    setConfig(DEFAULT_CONFIG)
  }, [])

  return { config, updateConfig, resetConfig }
}
