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
  setScroll: (offset: number, opts?: { animate?: boolean }) => void
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
  externalScrollLeft: number = 0,
): TimelineCoordAPI {
  const [zoomLevel, setZoomLevel] = useState(1)
  const [scrollLeft, setScrollLeft] = useState(0)
  const animFrameRef = useRef<number>(0)

  const pixelsPerSec = BASE_PPS * zoomLevel

  const timeToPixel = useCallback((time: number) => {
    return time * pixelsPerSec - scrollLeft
  }, [pixelsPerSec, scrollLeft])

  const pixelToTime = useCallback((pixel: number) => {
    return Math.max(0, (pixel + scrollLeft + externalScrollLeft) / pixelsPerSec)
  }, [pixelsPerSec, scrollLeft, externalScrollLeft])

  const visibleRange = useMemo(() => ({
    startTime: Math.max(0, (scrollLeft + externalScrollLeft) / pixelsPerSec),
    endTime: Math.min(totalDuration, (scrollLeft + externalScrollLeft + canvasWidth) / pixelsPerSec),
  }), [scrollLeft, externalScrollLeft, canvasWidth, pixelsPerSec, totalDuration])

  const zoomTo = useCallback((newZoom: number, centerTime?: number) => {
    const clamped = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, newZoom))
    setZoomLevel(prev => {
      const oldPPS = BASE_PPS * prev
      const newPPS = BASE_PPS * clamped
      setScrollLeft(sl => {
        const ct = centerTime ?? ((sl + canvasWidth / 2) / oldPPS)
        const centerPx = ct * oldPPS - sl
        const newSL = ct * newPPS - centerPx
        const totalW = totalDuration * newPPS
        const maxS = Math.max(0, totalW - canvasWidth)
        return Math.max(0, Math.min(maxS, newSL))
      })
      return clamped
    })
  }, [totalDuration, canvasWidth])

  const zoomIn = useCallback(() => {
    zoomTo(zoomLevel * ZOOM_STEP)
  }, [zoomLevel, zoomTo])

  const zoomOut = useCallback(() => {
    zoomTo(zoomLevel / ZOOM_STEP)
  }, [zoomLevel, zoomTo])

  const setZoom = useCallback((level: number) => {
    setZoomLevel(Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, level)))
  }, [])

  const zoomToFit = useCallback((padding: number = 0.05) => {
    const dur = totalDuration || 1
    const availableW = canvasWidth * (1 - 2 * padding)
    const neededZoom = dur / (availableW / BASE_PPS)
    setZoomLevel(Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, neededZoom)))
    setScrollLeft(0)
  }, [totalDuration, canvasWidth])

  const zoomToTimeRange = useCallback((startTime: number, endTime: number) => {
    const dur = Math.max(0.5, endTime - startTime)
    const neededZoom = dur / (canvasWidth * 0.9 / BASE_PPS)
    const clamped = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, neededZoom))
    const mid = (startTime + endTime) / 2
    setZoomLevel(clamped)
    const newPPS = BASE_PPS * clamped
    const newSL = mid * newPPS - canvasWidth / 2
    const totalW = totalDuration * newPPS
    const maxS = Math.max(0, totalW - canvasWidth)
    setScrollLeft(Math.max(0, Math.min(maxS, newSL)))
  }, [totalDuration, canvasWidth])

  const setScroll = useCallback((offset: number, opts?: { animate?: boolean }) => {
    const totalW = totalDuration * pixelsPerSec
    const maxS = Math.max(0, totalW - canvasWidth)
    const clamped = Math.max(0, Math.min(maxS, offset))
    if (opts?.animate) {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current)
      const start = scrollLeft
      const delta = clamped - start
      const duration = 200
      const startTime = performance.now()
      const tick = (now: number) => {
        const elapsed = now - startTime
        const t = Math.min(1, elapsed / duration)
        const eased = t * (2 - t)
        setScrollLeft(start + delta * eased)
        if (t < 1) animFrameRef.current = requestAnimationFrame(tick)
      }
      animFrameRef.current = requestAnimationFrame(tick)
    } else {
      setScrollLeft(clamped)
    }
  }, [totalDuration, canvasWidth, pixelsPerSec, scrollLeft])

  const scrollToTime = useCallback((time: number) => {
    setScrollLeft(Math.max(0, time * pixelsPerSec - canvasWidth * 0.3))
  }, [pixelsPerSec, canvasWidth])

  const centerOnTime = useCallback((time: number) => {
    const totalW = totalDuration * pixelsPerSec
    const maxS = Math.max(0, totalW - canvasWidth)
    const sl = time * pixelsPerSec - canvasWidth / 2
    setScroll(Math.max(0, Math.min(maxS, sl)))
  }, [totalDuration, canvasWidth, pixelsPerSec, setScroll])

  return {
    timeToPixel, pixelToTime, pixelsPerSec, zoomLevel,
    zoomIn, zoomOut, setZoom, zoomTo, zoomToFit, zoomToTimeRange,
    scrollToTime, setScroll, centerOnTime,
    visibleRange, canvasWidth,
  }
}
