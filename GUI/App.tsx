import { useState, useCallback, useEffect } from 'react'
import { ThemeProvider, CssBaseline, Box, Alert, Snackbar, Typography } from '@mui/material'
import theme from './theme'
import { Sidebar } from './components/Sidebar'
import { PipelinePanel } from './components/sections/PipelinePanel'
import { StepConfig } from './components/sections/StepConfig'
import { OutputSettings } from './components/sections/OutputSettings'
import { AdvancedSettings } from './components/sections/AdvancedSettings'
import { Toolbar } from './components/sections/Toolbar'
import { FilePickerDialog } from './components/FilePickerDialog'
import { SubtitleOptimizerDialog } from './components/SubtitleOptimizerDialog'
import { SubtitleReview } from './components/sections/SubtitleReview'
import { KeepAliveSection } from './components/KeepAliveSection'
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
  const [subtitleOptimizerOpen, setSubtitleOptimizerOpen] = useState(false)
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
  }, [config, startPipeline, showMsg])

  const handleForceRetry = useCallback(() => {
    if (!config.videoPath) {
      showMsg('请先选择视频文件', 'error')
      return
    }
    updateConfig('forceRetry', true)
    startPipeline(config)
  }, [config, updateConfig, startPipeline, showMsg])

  const handleStartBatch = useCallback(async () => {
    if (batchFiles.length === 0) {
      showMsg('请先添加视频文件', 'error')
      return
    }
    try {
      await startBatch(batchFiles, config)
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

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
        <Sidebar activeTab={activeTab} onTabChange={setActiveTab} />
        <Box sx={{ flexGrow: 1, overflow: 'auto', p: 4, pt: 3, display: 'flex', flexDirection: 'column', gap: 4 }}>
          <KeepAliveSection active={activeTab === '主界面'}>
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
              logs={logs}
            />
          </KeepAliveSection>
          <KeepAliveSection active={activeTab === '步骤配置'}>
            <StepConfig config={config} onConfigChange={updateConfig} />
          </KeepAliveSection>
          <KeepAliveSection active={activeTab === '输出设置'}>
            <Box sx={{ maxWidth: 600 }}>
              <OutputSettings config={config} onConfigChange={updateConfig} showTitle={false} />
            </Box>
          </KeepAliveSection>
          <KeepAliveSection active={activeTab === '高级设置'}>
            <Box>
              <AdvancedSettings config={config} onConfigChange={updateConfig} showTitle={false} />
            </Box>
          </KeepAliveSection>
          <KeepAliveSection active={activeTab === '工具栏'}>
            <Toolbar
              onImportVideo={handleSelectFile}
              onOptimizeSubtitles={() => setSubtitleOptimizerOpen(true)}
              onReviewSubtitles={() => setActiveTab('字幕校准')}
              onExportVideo={() => showMsg('导出功能开发中', 'info')}
              onQuickConfig={resetConfig}
              onSaveConfig={handleSaveConfig}
            />
          </KeepAliveSection>
          <KeepAliveSection active={activeTab === '字幕校准'}>
            <SubtitleReview videoPath={config.videoPath} onSuccess={(msg) => showMsg(msg, 'success')} isActive={activeTab === '字幕校准'} />
          </KeepAliveSection>
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

      <SubtitleOptimizerDialog
        open={subtitleOptimizerOpen}
        onClose={() => setSubtitleOptimizerOpen(false)}
        onSuccess={(msg) => showMsg(msg, 'success')}
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
