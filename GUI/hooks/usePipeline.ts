import { useState, useCallback } from 'react'
import type { PipelineConfig, PipelineStatus, LogEntry } from '../types'

const API = '/api/pipeline'

export function usePipeline() {
  const [status, setStatus] = useState<PipelineStatus>({
    state: 'idle', progress: 0, currentStep: '就绪', jobId: null,
  })
  const [logs, setLogs] = useState<LogEntry[]>([])

  const appendLog = useCallback((entry: LogEntry) => {
    setLogs(prev => [...prev, entry])
  }, [])

  const handleDone = useCallback((finalStatus: string) => {
    setStatus(prev => ({
      ...prev,
      state: finalStatus as PipelineStatus['state'],
      progress: finalStatus === 'completed' ? 100 : prev.progress,
      currentStep: finalStatus === 'completed' ? '处理完成' : '处理结束',
    }))
  }, [])

  // Poll status while running
  const pollStatus = useCallback(async (jobId: string) => {
    const poll = async () => {
      try {
        const res = await fetch(`${API}/${jobId}/status`)
        if (!res.ok) return
        const data = await res.json()
        setStatus(prev => ({
          ...prev,
          progress: data.progress,
          currentStep: data.current_step,
        }))
        if (data.status === 'running') {
          setTimeout(poll, 2000)
        }
      } catch { /* ignore */ }
    }
    poll()
  }, [])

  const startPipeline = useCallback(async (config: PipelineConfig) => {
    setLogs([])
    setStatus({ state: 'running', progress: 5, currentStep: '启动中...', jobId: null })

    try {
      const res = await fetch(`${API}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_path: config.videoPath,
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
          tts_workers: config.ttsWorkers,
          skip_align: !config.enableAlignment,
          align_lang: config.lang !== 'auto' ? config.lang : '',
          // Caption rendering params (all 13)
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
          bgm_volume: config.bgmVolume,
        }),
      })

      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || '启动失败')
      }

      const { job_id } = await res.json()
      setStatus(prev => ({ ...prev, jobId: job_id, currentStep: '流水线运行中...' }))
      pollStatus(job_id)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setStatus({ state: 'failed', progress: 0, currentStep: '启动失败', jobId: null })
      appendLog({ level: 'ERROR', message: msg, timestamp: new Date().toLocaleTimeString() })
    }
  }, [appendLog, pollStatus])

  const cancelPipeline = useCallback(async () => {
    if (!status.jobId) return
    try {
      await fetch(`${API}/${status.jobId}/cancel`, { method: 'POST' })
      setStatus(prev => ({ ...prev, state: 'cancelled', currentStep: '已取消' }))
      appendLog({ level: 'WARN', message: '任务已取消', timestamp: new Date().toLocaleTimeString() })
    } catch { /* ignore */ }
  }, [status.jobId, appendLog])

  return {
    status,
    logs,
    appendLog,
    handleDone,
    startPipeline,
    cancelPipeline,
  }
}
