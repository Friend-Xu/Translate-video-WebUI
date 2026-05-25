import { useMemo } from 'react'
import type { EventViewModel } from '../types'

interface UseVirtualEventsOptions {
  events: EventViewModel[]
  visibleStartTime: number
  visibleEndTime: number
  bufferSec: number
  totalDuration: number
  pixelsPerSec: number
}

interface UseVirtualEventsResult {
  virtualEvents: EventViewModel[]
  startIndex: number
  endIndex: number
  totalVirtualWidth: number
}

export function useVirtualEvents({
  events, visibleStartTime, visibleEndTime, bufferSec, totalDuration, pixelsPerSec,
}: UseVirtualEventsOptions): UseVirtualEventsResult {
  return useMemo(() => {
    const bufferStart = visibleStartTime - bufferSec
    const bufferEnd = visibleEndTime + bufferSec

    // Binary search for first event whose end > bufferStart
    let lo = 0
    let hi = events.length
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (events[mid].end <= bufferStart) lo = mid + 1
      else hi = mid
    }
    const startIndex = lo

    // Binary search for first event whose start > bufferEnd
    lo = 0
    hi = events.length
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (events[mid].start <= bufferEnd) lo = mid + 1
      else hi = mid
    }
    const endIndex = lo

    const virtualEvents = events.slice(startIndex, endIndex)
    const totalVirtualWidth = totalDuration * pixelsPerSec

    return { virtualEvents, startIndex, endIndex, totalVirtualWidth }
  }, [events, visibleStartTime, visibleEndTime, bufferSec, totalDuration, pixelsPerSec])
}
