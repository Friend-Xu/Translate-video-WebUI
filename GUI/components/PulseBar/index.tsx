import { Box, Typography, Chip, Badge } from '@mui/material'
import FiberManualRecord from '@mui/icons-material/FiberManualRecord'
import CloudDownloadOutlined from '@mui/icons-material/CloudDownloadOutlined'
import { useAppStore } from '../../store/useAppStore'
import { MODE_META } from '../../types/modes'
import type { ConnectionState } from '../../hooks/useSSE'

interface Props {
  videoName?: string
  sourceLang?: string
  targetLang?: string
  connectionState?: ConnectionState
  pipelineStage?: string
  backendOnline?: boolean
  onExport?: () => void
}

const SSE_COLORS: Record<ConnectionState, string> = {
  connected: '#4CAF50',
  reconnecting: '#FF9800',
  closed: '#F44336',
}

const SSE_LABELS: Record<ConnectionState, string> = {
  connected: '已连接',
  reconnecting: '重连中',
  closed: '已断开',
}

export default function PulseBar({
  videoName, sourceLang, targetLang,
  connectionState = 'closed', pipelineStage, backendOnline = true, onExport,
}: Props) {
  const mode = useAppStore(s => s.mode)
  const drafts = useAppStore(s => s.pendingDrafts)
  const meta = MODE_META[mode]

  return (
    <Box sx={{
      display: 'flex', alignItems: 'center', gap: 2, px: 2,
      height: '100%', width: '100%',
    }}>
      {/* Left: Video info */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
        <Typography variant="body2" noWrap sx={{ maxWidth: 200, fontWeight: 500 }}>
          {videoName || '未选择视频'}
        </Typography>
        {sourceLang && (
          <Chip label={`${sourceLang} → ${targetLang || '?'}`} size="small"
            sx={{ fontSize: '0.65rem', height: 20 }} />
        )}
      </Box>

      <Box sx={{ flexGrow: 1 }} />

      {/* Center: Mode capsule */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Chip
          icon={<FiberManualRecord sx={{ fontSize: 10, fill: meta.hexColor }} />}
          label={meta.label}
          size="small"
          sx={{
            fontWeight: 600, fontSize: '0.75rem',
            bgcolor: `${meta.hexColor}22`, color: meta.hexColor,
            border: `1px solid ${meta.hexColor}44`,
          }}
        />
        {drafts.size > 0 && (
          <Badge badgeContent={drafts.size} color="warning" sx={{ '& .MuiBadge-badge': { fontSize: '0.65rem' } }}>
            <Box sx={{ width: 8 }} />
          </Badge>
        )}
      </Box>

      <Box sx={{ flexGrow: 1 }} />

      {/* Right: Status indicator */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          {pipelineStage ? (
            <>
              <FiberManualRecord sx={{ fontSize: 8, fill: SSE_COLORS[connectionState] }} />
              <Typography variant="caption" sx={{ color: 'grey.400' }}>
                {SSE_LABELS[connectionState]}
              </Typography>
            </>
          ) : (
            <>
              <FiberManualRecord sx={{ fontSize: 8, fill: backendOnline ? '#4CAF50' : '#F44336' }} />
              <Typography variant="caption" sx={{ color: 'grey.400' }}>
                {backendOnline ? '后端在线' : '后端离线'}
              </Typography>
            </>
          )}
        </Box>

        {pipelineStage && (
          <Chip label={pipelineStage} size="small"
            sx={{ fontSize: '0.65rem', height: 20, bgcolor: 'grey.800', color: 'grey.300' }} />
        )}

        {onExport && (
          <Box
            component="button"
            onClick={onExport}
            aria-label="一键导出"
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              color: 'inherit', padding: 2,
            }}
          >
            <CloudDownloadOutlined sx={{ fontSize: 18 }} />
          </Box>
        )}
      </Box>
    </Box>
  )
}
