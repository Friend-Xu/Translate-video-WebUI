import { useCallback, useRef, useState, useEffect } from 'react'
import { Box } from '@mui/material'
import { useAppStore } from '../../store/useAppStore'
import type { EventViewModel } from '../../types'

interface Props {
  events: EventViewModel[]
  children: React.ReactNode
  pixelToTime: (pixel: number) => number
  containerRef: React.RefObject<HTMLDivElement | null>
}

function isOnEventBlock(target: HTMLElement): boolean {
  let el: HTMLElement | null = target
  while (el) {
    if (el.dataset?.eventBlock === 'true') return true
    if (el.dataset?.arena === 'true') return false
    el = el.parentElement
  }
  return false
}

function isOnTrackHeader(target: HTMLElement): boolean {
  let el: HTMLElement | null = target
  while (el) {
    if (el.dataset?.trackHeader === 'true') return true
    if (el.dataset?.arena === 'true') return false
    el = el.parentElement
  }
  return false
}

export default function RubberBandSelect({
  events, children, pixelToTime, containerRef: _containerRef,
}: Props) {
  const [rubberBand, setRubberBand] = useState<{ x: number; y: number; w: number; h: number } | null>(null)
  const [dragging, setDragging] = useState(false)
  const startRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 })
  const selfRef = useRef<HTMLDivElement | null>(null)

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return
    const target = e.target as HTMLElement
    if (isOnEventBlock(target) || isOnTrackHeader(target)) return

    const rect = selfRef.current?.getBoundingClientRect()
    if (!rect) return

    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    startRef.current = { x, y }
    setRubberBand({ x, y, w: 0, h: 0 })
    setDragging(true)
  }, [])

  useEffect(() => {
    if (!dragging) return

    const onMove = (e: MouseEvent) => {
      const rect = selfRef.current?.getBoundingClientRect()
      if (!rect) return

      const x = e.clientX - rect.left
      const y = e.clientY - rect.top
      const sx = startRef.current.x
      const sy = startRef.current.y

      setRubberBand({
        x: Math.min(sx, x),
        y: Math.min(sy, y),
        w: Math.abs(x - sx),
        h: Math.abs(y - sy),
      })
    }

    const onUp = (e: MouseEvent) => {
      setDragging(false)
      setRubberBand(null)

      const rect = selfRef.current?.getBoundingClientRect()
      if (!rect) return

      const endX = e.clientX - rect.left
      const endY = e.clientY - rect.top
      const sx = startRef.current.x
      const sy = startRef.current.y

      const dX = Math.abs(endX - sx)
      const dY = Math.abs(endY - sy)

      if (dX < 5 && dY < 5) return

      const minTime = pixelToTime(Math.min(sx, endX))
      const maxTime = pixelToTime(Math.max(sx, endX))

      const inRect = events.filter(evt => evt.end >= minTime && evt.start <= maxTime)
      if (inRect.length === 0) return

      const store = useAppStore.getState()
      if (e.ctrlKey || e.metaKey) {
        const current = new Set(store.selectedEventIds)
        for (const evt of inRect) {
          if (current.has(evt.id)) current.delete(evt.id)
          else current.add(evt.id)
        }
        store.selectAllVisible(Array.from(current))
      } else if (e.shiftKey) {
        const current = new Set(store.selectedEventIds)
        for (const evt of inRect) current.add(evt.id)
        store.selectAllVisible(Array.from(current))
      } else {
        store.selectAllVisible(inRect.map(evt => evt.id))
      }
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [dragging, events, pixelToTime])

  return (
    <Box ref={selfRef} onMouseDown={handleMouseDown} sx={{ position: 'relative', height: '100%', width: '100%' }}>
      {children}

      {rubberBand && rubberBand.w > 2 && rubberBand.h > 2 && (
        <Box sx={{
          position: 'absolute',
          left: rubberBand.x,
          top: rubberBand.y,
          width: rubberBand.w,
          height: rubberBand.h,
          bgcolor: 'rgba(33, 150, 243, 0.15)',
          border: '1px solid rgba(33, 150, 243, 0.5)',
          zIndex: 30,
          pointerEvents: 'none',
          borderRadius: 0.5,
        }} />
      )}
    </Box>
  )
}
