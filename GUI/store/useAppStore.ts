import { create } from 'zustand'
import type { PatchPreview, SpeakerInfo, TimelinePatchData, ExportPreset, WorkspaceManifest, EventViewModel, WaveformData, DataSource, WorkflowPreset, WorkspaceSummary } from '../types'
import type { Mode, PatchDraft, IssueFilter, JobState, CrossModeContext, SpeakerLaneData, SpeakerQuality, VoiceCard, SubtitleEntry, ReviewFilterMode } from '../types/modes'
import type { TrackDefinition } from '../types/timeline'
import type { TrackWaveformData } from '../types'
import { DEFAULT_TRACKS, TRACK_VISIBILITY_MAP, SPEAKER_TRACK_PRESET } from '../types/timeline'
import { MOCK_SPEAKER_LOAD } from '../mocks/mockData'

export type { Mode, PatchDraft, IssueFilter, JobState }
export type TimelineFocus = 'default' | 'speaker' | 'patch'

export interface AppState {
  mode: Mode
  timelineFocus: TimelineFocus
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

  // Export state
  exportPresets: ExportPreset[]
  activePresetId: string | null
  exportPreviewText: { zh: string; en: string }

  // Review state (字幕校验)
  timelineViewMode: 'timeline' | 'table'
  reviewEntries: SubtitleEntry[]
  reviewSearchQuery: string
  reviewFilterMode: ReviewFilterMode

  // Workspace state (TRV-PLAN-2026-001 §8.2)
  dataSource: DataSource
  workspace: string
  events: EventViewModel[]
  waveform: WaveformData | null
  ttsWaveforms: TrackWaveformData[] | null
  manifest: WorkspaceManifest | null
  loading: boolean
  error: string | null

  // Hub state (Phase 1)
  workflowPresets: WorkflowPreset[]
  workspaceList: WorkspaceSummary[]

  // Actions — Mode
  setMode: (mode: Mode) => void
  setTimelineFocus: (focus: TimelineFocus) => void
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
  fetchSpeakerLanes: (workspace?: string) => Promise<void>
  setSelectedSpeaker: (speakerId: string | null) => void
  toggleSpeakerSelection: (speakerId: string) => void
  setVoicePresets: (presets: VoiceCard[]) => void
  setSpeakerQualities: (qualities: Record<string, SpeakerQuality>) => void
  bindVoice: (speakerId: string, voiceId: string) => void

  // Actions — Export
  setExportPresets: (presets: ExportPreset[]) => void
  savePreset: (preset: ExportPreset) => void
  deletePreset: (id: string) => void
  duplicatePreset: (id: string) => void
  setActivePreset: (id: string | null) => void
  setExportPreviewText: (text: { zh: string; en: string }) => void

  // Actions — Workspace (TRV-PLAN-2026-001 §8.2)
  loadWorkspace: (workspacePath: string) => Promise<void>
  clearWorkspace: () => void
  setDataSource: (source: DataSource) => void

  // Actions — Hub (Phase 1)
  fetchWorkflowPresets: () => Promise<void>
  fetchWorkspaceList: () => Promise<void>
  createWorkspace: (videoPath: string, presetId: string, name?: string) => Promise<string>

  // Actions — Review (字幕校验)
  setTimelineViewMode: (mode: 'timeline' | 'table') => void
  setReviewEntries: (entries: SubtitleEntry[]) => void
  updateReviewEntry: (index: number, update: Partial<SubtitleEntry>) => void
  setReviewSearchQuery: (q: string) => void
  setReviewFilterMode: (mode: ReviewFilterMode) => void
}

