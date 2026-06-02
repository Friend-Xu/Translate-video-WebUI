import { useState, useMemo, useCallback } from 'react'
import {
  Box, Typography, Button, Chip, Dialog, DialogTitle, DialogContent,
  DialogActions, FormControl, InputLabel, Select, MenuItem, Switch,
  FormControlLabel, LinearProgress, Alert,
} from '@mui/material'
import FileDownloadIcon from '@mui/icons-material/FileDownloadRounded'
import CheckCircleIcon from '@mui/icons-material/CheckCircleRounded'
import WarningIcon from '@mui/icons-material/WarningRounded'
import ErrorIcon from '@mui/icons-material/ErrorRounded'
import SettingsIcon from '@mui/icons-material/SettingsRounded'
import { useAppStore } from '../../store/useAppStore'
import type { EventViewModel, ExportReadinessCheck, ExportReadinessWarning } from '../../types'

interface Props { events: EventViewModel[] }

function computeReadiness(
  events: EventViewModel[], draftsCount: number,
  unboundSpeakers: string[], failedBatchCount: number,
): ExportReadinessCheck {
  const warnings: ExportReadinessWarning[] = []
  const lowConfidence = events.filter(e => e.confidence < 0.7)
  if (lowConfidence.length > 0) {
    warnings.push({ severity: 'warning', message: `${lowConfidence.length} 个事件置信度低于 0.7`, action: { label: '在 Timeline 中修复', mode: 'timeline' } })
  }
  if (draftsCount > 0) {
    warnings.push({ severity: 'warning', message: `${draftsCount} 个补丁尚未应用`, action: { label: '查看补丁', mode: 'patch' } })
  }
  if (unboundSpeakers.length > 0) {
    warnings.push({ severity: 'warning', message: `${unboundSpeakers.length} 个声线未绑定`, action: { label: '绑定声线', mode: 'timeline' } })
  }
  if (failedBatchCount > 0) {
    warnings.push({ severity: 'error', message: `${failedBatchCount} 个批处理任务失败`, action: { label: '查看队列', mode: 'batch' } })
  }
  return { totalEvents: events.length, lowConfidenceCount: lowConfidence.length, unappliedPatches: draftsCount, unboundSpeakers: unboundSpeakers.length, failedBatchTasks: failedBatchCount, warnings, isReady: warnings.filter(w => w.severity === 'error').length === 0 }
}

