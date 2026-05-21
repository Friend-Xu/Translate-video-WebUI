import { useCallback, useEffect, useState } from 'react'
import { CloudUploadOutlined, InsertDriveFileOutlined } from '@mui/icons-material'
import {
  Box, Typography, Card, CardContent, Button, Select, MenuItem,
  LinearProgress, Stack, Checkbox, FormControlLabel, Divider,
  ToggleButtonGroup, ToggleButton, Chip, List, ListItemButton, ListItemText,
} from '@mui/material'
import Grid from '@mui/material/Grid'
import FolderOpenIcon from '@mui/icons-material/FolderOpenRounded'
import SmartDisplayIcon from '@mui/icons-material/SmartDisplayRounded'
import ViewModuleIcon from '@mui/icons-material/ViewModuleRounded'
import PlayArrowIcon from '@mui/icons-material/PlayArrowRounded'
import StopIcon from '@mui/icons-material/StopRounded'
import RefreshIcon from '@mui/icons-material/RefreshRounded'
import SkipNextIcon from '@mui/icons-material/SkipNextRounded'
import LanguageIcon from '@mui/icons-material/LanguageRounded'
import MemoryIcon from '@mui/icons-material/MemoryRounded'
import DeveloperBoardIcon from '@mui/icons-material/DeveloperBoardRounded'
import AddIcon from '@mui/icons-material/AddRounded'
import { DndContext, closestCenter, KeyboardSensor, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy, arrayMove } from '@dnd-kit/sortable'
import { SectionHeader } from '../SectionHeader'
import { ControlCard } from '../ControlCard'
import { SortableVideoItem } from '../SortableVideoItem'
import { LogPanel } from './LogPanel'
import type { PipelineConfig, PipelineStatus, PipelineMode, BatchStatus, LogEntry } from '../../types'

interface PipelinePanelProps {
  config: PipelineConfig
  onConfigChange: <K extends keyof PipelineConfig>(key: K, value: PipelineConfig[K]) => void
  status: PipelineStatus
  onStart: () => void
  onCancel: () => void
  onForceRetry: () => void
  onSelectFile: () => void
  mode: PipelineMode
  onModeChange: (mode: PipelineMode) => void
  batch: BatchStatus
  batchFiles: string[]
  onStartBatch: () => void
  onCancelBatch: () => void
  onSkipCurrent: () => void
  onViewLogs: (jobId: string | null) => void
  activeVideoJobId: string | null
  onAddFiles: () => void
  onReorderFiles: (reordered: string[]) => void
  onRemoveFile: (path: string) => void
  logs: LogEntry[]
  connectionState?: 'connected' | 'reconnecting' | 'closed'
  onStartReview?: () => void
  reviewSaved?: boolean
  onContinueTTS?: () => void
  onFileDropped?: (file: File) => void
  onOpenOutputFolder?: () => void
  logFirstIndex?: number
  logTotal?: number
  onLoadOlderLogs?: () => void
}

const statusChipColor: Record<string, 'default' | 'primary' | 'success' | 'error' | 'warning'> = {
  queued: 'default',
  running: 'primary',
  completed: 'success',
  failed: 'error',
  cancelled: 'warning',
}

