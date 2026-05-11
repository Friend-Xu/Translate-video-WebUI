import { useState, useCallback } from 'react'
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, TextField, Typography, Box, Stack, Alert, Chip,
  LinearProgress,
} from '@mui/material'
import VideocamIcon from '@mui/icons-material/VideocamRounded'
import AudiotrackIcon from '@mui/icons-material/AudiotrackRounded'
import MergeTypeIcon from '@mui/icons-material/MergeTypeRounded'
import CheckCircleIcon from '@mui/icons-material/CheckCircleRounded'
import WarningIcon from '@mui/icons-material/WarningRounded'
import ErrorIcon from '@mui/icons-material/ErrorRounded'
import FolderOpenIcon from '@mui/icons-material/FolderOpenRounded'
import { FilePickerDialog } from './FilePickerDialog'

interface Defect {
  type: string
  name: string
  severity: string
  details: string
  action: string
  container_duration: number
  audio_duration: number
  drift_pct: number
}

interface AnalysisResult {
  video_path: string
  has_audio: boolean
  video_container_duration: number
  video_decoded_duration: number
  video_internal_drift: number
  audio_container_duration: number
  audio_decoded_duration: number
  audio_internal_drift: number
  duration_match: boolean
  duration_diff_sec: number
  defects: Defect[]
  companion_audio: string
  suggested_action: string
  error?: string
}

interface MuxResult {
  output_path: string
  output_name: string
  size_mb: number
  success: boolean
}

interface MediaMuxDialogProps {
  open: boolean
  onClose: () => void
  onSuccess: (msg: string) => void
  initialPath?: string
}

const AUDIO_EXT = ['.mp3', '.m4a', '.wav', '.opus', '.aac', '.ogg', '.flac', '.wma', '.webm']
const VIDEO_EXT = ['.mp4']

