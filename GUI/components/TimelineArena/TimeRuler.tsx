import { Box, Typography } from '@mui/material'
import type { TimelineCoordAPI } from '../../hooks/useTimelineCoordinates'

interface Props {
  coord: TimelineCoordAPI
  totalDuration: number
  canvasWidth: number
  markers?: { time: number; label: string; color: string }[]
  onMarkerClick?: (time: number) => void
}

export default function TimeRuler({ coord, totalDuration, canvasWidth, markers, onMarkerClick }: Props) {
  const { timeToPixel, pixelsPerSec } = coord
  const showMs = pixelsPerSec >= 200
  const interval = showMs ? 0.5 : 1

  return (
    <Box sx={{
      position: 'sticky', top: 0, zIndex: 10,
      height: 22, width: canvasWidth || '100%',
      bgcolor: 'rgba(0,0,0,0.5)',
      borderBottom: '1px solid rgba(255,255,255,0.12)',
    }}>
      {Array.from({ length: Math.ceil(totalDuration / interval) }).map((_, i) => {
        const t = i * interval
        const x = timeToPixel(t)
        if (x < -20 || x > canvasWidth + 20) return null
        const major = t % 1 === 0
        return (
          <Box key={i} sx={{
            position: 'absolute', left: x, bottom: 0,
            height: major ? 14 : 8,
            borderLeft: '1px solid',
            borderColor: major ? 'rgba(255,255,255,0.3)' : 'rgba(255,255,255,0.1)',
          }}>
            {major && (
              <Typography sx={{
                position: 'absolute', top: 1, left: 3,
                fontSize: '0.55rem', color: 'rgba(255,255,255,0.5)',
                whiteSpace: 'nowrap',
              }}>
                {showMs ? `${t.toFixed(1)}s` : `${t}s`}
              </Typography>
            )}
          </Box>
        )
      })}
      {markers?.map((m, idx) => {
        const x = timeToPixel(m.time)
        if (x < -5 || x > canvasWidth + 5) return null
        return (
          <Box key={idx} onClick={() => onMarkerClick?.(m.time)} sx={{
            position: 'absolute', left: x, top: 2,
            width: 10, height: 10, borderRadius: '50%',
            bgcolor: m.color, cursor: 'pointer',
            border: '1px solid rgba(255,255,255,0.6)', zIndex: 2,
          }} />
        )
      })}
    </Box>
  )
}
