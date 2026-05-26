import { useCallback } from 'react'
import type { EventViewModel } from '../types'

export interface ConflictInfo {
  hasConflict: boolean
  overlappingEvents: EventViewModel[]
  overlapStart: number
  overlapEnd: number
}

export function useConflictDetector(events: EventViewModel[]) {
  const checkConflict = useCallback((movingEventId: string, newStart: number, newEnd: number): ConflictInfo => {
    const overlapping = events.filter(evt => {
      if (evt.id === movingEventId) return false
      return evt.start < newEnd && evt.end > newStart
    })

    const overlapStart = overlapping.length > 0
      ? Math.max(newStart, Math.min(...overlapping.map(e => e.start)))
      : 0
    const overlapEnd = overlapping.length > 0
      ? Math.min(newEnd, Math.max(...overlapping.map(e => e.end)))
      : 0

    return {
      hasConflict: overlapping.length > 0,
      overlappingEvents: overlapping,
      overlapStart,
      overlapEnd,
    }
  }, [events])

  return { checkConflict }
}
