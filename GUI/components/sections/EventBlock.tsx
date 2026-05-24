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
  onClick: (e: React.MouseEvent) => void
  onDoubleClick: (e: React.MouseEvent) => void
  onContextMenu: (e: React.MouseEvent) => void
}

export default function EventBlock({
  event, laneColor, left, width, laneHeight,
  isSelected, isMultiSelected, onClick, onDoubleClick, onContextMenu,
}: Props) {
  const margin = 6
  const h = laneHeight - margin * 2
  const sel = isSelected || isMultiSelected

  return (
    <Box sx={{
      position: 'absolute', left, top: margin, width: Math.max(width, 3), height: h,
      bgcolor: sel ? laneColor : `${laneColor}88`,
      borderRadius: 0.75, overflow: 'hidden', cursor: 'pointer',
      border: sel ? '2px solid #333' : '1px solid transparent',
      '&:hover': { filter: 'brightness(1.2)', zIndex: 3 },
    }}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      onContextMenu={onContextMenu}
      title={`${event.text}\n${event.translation || ''}\n${event.start.toFixed(1)}s-${event.end.toFixed(1)}s`}
    >
      {/* Patch indicator */}
      {event.visualState.hasPatches && (
        <Box sx={{
          position: 'absolute', top: 1, left: 1,
          width: 7, height: 7, borderRadius: '50%', bgcolor: '#FF9800',
          border: '1px solid #fff', zIndex: 5,
        }} />
      )}
      {/* AI suggestion indicator */}
      {event.visualState.hasAiSuggestion && !event.visualState.hasPatches && (
        <Box sx={{
          position: 'absolute', top: 1, left: 1,
          width: 7, height: 7, borderRadius: '50%', bgcolor: '#FFEB3B',
          border: '1px solid #fff', zIndex: 5,
        }} />
      )}

      {width > 30 && (
        <Box sx={{ px: 0.75, height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          {width > 80 && event.translation && (
            <Typography sx={{
              fontSize: '0.58rem', color: '#fff', whiteSpace: 'nowrap',
              overflow: 'hidden', textOverflow: 'ellipsis',
              textShadow: '0 1px 2px rgba(0,0,0,0.4)', lineHeight: 1.1,
            }}>
              {event.translation}
            </Typography>
          )}
          <Typography sx={{
            fontSize: '0.55rem', color: 'rgba(255,255,255,0.85)',
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            lineHeight: 1.1,
          }}>
            {event.text}
          </Typography>
        </Box>
      )}

      {/* Confidence bar */}
      <Box sx={{
        position: 'absolute', bottom: 0, left: 0, right: 0, height: 2,
        bgcolor: event.confidence > 0.9 ? '#4CAF50' : event.confidence > 0.7 ? '#FF9800' : '#9E9E9E',
      }} />
    </Box>
  )
}
