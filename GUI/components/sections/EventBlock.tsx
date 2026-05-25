import { memo, useState, useRef, useCallback } from 'react'
import { Box, Typography } from '@mui/material'
import CheckIcon from '@mui/icons-material/CheckRounded'
import { useAppStore } from '../../store/useAppStore'
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
  hasAppliedPatch?: boolean
  isOverlong?: boolean
  readOnly?: boolean
  onClick: (e: React.MouseEvent) => void
  onDoubleClick: (e: React.MouseEvent) => void
  onContextMenu: (e: React.MouseEvent) => void
}

const DENSE_THRESHOLD = 80
const COMPACT_THRESHOLD = 40
const MINI_THRESHOLD = 20
const OVERLONG_RED = 8
const OVERLONG_ORANGE = 5

function EventBlock({
  event, laneColor, left, width, laneHeight,
  isSelected, isMultiSelected, hasDraft, hasAppliedPatch, isOverlong, readOnly,
  onClick, onContextMenu,
}: Props) {
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState(event.translation)
  const editRef = useRef<HTMLDivElement | null>(null)
  const addDraft = useAppStore(s => s.addDraft)

  const margin = 6
  const h = laneHeight - margin * 2
  const sel = isSelected || isMultiSelected || editing
  const duration = event.end - event.start
  const overlong = isOverlong ?? duration > OVERLONG_RED
  const overlongWarn = !overlong && duration > OVERLONG_ORANGE

  const handleDoubleClick = useCallback((e: React.MouseEvent) => {
    if (readOnly) return
    e.stopPropagation()
    setEditText(event.translation)
    setEditing(true)
    setTimeout(() => editRef.current?.focus(), 50)
  }, [readOnly, event.translation])

  const commitEdit = useCallback(() => {
    if (editText !== event.translation && editText.trim()) {
      addDraft({
        eventId: event.id,
        opcode: 'SET_TRANSLATION',
        payload: { translation: editText.trim() },
        before: { translation: event.translation },
        after: { translation: editText.trim() },
        timestamp: Date.now(),
      })
    }
    setEditing(false)
  }, [editText, event, addDraft])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); commitEdit() }
    if (e.key === 'Escape') { setEditText(event.translation); setEditing(false) }
  }, [commitEdit, event.translation])

  const borderColor = event.confidence < 0.5
    ? '#FF9800'
    : sel ? '#333' : 'transparent'
  const borderWidth = event.confidence < 0.5 ? 2 : sel ? 2 : 1
  const showIndicators = width > COMPACT_THRESHOLD

  const indicatorDot = (color: string, key: string, pos?: 'first') => (
    <Box key={key} sx={{
      width: 7, height: 7, borderRadius: '50%', bgcolor: color,
      border: '1px solid', borderColor: 'common.white',
      flexShrink: 0, ml: pos === 'first' ? 0 : 1,
    }} />
  )

  return (
    <Box sx={{
      position: 'absolute', left, top: margin, width: Math.max(width, 3), height: h,
      bgcolor: sel ? laneColor : `${laneColor}88`,
      borderRadius: 0.75, overflow: 'hidden', cursor: readOnly ? 'default' : 'pointer',
      border: `${borderWidth}px solid ${borderColor}`,
      borderColor: editing ? 'primary.main' : borderColor,
      '&:hover': { filter: editing ? 'none' : 'brightness(1.2)', zIndex: 3 },
      opacity: isMultiSelected ? 0.6 : 1,
    }}
      data-event-block="true"
      onClick={editing ? undefined : onClick}
      onDoubleClick={handleDoubleClick}
      onContextMenu={onContextMenu}
      title={`${event.text}\n${event.translation || ''}\n${event.start.toFixed(1)}s-${event.end.toFixed(1)}s | conf=${event.confidence.toFixed(2)}`}
    >
      {/* Top-left indicators row */}
      {showIndicators && (
        <Box sx={{
          position: 'absolute', top: 1, left: 2, zIndex: 5,
          display: 'flex', alignItems: 'center', gap: 0,
        }}>
          {event.translation && (
            <CheckIcon sx={{ fontSize: 10, color: '#4CAF50', filter: 'drop-shadow(0 0 1px rgba(0,0,0,0.5))' }} />
          )}
          {event.visualState.hasPatches && !hasDraft && indicatorDot('#FF9800', 'patch', event.translation ? undefined : 'first')}
          {hasAppliedPatch && indicatorDot('#2196F3', 'applied', !event.translation && !event.visualState.hasPatches ? 'first' : undefined)}
          {event.visualState.hasAiSuggestion && !event.visualState.hasPatches && !hasDraft && !hasAppliedPatch &&
            indicatorDot('#FFEB3B', 'ai')}
        </Box>
      )}

      {/* Draft indicator */}
      {hasDraft && showIndicators && (
        <Box sx={{
          position: 'absolute', top: 1, right: overlong || overlongWarn ? 12 : 2,
          width: 8, height: 8, borderRadius: '50%',
          bgcolor: '#FF9800', border: '1px solid', borderColor: 'common.white', zIndex: 5,
        }} />
      )}

      {/* Overlong indicator — top-right triangle */}
      {overlong && showIndicators && (
        <Box sx={{
          position: 'absolute', top: 0, right: 0, zIndex: 5,
          width: 0, height: 0,
          borderStyle: 'solid',
          borderWidth: '0 10px 10px 0',
          borderColor: 'transparent #F44336 transparent transparent',
        }} />
      )}
      {overlongWarn && showIndicators && (
        <Box sx={{
          position: 'absolute', top: 0, right: 0, zIndex: 5,
          width: 0, height: 0,
          borderStyle: 'solid',
          borderWidth: '0 8px 8px 0',
          borderColor: 'transparent #FF9800 transparent transparent',
        }} />
      )}

      {/* Low confidence dashed border overlay */}
      {event.confidence < 0.5 && (
        <Box sx={{
          position: 'absolute', inset: 0, zIndex: 2,
          border: '1px dashed rgba(255,152,0,0.5)', borderRadius: 0.75,
          pointerEvents: 'none',
        }} />
      )}

      {/* Density-adaptive content */}
      {width > MINI_THRESHOLD && (
        <Box sx={{
          px: 0.75, height: '100%',
          display: 'flex', flexDirection: 'column', justifyContent: 'center',
          mt: showIndicators ? 1 : 0,
        }}>
          {width > DENSE_THRESHOLD && event.translation && (
            <Typography sx={{
              fontSize: '0.58rem', color: 'common.white', whiteSpace: 'nowrap',
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
          <Typography sx={{ fontSize: '0.45rem', color: 'common.white', fontWeight: 700 }}>
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

      {/* Inline edit overlay */}
      {editing && width > 40 && (
        <Box
          ref={editRef}
          contentEditable
          suppressContentEditableWarning
          onBlur={commitEdit}
          onKeyDown={handleKeyDown}
          sx={{
            position: 'absolute', inset: 0, zIndex: 10,
            bgcolor: 'rgba(0,0,0,0.85)', color: 'common.white',
            fontSize: '0.58rem', p: 0.5, outline: 'none',
            borderRadius: 0.75, overflow: 'auto',
          }}
        >
          {editText}
        </Box>
      )}
    </Box>
  )
}

export default memo(EventBlock)
