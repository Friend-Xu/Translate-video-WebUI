import { useState, useCallback, useEffect } from 'react'
import { ThemeProvider, CssBaseline, Box, Alert, Snackbar, Typography, Button } from '@mui/material'
import CloudUploadOutlined from '@mui/icons-material/CloudUploadOutlined'
import theme from './theme'
import AppShell from './components/AppShell'
import GlobalBar from './components/GlobalBar/index'
import EvidenceDock from './components/EvidenceDock/index'
import NavRail from './components/NavRail/index'
import TimelineArena from './components/TimelineArena/index'
import VideoPreview from './components/TimelineArena/VideoPreview'
import ProjectHubPage from './components/ProjectHubPage'
import IRInspector from './components/IRInspector/index'
import OpsDashboard from './components/OpsDashboard'
import PatchManagementView from './components/ModeViews/PatchManagementView'
import ExportView from './components/ModeViews/ExportView'
import SettingsView from './components/ModeViews/SettingsView'
import SpeakerReviewView from './components/ModeViews/SpeakerReviewView'
import SpeakerInspector from './components/Inspector/SpeakerInspector'
import GlossaryManager from './components/GlossaryManager'
import LogsView from './components/ModeViews/LogsView'
import ReviewTable from './components/TimelineArena/ReviewTable'
import CommandPalette from './components/CommandPalette'
import { useConfig } from './hooks/useConfig'
import { usePipeline } from './hooks/usePipeline'
import { useSSE } from './hooks/useSSE'
import { useBatch } from './hooks/useBatch'
import { useAppStore } from './store/useAppStore'
import { ErrorBanner } from './components/LoadingSkeleton'
import { MOCK_EVENTS, MOCK_WAVEFORM } from './mocks/mockData'
import WorkspaceSelector from './components/WorkspaceSelector'