export const useAppStore = create<AppState>((set, get) => ({
  mode: 'hub' as Mode,
  timelineFocus: 'default' as TimelineFocus,
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

  exportPresets: [],
  activePresetId: null,
  exportPreviewText: { zh: 'Minecraft我的世界 村民交易', en: 'Minecraft Villager Trade x64' },

  // Review defaults (字幕校验)
  timelineViewMode: 'timeline' as 'timeline' | 'table',
  reviewEntries: [] as SubtitleEntry[],
  reviewSearchQuery: '',
  reviewFilterMode: 'all' as ReviewFilterMode,

  // Workspace defaults (TRV-PLAN-2026-001)
  dataSource: 'mock' as DataSource,
  workspace: '',
  events: [],
  waveform: null,
  ttsWaveforms: null,
  manifest: null,
  loading: false,
  error: null,

  // Hub defaults (Phase 1)
  workflowPresets: [],
  workspaceList: [],

  // ── Mode ──
  setMode: (mode) => {
    // Clear timelineFocus when switching away from timeline
    if (mode !== 'timeline') {
      set({ timelineFocus: 'default' })
    }

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
    // When timelineFocus is 'speaker', overlay speaker track presets
    const focusPreset = get().timelineFocus === 'speaker' ? SPEAKER_TRACK_PRESET : {}
    const modePreset = TRACK_VISIBILITY_MAP[mode] || {}
    const preset = { ...modePreset, ...focusPreset }
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

  setTimelineFocus: (focus) => {
    const { mode, tracks } = get()
    if (mode !== 'timeline' && focus !== 'default') {
      // Entering a focus mode from non-timeline: switch to timeline first
      set({ timelineFocus: focus })
      get().setMode('timeline')
      return
    }
    // Apply or clear speaker track visibility overrides
    const speakerPreset = focus === 'speaker' ? SPEAKER_TRACK_PRESET : {}
    const newTracks = tracks.map(track => {
      const focusOverride = speakerPreset[track.type]
      if (focus === 'speaker' && focusOverride) {
        return { ...track, ...focusOverride }
      }
      if (focus === 'default') {
        // Restore defaults from DEFAULT_TRACKS for speaker-affected types
        const def = DEFAULT_TRACKS.find(d => d.id === track.id)
        if (def && speakerPreset[track.type]) {
          return { ...track, visible: def.visible, locked: def.locked, solo: def.solo, muted: def.muted }
        }
      }
      return track
    })
    set({ timelineFocus: focus, tracks: newTracks })
    if (focus === 'speaker') {
      get().fetchSpeakerLanes()
    }
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

  fetchSpeakerLanes: async (workspace) => {
    const LANE_COLORS = ['#FF9800', '#2196F3', '#4CAF50', '#9C27B0', '#E91E63', '#00BCD4']
    try {
      const body: Record<string, string> = {}
      const ws = workspace || get().workspace
      if (ws) body.workspace = ws
      const res = await fetch('/api/speaker/diarization/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) throw new Error('API not available')
      const data = await res.json()
      const lanes: SpeakerLaneData[] = (data.speaker_lanes || []).map((l: any, i: number) => ({
        ...l,
        color: l.color || LANE_COLORS[i % LANE_COLORS.length],
        segments: (l.segments || []).map((s: any, j: number) => ({
          ...s,
          eventId: s.eventId || `${l.speaker}_seg_${j}`,
        })),
      }))
      set({ speakerLanes: lanes })
      if (data.voice_presets) set({ voicePresets: data.voice_presets })
    } catch {
      // Fallback to mock data
      const mock = MOCK_SPEAKER_LOAD
      const lanes: SpeakerLaneData[] = mock.speaker_lanes.map((l: any, i: number) => ({
        speaker: l.speaker,
        display_name: mock.speakerNames[l.speaker] || l.speaker,
        voice_id: '',
        color: LANE_COLORS[i % LANE_COLORS.length],
        segments: (l.segments || []).map((s: any, j: number) => ({
          start: s.start, end: s.end,
          text: s.text || '',
          translation: s.translation,
          confidence: s.confidence || 0.9,
          eventId: s.eventId || `${l.speaker}_seg_${j}`,
        })),
        segment_count: l.segments?.length || 0,
        total_duration: l.segments ? l.segments.reduce((sum: number, s: any) => sum + (s.end - s.start), 0) : 0,
      }))
      set({ speakerLanes: lanes })
      set({ voicePresets: [
        { id: 'vc_001', name: '晓晓 (女声)', language: 'zh-CN', sampleText: '你好，欢迎使用语音合成系统。', engine: 'edge', locked: false },
        { id: 'vc_002', name: '云希 (男声)', language: 'zh-CN', sampleText: '这是来自微软的边缘语音合成。', engine: 'edge', locked: false },
        { id: 'vc_004', name: 'ChatTTS Seed 2', language: 'zh-CN', sampleText: 'ChatTTS 多样本音色。', engine: 'chattts', locked: false },
        { id: 'vc_005', name: 'CosyVoice v2 Default', language: 'zh-CN', sampleText: 'CosyVoice 跨语言合成。', engine: 'cosyvoice', locked: true },
      ]})
    }
  },

  // ── Export ──
  setExportPresets: (presets) => set({ exportPresets: presets }),

  savePreset: (preset) => {
    const now = new Date().toISOString()
    const saved = { ...preset, updatedAt: now, createdAt: preset.createdAt || now }
    const presets = get().exportPresets
    const idx = presets.findIndex(p => p.id === saved.id)
    const next = idx >= 0
      ? presets.map(p => p.id === saved.id ? saved : p)
      : [...presets, saved]
    set({ exportPresets: next, activePresetId: saved.id })
    try { localStorage.setItem('export-presets', JSON.stringify(next.filter(p => !p.isBuiltin))) } catch { /* quota */ }
  },

  deletePreset: (id) => {
    const presets = get().exportPresets.filter(p => p.id !== id)
    set({ exportPresets: presets, activePresetId: get().activePresetId === id ? null : get().activePresetId })
    try { localStorage.setItem('export-presets', JSON.stringify(presets.filter(p => !p.isBuiltin))) } catch { /* quota */ }
  },

  duplicatePreset: (id) => {
    const source = get().exportPresets.find(p => p.id === id)
    if (!source) return
    const now = new Date().toISOString()
    const copy: ExportPreset = {
      ...source, id: `preset_${Date.now()}`,
      name: `${source.name} (副本)`, isBuiltin: false,
      createdAt: now, updatedAt: now,
      video: { ...source.video }, subtitle: { ...source.subtitle },
      audio: { ...source.audio }, output: { ...source.output }, quality: { ...source.quality },
    }
    const next = [...get().exportPresets, copy]
    set({ exportPresets: next, activePresetId: copy.id })
    try { localStorage.setItem('export-presets', JSON.stringify(next.filter(p => !p.isBuiltin))) } catch { /* quota */ }
  },

  setActivePreset: (id) => set({ activePresetId: id }),
  setExportPreviewText: (text) => set({ exportPreviewText: text }),

  // ── Workspace Actions (TRV-PLAN-2026-001 §8.2) ──

  loadWorkspace: async (workspacePath) => {
    set({ loading: true, error: null, dataSource: 'workspace' })

    try {
      // Step 1: Load manifest
      const manifestRes = await fetch(
        `/api/project/manifest/resolve?workspace=${encodeURIComponent(workspacePath)}`
      )
      if (!manifestRes.ok) {
        const errData = await manifestRes.json().catch(() => ({}))
        throw new Error((errData as any).detail || `项目不存在: ${workspacePath}`)
      }
      const manifestData = await manifestRes.json()

      // Step 2: Load events via speaker/diarization/load
      const loadRes = await fetch('/api/speaker/diarization/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace: workspacePath }),
      })
      if (!loadRes.ok) throw new Error('无法加载时间轴数据')
      const loadData = await loadRes.json()

      const events = Object.values(loadData.inspector_data || {}) as EventViewModel[]

      // Step 3: Load waveform (non-fatal)
      let waveform: WaveformData | null = null
      try {
        const wfRes = await fetch(
          `/api/speaker/diarization/waveform?workspace=${encodeURIComponent(workspacePath)}`
        )
        if (wfRes.ok) waveform = await wfRes.json()
      } catch { /* non-fatal */ }

      set({
        workspace: workspacePath,
        events,
        waveform,
        manifest: manifestData.manifest,
        loading: false,
        error: null,
      })
    } catch (err) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : '未知错误',
      })
    }
  },

  clearWorkspace: () => set({
    dataSource: 'mock',
    workspace: '',
    events: [],
    waveform: null,
    ttsWaveforms: null,
    manifest: null,
    loading: false,
    error: null,
  }),

  setDataSource: (source) => set({ dataSource: source }),

  // ── Review (字幕校验) ──
  setTimelineViewMode: (mode) => set({ timelineViewMode: mode }),
  setReviewEntries: (entries) => set({ reviewEntries: entries }),
  updateReviewEntry: (index, update) => set(state => ({
    reviewEntries: state.reviewEntries.map(e =>
      e.index === index ? { ...e, ...update } : e
    ),
  })),
  setReviewSearchQuery: (q) => set({ reviewSearchQuery: q }),
  setReviewFilterMode: (mode) => set({ reviewFilterMode: mode }),

  // ── Hub Actions (Phase 1) ──

  fetchWorkflowPresets: async () => {
    try {
      const res = await fetch('/api/workflow/presets')
      if (res.ok) {
        const data = await res.json()
        set({ workflowPresets: data.presets || [] })
      }
    } catch { /* non-critical */ }
  },

  fetchWorkspaceList: async () => {
    try {
      const res = await fetch('/api/workspaces')
      if (res.ok) {
        const data = await res.json()
        set({ workspaceList: data.workspaces || [] })
      }
    } catch { /* non-critical */ }
  },

  createWorkspace: async (videoPath, presetId, name) => {
    set({ loading: true, error: null })
    try {
      const res = await fetch('/api/workspace/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ video_path: videoPath, workflow_preset: presetId, name: name || '' }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error((err as any).detail || '创建工作区失败')
      }
      const data = await res.json()
      set({ workspace: data.workspace, manifest: data.manifest, loading: false })
      return data.workspace as string
    } catch (err) {
      set({ loading: false, error: err instanceof Error ? err.message : '未知错误' })
      throw err
    }
  },
}))
