import { Box, Typography, Card, CardContent, Chip, Button, LinearProgress, Divider } from '@mui/material'
import PlayArrowIcon from '@mui/icons-material/PlayArrowRounded'
import StopIcon from '@mui/icons-material/StopRounded'
import MemoryIcon from '@mui/icons-material/MemoryRounded'
import StorageIcon from '@mui/icons-material/StorageRounded'
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

export default function OpsDashboard({
  batch, cpuUsage, memUsage, gpuUsage,
  modelsOnline = [],
  onStartBatch, onCancelBatch, onSkipCurrent,
}: Props) {
  const isRunning = batch?.status === 'running'

  return (
    <Box sx={{ p: 2, height: '100%', overflow: 'auto' }}>
      {/* Resource cards */}
      <Box sx={{ display: 'flex', gap: 2, mb: 2, flexWrap: 'wrap' }}>
        {[
          { label: 'CPU', value: cpuUsage, color: 'primary' as const, Icon: MemoryIcon },
          { label: '内存', value: memUsage, color: 'secondary' as const, Icon: StorageIcon },
          { label: 'GPU', value: gpuUsage, color: 'success' as const, Icon: MemoryIcon },
        ].filter(r => r.value != null).map(r => (
          <Card key={r.label} sx={{ flex: 1, minWidth: 120 }}>
            <CardContent sx={{ p: 1.5, '&:last-child': { pb: 1.5 } }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5 }}>
                <r.Icon sx={{ fontSize: 16, color: `${r.color}.main` }} />
                <Typography variant="caption">{r.label}</Typography>
              </Box>
              <Typography variant="h6" sx={{ fontSize: '1.1rem' }}>
                {r.value!.toFixed(0)}%
              </Typography>
              <LinearProgress variant="determinate" value={r.value!} color={r.color}
                sx={{ mt: 0.5, height: 3, borderRadius: 1 }} />
            </CardContent>
          </Card>
        ))}
      </Box>

      {/* Models */}
      <Box sx={{ mb: 2 }}>
        <Typography variant="subtitle2" sx={{ mb: 0.5, fontSize: '0.78rem' }}>模型状态</Typography>
        <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
          {modelsOnline.length > 0
            ? modelsOnline.map(m => <Chip key={m} label={m} size="small" color="success" variant="outlined" sx={{ fontSize: '0.65rem' }} />)
            : <Chip label="无模型在线" size="small" color="default" variant="outlined" sx={{ fontSize: '0.65rem' }} />}
        </Box>
      </Box>

      <Divider sx={{ my: 1.5 }} />

      {/* Batch queue */}
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
        <Typography variant="subtitle2" sx={{ fontSize: '0.78rem', flexGrow: 1 }}>批处理队列</Typography>
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          {isRunning ? (
            <>
              <Button size="small" color="warning" startIcon={<StopIcon />} onClick={onCancelBatch} sx={{ fontSize: '0.7rem' }}>取消</Button>
              <Button size="small" variant="outlined" onClick={onSkipCurrent} sx={{ fontSize: '0.7rem' }}>跳过</Button>
            </>
          ) : (
            <Button size="small" variant="contained" startIcon={<PlayArrowIcon />} onClick={onStartBatch} sx={{ fontSize: '0.7rem' }}>开始批处理</Button>
          )}
        </Box>
      </Box>

      {batch && batch.videos.length > 0 ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          {batch.videos.map((v: BatchVideoItem) => (
            <Box key={v.video_path} sx={{
              display: 'flex', alignItems: 'center', gap: 1, p: 1,
              borderRadius: 1, bgcolor: 'action.hover',
            }}>
              <Chip label={v.status} size="small"
                color={v.status === 'completed' ? 'success' : v.status === 'failed' ? 'error' : v.status === 'running' ? 'primary' : 'default'}
                sx={{ fontSize: '0.6rem', height: 18 }} />
              <Typography variant="body2" noWrap sx={{ flexGrow: 1, fontSize: '0.72rem' }}>{v.video_name}</Typography>
              {v.status === 'running' && <LinearProgress variant="indeterminate" sx={{ width: 60, height: 3, borderRadius: 1 }} />}
            </Box>
          ))}
        </Box>
      ) : (
        <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 2 }}>
          暂无批处理任务
        </Typography>
      )}
    </Box>
  )
}
