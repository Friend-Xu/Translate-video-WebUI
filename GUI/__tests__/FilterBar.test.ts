import { describe, it, expect } from 'vitest'

interface EventLike {
  id: string; speaker: string | null; confidence: number
  start: number; end: number
  patches: { length: number }
  visualState?: { hasAiSuggestion?: boolean }
}

interface FilterState {
  minConfidence: number; maxConfidence: number; speakers: Set<string>
  patchStatus: 'all' | 'has' | 'no'; aiOnly: boolean; maxDuration: number
}

const DEFAULT_FILTER: FilterState = {
  minConfidence: 0, maxConfidence: 1, speakers: new Set(),
  patchStatus: 'all', aiOnly: false, maxDuration: 999,
}

function applyFilter(events: EventLike[], filter: FilterState): { visible: EventLike[]; dimmed: Set<string> } {
  const dimmed = new Set<string>()
  const visible = events.filter(e => {
    let match = true
    if (e.confidence < filter.minConfidence || e.confidence > filter.maxConfidence) match = false
    if (filter.speakers.size > 0 && e.speaker && !filter.speakers.has(e.speaker)) match = false
    if (filter.patchStatus === 'has' && e.patches.length === 0) match = false
    if (filter.patchStatus === 'no' && e.patches.length > 0) match = false
    if (filter.aiOnly && !e.visualState?.hasAiSuggestion) match = false
    if (e.end - e.start > filter.maxDuration) match = false
    if (!match) dimmed.add(e.id)
    return true
  })
  return { visible, dimmed }
}

function evt(overrides: Partial<EventLike> = {}): EventLike {
  return { id: 'e1', speaker: 'SPEAKER_00', confidence: 0.95, start: 0, end: 5, patches: { length: 0 }, ...overrides }
}

const events = [
  evt({ id: 'e1', confidence: 0.95, speaker: 'SPEAKER_00' }),
  evt({ id: 'e2', confidence: 0.50, speaker: 'SPEAKER_01' }),
  evt({ id: 'e3', confidence: 0.30, speaker: 'SPEAKER_00', patches: { length: 2 } }),
  evt({ id: 'e4', confidence: 0.99, speaker: null, start: 0, end: 12 }),
  evt({ id: 'e5', confidence: 0.80, speaker: 'SPEAKER_01', visualState: { hasAiSuggestion: true } }),
]

describe('applyFilter', () => {
  it('default filter shows all with nothing dimmed', () => {
    const { visible, dimmed } = applyFilter(events, DEFAULT_FILTER)
    expect(visible).toHaveLength(5)
    expect(dimmed.size).toBe(0)
  })

  it('minConfidence dims low-confidence', () => {
    const { dimmed } = applyFilter(events, { ...DEFAULT_FILTER, minConfidence: 0.6 })
    expect(dimmed.has('e2')).toBe(true)
    expect(dimmed.has('e3')).toBe(true)
    expect(dimmed.has('e1')).toBe(false)
  })

  it('speaker filter dims non-matching speakers', () => {
    const { dimmed } = applyFilter(events, { ...DEFAULT_FILTER, speakers: new Set(['SPEAKER_00']) })
    expect(dimmed.has('e2')).toBe(true)   // SPEAKER_01 — dimmed
    expect(dimmed.has('e4')).toBe(false)  // null speaker — not dimmed (no speaker to match)
    expect(dimmed.has('e1')).toBe(false)  // SPEAKER_00 — visible
    expect(dimmed.has('e3')).toBe(false)  // SPEAKER_00 — visible
  })

  it('patchStatus=has dims events without patches', () => {
    const { dimmed } = applyFilter(events, { ...DEFAULT_FILTER, patchStatus: 'has' })
    expect(dimmed.has('e3')).toBe(false)
    expect(dimmed.has('e1')).toBe(true)
  })

  it('patchStatus=no dims events with patches', () => {
    const { dimmed } = applyFilter(events, { ...DEFAULT_FILTER, patchStatus: 'no' })
    expect(dimmed.has('e3')).toBe(true)
    expect(dimmed.has('e1')).toBe(false)
  })

  it('aiOnly dims events without AI suggestions', () => {
    const { dimmed } = applyFilter(events, { ...DEFAULT_FILTER, aiOnly: true })
    expect(dimmed.has('e5')).toBe(false)
    expect(dimmed.has('e1')).toBe(true)
  })

  it('maxDuration dims overlong events', () => {
    const { dimmed } = applyFilter(events, { ...DEFAULT_FILTER, maxDuration: 8 })
    expect(dimmed.has('e4')).toBe(true)
    expect(dimmed.has('e1')).toBe(false)
  })
})
