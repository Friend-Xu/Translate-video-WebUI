import { useState, useCallback, useMemo, useRef } from 'react'

export interface TimelineCoordAPI {
  timeToPixel: (time: number) => number
  pixelToTime: (pixel: number) => number
  pixelsPerSec: number
  zoomLevel: number
  zoomIn: (centerTime?: number) => void
  zoomOut: (centerTime?: number) => void
  setZoom: (level: number) => void
  zoomTo: (newZoom: number, centerTime?: number) => void
  zoomToFit: (padding?: number) => void
  zoomToTimeRange: (startTime: number, endTime: number) => void
  scrollToTime: (time: number) => void
  centerOnTime: (time: number) => void
  visibleRange: { startTime: number; endTime: number }
  canvasWidth: number
}

const MIN_ZOOM = 0.1
const MAX_ZOOM = 50
const BASE_PPS = 80
const ZOOM_STEP = 1.3

export function useTimelineCoordinates(
  totalDuration: number,
  canvasWidth: number,
  scrollPx: number = 0,
  onScrollChange?: (px: number) => void,
): TimelineCoordAPI {
  const [zoomLevel, setZoomLevel] = useState(1)
  const animFrameRef = useRef<number>(0)

  const pixelsPerSec = BASE_PPS * zoomLevel

  const setScroll = useCallback((offset: number, opts?: { animate?: boolean }) => {
    if (!onScrollChange) return
    const totalW = totalDuration * pixelsPerSec
    const maxS = Math.max(0, totalW - canvasWidth)
    const clamped = Math.max(0, Math.min(maxS, offset))
    if (opts?.animate) {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current)
      const start = scrollPx
      const delta = clamped - start
      const duration = 200
      const startT = performance.now()
      const tick = (now: number) => {
        const elapsed = now - startT
        const t = Math.min(1, elapsed / duration)
        const eased = t * (2 - t)
        onScrollChange(start + delta * eased)
        if (t < 1) animFrameRef.current = requestAnimationFrame(tick)
      }
      animFrameRef.current = requestAnimationFrame(tick)
    } else {
      onScrollChange(clamped)
    }
  }, [totalDuration, canvasWidth, pixelsPerSec, scrollPx, onScrollChange])

  const timeToPixel = useCallback((time: number) => {
    return time * pixelsPerSec - scrollPx
  }, [pixelsPerSec, scrollPx])

  const pixelToTime = useCallback((pixel: number) => {
    return Math.max(0, (pixel + scrollPx) / pixelsPerSec)
  }, [pixelsPerSec, scrollPx])

  const visibleRange = useMemo(() => ({
    startTime: Math.max(0, scrollPx / pixelsPerSec),
    endTime: Math.min(totalDuration, (scrollPx + canvasWidth) / pixelsPerSec),
  }), [scrollPx, canvasWidth, pixelsPerSec, totalDuration])

  const zoomTo = useCallback((newZoom: number, centerTime?: number) => {
    const clamped = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, newZoom))
    setZoomLevel(prev => {
      const oldPPS = BASE_PPS * prev
      const newPPS = BASE_PPS * clamped
      const ct = centerTime ?? ((scrollPx + canvasWidth / 2) / oldPPS)
      const newSL = ct * newPPS - canvasWidth / 2
      const totalW = totalDuration * newPPS
      const maxS = Math.max(0, totalW - canvasWidth)
      if (onScrollChange) onScrollChange(Math.max(0, Math.min(maxS, newSL)))
      return clamped
    })
  }, [totalDuration, canvasWidth, scrollPx, onScrollChange])

  const zoomIn = useCallback(() => zoomTo(zoomLevel * ZOOM_STEP), [zoomLevel, zoomTo])
  const zoomOut = useCallback(() => zoomTo(zoomLevel / ZOOM_STEP), [zoomLevel, zoomTo])

  const setZoom = useCallback((level: number) => {
    setZoomLevel(Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, level)))
  }, [])

  const zoomToFit = useCallback((padding: number = 0.05) => {
    const dur = totalDuration || 1
    const availableW = canvasWidth * (1 - 2 * padding)
    const neededZoom = dur / (availableW / BASE_PPS)
    setZoomLevel(Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, neededZoom)))
    if (onScrollChange) onScrollChange(0)
  }, [totalDuration, canvasWidth, onScrollChange])

  const zoomToTimeRange = useCallback((startTime: number, endTime: number) => {
    const dur = Math.max(0.5, endTime - startTime)
    const neededZoom = dur / (canvasWidth * 0.9 / BASE_PPS)
    const clamped = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, neededZoom))
    const mid = (startTime + endTime) / 2
    setZoomLevel(clamped)
    const newPPS = BASE_PPS * clamped
    if (onScrollChange) onScrollChange(Math.max(0, mid * newPPS - canvasWidth / 2))
  }, [totalDuration, canvasWidth, onScrollChange])

  const scrollToTime = useCallback((time: number) => {
    setScroll(Math.max(0, time * pixelsPerSec - canvasWidth * 0.3))
  }, [pixelsPerSec, canvasWidth, setScroll])

  const centerOnTime = useCallback((time: number) => {
    setScroll(Math.max(0, time * pixelsPerSec - canvasWidth / 2))
  }, [pixelsPerSec, canvasWidth, setScroll])

  return {
    timeToPixel, pixelToTime, pixelsPerSec, zoomLevel,
    zoomIn, zoomOut, setZoom, zoomTo, zoomToFit, zoomToTimeRange,
    scrollToTime, centerOnTime,
    visibleRange, canvasWidth,
  }
}