const statusLabel: Record<string, string> = {
  queued: '排队中',
  running: '处理中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

export function PipelinePanel({
  config, onConfigChange, status,
  onStart, onCancel, onForceRetry, onSelectFile,
  mode, onModeChange,
  batch, batchFiles,
  onStartBatch, onCancelBatch, onSkipCurrent,
  onViewLogs, activeVideoJobId,
  onAddFiles, onReorderFiles, onRemoveFile,
  logs, connectionState,
  onStartReview,
  reviewSaved = false,
  onContinueTTS,
  onFileDropped,
  onOpenOutputFolder,
  logFirstIndex, logTotal, onLoadOlderLogs,
}: PipelinePanelProps) {

  const isRunning = status.state === 'running' || batch.status === 'running'
  const [dragOver, setDragOver] = useState(false)
  const [videoInfo, setVideoInfo] = useState<{ duration: number; width: number; height: number } | null>(null)

  useEffect(() => {
    if (mode === 'single' && config.videoPath) {
      fetch(`/api/video/info?path=${encodeURIComponent(config.videoPath)}`)
        .then(r => r.ok ? r.json() : Promise.reject(r.status))
        .then((info: any) => {
          if (info.duration > 0 || info.width > 0) setVideoInfo(info)
          else setVideoInfo(null)
        })
        .catch(() => setVideoInfo(null))
    } else {
      setVideoInfo(null)
    }
  }, [config.videoPath, mode])

  // Translation is complete when pipeline has moved past the translate step into TTS, or finished entirely
  const translationComplete =
    status.state === 'completed' ||
    status.currentStep.includes('TTS')

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const handleDragEnd = useCallback((event: any) => {
    const { active, over } = event
    if (over && active.id !== over.id) {
      const oldIndex = batchFiles.indexOf(active.id as string)
      const newIndex = batchFiles.indexOf(over.id as string)
      const reordered = arrayMove(batchFiles, oldIndex, newIndex)
      onReorderFiles(reordered)
    }
  }, [batchFiles, onReorderFiles])

  // ---- Drag-and-drop from OS ----
  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation()
    if (e.dataTransfer.types.includes('Files')) setDragOver(true)
  }, [])
  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation()
    // Only set false if leaving the card itself (not a child)
    if ((e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) return
    setDragOver(false)
  }, [])
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation()
  }, [])
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file && onFileDropped) onFileDropped(file)
  }, [onFileDropped])

  const logHeaderLabel = mode === 'batch' && activeVideoJobId
    ? `查看日志: ${(batch.videos.find(v => v.job_id === activeVideoJobId) || {} as any).video_name || activeVideoJobId}`
    : undefined

  const controlsCard = (
    <Card>
      <CardContent>
        <Typography variant="subtitle2" gutterBottom>步骤控制</Typography>

        <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, auto)', columnGap: 1, mb: 2, alignItems: 'start' }}>
          {/* Column 1: 字幕提取 + 子功能 */}
          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
            <FormControlLabel
              control={<Checkbox size="small" checked={config.enableExtract} onChange={e => onConfigChange('enableExtract', e.target.checked)} disabled={isRunning} />}
              label={<Typography variant="body2">启用字幕提取</Typography>}
            />
            <Box sx={{ display: 'flex', alignItems: 'center', position: 'relative', height: 32 }}>
              <Box sx={{ position: 'relative', width: 22, height: 32, flexShrink: 0 }}>
                <Box sx={{ position: 'absolute', left: 11, top: -4, height: 36, width: 2, bgcolor: 'primary.main' }} />
                <Box sx={{ position: 'absolute', left: 11, top: 14, width: 10, height: 2, bgcolor: 'primary.main' }} />
              </Box>
              <FormControlLabel
                control={<Checkbox size="small" checked={config.enableDefectCheck} onChange={e => onConfigChange('enableDefectCheck', e.target.checked)} disabled={isRunning || !config.enableExtract} />}
                label={<Typography variant="body2" sx={{ color: !config.enableExtract ? 'text.disabled' : undefined }}>启用音频缺陷检测</Typography>}
              />
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', position: 'relative', height: 32 }}>
              <Box sx={{ position: 'relative', width: 22, height: 32, flexShrink: 0 }}>
                <Box sx={{ position: 'absolute', left: 11, top: -4, height: 20, width: 2, bgcolor: 'primary.main' }} />
                <Box sx={{ position: 'absolute', left: 11, top: 14, width: 10, height: 2, bgcolor: 'primary.main' }} />
              </Box>
              <FormControlLabel
                control={<Checkbox size="small" checked={config.enableAlignment} onChange={e => onConfigChange('enableAlignment', e.target.checked)} disabled={isRunning || !config.enableExtract} />}
                label={<Typography variant="body2" sx={{ color: !config.enableExtract ? 'text.disabled' : undefined }}>启用 wav2vec2 强制对齐</Typography>}
              />
            </Box>
          </Box>
          {/* Column 2: 翻译 + 子功能 */}
          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
            <FormControlLabel
              control={<Checkbox size="small" checked={config.enableTranslate} onChange={e => onConfigChange('enableTranslate', e.target.checked)} disabled={isRunning} />}
              label={<Typography variant="body2">启用翻译</Typography>}
            />
            <Box sx={{ display: 'flex', alignItems: 'center', position: 'relative', height: 32 }}>
              <Box sx={{ position: 'relative', width: 22, height: 32, flexShrink: 0 }}>
                <Box sx={{ position: 'absolute', left: 11, top: -4, height: 36, width: 2, bgcolor: 'primary.main' }} />
                <Box sx={{ position: 'absolute', left: 11, top: 14, width: 10, height: 2, bgcolor: 'primary.main' }} />
              </Box>
              <FormControlLabel
                control={<Checkbox size="small" checked={config.enableSemanticValidation} onChange={e => onConfigChange('enableSemanticValidation', e.target.checked)} disabled={isRunning || !config.enableTranslate} />}
                label={<Typography variant="body2" sx={{ color: !config.enableTranslate ? 'text.disabled' : undefined }}>启用语义校验 (MiniLM)</Typography>}
              />
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', position: 'relative', height: 32 }}>
              <Box sx={{ position: 'relative', width: 22, height: 32, flexShrink: 0 }}>
                <Box sx={{ position: 'absolute', left: 11, top: 0, height: 32, width: 2, bgcolor: 'primary.main' }} />
                <Box sx={{ position: 'absolute', left: 11, top: 14, width: 10, height: 2, bgcolor: 'primary.main' }} />
              </Box>
              <FormControlLabel
                control={<Checkbox size="small"
                  checked={config.enableNaturalnessCheck && (config.targetLang === 'zh-CN' || config.targetLang === 'en')}
                  onChange={e => onConfigChange('enableNaturalnessCheck', e.target.checked)}
                  disabled={isRunning || !config.enableTranslate || !config.enableSemanticValidation || (config.targetLang !== 'zh-CN' && config.targetLang !== 'en')}
                />}
                label={
                  <Typography variant="body2" sx={{ color: (!config.enableTranslate || !config.enableSemanticValidation || (config.targetLang !== 'zh-CN' && config.targetLang !== 'en')) ? 'text.disabled' : undefined }}>
                    启用自然度检查 (PPL) {config.targetLang !== 'zh-CN' && config.targetLang !== 'en' ? '— 仅中文/英文有效' : ''}
                  </Typography>
                }
              />
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', position: 'relative', height: 32 }}>
              <Box sx={{ position: 'relative', width: 22, height: 32, flexShrink: 0 }}>
                <Box sx={{ position: 'absolute', left: 11, top: 0, height: 32, width: 2, bgcolor: 'primary.main' }} />
                <Box sx={{ position: 'absolute', left: 11, top: 14, width: 10, height: 2, bgcolor: 'primary.main' }} />
              </Box>
              <FormControlLabel
                control={<Checkbox size="small" checked={config.enableTermReplacement} onChange={e => onConfigChange('enableTermReplacement', e.target.checked)} disabled={isRunning || !config.enableTranslate} />}
                label={<Typography variant="body2" sx={{ color: !config.enableTranslate ? 'text.disabled' : undefined }}>启用术语表</Typography>}
              />
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', position: 'relative', height: 32 }}>
              <Box sx={{ position: 'relative', width: 22, height: 32, flexShrink: 0 }}>
                <Box sx={{ position: 'absolute', left: 11, top: -4, height: 20, width: 2, bgcolor: 'primary.main' }} />
                <Box sx={{ position: 'absolute', left: 11, top: 14, width: 10, height: 2, bgcolor: 'primary.main' }} />
              </Box>
              <FormControlLabel
                control={<Checkbox size="small" checked={config.enableReviewAfterTranslate} onChange={e => onConfigChange('enableReviewAfterTranslate', e.target.checked)} disabled={isRunning || !config.enableTranslate} />}
                label={<Typography variant="body2" sx={{ color: !config.enableTranslate ? 'text.disabled' : undefined }}>翻译完成后先校验</Typography>}
              />
            </Box>
          </Box>
          {/* Column 3: TTS + 声音克隆（子功能） */}
          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
            <FormControlLabel
              control={<Checkbox size="small" checked={config.enableTTS} onChange={e => onConfigChange('enableTTS', e.target.checked)} disabled={isRunning} />}
              label={<Typography variant="body2">启用TTS合成</Typography>}
            />
            <Box sx={{ display: 'flex', alignItems: 'center', position: 'relative', height: 32 }}>
              <Box sx={{ position: 'relative', width: 22, height: 32, flexShrink: 0 }}>
                <Box sx={{ position: 'absolute', left: 11, top: -4, height: 20, width: 2, bgcolor: 'primary.main' }} />
                <Box sx={{ position: 'absolute', left: 11, top: 14, width: 10, height: 2, bgcolor: 'primary.main' }} />
              </Box>
              <FormControlLabel
                control={<Checkbox size="small" checked={config.enableVoiceClone} onChange={e => onConfigChange('enableVoiceClone', e.target.checked)} disabled={isRunning || !config.enableTTS} />}
                label={<Typography variant="body2" sx={{ color: !config.enableTTS ? 'text.disabled' : undefined }}>启用声音克隆</Typography>}
              />
              {(config.engine === 'indextts' || config.engine === 'cosyvoice') && (
                <Typography variant="caption" color="info.main" sx={{ ml: 4.5, display: 'block', mt: -0.5 }}>
                  {config.engine} 引擎已内置零样本音色克隆，无需独立 voice cloner
                </Typography>
              )}
            </Box>
          </Box>
        </Box>

        <Divider sx={{ mb: 2 }} />

        <Stack direction="row" spacing={2} sx={{ mb: 3 }}>
          {mode === 'single' ? (
            <>
              {status.state === 'running' ? (
                <Button variant="contained" color="error" startIcon={<StopIcon />} onClick={onCancel}>
                  取消处理
                </Button>
              ) : translationComplete && reviewSaved && onContinueTTS ? (
                <Button variant="contained" color="success" startIcon={<PlayArrowIcon />} onClick={onContinueTTS}>
                  继续TTS合成
                </Button>
              ) : (
                <Button variant="contained" startIcon={<PlayArrowIcon />} onClick={onStart} disabled={!config.videoPath}>
                  开始处理
                </Button>
              )}
              <Button variant="outlined" color="error" startIcon={<RefreshIcon />} onClick={onForceRetry}
                disabled={status.state === 'running'}>
                强制重新执行
              </Button>
            </>
          ) : (
            <>
              {batch.status === 'running' ? (
                <>
                  <Button variant="contained" color="error" startIcon={<StopIcon />} onClick={onCancelBatch}>
                    取消批次
                  </Button>
                  <Button variant="outlined" startIcon={<SkipNextIcon />} onClick={onSkipCurrent}>
                    跳过当前
                  </Button>
                </>
              ) : (
                <Button variant="contained" startIcon={<PlayArrowIcon />} onClick={onStartBatch} disabled={batchFiles.length === 0}>
                  开始批处理
                </Button>
              )}
            </>
          )}
        </Stack>

        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
          <Typography variant="subtitle2">
            {mode === 'single'
              ? (status.state === 'idle' ? '就绪' : status.currentStep)
              : (batch.status === 'idle' ? '就绪' : batch.status === 'running'
                ? `处理中 (${batch.completed_count + 1}/${batch.total_count})`
                : batch.status === 'completed' ? '全部完成' : batch.status === 'partial' ? '部分完成' : batch.status
              )
            }
          </Typography>
          <Typography variant="body2" fontWeight={600} color="primary">
            {mode === 'single'
              ? `${status.progress}%`
              : `${batch.total_count > 0 ? Math.round(batch.completed_count / batch.total_count * 100) : 0}%`
            }
          </Typography>
        </Box>
        <LinearProgress
          variant="determinate"
          value={
            mode === 'single'
              ? status.progress
              : batch.total_count > 0 ? (batch.completed_count / batch.total_count) * 100 : 0
          }
        />
        {config.videoPath && onOpenOutputFolder && (
          <Button
            variant="outlined"
            size="small"
            startIcon={<FolderOpenIcon />}
            onClick={onOpenOutputFolder}
            sx={{ mt: 2, borderRadius: 2 }}
          >
            {status.state === 'completed' ? '打开输出文件夹' : '打开视频所在目录'}
          </Button>
        )}
      </CardContent>
    </Card>
  )

  return (
    <>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-start', mb: 1 }}>
        <SectionHeader title="主界面 (Pipeline 控制面板)" />
        <ToggleButtonGroup
          value={mode}
          exclusive
          onChange={(_, v) => v && onModeChange(v)}
          size="small"
          sx={{
            '& .MuiToggleButton-root': {
              '&.Mui-selected': {
                bgcolor: 'primary.main',
                color: 'primary.contrastText',
                '&:hover': { bgcolor: 'primary.dark' },
              },
            },
          }}
        >
          <ToggleButton value="single">
            <SmartDisplayIcon fontSize="small" sx={{ mr: 0.5 }} />
            单视频
          </ToggleButton>
          <ToggleButton value="batch">
            <ViewModuleIcon fontSize="small" sx={{ mr: 0.5 }} />
            批处理
          </ToggleButton>
        </ToggleButtonGroup>
      </Box>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 3 }}>
          {mode === 'single' ? (
            <Card
              onDragEnter={handleDragEnter}
              onDragLeave={handleDragLeave}
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              sx={{
                height: '100%', display: 'flex', flexDirection: 'column',
                bgcolor: dragOver ? 'primary.dark' : 'action.hover',
                border: '2px dashed',
                borderColor: dragOver ? 'primary.main' : config.videoPath ? 'success.main' : 'divider',
                transition: 'all 0.2s ease',
                transform: dragOver ? 'scale(1.02)' : 'scale(1)',
                boxShadow: dragOver ? 6 : 0,
                cursor: 'pointer',
              }}
              onClick={() => !config.videoPath && onSelectFile()}
            >
              <CardContent sx={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', flex: 1, gap: 1.5 }}>
                <Box display="flex" alignItems="center" gap={1}>
                  {config.videoPath ? (
                    <InsertDriveFileOutlined color="success" />
                  ) : (
                    <CloudUploadOutlined color={dragOver ? 'inherit' : 'primary'} sx={{ fontSize: 32, opacity: dragOver ? 1 : 0.7 }} />
                  )}
                  <Typography variant="body1" fontWeight={600} color={dragOver ? 'white' : 'text.primary'}>
                    {config.videoPath ? '视频已选择' : dragOver ? '释放以选择文件' : '视频导入'}
                  </Typography>
                </Box>
                {config.videoPath ? (
                  <>
                    <TextFieldDisplay value={config.videoPath.split(/[\\/]/).pop() || config.videoPath} placeholder="" />
                    {videoInfo && (
                      <Box display="flex" gap={2} flexWrap="wrap">
                        {videoInfo.duration > 0 && (
                          <Typography variant="caption" color="text.secondary">
                            {Math.floor(videoInfo.duration / 60)}:{String(Math.floor(videoInfo.duration % 60)).padStart(2, '0')}
                          </Typography>
                        )}
                        {videoInfo.width > 0 && (
                          <Typography variant="caption" color="text.secondary">
                            {videoInfo.width}x{videoInfo.height}
                          </Typography>
                        )}
                      </Box>
                    )}
                    <Button variant="outlined" size="small" disableElevation sx={{ borderRadius: 2 }} onClick={onSelectFile}>
                      更换文件
                    </Button>
                  </>
                ) : (
                  <>
                    <Typography variant="body2" color={dragOver ? 'rgba(255,255,255,0.7)' : 'text.secondary'}>
                      将视频拖放到此处或点击选择
                    </Typography>
                    <Button variant="contained" size="small" disableElevation sx={{ borderRadius: 2 }} onClick={onSelectFile}>
                      选择文件
                    </Button>
                  </>
                )}
              </CardContent>
            </Card>
          ) : (
            <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column', bgcolor: 'action.hover', border: '2px dashed', borderColor: 'divider' }}>
              <CardContent sx={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', flex: 1, gap: 1.5 }}>
                <Box display="flex" alignItems="center" gap={1}>
                  <FolderOpenIcon color="primary" />
                  <Typography variant="body1" fontWeight={600} color="text.primary">
                    批次导入
                  </Typography>
                </Box>
                {batchFiles.length === 0 ? (
                  <Typography variant="body2" color="text.secondary">尚未选择视频文件</Typography>
                ) : (
                  <Typography variant="body2">已选 {batchFiles.length} 个视频</Typography>
                )}
                <Button variant="contained" size="small" disableElevation sx={{ borderRadius: 2 }} onClick={onAddFiles} startIcon={<AddIcon />}>
                  添加文件
                </Button>
              </CardContent>
            </Card>
          )}
        </Grid>

        <Grid size={{ xs: 12, md: 3 }}>
          <ControlCard icon={<LanguageIcon color="primary" />} title="语言设置" subtitle="源语言 / 目标语言">
            <Box sx={{ display: 'flex', gap: 1, mt: 1 }}>
              <Select size="small" fullWidth value={config.lang} onChange={e => onConfigChange('lang', e.target.value as PipelineConfig['lang'])}>
                <MenuItem value="auto">源: 自动检测</MenuItem>
                <MenuItem value="en">源: 英文</MenuItem>
                <MenuItem value="zh">源: 中文</MenuItem>
                <MenuItem value="ja">源: 日文</MenuItem>
              </Select>
              <Select size="small" fullWidth value={config.targetLang} onChange={e => onConfigChange('targetLang', e.target.value as PipelineConfig['targetLang'])}>
                <MenuItem value="zh-CN">目标: 简体中文</MenuItem>
                <MenuItem value="en">目标: English</MenuItem>
                <MenuItem value="ja">目标: 日本語</MenuItem>
                <MenuItem value="ko">目标: 한국어</MenuItem>
                <MenuItem value="auto">目标: 自动</MenuItem>
              </Select>
            </Box>
          </ControlCard>
        </Grid>

        <Grid size={{ xs: 12, md: 3 }}>
          <ControlCard icon={<MemoryIcon color="primary" />} title="Whisper 模型" subtitle="选择提取模型">
            <Select size="small" fullWidth value={config.model} onChange={e => onConfigChange('model', e.target.value as PipelineConfig['model'])} sx={{ mt: 1 }}>
              <MenuItem value="small">小型 (Small)</MenuItem>
              <MenuItem value="medium">中型 (Medium)</MenuItem>
              <MenuItem value="turbo">Turbo (推荐)</MenuItem>
              <MenuItem value="large-v3">大型 (Large-v3)</MenuItem>
            </Select>
          </ControlCard>
        </Grid>

        <Grid size={{ xs: 12, md: 3 }}>
          <ControlCard icon={<DeveloperBoardIcon color="primary" />} title="计算设备" subtitle="CPU / GPU">
            <Select size="small" fullWidth value={config.device} onChange={e => onConfigChange('device', e.target.value as PipelineConfig['device'])} sx={{ mt: 1 }}>
              <MenuItem value="cpu">CPU</MenuItem>
              <MenuItem value="cuda">GPU</MenuItem>
            </Select>
          </ControlCard>
        </Grid>
      </Grid>

      {mode === 'single' ? (
        <Grid container spacing={3} sx={{ mt: 0, alignItems: 'flex-start' }}>
          <Grid size={{ xs: 12, md: 5 }}>
            {controlsCard}
          </Grid>
          <Grid size={{ xs: 12, md: 7 }}>
            <LogPanel logs={logs} showTitle={false} reviewEnabled={translationComplete} onStartReview={onStartReview} connectionState={connectionState} logFirstIndex={logFirstIndex} logTotal={logTotal} onLoadOlder={onLoadOlderLogs} />
          </Grid>
        </Grid>
      ) : (
        <Grid container spacing={3} sx={{ mt: 0, alignItems: 'flex-start' }}>
          <Grid size={{ xs: 12, md: 5 }}>
            {batchFiles.length > 0 && (
              <Card sx={{ mb: 3 }}>
                <CardContent>
                  <Typography variant="subtitle2" gutterBottom>
                    批次文件列表
                    {batch.total_count > 0 && (
                      <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 1 }}>
                        （完成 {batch.completed_count}/{batch.total_count}{batch.failed_count > 0 ? `，失败 ${batch.failed_count}` : ''}）
                      </Typography>
                    )}
                  </Typography>
                  {batch.status === 'idle' ? (
                    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
                      <SortableContext items={batchFiles} strategy={verticalListSortingStrategy}>
                        <List dense sx={{ maxHeight: 200, overflow: 'auto', bgcolor: 'background.paper', borderRadius: 1, border: '1px solid', borderColor: 'divider' }}>
                          {batchFiles.map((videoPath) => {
                            const videoName = videoPath.split(/[/\\]/).pop() || videoPath
                            return (
                              <SortableVideoItem
                                key={videoPath}
                                id={videoPath}
                                videoName={videoName}
                                disabled={false}
                                selected={false}
                                progress={0}
                                statusLabel="排队中"
                                statusColor="default"
                                statusVariant="outlined"
                                onClick={() => {}}
                                onRemove={() => onRemoveFile(videoPath)}
                              />
                            )
                          })}
                        </List>
                      </SortableContext>
                    </DndContext>
                  ) : (
                    <List dense sx={{ maxHeight: 200, overflow: 'auto', bgcolor: 'background.paper', borderRadius: 1, border: '1px solid', borderColor: 'divider' }}>
                      {batch.videos.map((v) => (
                        <ListItemButton
                          key={v.video_path}
                          selected={activeVideoJobId === v.job_id}
                          onClick={() => onViewLogs(v.job_id)}
                          dense
                        >
                          <ListItemText
                            primary={v.video_name}
                            primaryTypographyProps={{ noWrap: true, fontSize: '0.875rem' }}
                            secondary={v.current_step}
                            secondaryTypographyProps={{ variant: 'caption' }}
                          />
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 200 }}>
                            <Box sx={{ flex: 1, maxWidth: 100 }}>
                              <LinearProgress variant="determinate" value={v.progress} sx={{ height: 4, borderRadius: 2 }} />
                            </Box>
                            <Chip
                              label={statusLabel[v.status] || v.status}
                              color={statusChipColor[v.status] || 'default'}
                              size="small"
                              variant={v.status === 'running' ? 'filled' : 'outlined'}
                            />
                          </Box>
                        </ListItemButton>
                      ))}
                    </List>
                  )}
                </CardContent>
              </Card>
            )}
            {controlsCard}
          </Grid>
          <Grid size={{ xs: 12, md: 7 }}>
            <LogPanel logs={logs} showTitle={false} headerLabel={logHeaderLabel} reviewEnabled={translationComplete} onStartReview={onStartReview} connectionState={connectionState} logFirstIndex={logFirstIndex} logTotal={logTotal} onLoadOlder={onLoadOlderLogs} />
          </Grid>
        </Grid>
      )}
    </>
  )
}

function TextFieldDisplay({ value, placeholder }: { value: string; placeholder: string }) {
  return (
    <Box sx={{ px: 1.5, py: 1, bgcolor: 'background.paper', borderRadius: 1, border: '1px solid', borderColor: 'divider', fontSize: '0.875rem', minHeight: 36, display: 'flex', alignItems: 'center', color: value ? 'text.primary' : 'text.secondary' }}>
      {value || placeholder}
    </Box>
  )
}
