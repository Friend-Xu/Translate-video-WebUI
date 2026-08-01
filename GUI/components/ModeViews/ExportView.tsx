import { useState, useMemo, useCallback } from 'react'
import {
  Box, Typography, Button, Chip, Dialog, DialogTitle, DialogContent,
  DialogActions, LinearProgress, Alert, Card, CardContent, Grid,
} from '@mui/material'
import FileDownloadIcon from '@mui/icons-material/FileDownloadRounded'
import CheckCircleIcon from '@mui/icons-material/CheckCircleRounded'
import WarningIcon from '@mui/icons-material/WarningRounded'
import ErrorIcon from '@mui/icons-material/ErrorRounded'
import SettingsIcon from '@mui/icons-material/SettingsRounded'
import VideoFileIcon from '@mui/icons-material/VideoFileRounded'
import RecordVoiceOverIcon from '@mui/icons-material/RecordVoiceOverRounded'
import EditNoteIcon from '@mui/icons-material/EditNoteRounded'
import PeopleIcon from '@mui/icons-material/PeopleRounded'
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

  const unboundSpeakers = useMemo(() =>
    (speakerLanes || []).filter((l: any) => !l.voice_id).map((l: any) => l.display_name || l.speaker),
  [speakerLanes])

  const readiness = useMemo(() =>
    computeReadiness(events, pendingDrafts.size, unboundSpeakers, 0),
  [events, pendingDrafts.size, unboundSpeakers])

  const handleExport = useCallback(async () => {
    setExporting(true)
    setExportResult(null)
    try {
      const res = await fetch('/api/export/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace,
          video_path: manifest?.video_path || '',
          target_lang: 'zh',
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

      <Box sx={{ flex: 1, overflow: 'auto', p: 3, maxWidth: 1360, mx: 'auto', width: '100%' }}>
        <Grid container spacing={2.5}>
          {/* Left column: readiness + stats */}
          <Grid size={{ xs: 12, md: 8 }}>
            {/* Readiness card */}
            <Card variant="outlined" sx={{ borderRadius: 2.5, mb: 2.5 }}>
              <CardContent sx={{ p: 2.5, '&:last-child': { pb: 2.5 } }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
                  <Box sx={{
                    width: 40, height: 40, borderRadius: '50%', flexShrink: 0,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    bgcolor: readiness.isReady ? 'rgba(76,175,80,0.12)' : 'rgba(255,152,0,0.12)',
                  }}>
                    {readiness.isReady
                      ? <CheckCircleIcon sx={{ color: 'success.main', fontSize: 22 }} />
                      : <WarningIcon sx={{ color: 'warning.main', fontSize: 22 }} />}
                  </Box>
                  <Box sx={{ flexGrow: 1 }}>
                    <Typography variant="subtitle1" fontWeight={600} sx={{ fontSize: '0.95rem' }}>
                      {readiness.isReady ? '就绪 — 可以导出' : '存在需注意的问题'}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      导出前检查会标记可能影响成片质量的问题
                    </Typography>
                  </Box>
                  <Chip label={`${events.length} 个事件`} size="small" variant="outlined" />
                </Box>

                {readiness.warnings.length > 0 ? (
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                    {readiness.warnings.map((w, i) => (
                      <Box key={i} sx={{
                        display: 'flex', alignItems: 'center', gap: 1.5,
                        p: 1.25, borderRadius: 1.5,
                        bgcolor: w.severity === 'error' ? 'rgba(244,67,54,0.06)' : 'rgba(255,152,0,0.06)',
                        border: '1px solid',
                        borderColor: w.severity === 'error' ? 'rgba(244,67,54,0.2)' : 'rgba(255,152,0,0.2)',
                      }}>
                        {w.severity === 'error'
                          ? <ErrorIcon sx={{ fontSize: 18, color: 'error.main', flexShrink: 0 }} />
                          : <WarningIcon sx={{ fontSize: 18, color: 'warning.main', flexShrink: 0 }} />}
                        <Typography variant="body2" sx={{ fontSize: '0.8rem', flexGrow: 1 }}>{w.message}</Typography>
                        {w.action && (
                          <Button size="small" variant="text" sx={{ fontSize: '0.7rem', flexShrink: 0 }}
                            onClick={() => setMode(w.action!.mode as any)}>
                            {w.action.label}
                          </Button>
                        )}
                      </Box>
                    ))}
                  </Box>
                ) : (
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, p: 1.25, borderRadius: 1.5, bgcolor: 'rgba(76,175,80,0.06)', border: '1px solid rgba(76,175,80,0.2)' }}>
                    <CheckCircleIcon sx={{ fontSize: 18, color: 'success.main' }} />
                    <Typography variant="body2" sx={{ fontSize: '0.8rem', color: 'success.dark' }}>
                      所有检查已通过，字幕和说话人均已就绪。
                    </Typography>
                  </Box>
                )}
              </CardContent>
            </Card>

            {/* Data overview card */}
            <Card variant="outlined" sx={{ borderRadius: 2.5 }}>
              <CardContent sx={{ p: 2.5, '&:last-child': { pb: 2.5 } }}>
                <Typography variant="subtitle2" fontWeight={600} sx={{ fontSize: '0.85rem', mb: 1.5 }}>
                  导出数据概览
                </Typography>
                <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap' }}>
                  {[
                    { icon: <EditNoteIcon sx={{ fontSize: 18 }} />, label: '字幕事件', value: `${events.length}` },
                    { icon: <PeopleIcon sx={{ fontSize: 18 }} />, label: '说话人', value: `${(speakerLanes || []).length}` },
                    { icon: <RecordVoiceOverIcon sx={{ fontSize: 18 }} />, label: '声线未绑定', value: `${unboundSpeakers.length}` },
                    { icon: <EditNoteIcon sx={{ fontSize: 18 }} />, label: '未应用补丁', value: `${pendingDrafts.size}` },
                  ].map(s => (
                    <Box key={s.label} sx={{
                      flex: '1 1 140px', p: 1.5, borderRadius: 1.5,
                      bgcolor: 'rgba(0,0,0,0.025)', border: '1px solid', borderColor: 'divider',
                      display: 'flex', alignItems: 'center', gap: 1,
                    }}>
                      <Box sx={{ color: 'primary.main', display: 'flex' }}>{s.icon}</Box>
                      <Box>
                        <Typography variant="h6" sx={{ fontSize: '1.05rem', lineHeight: 1.2 }}>{s.value}</Typography>
                        <Typography variant="caption" color="text.secondary">{s.label}</Typography>
                      </Box>
                    </Box>
                  ))}
                </Box>
              </CardContent>
            </Card>
          </Grid>

          {/* Right column: video info + export CTA */}
          <Grid size={{ xs: 12, md: 4 }}>
            <Card variant="outlined" sx={{ borderRadius: 2.5, mb: 2.5 }}>
              <CardContent sx={{ p: 2.5, '&:last-child': { pb: 2.5 } }}>
                <Typography variant="subtitle2" fontWeight={600} sx={{ fontSize: '0.85rem', mb: 1.5 }}>
                  当前项目
                </Typography>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 1 }}>
                  <Box sx={{
                    width: 38, height: 38, borderRadius: 1.5, flexShrink: 0,
                    bgcolor: 'rgba(33,150,243,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    <VideoFileIcon sx={{ color: 'primary.main', fontSize: 20 }} />
                  </Box>
                  <Box sx={{ minWidth: 0 }}>
                    <Typography variant="body2" noWrap sx={{ fontSize: '0.8rem', fontWeight: 500 }}>
                      {manifest?.video_path ? manifest.video_path.split(/[/\\]/).pop() : '未加载视频'}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {manifest?.video_duration ? `时长 ${Math.round(manifest.video_duration)}s` : ''}
                      {workspace ? ' · 工作区已加载' : ' · 无工作区'}
                    </Typography>
                  </Box>
                </Box>
                <Typography variant="caption" color="text.disabled" noWrap sx={{ display: 'block', fontSize: '0.65rem' }}>
                  {workspace || '—'}
                </Typography>
              </CardContent>
            </Card>

            <Card variant="outlined" sx={{ borderRadius: 2.5 }}>
              <CardContent sx={{ p: 2.5, '&:last-child': { pb: 2.5 } }}>
                <Typography variant="subtitle2" fontWeight={600} sx={{ fontSize: '0.85rem', mb: 2 }}>
                  导出成片
                </Typography>
                <Button variant="contained" size="large" fullWidth
                  onClick={() => setConfirmOpen(true)} disabled={exporting || events.length === 0}
                  sx={{ borderRadius: 2, py: 1.5, fontSize: '0.95rem', fontWeight: 600, textTransform: 'none' }}>
                  导出配音视频
                  <Box component="span" sx={{
                    ml: 1.5, width: 28, height: 28, borderRadius: '50%',
                    bgcolor: 'rgba(255,255,255,0.22)',
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    <FileDownloadIcon sx={{ fontSize: 16 }} />
                  </Box>
                </Button>
                {exporting && <LinearProgress sx={{ mt: 2, borderRadius: 1 }} />}
                {exportResult && (
                  <Alert severity={exportResult.ok ? 'success' : 'error'} variant="outlined"
                    sx={{ mt: 2 }} onClose={() => setExportResult(null)}>
                    {exportResult.message}
                  </Alert>
                )}
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      </Box>

      {/* Confirm Dialog */}
      <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>确认导出</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary">
            将使用项目设置中的参数进行导出（当前版本导出参数暂不可自定义）。
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmOpen(false)}>取消</Button>
          <Button variant="contained" onClick={handleExport} startIcon={<FileDownloadIcon />}>开始导出</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
