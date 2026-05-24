import { Box, Typography } from '@mui/material'
import type { EventViewModel } from '../../types'

interface Props {
  event: EventViewModel
  laneColor: string
  left: number
  width: number
  laneHeight: number
  isSelected: boolean
  isMultiSelected: boolean
  hasDraft?: boolean
  onClick: (e: React.MouseEvent) => void
  onDoubleClick: (e: React.MouseEvent) => void
  onContextMenu: (e: React.MouseEvent) => void
}

const DENSE_THRESHOLD = 80
const COMPACT_THRESHOLD = 40
const MINI_THRESHOLD = 20

export default function EventBlock({
  event, laneColor, left, width, laneHeight,
  isSelected, isMultiSelected, hasDraft,
  onClick, onDoubleClick, onContextMenu,
}: Props) {
  const margin = 6
  const h = laneHeight - margin * 2
  const sel = isSelected || isMultiSelected

  const borderColor = event.confidence < 0.5
    ? '#FF9800'
    : sel ? '#333' : 'transparent'
  const borderWidth = event.confidence < 0.5 ? 2 : sel ? 2 : 1

  return (
    <Box sx={{
      position: 'absolute', left, top: margin, width: Math.max(width, 3), height: h,
      bgcolor: sel ? laneColor : `${laneColor}88`,
      borderRadius: 0.75, overflow: 'hidden', cursor: 'pointer',
      border: `${borderWidth}px solid ${borderColor}`,
      '&:hover': { filter: 'brightness(1.2)', zIndex: 3 },
      opacity: isMultiSelected ? 0.6 : 1,
    }}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      onContextMenu={onContextMenu}
      title={`${event.text}\n${event.translation || ''}\n${event.start.toFixed(1)}s-${event.end.toFixed(1)}s | conf=${event.confidence.toFixed(2)}`}
    >
      {/* Draft indicator */}
      {hasDraft && (
        <Box sx={{
          position: 'absolute', top: 1, right: 1,
          width: 8, height: 8, borderRadius: '50%',
          bgcolor: '#FF9800', border: '1px solid #fff', zIndex: 5,
        }} />
      )}

      {/* Patch indicator */}
      {event.visualState.hasPatches && !hasDraft && (
        <Box sx={{
          position: 'absolute', top: 1, left: 1,
          width: 7, height: 7, borderRadius: '50%', bgcolor: '#FF9800',
          border: '1px solid #fff', zIndex: 5,
        }} />
      )}

      {/* AI suggestion indicator */}
      {event.visualState.hasAiSuggestion && !event.visualState.hasPatches && !hasDraft && (
        <Box sx={{
          position: 'absolute', top: 1, left: 1,
          width: 7, height: 7, borderRadius: '50%', bgcolor: '#FFEB3B',
          border: '1px solid #fff', zIndex: 5,
        }} />
      )}

      {/* Density-adaptive content */}
      {width > MINI_THRESHOLD && (
        <Box sx={{
          px: 0.75, height: '100%',
          display: 'flex', flexDirection: 'column', justifyContent: 'center',
        }}>
          {width > DENSE_THRESHOLD && event.translation && (
            <Typography sx={{
              fontSize: '0.58rem', color: '#fff', whiteSpace: 'nowrap',
              overflow: 'hidden', textOverflow: 'ellipsis',
              textShadow: '0 1px 2px rgba(0,0,0,0.4)', lineHeight: 1.1,
            }}>
              {event.translation}
            </Typography>
          )}
          {width > COMPACT_THRESHOLD && (
            <Typography sx={{
              fontSize: '0.55rem', color: 'rgba(255,255,255,0.85)',
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
              lineHeight: 1.1,
            }}>
              {event.text}
            </Typography>
          )}
        </Box>
      )}

      {/* Mini mode: show segment index */}
      {width <= MINI_THRESHOLD && width > 3 && (
        <Box sx={{
          height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <Typography sx={{ fontSize: '0.45rem', color: '#fff', fontWeight: 700 }}>
            {width <= 6 ? '' : event.id.replace('seg_', '')}
          </Typography>
        </Box>
      )}

      {/* Confidence bar */}
      <Box sx={{
        position: 'absolute', bottom: 0, left: 0, right: 0, height: 2,
        bgcolor: event.confidence >= 0.9 ? '#4CAF50'
          : event.confidence >= 0.7 ? '#FF9800'
          : event.confidence >= 0.5 ? '#FF5722'
          : '#F44336',
      }} />
    </Box>
  )
}
