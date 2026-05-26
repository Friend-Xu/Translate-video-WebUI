import { Box, Chip } from '@mui/material'
import { useAppStore } from '../../store/useAppStore'
import type { TimelineCoordAPI } from '../../hooks/useTimelineCoordinates'

interface Props {
  coord: TimelineCoordAPI
}

const PRESETS = [
  { label: '1s', seconds: 1 },
  { label: '5s', seconds: 5 },
  { label: '30s', seconds: 30 },
  { label: 'All', seconds: 0 },
]

export default function ZoomPresets({ coord }: Props) {
  const playheadPosition = useAppStore(s => s.playheadPosition)

  return (
    <Box sx={{ display: 'flex', gap: 0.5 }}>
      {PRESETS.map(p => {
        const handleClick = () => {
          if (p.seconds === 0) {
            coord.zoomToFit(0.05)
          } else {
            const half = p.seconds / 2
            coord.zoomToTimeRange(
              Math.max(0, playheadPosition - half),
              playheadPosition + half,
            )
          }
        }
        return (
          <Chip
            key={p.label}
            label={p.label}
            size="small"
            variant="outlined"
            onClick={handleClick}
            sx={{
              fontSize: '0.6rem', height: 22, borderRadius: 0.75,
              color: 'rgba(255,255,255,0.6)', borderColor: 'rgba(255,255,255,0.2)',
              cursor: 'pointer',
              '&:hover': { bgcolor: 'rgba(255,255,255,0.1)', color: 'common.white' },
            }}
          />
        )
      })}
    </Box>
  )
}