export default function App() {
  const { config, updateConfig } = useConfig()
  const { status, logs, appendLog, handleDone, logFirstIndex, logTotal, loadOlderLogs } = usePipeline()
  const { batch, cancelBatch, skipCurrent } = useBatch()

  const [snackbar, setSnackbar] = useState<{ open: boolean; msg: string; severity: 'success' | 'error' | 'info' }>({
    open: false, msg: '', severity: 'info',
  })
  const [backendOnline, setBackendOnline] = useState(true)
  const [dragOverWindow, setDragOverWindow] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [sysStatus, setSysStatus] = useState<{
    cpuUsage: number; memUsage: number; gpuUsage: number | null; modelsOnline: string[]
  } | null>(null)

  const mode = useAppStore(s => s.mode)
  const setMode = useAppStore(s => s.setMode)
  const selectedEventId = useAppStore(s => s.selectedEventId)
  const ttsWaveforms = useAppStore(s => s.ttsWaveforms)

  // SSE
  const sseJobId = status.jobId
  const { connectionState } = useSSE(sseJobId, appendLog, handleDone, () => {})

  // Backend ping
  useEffect(() => {
    const ping = () => fetch('/api/system/info').then(r => setBackendOnline(r.ok)).catch(() => setBackendOnline(false))
    ping()
    const iv = setInterval(ping, 30000)
    return () => clearInterval(iv)
  }, [])

  // System status
  useEffect(() => {
    const poll = () => fetch('/api/system/status').then(r => r.ok ? r.json() : Promise.reject()).then(setSysStatus).catch(() => {})
    poll()
    const iv = setInterval(poll, 10000)
    return () => clearInterval(iv)
  }, [])

  // Window drag overlay
  useEffect(() => {
    let counter = 0
    const onDragEnter = (e: DragEvent) => {
      e.preventDefault()
      if (e.dataTransfer?.types.includes('Files')) { counter++; if (counter === 1) setDragOverWindow(true) }
    }
    const onDragLeave = (e: DragEvent) => { e.preventDefault(); counter--; if (counter <= 0) { counter = 0; setDragOverWindow(false) } }
    const onDragOver = (e: DragEvent) => { e.preventDefault() }
    const onDrop = (e: DragEvent) => { e.preventDefault(); counter = 0; setDragOverWindow(false) }
    window.addEventListener('dragenter', onDragEnter)
    window.addEventListener('dragleave', onDragLeave)
    window.addEventListener('dragover', onDragOver)
    window.addEventListener('drop', onDrop)
    return () => {
      window.removeEventListener('dragenter', onDragEnter)
      window.removeEventListener('dragleave', onDragLeave)
      window.removeEventListener('dragover', onDragOver)
      window.removeEventListener('drop', onDrop)
    }
  }, [])

  const showMsg = useCallback((msg: string, severity: 'success' | 'error' | 'info' = 'info') => {
    setSnackbar({ open: true, msg, severity })
  }, [])

  // 全局错误展示: store.error 变化 → snackbar (操作失败必须响亮, 禁止静默吞错)
  const storeError = useAppStore(s => s.error)
  useEffect(() => {
    if (storeError) showMsg(storeError, 'error')
  }, [storeError, showMsg])

  const handleFileDropped = useCallback(async (file: File) => {
    const q = `name=${encodeURIComponent(file.name)}&size=${file.size}`
    try {
      const findRes = await fetch(`/api/files/find?${q}`)
      if (findRes.ok) {
        const data = await findRes.json()
        updateConfig('videoPath', data.path)
        showMsg(`已选择: ${data.name}`, 'success')
        return
      }
    } catch { /* fall through */ }

    showMsg(`正在导入 "${file.name}"...`, 'info')
    const form = new FormData()
    form.append('file', file)
    try {
      const upRes = await fetch('/api/files/upload', { method: 'POST', body: form })
      if (!upRes.ok) {
        showMsg(`导入失败: ${(await upRes.json().catch(() => ({ detail: upRes.statusText })) as any).detail || upRes.statusText}`, 'error')
        return
      }
      const data = await upRes.json()
      updateConfig('videoPath', data.path)
      showMsg(`已导入: ${data.name}`, 'success')
    } catch (e: any) {
      showMsg(`导入失败: ${e.message}`, 'error')
    }
  }, [updateConfig, showMsg])

  // Workspace data (TRV-PLAN-2026-001)
  const dataSource = useAppStore(s => s.dataSource)
  const storeEvents = useAppStore(s => s.events)
  const storeWaveform = useAppStore(s => s.waveform)
  const storeWorkspace = useAppStore(s => s.workspace)
  const manifest = useAppStore(s => s.manifest)
  const playheadPosition = useAppStore(s => s.playheadPosition)
  const isWorkspace = dataSource === 'workspace' && storeEvents.length > 0

  const events = isWorkspace ? storeEvents : MOCK_EVENTS
  const waveform = isWorkspace && storeWaveform ? storeWaveform : MOCK_WAVEFORM
  const totalDuration = isWorkspace
    ? manifest?.video_duration || Math.max(...storeEvents.map(e => e.end), 5)
    : Math.max(...MOCK_EVENTS.map(e => e.end), 80)
  const videoSrc = isWorkspace && manifest?.video_path
    ? `/api/files/video?path=${encodeURIComponent(manifest.video_path)}`
    : null

  const selectedEvent = events.find(e => e.id === selectedEventId) || null

  // VideoPreview 放在 Inspector 面板上方
  const inspectorWithVideo = mode === 'timeline' || mode === 'speaker' || mode === 'review' ? (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <VideoPreview
        videoSrc={videoSrc || null}
        currentTime={playheadPosition}
        events={events}
        onTimeUpdate={(t) => useAppStore.getState().setPlayhead(t)}
      />
      <Typography variant="caption" sx={{ fontWeight: 600, px: 1.5, pt: 1, display: 'block', color: 'text.secondary', fontSize: '0.65rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        事件详情
      </Typography>
      <Box sx={{ flex: '1 1 auto', overflow: 'hidden auto', minHeight: 0 }}>
        <IRInspector event={selectedEvent} />
      </Box>
      {mode === 'speaker' && (
        <SpeakerInspector events={events} speakerLanes={[]} />
      )}
    </Box>
  ) : null

  const arenaContent = (
    <>
      <Box sx={{ display: mode === 'hub' ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
        <ProjectHubPage />
      </Box>
      <Box sx={{ display: mode === 'batch' ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
        <OpsDashboard
          batch={batch}
          cpuUsage={sysStatus?.cpuUsage}
          memUsage={sysStatus?.memUsage}
          gpuUsage={sysStatus?.gpuUsage}
          modelsOnline={sysStatus?.modelsOnline || []}
          onStartBatch={() => showMsg('请先将视频文件拖拽到窗口以开始批处理', 'info')}
          onCancelBatch={cancelBatch}
          onSkipCurrent={skipCurrent}
        />
      </Box>
      <Box sx={{ display: mode === 'patch' ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
        <PatchManagementView events={events} />
      </Box>
      <Box sx={{ display: mode === 'export' ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
        <ExportView events={events} />
      </Box>
      <Box sx={{ display: mode === 'speaker' ? 'flex' : 'none', flex: 1, width: '100%', overflow: 'hidden', position: 'relative' }}>
        {!isWorkspace && (
          <Box sx={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, zIndex: 50,
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            bgcolor: 'rgba(0,0,0,0.75)', gap: 2, px: 3 }}>
            <Typography variant="h6" color="text.secondary" textAlign="center">尚未加载项目数据</Typography>
            <Button variant="contained" onClick={() => setMode('hub')}>返回项目中心</Button>
          </Box>
        )}
        <SpeakerReviewView events={events} />
      </Box>
      <Box sx={{ display: mode === 'review' ? 'flex' : 'none', flex: 1, overflow: 'hidden', position: 'relative' }}>
        {!isWorkspace && (
          <Box sx={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, zIndex: 50,
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            bgcolor: 'rgba(0,0,0,0.75)', gap: 2, px: 3 }}>
            <Typography variant="h6" color="text.secondary" textAlign="center">尚未加载项目数据</Typography>
            <Button variant="contained" onClick={() => setMode('hub')}>返回项目中心</Button>
          </Box>
        )}
        <ReviewTable events={events} workspace={storeWorkspace} onSeek={(t) => useAppStore.getState().setPlayhead(t)} />
      </Box>
      <Box sx={{ display: mode === 'settings' ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
        <SettingsView />
      </Box>
      <Box sx={{ display: mode === 'glossary' ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
        <GlossaryManager />
      </Box>
      <Box sx={{ display: mode === 'logs' ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
        <LogsView />
      </Box>
      <Box sx={{ display: mode === 'timeline' ? 'flex' : 'none', flex: 1, overflow: 'hidden', position: 'relative' }}>
        {!isWorkspace && (
          <Box sx={{
            position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, zIndex: 50,
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            bgcolor: 'rgba(0,0,0,0.75)', gap: 2, px: 3,
          }}>
            <Typography variant="h6" color="text.secondary" textAlign="center">
              尚未加载项目数据
            </Typography>
            <Typography variant="body2" color="text.disabled" textAlign="center" sx={{ maxWidth: 420 }}>
              当前显示的是示例数据。请在项目中心选择已有项目，或创建新的 Timeline Runtime 以加载真实数据。
            </Typography>
            <Button variant="contained" onClick={() => setMode('hub')}>
              返回项目中心
            </Button>
          </Box>
        )}
        <TimelineArena
          events={events}
          waveform={waveform}
          totalDuration={totalDuration}
          ttsWaveforms={ttsWaveforms || undefined}
          onDropVideo={handleFileDropped}
        />
      </Box>
    </>
  )

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />

      {errorMsg && <ErrorBanner message={errorMsg} onDismiss={() => setErrorMsg(null)} />}

      <AppShell
        pulseBar={
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0 }}>
            <GlobalBar
              projectName={config.videoPath ? config.videoPath.split(/[/\\]/).pop() : undefined}
              workspace={config.videoPath ? config.videoPath.split(/[/\\]/).slice(0, -1).join('/') : undefined}
              cpuUsage={sysStatus?.cpuUsage}
            memUsage={sysStatus?.memUsage}
            gpuUsage={sysStatus?.gpuUsage}
          />
          <WorkspaceSelector />
          </Box>
        }
        railContent={<NavRail />}
        arenaContent={arenaContent}
        inspectorContent={inspectorWithVideo}
        dockContent={mode === 'timeline' || mode === 'speaker' || mode === 'review' ? (
          <EvidenceDock
            logs={logs}
            connectionState={connectionState}
            logFirstIndex={logFirstIndex.current}
            logTotal={logTotal.current}
            onLoadOlder={() => loadOlderLogs(status.jobId)}
            events={events}
            passTrace={events.length > 0 ? events[0].passTrace : undefined}
            batchStatus={batch}
          />
        ) : null}
      />

      <CommandPalette />

      {/* Full-page drag overlay */}
      {dragOverWindow && (
        <Box
          onDragOver={(e) => { e.preventDefault(); e.stopPropagation() }}
          onDrop={(e) => {
            e.preventDefault(); e.stopPropagation()
            setDragOverWindow(false)
            const file = e.dataTransfer.files[0]
            if (file) handleFileDropped(file)
          }}
          sx={{
            position: 'fixed', inset: 0, zIndex: 9999,
            bgcolor: 'rgba(0,0,0,0.65)',
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            border: '4px dashed', borderColor: 'primary.main', m: 4, borderRadius: 4,
          }}>
          <CloudUploadOutlined sx={{ fontSize: 80, color: 'primary.main', mb: 3, opacity: 0.9 }} />
          <Typography variant="h4" color="white" fontWeight={600}>释放以选择视频文件</Typography>
          <Typography variant="body1" color="rgba(255,255,255,0.6)" mt={1}>支持 .mp4 / .mkv / .avi / .mov 等常见格式</Typography>
        </Box>
      )}

      {/* Backend indicator */}
      <Box sx={{
        position: 'fixed', bottom: 0, left: 0, right: 0,
        bgcolor: 'grey.900', py: 0.5, px: 2, display: 'flex', alignItems: 'center', gap: 1, zIndex: 2000,
      }}>
        <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: backendOnline ? '#4caf50' : '#f44336' }} />
        <Typography variant="caption" color="text.secondary">
          {backendOnline ? '后端已连接' : '后端未连接'}
        </Typography>
      </Box>

      <Snackbar open={snackbar.open} autoHideDuration={4000}
        onClose={() => setSnackbar(prev => ({ ...prev, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}>
        <Alert severity={snackbar.severity} onClose={() => setSnackbar(prev => ({ ...prev, open: false }))} variant="filled">
          {snackbar.msg}
        </Alert>
      </Snackbar>
    </ThemeProvider>
  )
}
