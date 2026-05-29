import { useState, useCallback, useRef } from 'react'
import type { PipelineConfig, PipelineStatus, LogEntry } from '../types'

const API_OLD = '/api/pipeline'
const MAX_WINDOW = 500      // max loaded entries in memory
const TAIL_LIMIT = 200       // initial fetch size
const PAGE_LIMIT = 200       // scroll-up page size

let _nextId = 1              // global monotonic counter for unique keys

function nextId(): number { return _nextId++ }

/** Parse a raw log line into a LogEntry. Mirrors the parsing in useSSE.ts. */
function parseLine(raw: string): LogEntry {
  const match = raw.match(/^\[(\w+)\s*\]\s*(.*)/)
  let level: LogEntry['level'] = (match?.[1] || 'INFO') as LogEntry['level']
  let message = match?.[2] || raw
  if (message.includes('[STAGE]')) {
    level = 'STAGE'
    message = message.replace('[STAGE] ', '')
  }
  return { _id: nextId(), level, message, timestamp: new Date().toLocaleTimeString() }
}

export function usePipeline(apiBase: string = API_OLD) {
  const [status, setStatus] = useState<PipelineStatus>({
    state: 'idle', progress: 0, currentStep: '就绪', jobId: null, detail: '',
  })
  const [logs, setLogs] = useState<LogEntry[]>([])

  // Ref to avoid closure stale-value issues with jobId in cancelPipeline
  const jobIdRef = useRef<string | null>(null)

  const _setStatusAndRef = useCallback((updater: PipelineStatus | ((prev: PipelineStatus) => PipelineStatus)) => {
    setStatus(prev => {
      const next = typeof updater === 'function' ? updater(prev) : updater
      jobIdRef.current = next.jobId
      return next
    })
  }, [])

  // Virtual window: logs array is a sliding window into the full log file.
  // firstItemIndex is 0 during auto-follow; only set when prepending history.
  const firstItemIndex = useRef(0)
  // Global index of logs[0] in the full file — used internally for range lookups.
  // Always tracks the real position, even when firstItemIndex (the Virtuoso prop) is 0.
  const headGlobalIndex = useRef(0)
  const totalLines = useRef(0)
  const loadingOlder = useRef(false)

  const _buf = useRef<LogEntry[]>([])
  const _timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const flushBatch = useCallback(() => {
    if (_buf.current.length === 0) return
    setLogs(prev => {
      const next = [...prev, ..._buf.current]
      if (next.length > MAX_WINDOW) {
        const trim = next.length - MAX_WINDOW
        headGlobalIndex.current += trim
        // Don't change firstItemIndex during auto-follow — avoids Virtuoso jitter
        return next.slice(trim)
      }
      return next
    })
    totalLines.current += _buf.current.length
    _buf.current = []
    _timer.current = null
  }, [])

  const appendLog = useCallback((entry: LogEntry) => {
    // Ensure unique id
    if (entry._id == null) entry._id = nextId()
    _buf.current.push(entry)
    if (_timer.current === null) {
      _timer.current = setTimeout(flushBatch, 500)
    }
  }, [flushBatch])

  // Load initial tail from workspace log file
  const loadLogTail = useCallback(async (jobId: string) => {
    try {
      const res = await fetch(`${apiBase}/${jobId}/logs/tail?limit=${TAIL_LIMIT}`)
      if (!res.ok) return
      const data = await res.json()
      const entries: LogEntry[] = (data.lines || []).map(parseLine)
      if (entries.length > 0) {
        setLogs(entries)
        totalLines.current = data.total || entries.length
        headGlobalIndex.current = Math.max(0, totalLines.current - entries.length)
        firstItemIndex.current = 0  // auto-follow mode, don't expose to Virtuoso
      }
    } catch { /* ignore */ }
  }, [])

  // Load older entries when user scrolls to top (startReached)
  const loadOlderLogs = useCallback(async (jobId: string | null) => {
    if (!jobId || loadingOlder.current) return
    // Use headGlobalIndex (real position) for range lookup
    const before = headGlobalIndex.current
    if (before <= 0) return

    loadingOlder.current = true
    try {
      const res = await fetch(`${apiBase}/${jobId}/logs/range?before=${before}&limit=${PAGE_LIMIT}`)
      if (!res.ok) return
      const data = await res.json()
      const olderEntries: LogEntry[] = (data.lines || []).map(parseLine)
      if (olderEntries.length > 0) {
        setLogs(prev => {
          const next = [...olderEntries, ...prev]
          if (next.length > MAX_WINDOW) {
            return next.slice(0, MAX_WINDOW)
          }
          return next
        })
        const newFirst = data.first ?? (before - olderEntries.length)
        headGlobalIndex.current = newFirst
        firstItemIndex.current = newFirst  // set only when prepending
      }
    } catch { /* ignore */ }
    finally {
      loadingOlder.current = false
    }
  }, [])

  const handleDone = useCallback((finalStatus: string) => {
    flushBatch()
    _setStatusAndRef(prev => ({
      ...prev,
      state: finalStatus as PipelineStatus['state'],
      progress: finalStatus === 'completed' ? 100 : prev.progress,
      currentStep: finalStatus === 'completed' ? '处理完成' : '处理结束',
    }))
  }, [flushBatch, _setStatusAndRef])

  // Poll status while running
  const pollStatus = useCallback(async (jobId: string) => {
    const poll = async () => {
      try {
        const res = await fetch(`${apiBase}/${jobId}/status`)
        if (!res.ok) return
        const data = await res.json()
        setStatus(prev => ({
          ...prev,
          progress: data.progress,
          currentStep: data.current_step,
          detail: data.detail || '',
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
    firstItemIndex.current = 0
    headGlobalIndex.current = 0
    totalLines.current = 0
    setStatus({ state: 'running', progress: 5, currentStep: '启动中...', jobId: null, detail: '' })

    try {
      const res = await fetch(`${apiBase}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_path: config.videoPath,
          lang: config.lang,
          target_lang: config.targetLang,
          model: config.model,
          device: config.device,
          engine: config.engine,
          skip_extract: !config.enableExtract,
          skip_translate: !config.enableTranslate,
          skip_tts: !config.enableTTS,
          skip_defect_check: !config.enableDefectCheck,
          skip_demucs: !config.enableDemucs,
          skip_semantic_validation: !config.enableSemanticValidation,
          skip_naturalness_check: !config.enableNaturalnessCheck,
          force: config.forceRetry,
          num_workers: config.numWorkers,
          tts_workers: config.ttsWorkers,
          chattts_workers: config.chatttsWorkers,
          skip_align: !config.enableAlignment,
          align_lang: config.lang !== 'auto' ? config.lang : '',
          enable_speaker_diarization: config.enableSpeakerDiarization,
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
          chattts_speaker_seed: config.chatttsSpeakerSeed,
          chattts_model_source: config.chatttsModelSource,
          chattts_model_path: config.chatttsModelPath,
          chattts_speaker_pt: config.chatttsSpeakerPt,
          cosyvoice_tts_model_version: config.cosyvoiceTtsModelVersion,
          cosyvoice_tts_model_path: config.cosyvoiceTtsModelPath,
          cosyvoice_tts_prompt_audio: config.cosyvoiceTtsPromptAudio,
          cosyvoice_tts_prompt_text: config.cosyvoiceTtsPromptText,
          cosyvoice_tts_fp16: config.cosyvoiceTtsFp16,
          cosyvoice_tts_workers: config.cosyvoiceTtsWorkers,
          cosyvoice_tts_speed: config.cosyvoiceTtsSpeed,
          cosyvoice_tts_mode: config.cosyvoiceTtsMode,
          cosyvoice_tts_lang: config.cosyvoiceTtsLang,
          loudness_norm_enabled: config.loudnessNormEnabled,
          loudness_target_auto: config.loudnessTargetAuto,
          loudness_target_lufs: config.loudnessTargetLufs,
          enable_emotion: config.enableEmotionClone,
          voice_clone_engine: config.enableVoiceClone ? config.voiceCloneEngine : 'none',
          voice_clone_device: config.voiceCloneDevice,
          voice_clone_concurrency: config.voiceCloneConcurrency,
        }),
      })

      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || '启动失败')
      }

      const { job_id } = await res.json()
      _setStatusAndRef(prev => ({ ...prev, jobId: job_id, currentStep: '流水线运行中...' }))

      // Load initial log tail from file, then start polling + SSE
      await loadLogTail(job_id)
      pollStatus(job_id)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setStatus({ state: 'failed', progress: 0, currentStep: '启动失败', jobId: null, detail: '' })
      appendLog({ level: 'ERROR', message: msg, timestamp: new Date().toLocaleTimeString() })
    }
  }, [appendLog, pollStatus, loadLogTail])

  const cancelPipeline = useCallback(async () => {
    const jid = jobIdRef.current
    if (!jid) return
    try {
      await fetch(`${apiBase}/${jid}/cancel`, { method: 'POST' })
      _setStatusAndRef(prev => ({ ...prev, state: 'cancelled', currentStep: '已取消' }))
      appendLog({ level: 'WARN', message: '任务已取消', timestamp: new Date().toLocaleTimeString() })
    } catch { /* ignore */ }
  }, [appendLog, _setStatusAndRef])

  return {
    status,
    setStatus: _setStatusAndRef,
    logs,
    appendLog,
    handleDone,
    startPipeline,
    cancelPipeline,
    pollStatus,
    loadLogTail,
    logFirstIndex: firstItemIndex,
    logTotal: totalLines,
    loadOlderLogs,
  }
}
