import { useState, useCallback, useEffect } from 'react'
import { ThemeProvider, CssBaseline, Box, Alert, Snackbar, Typography, Dialog, DialogTitle, DialogContent } from '@mui/material'
import CloudUploadOutlined from '@mui/icons-material/CloudUploadOutlined'
import theme from './theme'
import { Sidebar } from './components/Sidebar'
import { PipelinePanel } from './components/sections/PipelinePanel'
import { StepConfig } from './components/sections/StepConfig'
import { OutputSettings } from './components/sections/OutputSettings'
import { AdvancedSettings } from './components/sections/AdvancedSettings'
import { Toolbar } from './components/sections/Toolbar'
import { FilePickerDialog } from './components/FilePickerDialog'
import { SubtitleOptimizerDialog } from './components/SubtitleOptimizerDialog'
import { MediaMuxDialog } from './components/MediaMuxDialog'
import { SubtitleReview } from './components/sections/SubtitleReview'
import { KeepAliveSection } from './components/KeepAliveSection'
import { useConfig } from './hooks/useConfig'
import { usePipeline } from './hooks/usePipeline'
import { useSSE } from './hooks/useSSE'
import { useBatch } from './hooks/useBatch'
import type { PipelineMode } from './types'
import { DEFAULT_CONFIG } from './types'

