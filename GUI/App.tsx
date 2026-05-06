import { useState, useCallback, useEffect } from 'react'
import { ThemeProvider, CssBaseline, Box, Alert, Snackbar, Typography } from '@mui/material'
import theme from './theme'
import { Sidebar } from './components/Sidebar'
import { PipelinePanel } from './components/sections/PipelinePanel'
import { StepConfig } from './components/sections/StepConfig'
import { OutputSettings } from './components/sections/OutputSettings'
import { AdvancedSettings } from './components/sections/AdvancedSettings'
import { LogPanel } from './components/sections/LogPanel'
import { Toolbar } from './components/sections/Toolbar'
import { FilePickerDialog } from './components/FilePickerDialog'
import { useConfig } from './hooks/useConfig'
import { usePipeline } from './hooks/usePipeline'
import { useSSE } from './hooks/useSSE'
import { useBatch } from './hooks/useBatch'
import type { PipelineMode } from './types'

export default function App() {
  const [activeTab, setActiveTab] = useState('主界面')
  const [mode, setMode] = useState<PipelineMode>('single')
  const { config, updateConfig, resetConfig } = useConfig()
  const { status, logs, appendLog, handleDone, startPipeline, cancelPipeline } = usePipeline()
  const {
    batch, activeVideoJobId,
    startBatch, cancelBatch, skipCurrent,
    viewVideoLogs,
  } = useBatch()

  const [filePickerOpen, setFilePickerOpen] = useState(false)
  const [batchFiles, setBatchFiles] = useState<string[]>([])
  const [snackbar, setSnackbar] = useState<{ open: boolean; msg: string; severity: 'success' | 'error' | 'info' }>({
    open: false, msg: '', severity: 'info',
  })
  const [backendOnline, setBackendOnline] = useState(true)

  useEffect(() => {
    const ping = () => {
      fetch('/api/system/info')
        .then(r => setBackendOnline(r.ok))
        .catch(() => setBackendOnline(false))
    }
    ping()
    const interval = setInterval(ping, 30000)
    return () => clearInterval(interval)
  }, [])

  // SSE: batch mode uses active video's jobId, single mode uses status.jobId
  const sseJobId = mode === 'batch' ? activeVideoJobId : status.jobId
  useSSE(sseJobId, appendLog, handleDone, () => {})

  const showMsg = useCallback((msg: string, severity: 'success' | 'error' | 'info' = 'info') => {
    setSnackbar({ open: true, msg, severity })
  }, [])

  const handleReorderFiles = useCallback((reordered: string[]) => {
    setBatchFiles(reordered)
  }, [])

  const handleRemoveFile = useCallback((path: string) => {
    setBatchFiles(prev => prev.filter(p => p !== path))
  }, [])

  const handleSelectFile = useCallback(() => {
    setFilePickerOpen(true)
  }, [])

  const handleFileSelected = useCallback((path: string) => {
    updateConfig('videoPath', path)
    setFilePickerOpen(false)
    showMsg(`已选择: ${path}`, 'success')
  }, [updateConfig, showMsg])

  const handleBatchFilesSelected = useCallback((paths: string[], replace?: boolean) => {
    if (replace) {
      setBatchFiles(paths)
    } else {
      setBatchFiles(prev => {
        const existing = new Set(prev)
        for (const p of paths) existing.add(p)
        return Array.from(existing)
      })
    }
    setFilePickerOpen(false)
    showMsg(`已添加 ${paths.length} 个视频`, 'success')
  }, [showMsg])

  const handleStart = useCallback(() => {
    if (!config.videoPath) {
      showMsg('请先选择视频文件', 'error')
      return
    }
    startPipeline(config)
    setActiveTab('日志与反馈')
  }, [config, startPipeline, showMsg])

  const handleForceRetry = useCallback(() => {
    if (!config.videoPath) {
      showMsg('请先选择视频文件', 'error')
      return
    }
    updateConfig('forceRetry', true)
    startPipeline(config)
    setActiveTab('日志与反馈')
  }, [config, updateConfig, startPipeline, showMsg])

  const handleStartBatch = useCallback(async () => {
    if (batchFiles.length === 0) {
      showMsg('请先添加视频文件', 'error')
      return
    }
    try {
      await startBatch(batchFiles, config)
      setActiveTab('日志与反馈')
    } catch (e: any) {
      showMsg(e.message || '批次启动失败', 'error')
    }
  }, [batchFiles, config, startBatch, showMsg])

  const handleModeChange = useCallback((newMode: PipelineMode) => {
    if (status.state === 'running' || batch.status === 'running') return
    setMode(newMode)
  }, [status.state, batch.status])

  const handleSaveConfig = useCallback(() => {
    const { videoPath, outputPath, forceRetry, defaultVideoDir, ...toSave } = config
    fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(toSave),
    })
      .then(r => { if (r.ok) showMsg('配置已保存', 'success'); else showMsg('保存失败', 'error') })
      .catch(() => showMsg('保存失败', 'error'))
  }, [config, showMsg])

  const logHeaderLabel = mode === 'batch' && activeVideoJobId
    ? `查看日志: ${(batch.videos.find(v => v.job_id === activeVideoJobId) || {} as any).video_name || activeVideoJobId}`
    : undefined

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
        <Sidebar activeTab={activeTab} onTabChange={setActiveTab} />
        <Box sx={{ flexGrow: 1, overflow: 'auto', p: 4, pt: 3, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {activeTab === '主界面' && (
            <PipelinePanel
              config={config}
              onConfigChange={updateConfig}
              status={status}
              onStart={handleStart}
              onCancel={cancelPipeline}
              onForceRetry={handleForceRetry}
              onSelectFile={handleSelectFile}
              mode={mode}
              onModeChange={handleModeChange}
              batch={batch}
              batchFiles={batchFiles}
              onStartBatch={handleStartBatch}
              onCancelBatch={cancelBatch}
              onSkipCurrent={skipCurrent}
              onViewLogs={viewVideoLogs}
              activeVideoJobId={activeVideoJobId}
              onAddFiles={() => setFilePickerOpen(true)}
              onReorderFiles={handleReorderFiles}
              onRemoveFile={handleRemoveFile}
            />
          )}
          {activeTab === '步骤配置' && <StepConfig config={config} onConfigChange={updateConfig} />}
          {activeTab === '输出设置' && (
            <Box sx={{ maxWidth: 600 }}>
              <OutputSettings config={config} onConfigChange={updateConfig} showTitle={false} />
            </Box>
          )}
          {activeTab === '高级设置' && (
            <Box>
              <AdvancedSettings config={config} onConfigChange={updateConfig} showTitle={false} />
            </Box>
          )}
          {activeTab === '日志与反馈' && (
            <Box sx={{ maxWidth: 800 }}>
              <LogPanel logs={logs} showTitle={false} headerLabel={logHeaderLabel} />
            </Box>
          )}
          {activeTab === '工具栏' && (
            <Toolbar
              onImportVideo={handleSelectFile}
              onImportSubtitles={() => showMsg('字幕导入功能开发中', 'info')}
              onExportVideo={() => showMsg('导出功能开发中', 'info')}
              onQuickConfig={resetConfig}
              onSaveConfig={handleSaveConfig}
            />
          )}
        </Box>
      </Box>

      <FilePickerDialog
        open={filePickerOpen}
        onSelect={handleFileSelected}
        onClose={() => setFilePickerOpen(false)}
        initialPath={config.defaultVideoDir}
        multiple={mode === 'batch'}
        onSelectMultiple={handleBatchFilesSelected}
      />

      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={() => setSnackbar(prev => ({ ...prev, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity={snackbar.severity} onClose={() => setSnackbar(prev => ({ ...prev, open: false }))} variant="filled">
          {snackbar.msg}
        </Alert>
      </Snackbar>
      <Box sx={{ position: 'fixed', bottom: 0, left: 0, right: 0, bgcolor: 'grey.900', py: 0.5, px: 2, display: 'flex', alignItems: 'center', gap: 1, zIndex: 2000 }}>
        <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: backendOnline ? '#4caf50' : '#f44336' }} />
        <Typography variant="caption" color="text.secondary">
          {backendOnline ? '后端已连接' : '后端未连接'}
        </Typography>
      </Box>
    </ThemeProvider>
  )
}
