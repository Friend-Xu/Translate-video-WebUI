import { useState, useCallback, useEffect, useRef } from 'react'
import {
  Box, Typography, Button, Card, CardContent, CardActionArea,
  Chip, Divider, LinearProgress, Grid, Stepper, Step, StepLabel,
  Select, MenuItem, FormControl, InputLabel,
  Accordion, AccordionSummary, AccordionDetails,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMoreRounded'
import CloudUploadOutlined from '@mui/icons-material/CloudUploadOutlined'
import SubtitlesRounded from '@mui/icons-material/SubtitlesRounded'
import TheatersRounded from '@mui/icons-material/TheatersRounded'
import TranslateRounded from '@mui/icons-material/TranslateRounded'
import PodcastsRounded from '@mui/icons-material/PodcastsRounded'
import FolderOpenRounded from '@mui/icons-material/FolderOpenRounded'
import ErrorOutlineRounded from '@mui/icons-material/ErrorOutlineRounded'
import CheckCircleRounded from '@mui/icons-material/CheckCircleRounded'
import PlayArrowRounded from '@mui/icons-material/PlayArrowRounded'
import StopRounded from '@mui/icons-material/StopRounded'
import OpenInNewRounded from '@mui/icons-material/OpenInNewRounded'
import VideoFileRounded from '@mui/icons-material/VideoFileRounded'
import { useAppStore } from '../store/useAppStore'
import { usePipeline } from '../hooks/usePipeline'
import { useSSE } from '../hooks/useSSE'
import type { WorkflowPreset, WorkspaceSummary } from '../types'
import type { LogEntry } from '../types'

type Phase = 'hub' | 'config' | 'review' | 'running' | 'done'

const PRESET_ICONS: Record<string, React.ReactNode> = {
  SubtitlesRounded: <SubtitlesRounded sx={{ fontSize: 32 }} />,
  TheatersRounded: <TheatersRounded sx={{ fontSize: 32 }} />,
  TranslateRounded: <TranslateRounded sx={{ fontSize: 32 }} />,
  PodcastsRounded: <PodcastsRounded sx={{ fontSize: 32 }} />,
}

const STATE_LABELS: Record<string, { label: string; color: 'success' | 'info' | 'error' | 'warning' | 'default' }> = {
  ready: { label: 'Ready', color: 'success' },
  bootstrapping: { label: 'Processing', color: 'info' },
  uninitialized: { label: 'New', color: 'default' },
  failed: { label: 'Failed', color: 'error' },
  computing: { label: 'Computing', color: 'warning' },
  complete: { label: 'Complete', color: 'success' },
}

export default function ProjectHubPage() {
  const setMode = useAppStore(s => s.setMode)
  const loadWorkspace = useAppStore(s => s.loadWorkspace)
  const createWorkspace = useAppStore(s => s.createWorkspace)
  const fetchWorkflowPresets = useAppStore(s => s.fetchWorkflowPresets)
  const fetchWorkspaceList = useAppStore(s => s.fetchWorkspaceList)
  const workflowPresets = useAppStore(s => s.workflowPresets)
  const workspaceList = useAppStore(s => s.workspaceList)
  const manifest = useAppStore(s => s.manifest)
  const workspace = useAppStore(s => s.workspace)
  const error = useAppStore(s => s.error)

  // Hub state
  const [dragOver, setDragOver] = useState(false)
  const [selectedVideo, setSelectedVideo] = useState<{ path: string; name: string; size: number } | null>(null)
  const [starting, setStarting] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [availableVideos, setAvailableVideos] = useState<Array<{ name: string; path: string; size: number }>>([])
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Wizard state
  const [phase, setPhase] = useState<Phase>('hub')
  const [selectedPresetId, setSelectedPresetId] = useState('quick_subtitle')
  const [lang, setLang] = useState('en')
  const [targetLang, setTargetLang] = useState('zh')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [videoInfo, setVideoInfo] = useState<{ duration: number; resolution: string } | null>(null)

  const { status, logs, appendLog, cancelPipeline } = usePipeline()

  // Load data on mount
  useEffect(() => {
    fetchWorkflowPresets()
    fetchWorkspaceList()
    fetch('/api/files/search-videos?path=source_file')
      .then(r => r.json())
      .then(data => setAvailableVideos(data.videos || []))
      .catch(() => {})
  }, [fetchWorkflowPresets, fetchWorkspaceList])

  // SSE connection
  useSSE(status.jobId, appendLog, () => {}, () => {})

  // Load video info when manifest is available
  useEffect(() => {
    const videoPath = manifest?.video_path
    if (!videoPath) return
    fetch(`/api/video/info?path=${encodeURIComponent(videoPath)}`)
      .then(r => r.json())
      .then(data => setVideoInfo({ duration: data.duration || 0, resolution: data.resolution || 'unknown' }))
      .catch(() => {})
  }, [manifest?.video_path])

  const handleFileUpload = useCallback(async (file: File) => {
    setUploading(true)
    const form = new FormData()
    form.append('file', file)
    try {
      const res = await fetch('/api/files/upload', { method: 'POST', body: form })
      if (!res.ok) throw new Error('Upload failed')
      const data = await res.json()
      setSelectedVideo({ path: data.path, name: data.name, size: data.size })
    } catch { /* ignore */ }
    finally { setUploading(false) }
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent) => { e.preventDefault(); setDragOver(true) }, [])
  const handleDragLeave = useCallback(() => setDragOver(false), [])
  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFileUpload(file)
  }, [handleFileUpload])

  const handleBrowseClick = useCallback(() => fileInputRef.current?.click(), [])
  const handleFileInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) handleFileUpload(file)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [handleFileUpload])

  const handleSelectExistingVideo = useCallback(async (video: { name: string; path: string }) => {
    try {
      const res = await fetch(`/api/video/info?path=${encodeURIComponent(video.path)}`)
      const info = await res.json()
      setSelectedVideo({ path: video.path, name: video.name, size: info.size || 0 })
    } catch {
      setSelectedVideo({ path: video.path, name: video.name, size: 0 })
    }
  }, [])

  // Create workspace and enter config phase
  const handleCreateRuntime = useCallback(async (presetId: string) => {
    if (!selectedVideo) return
    setStarting(true)
    setSelectedPresetId(presetId)
    try {
      await createWorkspace(selectedVideo.path, presetId)
      setPhase('config')
    } catch { /* error in store */ }
    finally { setStarting(false) }
  }, [selectedVideo, createWorkspace])

  // Start bootstrap pipeline
  const handleStartBootstrap = useCallback(async () => {
    if (!workspace) return
    setPhase('running')
    const videoPath = manifest?.video_path || ''
    try {
      const res = await fetch('/api/pipeline/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ video_path: videoPath, lang, target_lang: targetLang }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error((err as any).detail || '启动失败')
      }
    } catch (e) {
      appendLog({ _id: Date.now(), level: 'ERROR', message: `启动失败: ${e}`, timestamp: new Date().toISOString() } as LogEntry)
      setPhase('review')
    }
  }, [workspace, manifest?.video_path, lang, targetLang, appendLog])

  const handleCancel = useCallback(() => {
    cancelPipeline()
    setPhase('review')
  }, [cancelPipeline])

  const handleOpenTimeline = useCallback(() => {
    if (workspace) loadWorkspace(workspace).then(() => setMode('timeline'))
  }, [workspace, loadWorkspace, setMode])

  const handleOpenWorkspace = useCallback(async (ws: WorkspaceSummary) => {
    await loadWorkspace(ws.path)
    setMode('timeline')
  }, [loadWorkspace, setMode])

  // Detect pipeline completion
  useEffect(() => {
    if (phase === 'running' && status.state === 'completed') {
      setPhase('done')
    }
  }, [phase, status.state])

  const selectedPreset = workflowPresets.find(p => p.id === selectedPresetId)
  const readyWorkspaces = workspaceList.filter(w => w.runtimeState === 'ready' || w.runtimeState === 'complete')
  const failedWorkspaces = workspaceList.filter(w => w.runtimeState === 'failed')
  const otherWorkspaces = workspaceList.filter(w => !['ready', 'complete', 'failed'].includes(w.runtimeState))

  // ── Hub View ──
  if (phase === 'hub') {
    return (
      <Box sx={{ height: '100%', overflow: 'auto', p: 4 }}>
        <Box sx={{ mb: 4, textAlign: 'center' }}>
          <Typography variant="h4" fontWeight={700} gutterBottom>Timeline Runtime System</Typography>
          <Typography variant="body1" color="text.secondary" sx={{ maxWidth: 600, mx: 'auto' }}>
            将视频转化为可编辑的 Timeline IR，选择一个 Workflow Preset 开始。
          </Typography>
        </Box>

        {/* Drop zone */}
        <Box onDragOver={handleDragOver} onDragLeave={handleDragLeave} onDrop={handleDrop}
          sx={{ border: '2px dashed', borderColor: dragOver ? 'primary.main' : selectedVideo ? 'success.main' : 'divider',
            borderRadius: 3, p: selectedVideo ? 2 : 6, mb: 4, textAlign: 'center',
            bgcolor: dragOver ? 'rgba(99,102,241,0.08)' : 'background.paper', transition: 'all 0.2s' }}>
          {selectedVideo ? (
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <CheckCircleRounded color="success" />
                <Box sx={{ textAlign: 'left' }}>
                  <Typography variant="body2" fontWeight={600}>{selectedVideo.name}</Typography>
                  <Typography variant="caption" color="text.secondary">{(selectedVideo.size / 1024 / 1024).toFixed(0)} MB</Typography>
                </Box>
              </Box>
              <Button size="small" variant="outlined" onClick={() => setSelectedVideo(null)}>更换</Button>
            </Box>
          ) : (
            <>
              <CloudUploadOutlined sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
              <Typography variant="h6" color="text.secondary" gutterBottom>拖放视频文件到此处</Typography>
              <Typography variant="caption" color="text.disabled" sx={{ display: 'block', mb: 2 }}>支持 .mp4 / .mkv / .avi / .mov</Typography>
              <input ref={fileInputRef} type="file" accept="video/*" style={{ display: 'none' }} onChange={handleFileInputChange} />
              <Button variant="outlined" size="small" onClick={handleBrowseClick} disabled={uploading}>
                {uploading ? '上传中...' : '选择视频文件'}
              </Button>
            </>
          )}
        </Box>

        {/* Available videos */}
        {!selectedVideo && availableVideos.length > 0 && (
          <Box sx={{ mb: 4 }}>
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>source_file/ 中的可用视频</Typography>
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
              {availableVideos.map(v => (
                <Chip key={v.path} icon={<VideoFileRounded />}
                  label={`${v.name} (${(v.size / 1024 / 1024).toFixed(0)} MB)`}
                  onClick={() => handleSelectExistingVideo(v)} variant="outlined"
                  sx={{ fontSize: '0.75rem', py: 2, px: 0.5, cursor: 'pointer',
                    '&:hover': { borderColor: 'primary.main', bgcolor: 'rgba(99,102,241,0.06)' } }} />
              ))}
            </Box>
          </Box>
        )}

        {/* Workflow Presets */}
        {selectedVideo && (
          <Box sx={{ mb: 4 }}>
            <Typography variant="subtitle1" fontWeight={600} gutterBottom>选择 Workflow Preset</Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 2 }}>
              每个 Preset 是一组预配置的 Pass DAG，用于初始化 Timeline Runtime
            </Typography>
            {workflowPresets.length === 0 ? <LinearProgress sx={{ borderRadius: 1 }} /> : (
              <Grid container spacing={2}>
                {workflowPresets.map((preset: WorkflowPreset) => (
                  <Grid key={preset.id} size={{ xs: 12, sm: 6, md: 3 }}>
                    <Card sx={{ border: '1px solid', borderColor: 'divider', transition: 'all 0.15s',
                      '&:hover': { borderColor: 'primary.main', boxShadow: 4 } }}>
                      <CardActionArea onClick={() => handleCreateRuntime(preset.id)} disabled={starting}>
                        <CardContent>
                          <Box sx={{ color: 'primary.main', mb: 1 }}>{PRESET_ICONS[preset.icon] || <PlayArrowRounded sx={{ fontSize: 32 }} />}</Box>
                          <Typography variant="subtitle2" fontWeight={600} gutterBottom>{preset.name}</Typography>
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>{preset.description}</Typography>
                          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                            {preset.passes.map(p => <Chip key={p} label={p} size="small" variant="outlined" sx={{ fontSize: '0.6rem', height: 18 }} />)}
                          </Box>
                          <Box sx={{ display: 'flex', gap: 0.5, mt: 1, flexWrap: 'wrap' }}>
                            {preset.tags.map(t => <Chip key={t} label={t} size="small" sx={{ fontSize: '0.55rem', height: 16, bgcolor: 'rgba(99,102,241,0.1)', color: 'primary.main' }} />)}
                          </Box>
                        </CardContent>
                      </CardActionArea>
                    </Card>
                  </Grid>
                ))}
              </Grid>
            )}
          </Box>
        )}

        <Divider sx={{ my: 3 }} />

        {/* Failed recovery */}
        {failedWorkspaces.length > 0 && (
          <Box sx={{ mb: 3 }}>
            <Typography variant="subtitle2" color="error.main" sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 1 }}>
              <ErrorOutlineRounded fontSize="small" /> 需要恢复的项目
            </Typography>
            <Grid container spacing={1}>
              {failedWorkspaces.map(ws => (
                <Grid key={ws.path} size={{ xs: 12, sm: 6, md: 4 }}>
                  <Card sx={{ border: '1px solid', borderColor: 'error.main', opacity: 0.85 }}>
                    <CardActionArea onClick={() => handleOpenWorkspace(ws)}>
                      <CardContent sx={{ py: 1.5 }}>
                        <Typography variant="body2" fontWeight={600}>{ws.name}</Typography>
                        <Chip label="FAILED" size="small" color="error" sx={{ fontSize: '0.6rem', height: 18, mt: 0.5 }} />
                      </CardContent>
                    </CardActionArea>
                  </Card>
                </Grid>
              ))}
            </Grid>
          </Box>
        )}

        {/* Workspace list */}
        <Box sx={{ mb: 3 }}>
          <Typography variant="subtitle1" fontWeight={600} gutterBottom>项目</Typography>
          {workspaceList.length === 0 ? (
            <Typography variant="body2" color="text.disabled">暂无项目。拖放视频文件开始创建第一个 Timeline Runtime。</Typography>
          ) : (
            <Grid container spacing={1}>
              {[...readyWorkspaces, ...otherWorkspaces].map(ws => {
                const st = STATE_LABELS[ws.runtimeState] || STATE_LABELS.uninitialized
                return (
                  <Grid key={ws.path} size={{ xs: 12, sm: 6, md: 4 }}>
                    <Card sx={{ border: '1px solid', borderColor: 'divider' }}>
                      <CardActionArea onClick={() => { if (ws.runtimeState === 'ready' || ws.runtimeState === 'complete') handleOpenWorkspace(ws) }}>
                        <CardContent sx={{ py: 1.5, display: 'flex', alignItems: 'center', gap: 1.5 }}>
                          <FolderOpenRounded sx={{ color: 'text.disabled', fontSize: 28 }} />
                          <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                            <Typography variant="body2" fontWeight={600} noWrap>{ws.name}</Typography>
                            <Typography variant="caption" color="text.secondary" noWrap>{ws.videoPath?.split(/[/\\]/).pop() || ws.path}</Typography>
                          </Box>
                          <Chip label={st.label} size="small" color={st.color} sx={{ fontSize: '0.6rem', height: 20, flexShrink: 0 }} />
                        </CardContent>
                      </CardActionArea>
                    </Card>
                  </Grid>
                )
              })}
            </Grid>
          )}
        </Box>
        {error && <Typography variant="caption" color="error.main" sx={{ display: 'block', mt: 2 }}>{error}</Typography>}
      </Box>
    )
  }

  // ── Config / Review / Running / Done Views ──
  const stepLabels = ['配置 Pass DAG', '审查并启动', '监控']
  const activeStep = phase === 'config' ? 0 : phase === 'review' ? 1 : 2

  return (
    <Box sx={{ height: '100%', overflow: 'auto', p: 3 }}>
      <Box sx={{ mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
          <Button size="small" variant="text" onClick={() => { setPhase('hub'); setSelectedVideo(null) }} sx={{ fontSize: '0.7rem' }}>
            ← 返回项目中心
          </Button>
        </Box>
        <Typography variant="h5" fontWeight={700}>Bootstrap Timeline Runtime</Typography>
        <Typography variant="body2" color="text.secondary">
          {selectedVideo?.name} · Preset: {selectedPreset?.name || selectedPresetId}
        </Typography>
      </Box>

      <Stepper activeStep={activeStep} sx={{ mb: 3 }}>
        {stepLabels.map(l => <Step key={l}><StepLabel>{l}</StepLabel></Step>)}
      </Stepper>

      {/* Phase: Config */}
      {(phase === 'config' || phase === 'review') && (
        <Box>
          {phase === 'config' && (
            <>
              <Card sx={{ p: 3, mb: 2 }}>
                <Typography variant="subtitle1" fontWeight={600} gutterBottom>Workflow Preset</Typography>
                <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mb: 2 }}>
                  {workflowPresets.map((preset: WorkflowPreset) => (
                    <Card key={preset.id} onClick={() => setSelectedPresetId(preset.id)}
                      sx={{ flex: '1 1 200px', maxWidth: 280, cursor: 'pointer',
                        border: '2px solid', borderColor: selectedPresetId === preset.id ? 'primary.main' : 'divider' }}>
                      <CardContent sx={{ py: 1.5 }}>
                        <Typography variant="subtitle2" fontWeight={600}>{preset.name}</Typography>
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>{preset.description.slice(0, 60)}...</Typography>
                        <Box sx={{ display: 'flex', gap: 0.3, flexWrap: 'wrap' }}>
                          {preset.passes.map(p => <Chip key={p} label={p} size="small" variant="outlined" sx={{ fontSize: '0.55rem', height: 16 }} />)}
                        </Box>
                      </CardContent>
                    </Card>
                  ))}
                </Box>
              </Card>

              <Card sx={{ p: 3, mb: 2 }}>
                <Typography variant="subtitle1" fontWeight={600} gutterBottom>语言设置</Typography>
                <Box sx={{ display: 'flex', gap: 2 }}>
                  <FormControl size="small" sx={{ minWidth: 120 }}>
                    <InputLabel>源语言</InputLabel>
                    <Select value={lang} label="源语言" onChange={e => setLang(e.target.value)}>
                      <MenuItem value="en">English</MenuItem><MenuItem value="zh">中文</MenuItem>
                      <MenuItem value="ja">日本語</MenuItem><MenuItem value="ko">한국어</MenuItem>
                      <MenuItem value="auto">自动检测</MenuItem>
                    </Select>
                  </FormControl>
                  <FormControl size="small" sx={{ minWidth: 120 }}>
                    <InputLabel>目标语言</InputLabel>
                    <Select value={targetLang} label="目标语言" onChange={e => setTargetLang(e.target.value)}>
                      <MenuItem value="zh">中文</MenuItem><MenuItem value="en">English</MenuItem>
                      <MenuItem value="ja">日本語</MenuItem><MenuItem value="ko">한국어</MenuItem>
                    </Select>
                  </FormControl>
                </Box>
              </Card>

              <Accordion expanded={showAdvanced} onChange={() => setShowAdvanced(!showAdvanced)}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}><Typography variant="subtitle2">高级配置</Typography></AccordionSummary>
                <AccordionDetails>
                  <Typography variant="body2" color="text.secondary" gutterBottom>ASR 模型、TTS 引擎、字幕样式、术语表等高级选项将在后续版本中开放。</Typography>
                  {selectedPreset && (
                    <Box sx={{ mt: 1 }}>
                      <Typography variant="caption" fontWeight={600}>当前 Preset 默认配置:</Typography>
                      <Box component="pre" sx={{ fontSize: '0.65rem', bgcolor: 'background.default', p: 1, borderRadius: 1, mt: 0.5, overflow: 'auto', maxHeight: 200 }}>{JSON.stringify(selectedPreset.configDefaults, null, 2)}</Box>
                    </Box>
                  )}
                </AccordionDetails>
              </Accordion>

              <Box sx={{ mt: 2 }}>
                <Button variant="contained" onClick={() => setPhase('review')}>审查并 Bootstrap</Button>
              </Box>
            </>
          )}

          {phase === 'review' && (
            <>
              <Card sx={{ p: 3, mb: 2 }}>
                <Typography variant="subtitle1" fontWeight={600} gutterBottom>配置摘要</Typography>
                <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 1 }}>
                  <Chip label={`Preset: ${selectedPreset?.name || selectedPresetId}`} size="small" color="primary" />
                  <Chip label={`${lang} → ${targetLang}`} size="small" variant="outlined" />
                  {videoInfo && <Chip label={`${(videoInfo.duration / 60).toFixed(1)}min`} size="small" variant="outlined" />}
                </Box>
                {selectedPreset && (
                  <Box>
                    <Typography variant="caption" color="text.secondary">Pass DAG:</Typography>
                    <Box sx={{ display: 'flex', gap: 0.3, flexWrap: 'wrap', mt: 0.5 }}>
                      {selectedPreset.passes.map((p, i) => (
                        <Box key={p} sx={{ display: 'flex', alignItems: 'center', gap: 0.3 }}>
                          <Chip label={p} size="small" variant="outlined" sx={{ fontSize: '0.6rem', height: 18 }} />
                          {i < selectedPreset.passes.length - 1 && <Typography variant="caption" color="text.disabled">→</Typography>}
                        </Box>
                      ))}
                    </Box>
                  </Box>
                )}
              </Card>
              <Box sx={{ display: 'flex', gap: 1 }}>
                <Button variant="outlined" onClick={() => setPhase('config')}>修改配置</Button>
                <Button variant="contained" startIcon={<PlayArrowRounded />} onClick={handleStartBootstrap}>Bootstrap Timeline</Button>
              </Box>
            </>
          )}
        </Box>
      )}

      {/* Phase: Running / Done */}
      {(phase === 'running' || phase === 'done') && (
        <Card sx={{ p: 3, mb: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
            <Box>
              <Typography variant="subtitle1" fontWeight={600}>
                {phase === 'done' ? 'Bootstrap 完成' : status.state === 'failed' ? 'Bootstrap 失败' : '正在初始化 Timeline Runtime...'}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                进度: {status.progress}%{status.currentStep ? ` · ${status.currentStep}` : ''}
              </Typography>
            </Box>
            {status.state === 'running' && (
              <Button size="small" color="error" variant="outlined" startIcon={<StopRounded />} onClick={handleCancel}>取消</Button>
            )}
          </Box>
          {status.state === 'running' && <LinearProgress variant="determinate" value={status.progress} sx={{ mb: 2, borderRadius: 1 }} />}
          <Box sx={{ bgcolor: 'background.default', borderRadius: 1, p: 1.5, maxHeight: 320, overflow: 'auto', fontFamily: 'monospace', fontSize: '0.7rem' }}>
            {logs.length === 0 ? <Typography variant="caption" color="text.disabled">等待日志输出...</Typography> :
              logs.map((entry: LogEntry, i: number) => (
                <Box key={i} sx={{ color: entry.level === 'ERROR' ? 'error.main' : entry.level === 'WARN' ? 'warning.main' : entry.level === 'STAGE' ? 'primary.main' : 'text.secondary', py: 0.1 }}>{entry.message}</Box>
              ))}
          </Box>
          {phase === 'done' && (
            <Button variant="contained" color="success" startIcon={<OpenInNewRounded />} onClick={handleOpenTimeline} sx={{ mt: 2 }}>
              在 Timeline Workbench 中打开
            </Button>
          )}
          {status.state === 'failed' && phase === 'running' && (
            <Box sx={{ display: 'flex', gap: 1, mt: 2 }}>
              <Button variant="outlined" onClick={() => setPhase('config')}>返回修改配置</Button>
              <Button variant="contained" onClick={handleStartBootstrap}>重试 Bootstrap</Button>
            </Box>
          )}
        </Card>
      )}
    </Box>
  )
}
