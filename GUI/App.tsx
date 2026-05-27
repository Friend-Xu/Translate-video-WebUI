import { useState, useCallback, useEffect } from 'react'
import { ThemeProvider, CssBaseline, Box, Alert, Snackbar, Typography } from '@mui/material'
import CloudUploadOutlined from '@mui/icons-material/CloudUploadOutlined'
import theme from './theme'
import AppShell from './components/AppShell'
import GlobalBar from './components/GlobalBar/index'
import EvidenceDock from './components/EvidenceDock/index'
import NavRail from './components/NavRail/index'
import TimelineArena from './components/TimelineArena/index'
import ProjectHubPage from './components/ProjectHubPage'
import IRInspector from './components/IRInspector/index'
import OpsDashboard from './components/OpsDashboard'
import PatchManagementView from './components/ModeViews/PatchManagementView'
import ExportView from './components/ModeViews/ExportView'
import CommandPalette from './components/CommandPalette'
import { useConfig } from './hooks/useConfig'
import { usePipeline } from './hooks/usePipeline'
import { useSSE } from './hooks/useSSE'
import { useBatch } from './hooks/useBatch'
import { useAppStore } from './store/useAppStore'
import { ErrorBanner } from './components/LoadingSkeleton'
import { MOCK_EVENTS, MOCK_WAVEFORM, MOCK_TTS_WAVEFORMS } from './mocks/mockData'
import { mockSystemStatus } from './mocks/mockHandlers'
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
  const selectedEventId = useAppStore(s => s.selectedEventId)

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
    mockSystemStatus().then(setSysStatus).catch(() => {})
    const iv = setInterval(() => mockSystemStatus().then(setSysStatus).catch(() => {}), 10000)
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
  const manifest = useAppStore(s => s.manifest)
  const isWorkspace = dataSource === 'workspace' && storeEvents.length > 0

  const events = isWorkspace ? storeEvents : MOCK_EVENTS
  const waveform = isWorkspace && storeWaveform ? storeWaveform : MOCK_WAVEFORM
  const totalDuration = isWorkspace
    ? Math.max(...storeEvents.map(e => e.end), 80)
    : 80
  const videoSrc = isWorkspace && manifest?.video_path
    ? `/api/files/video?path=${encodeURIComponent(manifest.video_path)}`
    : null

  const selectedEvent = events.find(e => e.id === selectedEventId) || null

  const arenaContent = (() => {
    switch (mode) {
      case 'hub':
        return <ProjectHubPage />
      case 'batch':
        return (
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
        )
      case 'patch':
        return <PatchManagementView events={events} />
      case 'export':
        return <ExportView events={events} />
      case 'timeline':
      default:
        return (
          <TimelineArena
            events={events}
            waveform={waveform}
            totalDuration={totalDuration}
            ttsWaveforms={MOCK_TTS_WAVEFORMS}
            videoSrc={videoSrc}
            onDropVideo={handleFileDropped}
          />
        )
    }
  })()

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
        inspectorContent={<IRInspector event={selectedEvent} />}
        dockContent={
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
        }
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
