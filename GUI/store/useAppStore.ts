import { create } from 'zustand'
import type { PatchPreview, SpeakerInfo, TimelinePatchData } from '../types'
import type { Mode, PatchDraft, IssueFilter, JobState } from '../types/modes'

export type { Mode, PatchDraft, IssueFilter, JobState }

export interface AppState {
  mode: Mode
  selectedEventId: string | null
  playheadPosition: number
  currentProjectId: string | null

  unappliedPatches: PatchPreview[]
  pendingDrafts: Map<string, PatchDraft>
  appliedPatches: TimelinePatchData[]

  issueFilter: IssueFilter | null
  speakerFocus: SpeakerInfo | null

  modeSessions: Partial<Record<Mode, Record<string, unknown>>>
  localJobStatus: Record<string, JobState>

  // Actions
  setMode: (mode: Mode) => void
  selectEvent: (eventId: string | null) => void
  setPlayhead: (position: number) => void
  setCurrentProject: (projectId: string | null) => void

  addDraft: (draft: PatchDraft) => void
  removeDraft: (eventId: string) => void
  applyDraft: (eventId: string) => void
  discardDraft: (eventId: string) => void
  applyAllDrafts: () => void
  discardAllDrafts: () => void
  undoLastPatch: () => TimelinePatchData | null

  setUnappliedPatches: (patches: PatchPreview[]) => void
  setIssueFilter: (filter: IssueFilter | null) => void
  setSpeakerFocus: (speaker: SpeakerInfo | null) => void
  setJobStatus: (eventId: string, state: JobState) => void
  removeJobStatus: (eventId: string) => void
}

export const useAppStore = create<AppState>((set, get) => ({
  mode: 'timeline',
  selectedEventId: null,
  playheadPosition: 0,
  currentProjectId: null,

  unappliedPatches: [],
  pendingDrafts: new Map(),
  appliedPatches: [],

  issueFilter: null,
  speakerFocus: null,

  modeSessions: {},
  localJobStatus: {},

  // ── Mode ──
  setMode: (mode) => {
    const { mode: oldMode, modeSessions } = get()
    if (oldMode === mode) return

    const currentSession = {
      selectedEventId: get().selectedEventId,
      issueFilter: get().issueFilter,
      speakerFocus: get().speakerFocus,
    }
    const restored = modeSessions[mode] || {}

    set({
      mode,
      modeSessions: { ...modeSessions, [oldMode]: currentSession },
      selectedEventId: (restored.selectedEventId as string | null) ?? get().selectedEventId,
      issueFilter: (restored.issueFilter as IssueFilter | null) ?? null,
      speakerFocus: (restored.speakerFocus as SpeakerInfo | null) ?? null,
    })
  },

  // ── Selection ──
  selectEvent: (eventId) => set({ selectedEventId: eventId }),
  setPlayhead: (position) => set({ playheadPosition: position }),
  setCurrentProject: (projectId) => set({ currentProjectId: projectId }),

  // ── Drafts ──
  addDraft: (draft) => {
    const next = new Map(get().pendingDrafts)
    next.set(draft.eventId, draft)
    set({ pendingDrafts: next })
  },

  removeDraft: (eventId) => {
    const next = new Map(get().pendingDrafts)
    next.delete(eventId)
    set({ pendingDrafts: next })
  },

  applyDraft: (eventId) => {
    const draft = get().pendingDrafts.get(eventId)
    if (!draft) return

    // Record as applied patch
    const applied: TimelinePatchData = {
      patch_id: `draft_${Date.now()}`,
      opcode: draft.opcode,
      targets: [draft.eventId],
      payload: draft.payload,
      reason: ['user edit'],
      score: 1.0,
      confidence: 1.0,
      parent_version: '',
      idempotency_key: `user_${Date.now()}`,
      author: 'user',
      timestamp: new Date().toISOString(),
    }
    const patches = [...get().appliedPatches, applied]
    if (patches.length > 50) patches.shift() // cap history

    const next = new Map(get().pendingDrafts)
    next.delete(eventId)
    set({ pendingDrafts: next, appliedPatches: patches })
  },

  discardDraft: (eventId) => {
    const next = new Map(get().pendingDrafts)
    next.delete(eventId)
    set({ pendingDrafts: next })
  },

  applyAllDrafts: () => {
    set({ pendingDrafts: new Map() })
  },

  discardAllDrafts: () => {
    set({ pendingDrafts: new Map() })
  },

  undoLastPatch: () => {
    const patches = get().appliedPatches
    if (patches.length === 0) return null
    const removed = patches[patches.length - 1]
    set({ appliedPatches: patches.slice(0, -1) })
    return removed
  },

  // ── Patches ──
  setUnappliedPatches: (patches) => set({ unappliedPatches: patches }),

  // ── Filters ──
  setIssueFilter: (filter) => set({ issueFilter: filter }),
  setSpeakerFocus: (speaker) => set({ speakerFocus: speaker }),

  // ── Jobs ──
  setJobStatus: (eventId, state) => {
    set({ localJobStatus: { ...get().localJobStatus, [eventId]: state } })
  },
  removeJobStatus: (eventId) => {
    const next = { ...get().localJobStatus }
    delete next[eventId]
    set({ localJobStatus: next })
  },
}))
