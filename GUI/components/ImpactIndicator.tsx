import { Box, Typography } from '@mui/material'

interface Props {
  affectedEventIds: string[]
  offsetSeconds: number
  startX: number
  width: number
  arenaHeight: number
}

export default function ImpactIndicator({
  affectedEventIds, offsetSeconds, startX, width, arenaHeight,
}: Props) {
  if (affectedEventIds.length === 0 || offsetSeconds === 0) return null

  return (
    <Box sx={{
      position: 'absolute', left: startX, top: 0, width: Math.max(width, 1),
      height: arenaHeight, pointerEvents: 'none', zIndex: 5,
    }}>
      <Box sx={{
        width: '100%', height: '100%',
        bgcolor: offsetSeconds > 0 ? 'rgba(255, 152, 0, 0.1)' : 'rgba(33, 150, 243, 0.1)',
        borderLeft: '2px dashed',
        borderRight: '2px dashed',
        borderColor: offsetSeconds > 0 ? 'warning.main' : 'info.main',
      }} />
      <Box sx={{
        position: 'absolute', top: 4, left: 4,
        bgcolor: 'rgba(0,0,0,0.7)', color: '#fff',
        px: 0.75, py: 0.25, borderRadius: 0.5,
      }}>
        <Typography variant="caption" sx={{ fontSize: '0.6rem' }}>
          {offsetSeconds > 0 ? '+' : ''}{offsetSeconds.toFixed(1)}s · {affectedEventIds.length} 事件
        </Typography>
      </Box>
    </Box>
  )
}