export default function ExportView({ events }: Props) {
  const setMode = useAppStore(s => s.setMode)
  const pendingDrafts = useAppStore(s => s.pendingDrafts)
  const speakerLanes = useAppStore(s => s.speakerLanes as any[])
  const workspace = useAppStore(s => s.workspace)
  const manifest = useAppStore(s => s.manifest)

  const [confirmOpen, setConfirmOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportResult, setExportResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [dialogFormat, setDialogFormat] = useState('mp4')
  const [dialogResolution, setDialogResolution] = useState('original')
  const [dialogPreserveAudio, setDialogPreserveAudio] = useState(false)

  const unboundSpeakers = useMemo(() =>
    (speakerLanes || []).filter((l: any) => !l.voice_id).map((l: any) => l.display_name || l.speaker),
  [speakerLanes])

  const readiness = useMemo(() =>
    computeReadiness(events, pendingDrafts.size, unboundSpeakers, 0),
  [events, pendingDrafts.size, unboundSpeakers])

  const severityIcon = (s: string) => s === 'error' ? <ErrorIcon sx={{ fontSize: 16 }} /> : s === 'warning' ? <WarningIcon sx={{ fontSize: 16 }} /> : null

  const handleExport = useCallback(async () => {
    setExporting(true)
    setExportResult(null)
    try {
      const res = await fetch('/api/core/pipeline/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_path: manifest?.video_path || '',
          preset_id: 'cinema_dub',
          use_core: true,
          workspace,
          target_lang: 'zh',
          export_mode: true,
        }),
      })
      if (!res.ok) throw new Error((await res.json().catch(() => ({})) as any).detail || '导出启动失败')
      setExportResult({ ok: true, message: '导出任务已启动，请在项目中心查看进度' })
    } catch (e: any) {
      setExportResult({ ok: false, message: e.message || '导出失败' })
    }
    setExporting(false)
    setConfirmOpen(false)
  }, [workspace, manifest?.video_path])

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', bgcolor: '#f8fafc' }}>
      <Box sx={{ px: 3, py: 2, display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper' }}>
        <Box>
          <Typography variant="h6" fontWeight={600}>导出配音视频</Typography>
          <Typography variant="caption" color="text.secondary">参数配置请前往项目设置</Typography>
        </Box>
        <Button size="small" startIcon={<SettingsIcon />} onClick={() => setMode('settings')}>项目设置</Button>
      </Box>

      <Box sx={{ flex: 1, overflow: 'auto', p: 3 }}>
        {/* Readiness */}
        <Box sx={{ mb: 3 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
            {readiness.isReady ? <CheckCircleIcon color="success" /> : <WarningIcon color="warning" />}
            <Typography fontWeight={600}>
              {readiness.isReady ? '就绪 — 可以导出' : '存在需注意的问题'}
            </Typography>
            <Chip label={`${events.length} 个事件`} size="small" variant="outlined" />
          </Box>

          {readiness.warnings.length > 0 && (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {readiness.warnings.map((w, i) => (
                <Alert key={i} severity={w.severity} icon={severityIcon(w.severity)} variant="outlined"
                  action={w.action ? (
                    <Button size="small" color="inherit" onClick={() => setMode(w.action!.mode as any)}>
                      {w.action.label}
                    </Button>
                  ) : undefined}
                  sx={{ py: 0 }}>
                  {w.message}
                </Alert>
              ))}
            </Box>
          )}
          {readiness.warnings.length === 0 && (
            <Typography variant="body2" color="text.secondary">所有检查已通过，字幕和说话人均已就绪。</Typography>
          )}
        </Box>

        {/* Export button */}
        <Button variant="contained" size="large" startIcon={exporting ? undefined : <FileDownloadIcon />}
          onClick={() => setConfirmOpen(true)} disabled={exporting || events.length === 0}
          sx={{ px: 4, py: 1.5 }}>
          {exporting ? '导出中...' : '导出配音视频'}
        </Button>
        {exporting && <LinearProgress sx={{ mt: 2 }} />}
        {exportResult && (
          <Alert severity={exportResult.ok ? 'success' : 'error'} sx={{ mt: 2 }} onClose={() => setExportResult(null)}>
            {exportResult.message}
          </Alert>
        )}
      </Box>

      {/* Confirm Dialog */}
      <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>确认导出</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            将使用项目设置中的参数进行导出。以下选项可快速覆盖：
          </Typography>
          <FormControl fullWidth size="small" sx={{ mb: 2 }}>
            <InputLabel>输出格式</InputLabel>
            <Select value={dialogFormat} onChange={e => setDialogFormat(e.target.value)} label="输出格式">
              <MenuItem value="mp4">MP4</MenuItem>
              <MenuItem value="mkv">MKV</MenuItem>
              <MenuItem value="mov">MOV</MenuItem>
            </Select>
          </FormControl>
          <FormControl fullWidth size="small" sx={{ mb: 2 }}>
            <InputLabel>分辨率</InputLabel>
            <Select value={dialogResolution} onChange={e => setDialogResolution(e.target.value)} label="分辨率">
              <MenuItem value="original">原始</MenuItem>
              <MenuItem value="1080p">1080p</MenuItem>
              <MenuItem value="720p">720p</MenuItem>
            </Select>
          </FormControl>
          <FormControlLabel control={<Switch checked={dialogPreserveAudio}
            onChange={e => setDialogPreserveAudio(e.target.checked)} />} label="保留原声轨" />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmOpen(false)}>取消</Button>
          <Button variant="contained" onClick={handleExport} startIcon={<FileDownloadIcon />}>开始导出</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
