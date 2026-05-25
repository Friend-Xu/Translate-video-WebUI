import { create } from 'zustand'
import type { PatchPreview, SpeakerInfo, TimelinePatchData } from '../types'
import type { Mode, PatchDraft, IssueFilter, JobState, CrossModeContext, SpeakerLaneData, SpeakerQuality, VoiceCard } from '../types/modes'
import type { TrackDefinition } from '../types/timeline'
import { DEFAULT_TRACKS, TRACK_VISIBILITY_MAP } from '../types/timeline'

export type { Mode, PatchDraft, IssueFilter, JobState }

export interface AppState {
  mode: Mode
  selectedEventIds: string[]
  selectedEventId: string | null
  playheadPosition: number
  currentProjectId: string | null

  tracks: TrackDefinition[]
  snapEnabled: boolean
  trackScrollLeft: number

  unappliedPatches: PatchPreview[]
  pendingDrafts: Map<string, PatchDraft>
  appliedPatches: TimelinePatchData[]

  issueFilter: IssueFilter | null
  speakerFocus: SpeakerInfo | null

  modeSessions: Partial<Record<Mode, Record<string, unknown>>>
  localJobStatus: Record<string, JobState>

  crossModeContext: CrossModeContext | null
  dockCollapsed: boolean
  debugMode: boolean

  // Speaker Review state
  speakerLanes: SpeakerLaneData[]
  speakerQualities: Record<string, SpeakerQuality>
  selectedSpeakerId: string | null
  selectedSpeakerIds: string[]
  voicePresets: VoiceCard[]

  // Actions — Mode
  setMode: (mode: Mode) => void
  navigateToEvent: (eventId: string, startTime: number, sourceMode?: Mode) => void

  // Actions — Selection
  selectEvent: (eventId: string | null, multi?: boolean) => void
  toggleEventSelection: (eventId: string) => void
  selectEventRange: (eventId: string) => void
  selectAllVisible: (ids: string[]) => void
  clearSelection: () => void
  setPlayhead: (position: number) => void

  // Actions — Project
  setCurrentProject: (projectId: string | null) => void

  // Actions — Tracks
  setTracks: (tracks: TrackDefinition[]) => void
  updateTrack: (id: string, partial: Partial<TrackDefinition>) => void
  resizeTrack: (id: string, height: number) => void
  toggleTrackVisibility: (id: string) => void
  toggleTrackLock: (id: string) => void
  toggleTrackSolo: (id: string) => void
  toggleTrackMute: (id: string) => void
  setSnapEnabled: (v: boolean) => void
  setTrackScrollLeft: (px: number) => void

  // Actions — Drafts
  addDraft: (draft: PatchDraft) => void
  removeDraft: (eventId: string) => void
  applyDraft: (eventId: string) => void
  discardDraft: (eventId: string) => void
  applyAllDrafts: () => void
  discardAllDrafts: () => void
  undoLastPatch: () => TimelinePatchData | null

  // Actions — Patches / Filters / Jobs
  setUnappliedPatches: (patches: PatchPreview[]) => void
  setIssueFilter: (filter: IssueFilter | null) => void
  setSpeakerFocus: (speaker: SpeakerInfo | null) => void
  setJobStatus: (eventId: string, state: JobState) => void
  removeJobStatus: (eventId: string) => void
  toggleDockCollapsed: () => void
  toggleDebugMode: () => void

  // Actions — Speaker Review
  setSpeakerLanes: (lanes: SpeakerLaneData[]) => void
  setSelectedSpeaker: (speakerId: string | null) => void
  toggleSpeakerSelection: (speakerId: string) => void
  setVoicePresets: (presets: VoiceCard[]) => void
  setSpeakerQualities: (qualities: Record<string, SpeakerQuality>) => void
  bindVoice: (speakerId: string, voiceId: string) => void
}

