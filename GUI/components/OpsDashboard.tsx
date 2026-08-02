import { useState, useMemo } from 'react'
import {
  Box, Typography, Card, CardContent, Chip, Button, LinearProgress, Divider,
  IconButton, Tooltip,
} from '@mui/material'
import PlayArrowIcon from '@mui/icons-material/PlayArrowRounded'
import StopIcon from '@mui/icons-material/StopRounded'
import MemoryIcon from '@mui/icons-material/MemoryRounded'
import StorageIcon from '@mui/icons-material/StorageRounded'
import OpenInNewIcon from '@mui/icons-material/OpenInNewRounded'
import SkipNextIcon from '@mui/icons-material/SkipNextRounded'
import RefreshIcon from '@mui/icons-material/RefreshRounded'
import CheckCircleIcon from '@mui/icons-material/CheckCircleRounded'
import ErrorIcon from '@mui/icons-material/ErrorRounded'
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmptyRounded'
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecordRounded'
import { useAppStore } from '../store/useAppStore'
import type { BatchStatus, BatchVideoItem } from '../types'

interface Props {
  batch?: BatchStatus | null
  cpuUsage?: number
  memUsage?: number
  gpuUsage?: number | null
  modelsOnline?: string[]
  onStartBatch?: () => void
  onCancelBatch?: () => void
  onSkipCurrent?: () => void
}

const STEPS = ['ASR', '翻译', '说话人', 'TTS', '对齐', '渲染', '导出']

function inferStageStatus(video: BatchVideoItem, stepIdx: number): 'done' | 'active' | 'pending' | 'failed' {
  const cur = video.current_step
  if (video.status === 'failed') return stepIdx <= 3 ? 'failed' : 'pending'
  if (video.status === 'completed') return 'done'
  if (video.status === 'queued') return 'pending'
  const curIdx = STEPS.findIndex(s => cur.includes(s) || s.includes(cur))
  if (curIdx < 0) return stepIdx === 0 ? 'active' : 'pending'
  if (stepIdx < curIdx) return 'done'
  if (stepIdx === curIdx) return 'active'
  return 'pending'
}

