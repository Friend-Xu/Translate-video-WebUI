import { Box, Typography, LinearProgress } from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircleRounded'
import PendingIcon from '@mui/icons-material/RadioButtonUncheckedRounded'
import ErrorIcon from '@mui/icons-material/ErrorRounded'

import type { StageInfo } from '../../types'

/**
 * StagePipeline — 阶段管线图
 *
 * 根据 status.stages 实时显示各阶段状态（待→进行→完成）。
 * 用于 ProjectHubPage 的 running/done 视图，替代单一 LinearProgress。
 *
 * 阶段顺序由 preset 的 passes 列表决定（外部传入），
 * stages 是后端填充的实时状态映射。
 */

interface Props {
  /** 阶段顺序列表（来自 preset.passes） */
  passOrder: string[]
  /** stage_id → StageInfo 实时状态映射（来自 status.stages） */
  stages: Record<string, StageInfo>
  /** 当前活跃的阶段 ID，用于高亮 */
  activeStage?: string
}

const STATUS_COLORS = {
  running: '#2563EB',
  completed: '#16A34A',
  failed: '#DC2626',
  pending: '#9CA3AF',
} as const

const STATUS_ICON = {
  running: null,  // spinner handled separately
  completed: CheckCircleIcon,
  failed: ErrorIcon,
  pending: PendingIcon,
}

function formatElapsed(s: number): string {
  if (s < 0.5) return '...'
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}m${sec}s`
}

export default function StagePipeline({ passOrder, stages, activeStage }: Props) {
  if (passOrder.length === 0) return null

  return (
    <Box sx={{ display: 'flex', alignItems: 'flex-start', flexWrap: 'wrap', gap: 0.3, mb: 2 }}>
      {passOrder.map((stageId, i) => {
        const info: StageInfo | undefined = stages[stageId]
        const status = info?.status || 'pending'
        const color = STATUS_COLORS[status]
        const Icon = STATUS_ICON[status]
        const isActive = status === 'running' || stageId === activeStage

        // Node label: use stage_label if available, otherwise stageId
        const displayLabel = info?.label || stageId.replace(/_/g, ' ')

        return (
          <Box key={stageId} sx={{ display: 'flex', alignItems: 'center', gap: 0.2 }}>
            {/* Node */}
            <Box sx={{
              px: 1.2, py: 1.0, borderRadius: 2,
              border: isActive ? `2px solid ${color}` : `1.5px solid ${color}20`,
              bgcolor: isActive ? `${color}0A` : status === 'completed' ? `${color}08` : 'transparent',
              minWidth: 64, textAlign: 'center',
              transition: 'border-color 0.3s, background-color 0.3s',
              position: 'relative',
            }}>
              {/* Spinner indicator for active stage */}
              {isActive && (
                <Box sx={{
                  position: 'absolute', top: -4, left: '50%', transform: 'translateX(-50%)',
                  width: 6, height: 6, borderRadius: '50%', bgcolor: color,
                  animation: 'pulse 1.2s ease-in-out infinite',
                  '@keyframes pulse': {
                    '0%, 100%': { opacity: 1, transform: 'translateX(-50%) scale(1)' },
                    '50%': { opacity: 0.4, transform: 'translateX(-50%) scale(1.8)' },
                  },
                }} />
              )}
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.3, mb: 0.3 }}>
                {Icon ? <Icon sx={{ fontSize: 14, color }} /> : (
                  <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: color, animation: 'pulse 1s infinite' }} />
                )}
              </Box>
              <Typography variant="caption" sx={{ fontSize: '0.6rem', color, fontWeight: isActive ? 700 : 500, lineHeight: 1.2 }}>
                {displayLabel}
              </Typography>
              {status === 'completed' && info?.elapsed !== undefined && info.elapsed > 0 && (
                <Typography variant="caption" sx={{ display: 'block', fontSize: '0.5rem', color: 'text.disabled', mt: 0.1 }}>
                  {formatElapsed(info.elapsed)}
                </Typography>
              )}
              {/* Inline mini-progress for running stage */}
              {isActive && (info?.total_items ?? 0) > 0 && (
                <Box sx={{ mt: 0.5, mb: -0.2 }}>
                  <LinearProgress
                    variant="determinate"
                    value={info?.percent ?? 0}
                    sx={{ height: 3, borderRadius: 1, bgcolor: `${color}20`, '& .MuiLinearProgress-bar': { bgcolor: color, borderRadius: 1 } }}
                  />
                  <Typography variant="caption" sx={{ fontSize: '0.48rem', color: 'text.disabled', display: 'block', textAlign: 'center' }}>
                    {info?.current_item ?? 0}/{info?.total_items ?? 0}
                  </Typography>
                </Box>
              )}
            </Box>
            {/* Arrow — not after last item */}
            {i < passOrder.length - 1 && (
              <Typography variant="caption" color={status === 'completed' ? 'success.main' : 'text.disabled'} sx={{ fontSize: '0.7rem', mx: 0.1 }}>
                →
              </Typography>
            )}
          </Box>
        )
      })}
    </Box>
  )
}