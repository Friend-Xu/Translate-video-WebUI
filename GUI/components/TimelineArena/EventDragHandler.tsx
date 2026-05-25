import { useCallback, useRef, useState } from 'react'
import { Box } from '@mui/material'
import { useAppStore } from '../../store/useAppStore'
import { useSnapSystem } from '../../hooks/useSnapSystem'
import type { EventViewModel } from '../../types'
import type { TimelineCoordAPI } from '../../hooks/useTimelineCoordinates'
import EventBlock from '../sections/EventBlock'

interface Props {
  event: EventViewModel
  coord: TimelineCoordAPI
  laneColor: string
  laneHeight: number
  isSelected: boolean
  isMultiSelected: boolean
  hasDraft: boolean
  readOnly: boolean
  onClick: (e: React.MouseEvent) => void
  onDoubleClick: () => void
  onContextMenu: (e: React.MouseEvent) => void
}

type DragMode = 'none' | 'move' | 'resize-left' | 'resize-right'

export default function EventDragHandler({
  event, coord, laneColor, laneHeight,
  isSelected, isMultiSelected, hasDraft, readOnly,
  onClick, onDoubleClick, onContextMenu,
}: Props) {
  const snapEnabled = useAppStore(s => s.snapEnabled)
  const playheadPosition = useAppStore(s => s.playheadPosition)
  const addDraft = useAppStore(s => s.addDraft)

  const [dragMode, setDragMode] = useState<DragMode>('none')
  const [previewX, setPreviewX] = useState<number | null>(null)
  const [previewWidth, setPreviewWidth] = useState<number | null>(null)
  const dragRef = useRef<{ startX: number; origStart: number; origEnd: number }>({
    startX: 0, origStart: event.start, origEnd: event.end,
  })

  const allEvents = useAppStore.getState().selectedEventIds.length >= 0
    ? [] // Populated from caller context — we need access to all events
    : []
  const { findNearestSnapTarget } = useSnapSystem({
    events: allEvents,
    playheadTime: playheadPosition,
    totalDuration: event.end * 2 || 80,
    timeToPixel: coord.timeToPixel,
    pixelToTime: coord.pixelToTime,
    thresholdPx: 8,
    enabled: snapEnabled,
  })

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (readOnly) return
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    const relX = e.clientX - rect.left
    const blockWidth = rect.width

    const nearEdge = relX < 8 ? 'resize-left' : relX > blockWidth - 8 ? 'resize-right' : null
    const mode: DragMode = nearEdge || 'move'

    setDragMode(mode)
    dragRef.current = { startX: e.clientX - rect.left, origStart: event.start, origEnd: event.end }
    e.preventDefault()
    e.stopPropagation()
  }, [readOnly, event])

  const snapPixel = useCallback((pixelX: number) => {
    if (!snapEnabled) return pixelX
    const result = findNearestSnapTarget(pixelX)
    return result ? result.snappedPixel : pixelX
  }, [snapEnabled, findNearestSnapTarget])

  const handleMouseUp = useCallback(() => {
    if (dragMode === 'none') return
    const { origStart, origEnd } = dragRef.current

    if (dragMode === 'move' && previewX != null) {
      const snappedTime = coord.pixelToTime(previewX)
      const duration = origEnd - origStart
      addDraft({
        eventId: event.id,
        opcode: 'MOVE_EVENT',
        payload: { start: snappedTime, end: snappedTime + duration },
        before: { start: origStart, end: origEnd },
        after: { start: snappedTime, end: snappedTime + duration },
        timestamp: Date.now(),
      })
    } else if (dragMode === 'resize-left' && previewX != null) {
      const snappedTime = coord.pixelToTime(previewX)
      addDraft({
        eventId: event.id,
        opcode: 'TRIM_START',
        payload: { start: snappedTime },
        before: { start: origStart, end: origEnd },
        after: { start: snappedTime, end: origEnd },
        timestamp: Date.now(),
      })
    } else if (dragMode === 'resize-right' && previewWidth != null) {
      const newEnd = origStart + previewWidth / coord.pixelsPerSec
      addDraft({
        eventId: event.id,
        opcode: 'TRIM_END',
        payload: { end: newEnd },
        before: { start: origStart, end: origEnd },
        after: { start: origStart, end: newEnd },
        timestamp: Date.now(),
      })
    }

    setDragMode('none')
    setPreviewX(null)
    setPreviewWidth(null)
  }, [dragMode, previewX, previewWidth, event.id, coord, addDraft])

  const onBlockMouseDown = useCallback((e: React.MouseEvent) => {
    handleMouseDown(e)
    if (!readOnly) {
      const onMove = (ev: MouseEvent) => {
        const dx = ev.movementX

        if (dragRef.current.startX === 0) return

        const { origStart, origEnd } = dragRef.current

        if (dragMode === 'move') {
          const curPx = (previewX ?? coord.timeToPixel(origStart)) + dx
          const snapped = snapPixel(curPx)
          setPreviewX(snapped)
        } else if (dragMode === 'resize-left') {
          const curPx = (previewX ?? coord.timeToPixel(origStart)) + dx
          const snapped = snapPixel(curPx)
          const newStart = coord.pixelToTime(snapped)
          if (newStart < origEnd - 0.1) {
            setPreviewX(snapped)
            setPreviewWidth(Math.max(3, (origEnd - newStart) * coord.pixelsPerSec))
          }
        } else if (dragMode === 'resize-right') {
          const curW = (previewWidth ?? (origEnd - origStart) * coord.pixelsPerSec) + dx
          const newEnd = origStart + Math.max(3, curW) / coord.pixelsPerSec
          if (newEnd > origStart + 0.1) {
            setPreviewWidth(Math.max(3, curW))
          }
        }
      }

      const onUp = () => {
        window.removeEventListener('mousemove', onMove)
        window.removeEventListener('mouseup', onUp)
        handleMouseUp()
      }

      window.addEventListener('mousemove', onMove)
      window.addEventListener('mouseup', onUp)
    }
  }, [handleMouseDown, handleMouseUp, readOnly, coord, snapPixel])

  const width = Math.max(3, (event.end - event.start) * coord.pixelsPerSec)
  const left = coord.timeToPixel(event.start)

  return (
    <Box sx={{ position: 'absolute', left: 0, top: 0 }}>
      {/* Draft preview — original position ghost */}
      {dragMode !== 'none' && (
        <Box sx={{
          position: 'absolute',
          left, top: 6,
          width, height: laneHeight - 12,
          border: '2px dashed rgba(255,152,0,0.6)',
          borderRadius: 0.75,
          pointerEvents: 'none', zIndex: 4,
        }} />
      )}

      {/* Draft preview — new position */}
      {dragMode !== 'none' && previewX != null && (
        <Box sx={{
          position: 'absolute',
          left: previewX, top: 6,
          width: previewWidth ?? width, height: laneHeight - 12,
          bgcolor: 'rgba(255,152,0,0.25)',
          borderRadius: 0.75,
          border: '1px solid rgba(255,152,0,0.5)',
          pointerEvents: 'none', zIndex: 5,
        }} />
      )}

      {/* Actual EventBlock with mouseDown trigger */}
      <Box onMouseDown={onBlockMouseDown} sx={{ cursor: readOnly ? 'default' : dragMode !== 'none' ? 'grabbing' : 'grab' }}>
        <EventBlock
          event={event}
          laneColor={laneColor}
          left={left}
          width={width}
          laneHeight={laneHeight}
          isSelected={isSelected}
          isMultiSelected={isMultiSelected}
          hasDraft={hasDraft}
          readOnly={readOnly}
          onClick={onClick}
          onDoubleClick={onDoubleClick}
          onContextMenu={onContextMenu}
        />
      </Box>
    </Box>
  )
}