export default function App() {
  const [activeTab, setActiveTab] = useState('主界面')
  const [mode, setMode] = useState<PipelineMode>('single')
  const { config, updateConfig, resetConfig } = useConfig()
  const { status, logs, appendLog, handleDone, startPipeline, cancelPipeline, logFirstIndex, logTotal, loadOlderLogs } = usePipeline()
  const {
    batch, activeVideoJobId,
    startBatch, cancelBatch, skipCurrent,
    viewVideoLogs,
  } = useBatch()

  const [filePickerOpen, setFilePickerOpen] = useState(false)
  const [subtitleOptimizerOpen, setSubtitleOptimizerOpen] = useState(false)
  const [mediaMuxOpen, setMediaMuxOpen] = useState(false)
  const [outputSettingsOpen, setOutputSettingsOpen] = useState(false)
  const [batchFiles, setBatchFiles] = useState<string[]>([])
  const [snackbar, setSnackbar] = useState<{ open: boolean; msg: string; severity: 'success' | 'error' | 'info' }>({
    open: false, msg: '', severity: 'info',
  })
  const [reviewSaved, setReviewSaved] = useState(false)
  const [prefillSrt, setPrefillSrt] = useState<{ source: string; translated: string; log: string; workspace: string } | null>(null)
  const [backendOnline, setBackendOnline] = useState(true)
  const [dragOverWindow, setDragOverWindow] = useState(false)

  // ---- Window-level drag overlay ----
  useEffect(() => {
    let counter = 0
    const onDragEnter = (e: DragEvent) => {
      e.preventDefault()
      if (e.dataTransfer?.types.includes('Files')) {
        counter++
        if (counter === 1) setDragOverWindow(true)
      }
    }
    const onDragLeave = (e: DragEvent) => {
      e.preventDefault()
      if (e.dataTransfer?.types.includes('Files')) {
        counter--
        if (counter <= 0) { counter = 0; setDragOverWindow(false) }
      }
    }
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
  const { connectionState } = useSSE(sseJobId, appendLog, handleDone, () => {})

  const showMsg = useCallback((msg: string, severity: 'success' | 'error' | 'info' = 'info') => {
    setSnackbar({ open: true, msg, severity })
  }, [])

  const handleFileDropped = useCallback(async (file: File) => {
    // 1. Try to find the file on the server filesystem by name+size
    const q = `name=${encodeURIComponent(file.name)}&size=${file.size}`
    try {
      const findRes = await fetch(`/api/files/find?${q}`)
      if (findRes.ok) {
        const data = await findRes.json()
        updateConfig('videoPath', data.path)
        showMsg(`已选择: ${data.name}`, 'success')
        return
      }
    } catch (_) { /* fall through to upload */ }

    // 2. Not found on disk — upload the file bytes
    showMsg(`正在导入 "${file.name}"...`, 'info')
    const form = new FormData()
    form.append('file', file)
    try {
      const upRes = await fetch('/api/files/upload', { method: 'POST', body: form })
      if (!upRes.ok) {
        const err = await upRes.json().catch(() => ({ detail: upRes.statusText }))
        showMsg(`导入失败: ${(err as any).detail || upRes.statusText}`, 'error')
        return
      }
      const data = await upRes.json()
      updateConfig('videoPath', data.path)
      showMsg(`已导入: ${data.name}`, 'success')
    } catch (e: any) {
      showMsg(`导入失败: ${e.message}`, 'error')
    }
  }, [updateConfig, showMsg])

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

  const handleExportConfig = useCallback(() => {
    const { videoPath, outputPath, forceRetry, defaultVideoDir, ...toExport } = config
    const blob = new Blob([JSON.stringify(toExport, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const now = new Date()
    const ts = `${now.getFullYear()}${String(now.getMonth()+1).padStart(2,'0')}${String(now.getDate()).padStart(2,'0')}-${String(now.getHours()).padStart(2,'0')}${String(now.getMinutes()).padStart(2,'0')}${String(now.getSeconds()).padStart(2,'0')}`
    a.href = url
    a.download = `pipeline-config-${ts}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    showMsg('配置已导出', 'success')
  }, [config, showMsg])

  const handleImportConfig = useCallback((file: File) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      try {
        const raw = JSON.parse(e.target?.result as string)
        if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
          showMsg('无效的配置文件格式', 'error')
          return
        }
        const validKeys = Object.keys(DEFAULT_CONFIG)
        const transientKeys = new Set(['videoPath', 'outputPath', 'forceRetry', 'defaultVideoDir'])
        let imported = 0
        for (const key of Object.keys(raw)) {
          if (!validKeys.includes(key) || transientKeys.has(key)) continue
          const expectedType = typeof (DEFAULT_CONFIG as any)[key]
          const valueType = typeof raw[key]
          if (expectedType === 'string' && valueType === 'number') {
            (updateConfig as any)(key, String(raw[key]))
            imported++
          } else if (valueType === expectedType || (expectedType === 'boolean' && valueType === 'boolean')) {
            (updateConfig as any)(key, raw[key])
            imported++
          }
        }
        showMsg(`已导入 ${imported} 项配置`, 'success')
      } catch {
        showMsg('配置文件解析失败，请检查文件内容', 'error')
      }
    }
    reader.readAsText(file)
  }, [updateConfig, showMsg])

  const handleStartReview = useCallback(() => {
    if (!config.videoPath) return
    const path = config.videoPath.replace(/\\/g, '/')
    const dir = path.substring(0, path.lastIndexOf('/'))
    const dot = path.lastIndexOf('.')
    const stem = dot > path.lastIndexOf('/') ? path.substring(path.lastIndexOf('/') + 1, dot) : path.substring(path.lastIndexOf('/') + 1)
    const workspace = `${dir}/${stem}_project`
    const sourceSrt = `${workspace}/01_extract/source.srt`
    const translatedSrt = `${workspace}/02_translate/machine.srt`
    const translateLog = `${workspace}/02_translate/translate-log.json`
    setPrefillSrt({ source: sourceSrt, translated: translatedSrt, log: translateLog, workspace })
    setActiveTab('字幕校准')
    setReviewSaved(false)
  }, [config.videoPath])

  const handleOpenOutputFolder = useCallback(async () => {
    if (!config.videoPath) return
    try {
      const res = await fetch(`/api/files/open-folder?video_path=${encodeURIComponent(config.videoPath)}`, { method: 'POST' })
      if (!res.ok) showMsg('输出目录尚不存在，请先完成一次处理', 'error')
    } catch (e: any) {
      showMsg(`打开失败: ${e.message}`, 'error')
    }
  }, [config.videoPath, showMsg])

  const handleContinueTTS = useCallback(() => {
    if (!config.videoPath) return
    startPipeline({ ...config, enableExtract: false, enableTranslate: false, enableTTS: true })
    setReviewSaved(false)
  }, [config, startPipeline])

  const handleReviewSaved = useCallback(() => {
    setReviewSaved(true)
  }, [])

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
              connectionState={connectionState}
              onStartReview={handleStartReview}
              reviewSaved={reviewSaved}
              onContinueTTS={handleContinueTTS}
              onFileDropped={handleFileDropped}
              onOpenOutputFolder={handleOpenOutputFolder}
              logFirstIndex={logFirstIndex.current}
              logTotal={logTotal.current}
              onLoadOlderLogs={() => loadOlderLogs(status.jobId)}
            />
          </KeepAliveSection>
          <KeepAliveSection active={activeTab === '步骤配置'}>
            <StepConfig config={config} onConfigChange={updateConfig} />
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
              onMediaMux={() => setMediaMuxOpen(true)}
              onOutputSettings={() => setOutputSettingsOpen(true)}
              onQuickConfig={resetConfig}
              onSaveConfig={handleSaveConfig}
              onExportConfig={handleExportConfig}
              onImportConfig={handleImportConfig}
            />
          </KeepAliveSection>
          <KeepAliveSection active={activeTab === '字幕校准'}>
            <SubtitleReview
              videoPath={config.videoPath}
              onSuccess={(msg) => { showMsg(msg, 'success'); handleReviewSaved() }}
              isActive={activeTab === '字幕校准'}
              prefillSourceSrt={prefillSrt?.source}
              prefillTranslatedSrt={prefillSrt?.translated}
              prefillTranslateLog={prefillSrt?.log}
              prefillWorkspace={prefillSrt?.workspace}
            />
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

      <MediaMuxDialog
        open={mediaMuxOpen}
        onClose={() => setMediaMuxOpen(false)}
        onSuccess={(msg) => showMsg(msg, 'success')}
        initialPath={config.defaultVideoDir}
      />

      <Dialog open={outputSettingsOpen} onClose={() => setOutputSettingsOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>输出设置</DialogTitle>
        <DialogContent sx={{ pt: 1 }}>
          <OutputSettings config={config} onConfigChange={updateConfig} showTitle={false} />
        </DialogContent>
      </Dialog>

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

      {/* Full-page drag overlay */}
      {dragOverWindow && mode === 'single' && (
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
            border: '4px dashed', borderColor: 'primary.main',
            m: 4, borderRadius: 4,
          }}>
          <CloudUploadOutlined sx={{ fontSize: 80, color: 'primary.main', mb: 3, opacity: 0.9 }} />
          <Typography variant="h4" color="white" fontWeight={600}>释放以选择视频文件</Typography>
          <Typography variant="body1" color="rgba(255,255,255,0.6)" mt={1}>支持 .mp4 / .mkv / .avi / .mov 等常见格式</Typography>
        </Box>
      )}

      <Box sx={{ position: 'fixed', bottom: 0, left: 0, right: 0, bgcolor: 'grey.900', py: 0.5, px: 2, display: 'flex', alignItems: 'center', gap: 1, zIndex: 2000 }}>
        <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: backendOnline ? '#4caf50' : '#f44336' }} />
        <Typography variant="caption" color="text.secondary">
          {backendOnline ? '后端已连接' : '后端未连接'}
        </Typography>
      </Box>
    </ThemeProvider>
  )
}
