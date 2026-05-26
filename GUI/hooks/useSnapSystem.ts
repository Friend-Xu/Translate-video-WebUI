import { useCallback } from 'react'
import type { SnapTarget, SnapResult, SnapTargetType } from '../types/timeline'
import type { EventViewModel } from '../types'

interface UseSnapSystemOptions {
  events: EventViewModel[]
  playheadTime: number
  markers?: { time: number }[]
  totalDuration: number
  timeToPixel: (time: number) => number
  pixelToTime: (pixel: number) => number
  thresholdPx?: number
  enabled: boolean
}

const DEFAULT_THRESHOLD = 8

const PRIORITY: Record<SnapTargetType, number> = {
  playhead: 0,
  marker: 1,
  'event-boundary': 2,
  grid: 3,
}

export function useSnapSystem(options: UseSnapSystemOptions) {
  const { events, playheadTime, markers, totalDuration, timeToPixel, pixelToTime, thresholdPx, enabled } = options
  const threshold = thresholdPx ?? DEFAULT_THRESHOLD

  const findNearestSnapTarget = useCallback((pixelX: number): SnapResult | null => {
    if (!enabled) return null

    const candidates: SnapTarget[] = []

    candidates.push({
      pixelX: timeToPixel(playheadTime),
      time: playheadTime,
      type: 'playhead',
    })

    for (const evt of events) {
      candidates.push({
        pixelX: timeToPixel(evt.start),
        time: evt.start,
        type: 'event-boundary',
        label: `${evt.id}.start`,
      })
      candidates.push({
        pixelX: timeToPixel(evt.end),
        time: evt.end,
        type: 'event-boundary',
        label: `${evt.id}.end`,
      })
    }

    for (const m of (markers || [])) {
      candidates.push({
        pixelX: timeToPixel(m.time),
        time: m.time,
        type: 'marker',
      })
    }

    // Grid lines within proximity (0.5s steps)
    const visibleStart = pixelToTime(pixelX - threshold * 2)
    const visibleEnd = pixelToTime(pixelX + threshold * 2)
    for (let t = 0; t <= totalDuration; t += 0.5) {
      if (t >= visibleStart && t <= visibleEnd) {
        candidates.push({
          pixelX: timeToPixel(t),
          time: t,
          type: 'grid',
        })
      }
    }

    const ranked = candidates
      .map(c => ({ ...c, distancePx: Math.abs(c.pixelX - pixelX) }))
      .filter(c => c.distancePx <= threshold)
      .sort((a, b) => {
        const d = a.distancePx - b.distancePx
        if (Math.abs(d) > 0.1) return d
        return (PRIORITY[a.type] ?? 99) - (PRIORITY[b.type] ?? 99)
      })

    if (ranked.length === 0) return null

    const best = ranked[0]
    return {
      snappedPixel: best.pixelX,
      snappedTime: best.time,
      type: best.type,
      distancePx: best.distancePx,
    }
  }, [enabled, playheadTime, events, markers, totalDuration, timeToPixel, pixelToTime, threshold])

  return { findNearestSnapTarget }
}