export const useAppStore = create<AppState>((set, get) => ({
  mode: 'timeline',
  selectedEventIds: [],
  selectedEventId: null,
  playheadPosition: 0,
  currentProjectId: null,

  tracks: DEFAULT_TRACKS,
  snapEnabled: true,
  trackScrollLeft: 0,

  unappliedPatches: [],
  pendingDrafts: new Map(),
  appliedPatches: [],

  issueFilter: null,
  speakerFocus: null,

  modeSessions: {},
  localJobStatus: {},

  crossModeContext: null,
  dockCollapsed: false,
  debugMode: false,

  speakerLanes: [],
  speakerQualities: {},
  selectedSpeakerId: null,
  selectedSpeakerIds: [],
  voicePresets: [],

  // ── Mode ──
  setMode: (mode) => {
    const { mode: oldMode, modeSessions, tracks } = get()
    if (oldMode === mode) return

    const currentSession = {
      selectedEventIds: get().selectedEventIds,
      issueFilter: get().issueFilter,
      speakerFocus: get().speakerFocus,
      trackOverrides: (modeSessions[oldMode]?.trackOverrides as Record<string, Partial<TrackDefinition>>) || {},
    }
    const restored = modeSessions[mode] || {}

    // Apply track visibility preset for the new mode
    const preset = TRACK_VISIBILITY_MAP[mode] || {}
    const overrides = (restored.trackOverrides as Record<string, Partial<TrackDefinition>>) || {}
    const newTracks = tracks.map(track => {
      const modePreset = preset[track.type]
      const userOverride = overrides[track.id]
      return { ...track, ...(modePreset || {}), ...(userOverride || {}) }
    })

    set({
      mode,
      tracks: newTracks,
      modeSessions: { ...modeSessions, [oldMode]: currentSession },
      selectedEventIds: (restored.selectedEventIds as string[]) ?? get().selectedEventIds,
      selectedEventId: (restored.selectedEventIds as string[])?.[0] ?? get().selectedEventIds[0] ?? null,
      issueFilter: (restored.issueFilter as IssueFilter | null) ?? null,
      speakerFocus: (restored.speakerFocus as SpeakerInfo | null) ?? null,
    })

    // 跨模式跳转覆盖: 若 crossModeContext 在 5s 内，覆盖恢复的选中状态
    const ctx = get().crossModeContext
    if (ctx && Date.now() - ctx.timestamp < 5000) {
      set({
        selectedEventIds: [ctx.eventId],
        selectedEventId: ctx.eventId,
        playheadPosition: ctx.playheadTarget,
      })
    }
  },

  navigateToEvent: (eventId, startTime, sourceMode) => {
    const ctx = {
      eventId,
      sourceMode: sourceMode ?? get().mode,
      playheadTarget: startTime,
      timestamp: Date.now(),
    }
    set({ crossModeContext: ctx, selectedEventIds: [eventId], selectedEventId: eventId, playheadPosition: startTime })
    if (get().mode !== 'timeline') get().setMode('timeline')
  },

  // ── Selection ──
  selectEvent: (eventId, multi) => {
    if (eventId === null) {
      set({ selectedEventIds: [], selectedEventId: null })
      return
    }
    if (multi) {
      const ids = get().selectedEventIds
      const idx = ids.indexOf(eventId)
      const next = idx >= 0 ? ids.filter(id => id !== eventId) : [...ids, eventId]
      set({ selectedEventIds: next, selectedEventId: next[0] ?? null })
    } else {
      set({ selectedEventIds: [eventId], selectedEventId: eventId })
    }
  },
  toggleEventSelection: (eventId) => {
    const ids = get().selectedEventIds
    const idx = ids.indexOf(eventId)
    const next = idx >= 0 ? ids.filter(id => id !== eventId) : [...ids, eventId]
    set({ selectedEventIds: next, selectedEventId: next[0] ?? null })
  },
  selectEventRange: (_eventId) => {
    // Range select requires event array — implemented in TimelineArena call site
    const ids = get().selectedEventIds
    set({ selectedEventIds: ids, selectedEventId: ids[0] ?? null })
  },
  selectAllVisible: (ids) => set({ selectedEventIds: ids, selectedEventId: ids[0] ?? null }),
  clearSelection: () => set({ selectedEventIds: [], selectedEventId: null }),
  setPlayhead: (position) => set({ playheadPosition: position }),
  setCurrentProject: (projectId) => set({ currentProjectId: projectId }),

  // ── Tracks ──
  setTracks: (tracks) => set({ tracks }),
  updateTrack: (id, partial) => {
    const tracks = get().tracks.map(t => t.id === id ? { ...t, ...partial } : t)
    // Save override to current mode session
    const mode = get().mode
    const sessions = { ...get().modeSessions }
    const session = (sessions[mode] || {}) as Record<string, unknown>
    const overrides = (session.trackOverrides as Record<string, Partial<TrackDefinition>>) || {}
    overrides[id] = { ...overrides[id], ...partial }
    session.trackOverrides = overrides
    sessions[mode] = session
    set({ tracks, modeSessions: sessions })
  },
  resizeTrack: (id, height) => {
    const tracks = get().tracks.map(t => t.id === id ? { ...t, height: Math.max(t.minHeight, Math.min(t.maxHeight ?? 300, height)) } : t)
    set({ tracks })
  },
  toggleTrackVisibility: (id) => {
    const track = get().tracks.find(t => t.id === id)
    if (track) get().updateTrack(id, { visible: !track.visible })
  },
  toggleTrackLock: (id) => {
    const track = get().tracks.find(t => t.id === id)
    if (track) get().updateTrack(id, { locked: !track.locked })
  },
  toggleTrackSolo: (id) => {
    const track = get().tracks.find(t => t.id === id)
    if (!track) return
    const newSolo = !track.solo
    const tracks = get().tracks.map(t => {
      if (t.id === id) return { ...t, solo: newSolo }
      if (newSolo) return { ...t, solo: false }
      return t
    })
    set({ tracks })
  },
  toggleTrackMute: (id) => {
    const track = get().tracks.find(t => t.id === id)
    if (track) get().updateTrack(id, { muted: !track.muted })
  },
  setSnapEnabled: (v) => set({ snapEnabled: v }),
  setTrackScrollLeft: (px) => set({ trackScrollLeft: px }),

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
    const drafts = get().pendingDrafts
    if (drafts.size === 0) return
    const now = new Date().toISOString()
    const newPatches: TimelinePatchData[] = []
    for (const [eventId, draft] of drafts) {
      newPatches.push({
        patch_id: `batch_${Date.now()}_${eventId}`,
        opcode: draft.opcode,
        targets: [draft.eventId],
        payload: draft.payload,
        reason: ['user batch apply'],
        score: 1.0, confidence: 1.0,
        parent_version: '', idempotency_key: `user_${Date.now()}`,
        author: 'user', timestamp: now,
      })
    }
    const history = [...get().appliedPatches, ...newPatches].slice(-50)
    set({ pendingDrafts: new Map(), appliedPatches: history })
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

  toggleDockCollapsed: () => set({ dockCollapsed: !get().dockCollapsed }),
  toggleDebugMode: () => set({ debugMode: !get().debugMode }),

  // ── Speaker Review ──
  setSpeakerLanes: (lanes) => set({ speakerLanes: lanes }),
  setSelectedSpeaker: (speakerId) => set({ selectedSpeakerId: speakerId, selectedSpeakerIds: speakerId ? [speakerId] : [] }),
  toggleSpeakerSelection: (speakerId) => {
    const ids = get().selectedSpeakerIds
    const idx = ids.indexOf(speakerId)
    const next = idx >= 0 ? ids.filter(id => id !== speakerId) : [...ids, speakerId]
    set({ selectedSpeakerIds: next, selectedSpeakerId: next[0] ?? null })
  },
  setVoicePresets: (presets) => set({ voicePresets: presets }),
  setSpeakerQualities: (qualities) => set({ speakerQualities: qualities }),
  bindVoice: (speakerId, voiceId) => {
    const lanes = get().speakerLanes.map(l =>
      l.speaker === speakerId ? { ...l, voice_id: voiceId } : l
    )
    set({ speakerLanes: lanes })
  },
}))