function fmtDuration(sec: number): string {
  if (!sec || sec <= 0) return '-'
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

type Phase = 'idle' | 'analyzing' | 'merging'

export function MediaMuxDialog({ open, onClose, onSuccess, initialPath }: MediaMuxDialogProps) {
  const [videoPath, setVideoPath] = useState('')
  const [audioPath, setAudioPath] = useState('')
  const [phase, setPhase] = useState<Phase>('idle')
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [muxResult, setMuxResult] = useState<MuxResult | null>(null)
  const [pickerTarget, setPickerTarget] = useState<'video' | 'audio' | null>(null)

  const resetAll = useCallback(() => {
    setVideoPath('')
    setAudioPath('')
    setPhase('idle')
    setResult(null)
    setMuxResult(null)
  }, [])

  const handleClose = () => {
    if (phase !== 'idle') return  // prevent close while processing
    resetAll()
    onClose()
  }

  const handleFilePicked = (path: string) => {
    if (pickerTarget === 'video') {
      setVideoPath(path)
      setResult(null)
      setMuxResult(null)
    } else if (pickerTarget === 'audio') {
      setAudioPath(path)
      setResult(null)
      setMuxResult(null)
    }
    setPickerTarget(null)
  }

  const handleMerge = async () => {
    if (!videoPath) return

    // Phase 1: analyze
    setPhase('analyzing')
    setResult(null)
    setMuxResult(null)

    let analysis: AnalysisResult
    try {
      const res = await fetch('/api/media/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ video_path: videoPath, audio_path: audioPath }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        setResult({
          video_path: videoPath, has_audio: false, video_container_duration: 0,
          video_decoded_duration: 0, video_internal_drift: 0,
          audio_container_duration: 0, audio_decoded_duration: 0, audio_internal_drift: 0,
          duration_match: true, duration_diff_sec: 0,
          defects: [], companion_audio: '', suggested_action: 'error',
          error: (err as any).detail || '分析失败',
        })
        setPhase('idle')
        return
      }
      analysis = await res.json()
      setResult(analysis)

      // Auto-fill companion audio
      if (analysis.companion_audio && !audioPath) {
        setAudioPath(analysis.companion_audio)
      }

      // Check if merge can proceed
      if (analysis.suggested_action === 'ok') {
        setPhase('idle')
        onSuccess('视频已有音频流，无需合并')
        return
      }
      if (analysis.suggested_action === 'no_audio') {
        setPhase('idle')
        return
      }
    } catch (e: any) {
      setResult({
        video_path: videoPath, has_audio: false, video_container_duration: 0,
        video_decoded_duration: 0, video_internal_drift: 0,
        audio_container_duration: 0, audio_decoded_duration: 0, audio_internal_drift: 0,
        duration_match: true, duration_diff_sec: 0,
        defects: [], companion_audio: '', suggested_action: 'error',
        error: e.message || '分析请求失败',
      })
      setPhase('idle')
      return
    }

    // Determine effective audio path (may have been auto-detected)
    const effectiveAudio = audioPath || analysis.companion_audio
    if (!effectiveAudio) {
      setPhase('idle')
      return
    }

    // Phase 2: merge
    setPhase('merging')
    try {
      const res = await fetch('/api/media/mux', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ video_path: videoPath, audio_path: effectiveAudio }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        onSuccess(`合并失败: ${(err as any).detail || res.statusText}`)
        setPhase('idle')
        return
      }
      const data: MuxResult = await res.json()
      setMuxResult(data)
      setPhase('idle')
      onSuccess(`合并完成: ${data.output_name} (${data.size_mb}MB)`)
    } catch (e: any) {
      onSuccess(`合并失败: ${e.message}`)
      setPhase('idle')
    }
  }

  const handleOpenFolder = () => {
    const target = muxResult?.output_path || videoPath
    if (target) {
      fetch(`/api/files/open-folder?video_path=${encodeURIComponent(target)}`, { method: 'POST' }).catch(() => {})
    }
  }

  const busy = phase !== 'idle'
  const canMerge = !!videoPath && !busy

  const pickerDir = () => {
    const ref = pickerTarget === 'audio' ? (audioPath || videoPath) : videoPath
    if (!ref) return initialPath
    return ref.substring(0, ref.lastIndexOf('\\'))
  }

  const buttonLabel = () => {
    if (phase === 'analyzing') return '正在分析音频流、时长、缺陷...'
    if (phase === 'merging') return '正在合并...'
    return '开始合并'
  }

  return (
    <>
      <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
        <DialogTitle>合并音视频</DialogTitle>
        <DialogContent sx={{ p: 2 }}>
          <Stack spacing={2.5}>
            <Typography variant="body2" color="text.secondary">
              适用于 DASH 等下载后视频和音频分离的情况。选择视频和音频后点击合并，系统自动检测时长、音频流和缺陷。
            </Typography>

            <Box>
              <Typography variant="caption" fontWeight={600} mb={0.5} display="block">视频文件</Typography>
              <Stack direction="row" spacing={1}>
                <TextField
                  size="small"
                  fullWidth
                  placeholder="选择或粘贴视频路径..."
                  value={videoPath}
                  disabled={busy}
                  onChange={e => { setVideoPath(e.target.value); setResult(null); setMuxResult(null) }}
                  slotProps={{ input: { startAdornment: <VideocamIcon sx={{ mr: 0.5, color: 'text.secondary', fontSize: 18 }} /> } }}
                />
                <Button variant="outlined" size="small" disabled={busy} onClick={() => setPickerTarget('video')} sx={{ minWidth: 80, flexShrink: 0 }}>
                  浏览
                </Button>
              </Stack>
            </Box>

            <Box>
              <Typography variant="caption" fontWeight={600} mb={0.5} display="block">音频文件</Typography>
              <Stack direction="row" spacing={1}>
                <TextField
                  size="small"
                  fullWidth
                  placeholder="选择、粘贴音频路径、留空则自动检测..."
                  value={audioPath}
                  disabled={busy}
                  onChange={e => { setAudioPath(e.target.value); setResult(null); setMuxResult(null) }}
                  slotProps={{ input: { startAdornment: <AudiotrackIcon sx={{ mr: 0.5, color: 'text.secondary', fontSize: 18 }} /> } }}
                />
                <Button variant="outlined" size="small" disabled={busy} onClick={() => setPickerTarget('audio')} sx={{ minWidth: 80, flexShrink: 0 }}>
                  浏览
                </Button>
              </Stack>
            </Box>

            <Box>
              <Button
                variant="contained"
                color="success"
                size="large"
                fullWidth
                startIcon={busy ? undefined : <MergeTypeIcon />}
                onClick={handleMerge}
                disabled={!canMerge}
              >
                {buttonLabel()}
              </Button>
            </Box>

            {busy && <LinearProgress />}

            {/* Analysis result */}
            {result && !result.error && (
              <Box sx={{ bgcolor: 'action.hover', borderRadius: 1, p: 1.5 }}>
                <Typography variant="subtitle2" mb={1}>检测结果</Typography>
                <Stack spacing={0.75}>
                  <Stack direction="row" spacing={1} alignItems="center">
                    {result.has_audio ? (
                      <CheckCircleIcon color="success" sx={{ fontSize: 18 }} />
                    ) : (
                      <WarningIcon color="warning" sx={{ fontSize: 18 }} />
                    )}
                    <Typography variant="body2">
                      {result.has_audio ? '视频包含音频流' : '视频无音频流'}
                    </Typography>
                  </Stack>

                  <Box sx={{ ml: 3.5 }}>
                    <Stack spacing={0.5}>
                      <Typography variant="caption" color="text.secondary">
                        视频 容器: {fmtDuration(result.video_container_duration)} | 解码: {fmtDuration(result.video_decoded_duration)}
                        {result.video_internal_drift > 0.05 && ` (偏差 ${result.video_internal_drift.toFixed(1)}s)`}
                      </Typography>
                      {result.audio_container_duration > 0 && (
                        <Typography variant="caption" color="text.secondary">
                          音频 容器: {fmtDuration(result.audio_container_duration)} | 解码: {fmtDuration(result.audio_decoded_duration)}
                          {result.audio_internal_drift > 0.05 && ` (偏差 ${result.audio_internal_drift.toFixed(1)}s)`}
                        </Typography>
                      )}
                    </Stack>
                  </Box>

                  {result.audio_container_duration > 0 && (
                    <Stack direction="row" spacing={1} alignItems="center">
                      {result.duration_match ? (
                        <CheckCircleIcon color="success" sx={{ fontSize: 18 }} />
                      ) : (
                        <ErrorIcon color="error" sx={{ fontSize: 18 }} />
                      )}
                      <Typography variant="body2">
                        {result.duration_match
                          ? `对比一致 (解码差 ${result.duration_diff_sec.toFixed(1)}s)`
                          : `对比偏差 ${result.duration_diff_sec.toFixed(1)}s — 可能存在同步问题`
                        }
                      </Typography>
                    </Stack>
                  )}

                  {result.companion_audio && !audioPath && (
                    <Box sx={{ ml: 3.5 }}>
                      <Chip
                        label={`自动检测到音频: ${result.companion_audio.split(/[/\\]/).pop()}`}
                        size="small" color="info" variant="outlined"
                      />
                    </Box>
                  )}

                  {result.defects.map((d, i) => (
                    <Alert key={i} severity={d.severity === 'severe' ? 'error' : 'warning'} sx={{ py: 0 }}>
                      [{d.type}] {d.name}
                      {d.drift_pct > 0 && ` — 漂移 ${d.drift_pct}%`}
                      {d.action && <> | 建议: {d.action}</>}
                    </Alert>
                  ))}

                  <Stack direction="row" spacing={1} alignItems="center">
                    {result.suggested_action === 'ok' ? (
                      <CheckCircleIcon color="success" sx={{ fontSize: 18 }} />
                    ) : result.suggested_action === 'mux' || result.suggested_action === 'mux_drift' ? (
                      <MergeTypeIcon color="primary" sx={{ fontSize: 18 }} />
                    ) : (
                      <ErrorIcon color="error" sx={{ fontSize: 18 }} />
                    )}
                    <Typography variant="body2" fontWeight={500}>
                      {result.suggested_action === 'ok' && '无需操作，视频正常'}
                      {result.suggested_action === 'mux' && '已自动合并'}
                      {result.suggested_action === 'mux_drift' && '已合并，但时长有偏差，注意检查同步'}
                      {result.suggested_action === 'no_audio' && '未找到音频文件，请手动指定'}
                    </Typography>
                  </Stack>
                </Stack>
              </Box>
            )}

            {result?.error && <Alert severity="error">{result.error}</Alert>}

            {muxResult && (
              <Alert severity="success" sx={{ py: 1 }}>
                <Typography variant="body2" fontWeight={600}>
                  合并完成: {muxResult.output_name}
                </Typography>
                <Typography variant="caption">
                  大小: {muxResult.size_mb} MB | 路径: {muxResult.output_path}
                </Typography>
                <Box mt={0.5}>
                  <Button size="small" startIcon={<FolderOpenIcon />} onClick={handleOpenFolder}>
                    打开所在目录
                  </Button>
                </Box>
              </Alert>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose} disabled={busy}>{muxResult ? '关闭' : '取消'}</Button>
        </DialogActions>
      </Dialog>

      {pickerTarget && (
        <FilePickerDialog
          open
          title={pickerTarget === 'video' ? '选择视频文件' : '选择音频文件'}
          onSelect={handleFilePicked}
          onClose={() => setPickerTarget(null)}
          initialPath={pickerDir()}
          acceptExtensions={pickerTarget === 'video' ? VIDEO_EXT : AUDIO_EXT}
        />
      )}
    </>
  )
}
