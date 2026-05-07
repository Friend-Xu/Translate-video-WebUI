import { useCallback } from 'react'
import {
  Box, Typography, Card, CardContent, Button, Select, MenuItem,
  LinearProgress, Stack, Checkbox, FormControlLabel, Divider,
  ToggleButtonGroup, ToggleButton, Chip, List, ListItemButton, ListItemText,
} from '@mui/material'
import Grid from '@mui/material/Grid'
import FolderOpenIcon from '@mui/icons-material/FolderOpenRounded'
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
  logs,
}: PipelinePanelProps) {

  const isRunning = status.state === 'running' || batch.status === 'running'

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

  const logHeaderLabel = mode === 'batch' && activeVideoJobId
    ? `查看日志: ${(batch.videos.find(v => v.job_id === activeVideoJobId) || {} as any).video_name || activeVideoJobId}`
    : undefined

  const controlsCard = (
    <Card>
      <CardContent>
        <Typography variant="subtitle2" gutterBottom>步骤控制</Typography>

        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 2 }}>
          <FormControlLabel
            control={<Checkbox size="small" checked={config.enableDefectCheck} onChange={e => onConfigChange('enableDefectCheck', e.target.checked)} disabled={isRunning} />}
            label={<Typography variant="body2">启用音频缺陷检测</Typography>}
          />
          <FormControlLabel
            control={<Checkbox size="small" checked={config.enableExtract} onChange={e => onConfigChange('enableExtract', e.target.checked)} disabled={isRunning} />}
            label={<Typography variant="body2">启用字幕提取</Typography>}
          />
          <FormControlLabel
            control={<Checkbox size="small" checked={config.enableTranslate} onChange={e => onConfigChange('enableTranslate', e.target.checked)} disabled={isRunning} />}
            label={<Typography variant="body2">启用翻译</Typography>}
          />
          <FormControlLabel
            control={<Checkbox size="small" checked={config.enableTTS} onChange={e => onConfigChange('enableTTS', e.target.checked)} disabled={isRunning} />}
            label={<Typography variant="body2">启用TTS合成</Typography>}
          />
        </Box>

        <Divider sx={{ mb: 2 }} />

        <Stack direction="row" spacing={2} sx={{ mb: 3 }}>
          {mode === 'single' ? (
            <>
              {status.state === 'running' ? (
                <Button variant="contained" color="error" startIcon={<StopIcon />} onClick={onCancel}>
                  取消处理
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
        >
          <ToggleButton value="single">单视频</ToggleButton>
          <ToggleButton value="batch">批处理</ToggleButton>
        </ToggleButtonGroup>
      </Box>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 3 }}>
          <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column', bgcolor: 'action.hover', border: '2px dashed', borderColor: 'divider' }}>
            <CardContent sx={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', flex: 1, gap: 1.5 }}>
              <Box display="flex" alignItems="center" gap={1}>
                <FolderOpenIcon color="primary" />
                <Typography variant="body1" fontWeight={600} color="text.primary">
                  {mode === 'single' ? '视频导入' : '批次导入'}
                </Typography>
              </Box>
              {mode === 'single' ? (
                <>
                  <TextFieldDisplay value={config.videoPath} placeholder="请选择视频文件（.mp4）" />
                  <Button variant="contained" size="small" disableElevation sx={{ borderRadius: 2 }} onClick={onSelectFile}>
                    选择文件
                  </Button>
                </>
              ) : (
                <>
                  {batchFiles.length === 0 ? (
                    <Typography variant="body2" color="text.secondary">尚未选择视频文件</Typography>
                  ) : (
                    <Typography variant="body2">已选 {batchFiles.length} 个视频</Typography>
                  )}
                  <Button variant="contained" size="small" disableElevation sx={{ borderRadius: 2 }} onClick={onAddFiles} startIcon={<AddIcon />}>
                    添加文件
                  </Button>
                </>
              )}
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 3 }}>
          <ControlCard icon={<LanguageIcon color="primary" />} title="源语言" subtitle="自动检测 / 英文 / 中文 / 日文">
            <Select size="small" fullWidth value={config.lang} onChange={e => onConfigChange('lang', e.target.value as PipelineConfig['lang'])} sx={{ mt: 1 }}>
              <MenuItem value="auto">自动检测</MenuItem>
              <MenuItem value="en">英文</MenuItem>
              <MenuItem value="zh">中文</MenuItem>
              <MenuItem value="ja">日文</MenuItem>
            </Select>
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
            <LogPanel logs={logs} showTitle={false} />
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
            <LogPanel logs={logs} showTitle={false} headerLabel={logHeaderLabel} />
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
