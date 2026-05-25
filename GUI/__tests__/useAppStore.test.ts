import { describe, it, expect, beforeEach } from 'vitest'
import { create } from 'zustand'
import type { PatchDraft } from '../types/modes'

interface TestState {
  mode: string
  pendingDrafts: Map<string, PatchDraft>
  appliedPatches: { patch_id: string; opcode: string; targets: string[]; author: string }[]
  setMode: (m: string) => void
  addDraft: (d: PatchDraft) => void
  applyDraft: (id: string) => void
  applyAllDrafts: () => void
  undoLastPatch: () => unknown
}

const useTestStore = create<TestState>((set, get) => ({
  mode: 'timeline',
  pendingDrafts: new Map(),
  appliedPatches: [],
  setMode: (mode) => set({ mode }),
  addDraft: (draft) => {
    const next = new Map(get().pendingDrafts)
    next.set(draft.eventId, draft)
    set({ pendingDrafts: next })
  },
  applyDraft: (eventId) => {
    const draft = get().pendingDrafts.get(eventId)
    if (!draft) return
    const applied = { patch_id: `draft_${Date.now()}`, opcode: draft.opcode, targets: [draft.eventId], author: 'user' }
    const next = new Map(get().pendingDrafts)
    next.delete(eventId)
    set({ pendingDrafts: next, appliedPatches: [...get().appliedPatches, applied] })
  },
  applyAllDrafts: () => {
    const drafts = get().pendingDrafts
    if (drafts.size === 0) return
    const newPatches = Array.from(drafts.entries()).map(([eventId, draft]) => ({
      patch_id: `batch_${Date.now()}_${eventId}`, opcode: draft.opcode, targets: [draft.eventId], author: 'user',
    }))
    set({ pendingDrafts: new Map(), appliedPatches: [...get().appliedPatches, ...newPatches] })
  },
  undoLastPatch: () => {
    const patches = get().appliedPatches
    if (patches.length === 0) return null
    const removed = patches[patches.length - 1]
    set({ appliedPatches: patches.slice(0, -1) })
    return removed
  },
}))

const draftFactory = (overrides = {}): PatchDraft => ({
  eventId: 'evt_001', opcode: 'SET_TRANSLATION',
  payload: { translation: '你好' },
  before: { translation: 'Hello' },
  after: { translation: '你好' },
  timestamp: Date.now(),
  ...overrides,
})

describe('Mode switching', () => {
  beforeEach(() => useTestStore.setState({ mode: 'timeline' }))
  it('defaults to timeline', () => expect(useTestStore.getState().mode).toBe('timeline'))
  it('setMode changes mode', () => {
    useTestStore.getState().setMode('speaker')
    expect(useTestStore.getState().mode).toBe('speaker')
  })
})

describe('Draft CRUD', () => {
  beforeEach(() => useTestStore.setState({ pendingDrafts: new Map(), appliedPatches: [] }))

  it('addDraft stores a draft', () => {
    useTestStore.getState().addDraft(draftFactory())
    expect(useTestStore.getState().pendingDrafts.size).toBe(1)
    expect(useTestStore.getState().pendingDrafts.get('evt_001')?.opcode).toBe('SET_TRANSLATION')
  })

  it('applyDraft removes draft and creates applied patch', () => {
    useTestStore.getState().addDraft(draftFactory())
    useTestStore.getState().applyDraft('evt_001')
    expect(useTestStore.getState().pendingDrafts.size).toBe(0)
    expect(useTestStore.getState().appliedPatches).toHaveLength(1)
    expect(useTestStore.getState().appliedPatches[0].opcode).toBe('SET_TRANSLATION')
  })

  it('applyAllDrafts processes all drafts', () => {
    useTestStore.getState().addDraft(draftFactory())
    useTestStore.getState().addDraft(draftFactory({ eventId: 'evt_002', opcode: 'RETAG_SPEAKER' }))
    useTestStore.getState().applyAllDrafts()
    expect(useTestStore.getState().pendingDrafts.size).toBe(0)
    expect(useTestStore.getState().appliedPatches).toHaveLength(2)
  })

  it('applyAllDrafts with empty drafts does nothing', () => {
    useTestStore.getState().applyAllDrafts()
    expect(useTestStore.getState().appliedPatches).toHaveLength(0)
  })

  it('undoLastPatch removes last applied patch', () => {
    useTestStore.getState().addDraft(draftFactory())
    useTestStore.getState().applyDraft('evt_001')
    const removed = useTestStore.getState().undoLastPatch()
    expect(removed).not.toBeNull()
    expect(useTestStore.getState().appliedPatches).toHaveLength(0)
  })

  it('undoLastPatch returns null when no patches', () => {
    expect(useTestStore.getState().undoLastPatch()).toBeNull()
  })
})
