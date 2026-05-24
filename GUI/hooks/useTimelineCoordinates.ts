import { useState, useCallback, useMemo } from 'react'

interface TimelineCoordAPI {
  timeToPixel: (time: number) => number
  pixelToTime: (pixel: number) => number
  pixelsPerSec: number
  zoomIn: (centerTime?: number) => void
  zoomOut: (centerTime?: number) => void
  setZoom: (level: number) => void
  scrollToTime: (time: number) => void
  setScroll: (offset: number) => void
  visibleRange: { startTime: number; endTime: number }
}

const MIN_ZOOM = 0.1
const MAX_ZOOM = 50
const BASE_PPS = 80
const ZOOM_STEP = 1.3

export function useTimelineCoordinates(
  totalDuration: number,
  canvasWidth: number,
): TimelineCoordAPI {
  const [zoomLevel, setZoomLevel] = useState(1)
  const [scrollLeft, setScrollLeft] = useState(0)

  const pixelsPerSec = BASE_PPS * zoomLevel

  const timeToPixel = useCallback((time: number) => {
    return time * pixelsPerSec - scrollLeft
  }, [pixelsPerSec, scrollLeft])

  const pixelToTime = useCallback((pixel: number) => {
    return Math.max(0, (pixel + scrollLeft) / pixelsPerSec)
  }, [pixelsPerSec, scrollLeft])

  const visibleRange = useMemo(() => ({
    startTime: Math.max(0, scrollLeft / pixelsPerSec),
    endTime: Math.min(totalDuration, (scrollLeft + canvasWidth) / pixelsPerSec),
  }), [scrollLeft, canvasWidth, pixelsPerSec, totalDuration])

  const zoomIn = useCallback(() => {
    setZoomLevel(prev => Math.min(MAX_ZOOM, prev * ZOOM_STEP))
  }, [])

  const zoomOut = useCallback(() => {
    setZoomLevel(prev => Math.max(MIN_ZOOM, prev / ZOOM_STEP))
  }, [])

  const setZoom = useCallback((level: number) => {
    setZoomLevel(Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, level)))
  }, [])

  const scrollToTime = useCallback((time: number) => {
    setScrollLeft(Math.max(0, time * pixelsPerSec - canvasWidth * 0.3))
  }, [pixelsPerSec, canvasWidth])

  const setScroll = useCallback((offset: number) => {
    const totalWidth = totalDuration * pixelsPerSec
    const maxScroll = Math.max(0, totalWidth - canvasWidth)
    setScrollLeft(Math.max(0, Math.min(maxScroll, offset)))
  }, [totalDuration, canvasWidth, pixelsPerSec])

  return {
    timeToPixel, pixelToTime, pixelsPerSec,
    zoomIn, zoomOut, setZoom,
    scrollToTime, setScroll,
    visibleRange,
  }
}
