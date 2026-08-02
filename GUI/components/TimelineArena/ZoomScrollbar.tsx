import { useRef, useCallback, useState } from 'react'
import { Box } from '@mui/material'
import type { TimelineCoordAPI } from '../../hooks/useTimelineCoordinates'

interface Props {
  coord: TimelineCoordAPI
  totalDuration: number
  canvasWidth: number
}

export default function ZoomScrollbar({ coord, totalDuration, canvasWidth }: Props) {
  const barRef = useRef<HTMLDivElement | null>(null)
  const [dragging, setDragging] = useState<'none' | 'center' | 'left' | 'right'>('none')

  const { visibleRange } = coord
  const thumbLeft = visibleRange.startTime / totalDuration * canvasWidth
  const thumbWidth = Math.max(4, (visibleRange.endTime - visibleRange.startTime) / totalDuration * canvasWidth)

  const handleMouseDown = useCallback((e: React.MouseEvent, part: 'center' | 'left' | 'right') => {
    e.preventDefault()
    setDragging(part)

    const startX = e.clientX
    const startTime = visibleRange.startTime + (visibleRange.endTime - visibleRange.startTime) / 2
    const startLeft = thumbLeft
    const startWidth = thumbWidth

    const onMove = (ev: MouseEvent) => {
      const dx = ev.clientX - startX
      if (part === 'center') {
        const dt = dx / canvasWidth * totalDuration
        coord.centerOnTime(startTime - dt)
      } else if (part === 'left') {
        const newLeft = startLeft + dx
        const newRight = startLeft + startWidth
        if (newLeft < newRight - 4) {
          const newStart = (newLeft / canvasWidth) * totalDuration
          const newEnd = (newRight / canvasWidth) * totalDuration
          coord.zoomToTimeRange(newStart, newEnd)
        }
      } else if (part === 'right') {
        const newRight = startLeft + startWidth + dx
        if (newRight > startLeft + 4) {
          const newEnd = (newRight / canvasWidth) * totalDuration
          coord.zoomToTimeRange(visibleRange.startTime, newEnd)
        }
      }
    }

    const onUp = () => {
      setDragging('none')
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [coord, totalDuration, canvasWidth, thumbLeft, thumbWidth, visibleRange.startTime])

  const handleBarClick = useCallback((e: React.MouseEvent) => {
    if (dragging !== 'none') return
    const rect = barRef.current?.getBoundingClientRect()
    if (!rect) return
    const relX = e.clientX - rect.left
    const targetTime = (relX / canvasWidth) * totalDuration
    coord.centerOnTime(targetTime)
  }, [coord, totalDuration, canvasWidth, dragging])

  return (
    <Box
      ref={barRef}
      onClick={handleBarClick}
      sx={{
        height: 16, width: canvasWidth, position: 'relative',
        bgcolor: 'rgba(255,255,255,0.04)', cursor: 'pointer',
        borderTop: '1px solid rgba(255,255,255,0.08)',
      }}
    >
      <Box
        onMouseDown={(e) => handleMouseDown(e as any, 'center')}
        sx={{
          position: 'absolute', left: thumbLeft, top: 2, bottom: 2,
          width: thumbWidth, bgcolor: 'rgba(255,255,255,0.15)',
          borderRadius: 0.5, cursor: 'grab',
          '&:hover': { bgcolor: 'rgba(255,255,255,0.25)' },
        }}
      >
        <Box
          onMouseDown={(e) => { e.stopPropagation(); handleMouseDown(e as any, 'left') }}
          sx={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 6, cursor: 'col-resize' }}
        />
        <Box
          onMouseDown={(e) => { e.stopPropagation(); handleMouseDown(e as any, 'right') }}
          sx={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: 6, cursor: 'col-resize' }}
        />
      </Box>
    </Box>
  )
}