export default function OpsDashboard({
  batch, cpuUsage, memUsage, gpuUsage,
  modelsOnline = [],
  onStartBatch, onCancelBatch, onSkipCurrent,
}: Props) {
  const isRunning = batch?.status === 'running'
  const setMode = useAppStore(s => s.setMode)
  const toggleDockCollapsed = useAppStore(s => s.toggleDockCollapsed)
  const dockCollapsed = useAppStore(s => s.dockCollapsed)
  const [selectedVideoIdx, setSelectedVideoIdx] = useState<number | null>(null)

  const selectedVideo = selectedVideoIdx != null ? batch?.videos[selectedVideoIdx] : null

  // Queue stats
  const queueStats = useMemo(() => {
    if (!batch?.videos) return { queued: 0, running: 0, completed: 0, failed: 0 }
    return {
      queued: batch.videos.filter(v => v.status === 'queued').length,
      running: batch.videos.filter(v => v.status === 'running').length,
      completed: batch.videos.filter(v => v.status === 'completed').length,
      failed: batch.videos.filter(v => v.status === 'failed').length,
    }
  }, [batch])

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <Box sx={{
        p: 1.5, borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper',
        display: 'flex', alignItems: 'center', gap: 2,
      }}>
        <Box>
          <Typography variant="subtitle2">批处理队列</Typography>
          <Typography variant="caption" color="text.secondary">
            {batch?.videos?.length || 0} 任务
            {isRunning && ` · ${batch!.completed_count}/${batch!.total_count} 完成`}
            {batch?.failed_count ? ` · ${batch.failed_count} 失败` : ''}
          </Typography>
        </Box>
        <Box sx={{ flexGrow: 1 }} />
        {/* Resource mini indicators */}
        {cpuUsage != null && (
          <Chip icon={<MemoryIcon sx={{ fontSize: 14 }} />}
            label={`CPU ${cpuUsage.toFixed(0)}%`} size="small" variant="outlined"
            sx={{ fontSize: '0.6rem', height: 22 }} />
        )}
        {memUsage != null && (
          <Chip icon={<StorageIcon sx={{ fontSize: 14 }} />}
            label={`MEM ${memUsage.toFixed(0)}%`} size="small" variant="outlined"
            sx={{ fontSize: '0.6rem', height: 22 }} />
        )}
        {gpuUsage != null && (
          <Chip icon={<MemoryIcon sx={{ fontSize: 14 }} />}
            label={`GPU ${gpuUsage.toFixed(0)}%`} size="small" variant="outlined"
            sx={{ fontSize: '0.6rem', height: 22 }} />
        )}
        <Divider orientation="vertical" flexItem />
        {isRunning ? (
          <>
            <Button size="small" color="warning" startIcon={<StopIcon />}
              onClick={onCancelBatch} sx={{ fontSize: '0.7rem' }}>取消</Button>
            <Button size="small" variant="outlined" startIcon={<SkipNextIcon />}
              onClick={onSkipCurrent} sx={{ fontSize: '0.7rem' }}>跳过</Button>
          </>
        ) : (
          <Button size="small" variant="contained" startIcon={<PlayArrowIcon />}
            onClick={onStartBatch} sx={{ fontSize: '0.7rem' }}>开始批处理</Button>
        )}
        {batch?.failed_count ? (
          <Button size="small" color="warning" variant="outlined" startIcon={<RefreshIcon />}
            onClick={onStartBatch} sx={{ fontSize: '0.7rem' }}>重试失败</Button>
        ) : null}
      </Box>

      <Box sx={{ flexGrow: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Left: Task List */}
        <Box sx={{
          flexGrow: 1, overflow: 'hidden auto', p: 1,
          display: 'flex', flexDirection: 'column', gap: 0.5,
        }}>
          {!batch || batch.videos.length === 0 ? (
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
              <Box sx={{ textAlign: 'center', maxWidth: 360 }}>
                <Box sx={{
                  width: 64, height: 64, borderRadius: '50%', mx: 'auto', mb: 2,
                  bgcolor: 'rgba(96,125,139,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  <HourglassEmptyIcon sx={{ fontSize: 30, color: 'text.disabled' }} />
                </Box>
                <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 0.5 }}>暂无批处理任务</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  在项目中心选择视频并运行流水线，或在窗口拖拽视频加入队列
                </Typography>
                <Button size="small" variant="contained" startIcon={<PlayArrowIcon />}
                  onClick={() => setMode('hub')}>
                  前往项目中心
                </Button>
              </Box>
            </Box>
          ) : (
            batch.videos.map((v, idx) => {
              const isSelected = selectedVideoIdx === idx
              const statusColor = v.status === 'completed' ? 'success'
                : v.status === 'failed' ? 'error'
                : v.status === 'running' ? 'primary'
                : 'default'
              return (
                <Card key={v.video_path} sx={{
                  cursor: 'pointer', bgcolor: isSelected ? 'action.selected' : 'background.paper',
                  border: isSelected ? '1px solid' : '1px solid transparent',
                  borderColor: isSelected ? 'primary.main' : 'divider',
                  '&:hover': { bgcolor: 'action.hover' },
                }}
                  onClick={() => setSelectedVideoIdx(isSelected ? null : idx)}>
                  <CardContent sx={{ p: 1, '&:last-child': { pb: 1 } }}>
                    {/* Row 1: name + status */}
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                      <Chip label={v.status} size="small" color={statusColor}
                        sx={{ fontSize: '0.55rem', height: 18 }} />
                      <Typography variant="body2" noWrap sx={{ flexGrow: 1, fontSize: '0.72rem' }}>
                        {v.video_name}
                      </Typography>
                      {v.status === 'failed' && (
                        <Tooltip title="切换到 Timeline 查看日志">
                          <IconButton size="small" onClick={(e) => { e.stopPropagation(); setMode('timeline'); if (dockCollapsed) toggleDockCollapsed() }}
                            sx={{ color: 'error.main', p: 0 }}>
                            <OpenInNewIcon sx={{ fontSize: 16 }} />
                          </IconButton>
                        </Tooltip>
                      )}
                    </Box>

                    {/* Row 2: progress bar */}
                    {v.status === 'running' && (
                      <Box sx={{ mb: 0.5 }}>
                        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.25 }}>
                          <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.55rem' }}>
                            {v.current_step || '进行中...'}
                          </Typography>
                          <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.55rem' }}>
                            {v.progress}%
                          </Typography>
                        </Box>
                        <LinearProgress variant="determinate" value={v.progress}
                          sx={{ height: 3, borderRadius: 1 }} />
                      </Box>
                    )}
                    {v.status === 'completed' && (
                      <LinearProgress variant="determinate" value={100} color="success"
                        sx={{ height: 3, borderRadius: 1, mb: 0.5 }} />
                    )}
                    {v.status === 'failed' && (
                      <LinearProgress variant="determinate" value={v.progress} color="error"
                        sx={{ height: 3, borderRadius: 1, mb: 0.5 }} />
                    )}

                    {/* Row 3: stage mini indicators */}
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.3 }}>
                      {STEPS.map((step, si) => {
                        const s = inferStageStatus(v, si)
                        const icon = s === 'done' ? <CheckCircleIcon sx={{ fontSize: 10, color: '#4CAF50' }} />
                          : s === 'active' ? <FiberManualRecordIcon sx={{ fontSize: 8, color: '#2196F3' }} />
                          : s === 'failed' ? <ErrorIcon sx={{ fontSize: 10, color: '#F44336' }} />
                          : <FiberManualRecordIcon sx={{ fontSize: 6, color: 'rgba(255,255,255,0.15)' }} />
                        return (
                          <Tooltip key={si} title={`${step}: ${s === 'done' ? '已完成' : s === 'active' ? '进行中' : s === 'failed' ? '失败' : '等待中'}`}>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.3 }}>
                              {icon}
                              <Typography variant="caption" sx={{
                                fontSize: '0.5rem',
                                color: s === 'done' ? '#4CAF50' : s === 'active' ? '#2196F3' : s === 'failed' ? '#F44336' : 'rgba(255,255,255,0.2)',
                              }}>
                                {step}
                              </Typography>
                              {si < STEPS.length - 1 && (
                                <Box sx={{ width: 4, height: 1, bgcolor: s === 'done' ? '#4CAF50' : 'rgba(255,255,255,0.1)', mx: 0.1 }} />
                              )}
                            </Box>
                          </Tooltip>
                        )
                      })}
                    </Box>
                  </CardContent>
                </Card>
              )
            })
          )}
        </Box>

        {/* Right: Task Detail + Resources panel */}
        <Box sx={{
          width: 320, minWidth: 320, borderLeft: 1, borderColor: 'divider',
          overflow: 'hidden auto', bgcolor: 'background.paper',
        }}>
          {/* Task details */}
          {selectedVideo ? (
            <Box sx={{ p: 1.5 }}>
              <Typography variant="subtitle2" sx={{ fontSize: '0.78rem', mb: 1 }}>
                {selectedVideo.video_name}
              </Typography>

              <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mb: 1.5 }}>
                <Chip label={selectedVideo.status} size="small"
                  color={selectedVideo.status === 'completed' ? 'success' : selectedVideo.status === 'failed' ? 'error' : selectedVideo.status === 'running' ? 'primary' : 'default'}
                  sx={{ fontSize: '0.6rem', height: 20 }} />
                <Chip label={`进度 ${selectedVideo.progress}%`} size="small" variant="outlined"
                  sx={{ fontSize: '0.6rem', height: 20 }} />
              </Box>

              {/* Info table */}
              <Box sx={{ mb: 1.5 }}>
                {[
                  ['路径', selectedVideo.video_path],
                  ['当前阶段', selectedVideo.current_step || '—'],
                  ['Job ID', selectedVideo.job_id || '—'],
                ].map(([label, value]) => (
                  <Box key={label} sx={{ display: 'flex', mb: 0.25 }}>
                    <Typography variant="caption" color="text.secondary" sx={{ width: 56, fontSize: '0.6rem', flexShrink: 0 }}>
                      {label}
                    </Typography>
                    <Typography variant="caption" sx={{ fontSize: '0.6rem', wordBreak: 'break-all' }}>
                      {value}
                    </Typography>
                  </Box>
                ))}
              </Box>

              <Divider sx={{ my: 1 }} />

              {/* Stage timeline */}
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                阶段进度
              </Typography>
              <Box sx={{ position: 'relative', ml: 1 }}>
                {STEPS.map((step, si) => {
                  const s = inferStageStatus(selectedVideo, si)
                  return (
                    <Box key={si} sx={{ display: 'flex', alignItems: 'flex-start', mb: 0.5, position: 'relative' }}>
                      {/* Vertical line */}
                      {si < STEPS.length - 1 && (
                        <Box sx={{
                          position: 'absolute', left: 6, top: 14,
                          width: 2, height: 'calc(100% + 4px)',
                          bgcolor: s === 'done' ? '#4CAF50' : 'rgba(255,255,255,0.1)',
                        }} />
                      )}
                      <Box sx={{
                        width: 14, height: 14, borderRadius: '50%', flexShrink: 0, mr: 1,
                        bgcolor: s === 'done' ? '#4CAF50' : s === 'active' ? '#2196F3' : s === 'failed' ? '#F44336' : 'grey.700',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        zIndex: 1,
                      }}>
                        {s === 'done' ? <CheckCircleIcon sx={{ fontSize: 10, color: '#fff' }} />
                          : s === 'failed' ? <ErrorIcon sx={{ fontSize: 10, color: '#fff' }} />
                          : s === 'active' ? <FiberManualRecordIcon sx={{ fontSize: 8, color: '#fff' }} />
                          : null}
                      </Box>
                      <Box>
                        <Typography variant="caption" sx={{
                          fontSize: '0.62rem',
                          color: s === 'done' ? 'success.light' : s === 'active' ? 'primary.light' : s === 'failed' ? 'error.light' : 'text.disabled',
                          fontWeight: s === 'active' ? 600 : 400,
                        }}>
                          {step}
                        </Typography>
                        <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.5rem', display: 'block' }}>
                          {s === 'done' ? '已完成' : s === 'active' ? '进行中' : s === 'failed' ? '失败' : '等待中'}
                        </Typography>
                      </Box>
                    </Box>
                  )
                })}
              </Box>

              {/* Actions */}
              <Divider sx={{ my: 1.5 }} />
              <Box sx={{ display: 'flex', gap: 0.5 }}>
                {selectedVideo.status === 'failed' && (
                  <Button size="small" variant="outlined" color="warning" startIcon={<RefreshIcon />}
                    fullWidth sx={{ fontSize: '0.65rem' }}
                    onClick={onStartBatch}>
                    重试
                  </Button>
                )}
                <Button size="small" variant="outlined" startIcon={<OpenInNewIcon />}
                  fullWidth sx={{ fontSize: '0.65rem' }}
                  onClick={() => { setMode('timeline'); if (dockCollapsed) toggleDockCollapsed() }}>
                  查看日志
                </Button>
              </Box>
            </Box>
          ) : (
            <Box sx={{ textAlign: 'center', py: 3, px: 1.5 }}>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                选择一个任务查看详情
              </Typography>
              {/* Resources panel when no selection */}
              <Typography variant="caption" color="text.disabled" sx={{ display: 'block', mb: 1 }}>
                资源监控
              </Typography>
              {[
                { label: 'CPU', value: cpuUsage, color: 'primary' as const, Icon: MemoryIcon },
                { label: '内存', value: memUsage, color: 'secondary' as const, Icon: StorageIcon },
                { label: 'GPU', value: gpuUsage, color: 'success' as const, Icon: MemoryIcon },
              ].filter(r => r.value != null).map(r => (
                <Card key={r.label} sx={{ mb: 0.5 }}>
                  <CardContent sx={{ p: 1, '&:last-child': { pb: 1 }, display: 'flex', alignItems: 'center', gap: 1 }}>
                    <r.Icon sx={{ fontSize: 16, color: `${r.color}.main` }} />
                    <Box sx={{ flexGrow: 1 }}>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                        <Typography variant="caption">{r.label}</Typography>
                        <Typography variant="caption">{r.value!.toFixed(0)}%</Typography>
                      </Box>
                      <LinearProgress variant="determinate" value={r.value!} color={r.color}
                        sx={{ height: 3, borderRadius: 1 }} />
                    </Box>
                  </CardContent>
                </Card>
              ))}
              {/* Models */}
              <Box sx={{ mt: 1 }}>
                <Typography variant="caption" color="text.disabled" sx={{ display: 'block', mb: 0.5 }}>
                  模型状态
                </Typography>
                <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                  {modelsOnline.length > 0
                    ? modelsOnline.map(m => <Chip key={m} label={m} size="small" color="success" variant="outlined"
                      sx={{ fontSize: '0.55rem', height: 18 }} />)
                    : <Chip label="无模型在线" size="small" variant="outlined"
                      sx={{ fontSize: '0.55rem', height: 18 }} />}
                </Box>
              </Box>
              {/* Queue summary */}
              {batch && (
                <Box sx={{ mt: 1.5 }}>
                  <Typography variant="caption" color="text.disabled" sx={{ display: 'block', mb: 0.5 }}>
                    队列统计
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <Chip label={`${queueStats.queued} 等待`} size="small" variant="outlined" sx={{ fontSize: '0.55rem', height: 18 }} />
                    <Chip label={`${queueStats.running} 运行`} size="small" color="primary" sx={{ fontSize: '0.55rem', height: 18 }} />
                    <Chip label={`${queueStats.completed} 完成`} size="small" color="success" sx={{ fontSize: '0.55rem', height: 18 }} />
                    {queueStats.failed > 0 && (
                      <Chip label={`${queueStats.failed} 失败`} size="small" color="error" sx={{ fontSize: '0.55rem', height: 18 }} />
                    )}
                  </Box>
                </Box>
              )}
            </Box>
          )}
        </Box>
      </Box>
    </Box>
  )
}
