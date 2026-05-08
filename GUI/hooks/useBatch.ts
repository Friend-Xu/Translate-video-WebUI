import { useState, useCallback, useRef } from 'react'
import type { BatchStatus, PipelineConfig } from '../types'

const API = '/api/batch'

export function useBatch() {
  const [batch, setBatch] = useState<BatchStatus>({
    batch_id: null,
    status: 'idle',
    current_index: 0,
    total_count: 0,
    completed_count: 0,
    failed_count: 0,
    videos: [],
    logs: [],
    created_at: '',
  })
  const [activeVideoJobId, setActiveVideoJobId] = useState<string | null>(null)
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  const startPolling = useCallback((batchId: string) => {
    if (pollTimer.current) clearInterval(pollTimer.current)
    pollTimer.current = setInterval(async () => {
      try {
        const res = await fetch(`${API}/${batchId}`)
        if (!res.ok) { clearInterval(pollTimer.current!); return }
        const data: BatchStatus = await res.json()
        setBatch(data)
        if (data.status !== 'running') {
          clearInterval(pollTimer.current!)
        }
      } catch { /* ignore network errors */ }
    }, 2000)
  }, [])

  const startBatch = useCallback(async (videoPaths: string[], config: PipelineConfig) => {
    const configPayload: Record<string, unknown> = {
      lang: config.lang,
      model: config.model,
      device: config.device,
      engine: config.engine,
      skip_extract: !config.enableExtract,
      skip_translate: !config.enableTranslate,
      skip_tts: !config.enableTTS,
      skip_defect_check: !config.enableDefectCheck,
      skip_demucs: !config.enableDemucs,
      force: config.forceRetry,
      num_workers: config.numWorkers,
      caption_font: config.captionFont,
      caption_font_size_mode: config.captionFontSizeMode,
      caption_font_size: config.captionFontSize,
      caption_font_color: config.captionFontColor,
      caption_stroke_width: config.captionStrokeWidth,
      caption_stroke_color: config.captionStrokeColor,
      caption_bg_color: config.captionBgColor,
      caption_alignment: config.captionAlignment,
      caption_position: config.captionPosition,
      caption_max_lines: config.captionMaxLines,
      caption_max_font_size: config.captionMaxFontSize,
      caption_font_size_factor: config.captionFontSizeFactor,
      caption_width_ratio: config.captionWidthRatio,
      caption_optimize: config.enableSubtitleOptimization,
    }

    const res = await fetch(`${API}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_paths: videoPaths, config: configPayload }),
    })
    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.detail || '批次启动失败')
    }
    const { batch_id, video_count } = await res.json()
    setBatch(prev => ({
      ...prev,
      batch_id,
      status: 'running',
      total_count: video_count,
      videos: [],
    }))
    startPolling(batch_id)
    return batch_id
  }, [startPolling])

  const cancelBatch = useCallback(async () => {
    if (!batch.batch_id) return
    await fetch(`${API}/${batch.batch_id}/cancel`, { method: 'POST' })
    setBatch(prev => ({ ...prev, status: 'cancelled' }))
    if (pollTimer.current) clearInterval(pollTimer.current)
  }, [batch.batch_id])

  const skipCurrent = useCallback(async () => {
    if (!batch.batch_id) return
    await fetch(`${API}/${batch.batch_id}/skip`, { method: 'POST' })
  }, [batch.batch_id])

  const viewVideoLogs = useCallback((jobId: string | null) => {
    setActiveVideoJobId(jobId)
  }, [])

  const resetBatch = useCallback(() => {
    setBatch({
      batch_id: null, status: 'idle', current_index: 0,
      total_count: 0, completed_count: 0, failed_count: 0,
      videos: [], logs: [], created_at: '',
    })
    setActiveVideoJobId(null)
    if (pollTimer.current) clearInterval(pollTimer.current)
  }, [])

  return {
    batch,
    activeVideoJobId,
    startBatch,
    cancelBatch,
    skipCurrent,
    viewVideoLogs,
    resetBatch,
  }
}
