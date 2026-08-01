import { create } from 'zustand'
import type { PatchPreview, SpeakerInfo, TimelinePatchData, ExportPreset, WorkspaceManifest, EventViewModel, WaveformData, DataSource, WorkflowPreset, WorkspaceSummary } from '../types'
import type { Mode, PatchDraft, IssueFilter, IssueItem, JobState, CrossModeContext, SpeakerLaneData, SpeakerQuality, VoiceCard, SubtitleEntry, ReviewFilterMode } from '../types/modes'
import type { TrackDefinition } from '../types/timeline'
import type { TrackWaveformData } from '../types'
import { DEFAULT_TRACKS, TRACK_VISIBILITY_MAP, SPEAKER_TRACK_PRESET } from '../types/timeline'
import { recordUserAction } from '../activityLog'

export type { Mode, PatchDraft, IssueFilter, JobState }
export type TimelineFocus = 'default' | 'speaker' | 'patch'

/** 前端可视化编辑操作审计条目 — 调试量化 (零请求, localStorage 持久化) */
export interface UiOpEntry {
  ts: number            // Date.now()
  ms: number            // 操作耗时
  op: string            // applyDraft / applyAllDrafts / undoLastPatch / discardAllDrafts / loadWorkspace
  ok: boolean
  opcode?: string
  eventId?: string
  extra?: string        // 附加量化: 快照事件数 / 成功数 / 失败数
  error?: string
}

const UI_OPS_MAX = 300
const UI_OPS_KEY = 'ui_ops'

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
  reviewFlags: IssueItem[]

  /** 可视化编辑操作审计 (零请求, 环形 300 条 + localStorage 'ui_ops') — 调试量化 */
  uiOps: UiOpEntry[]

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
  timelineViewMode: 'timeline' | 'table' | 'speaker-timeline'
  reviewEntries: SubtitleEntry[]
  reviewSearchQuery: string
  reviewFilterMode: ReviewFilterMode
  reviewTranslatedSrtPath: string

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
  _logOp: (op: string, ok: boolean, ms: number, extra?: string, error?: string, opcode?: string, eventId?: string) => void

  // Actions — Drafts
  addDraft: (draft: PatchDraft) => void
  removeDraft: (eventId: string) => void
  applyDraft: (eventId: string, silent?: boolean) => Promise<boolean>
  discardDraft: (eventId: string) => void
  applyAllDrafts: () => Promise<number>
  discardAllDrafts: () => void
  undoLastPatch: () => Promise<{ ok: boolean; patch: TimelinePatchData | null }>

  // Actions — Patches / Filters / Jobs
  setUnappliedPatches: (patches: PatchPreview[]) => void
  fetchPatchLog: () => Promise<void>
  fetchReviewFlags: (workspace?: string) => Promise<void>
  setIssueFilter: (filter: IssueFilter | null) => void
  setSpeakerFocus: (speaker: SpeakerInfo | null) => void
  setJobStatus: (eventId: string, state: JobState) => void
  removeJobStatus: (eventId: string) => void
  toggleDockCollapsed: () => void
  toggleDebugMode: () => void

  // Actions — Speaker Review
  setSpeakerLanes: (lanes: SpeakerLaneData[]) => void
  syncSpeakerLanesFromEvents: (serverEvents: Record<string, EventViewModel>) => void
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
  reloadEvents: () => Promise<void>
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
  loadReviewEntries: (workspaceOverride?: string) => Promise<void>
  saveReviewEntries: () => Promise<void>
}

// ── Opcode mapping: frontend PatchDraft → backend TimelinePatch ──

const OPCODE_MAP: Record<string, string> = {
  ASSIGN_SPEAKER: 'ASSIGN_SPEAKER',
  MERGE_SPEAKERS: 'MERGE_SPEAKERS',
  RENAME_SPEAKER: 'RENAME_SPEAKER',
  LOCK_SPEAKER: 'LOCK_SPEAKER',
  CREATE_SPEAKER: 'CREATE_SPEAKER',
  SPLIT_SEGMENT: 'SPLIT',
  RESIZE_SEGMENT: 'RESIZE',
  SET_TRANSLATION: 'SET_TRANSLATION',
  MERGE: 'MERGE',
  // P3-A: timeline 编辑 opcode 补全 (此前降级 ANNOTATE 静默零写入)
  MOVE_EVENT: 'MOVE_EVENT',
  TRIM_START: 'TRIM_START',
  TRIM_END: 'TRIM_END',
  SPLIT_EVENT: 'SPLIT_EVENT',
  MERGE_PREV: 'MERGE_PREV',
  MERGE_NEXT: 'MERGE_NEXT',
  APPLY_AI_SUGGESTION: 'APPLY_AI_SUGGESTION',
  RETRIGGER: 'RETRIGGER',
  ANNOTATE: 'ANNOTATE',
}

// 本地状态 draft: 不是写操作, 不进 patch 链 (预览/丢弃由前端处理)
const LOCAL_ONLY_OPCODES = new Set(['AI_SUGGEST', 'DISMISS_AI_SUGGESTION'])

function patchDraftToApiFormat(draft: PatchDraft): Record<string, unknown> {
  const backendOpcode = OPCODE_MAP[draft.opcode]
  if (!backendOpcode) {
    throw new Error(`未知 draft opcode: ${draft.opcode} (合法: ${Object.keys(OPCODE_MAP).join(', ')})`)
  }

  let payload = { ...draft.payload }
  if (backendOpcode === 'RETAG_SPEAKER' && !payload.new_speaker) {
    payload = { new_speaker: (draft.payload as any).target || (draft.payload as any).new_speaker || '' }
  }
  if (backendOpcode === 'SPLIT' && !payload.split_point) {
    payload = { split_point: (draft.payload as any).split_at || (draft.payload as any).split_point || 0 }
  }

  return {
    patch_id: `draft_${draft.timestamp}`,
    opcode: backendOpcode,
    targets: draft.opcode === 'MERGE' && draft.payload.merge_with
      ? [draft.eventId, draft.payload.merge_with as string]
      : [draft.eventId],
    payload,
    reason: ['user edit'],
    score: 1.0,
    confidence: 1.0,
    parent_version: '',
    idempotency_key: `user_${draft.timestamp}`,
    author: 'user',
    timestamp: new Date(draft.timestamp).toISOString(),
  }
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
  reviewFlags: [],

  issueFilter: null,
  speakerFocus: null,

  modeSessions: {},
  localJobStatus: {},

  crossModeContext: null,
  dockCollapsed: false,
  debugMode: false,

  uiOps: [],

  speakerLanes: [],
  speakerQualities: {},
  selectedSpeakerId: null,
  selectedSpeakerIds: [],
  voicePresets: [],

  exportPresets: [],
  activePresetId: null,
  exportPreviewText: { zh: 'Minecraft我的世界 村民交易', en: 'Minecraft Villager Trade x64' },

  // Review defaults (字幕校验)
  timelineViewMode: 'timeline' as 'timeline' | 'table' | 'speaker-timeline',
  reviewEntries: [] as SubtitleEntry[],
  reviewSearchQuery: '',
  reviewFilterMode: 'all' as ReviewFilterMode,
  reviewTranslatedSrtPath: '',

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

  // ── 操作审计 (调试量化, 零请求) ──
  _logOp: (op, ok, ms, extra = '', error = '', opcode = '', eventId = '') => {
    const entry: UiOpEntry = { ts: Date.now(), ms: Math.round(ms), op, ok, opcode, eventId, extra, error }
    set(state => {
      const uiOps = [...state.uiOps, entry].slice(-UI_OPS_MAX)
      try {
        localStorage.setItem(UI_OPS_KEY, JSON.stringify(uiOps))
      } catch { /* localStorage 失败不阻塞操作 (非核心缓存) */ }
      return { uiOps }
    })
  },

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

  applyDraft: async (eventId, silent = false) => {
    const t0 = performance.now()
    const draft = get().pendingDrafts.get(eventId)
    if (!draft) {
      get()._logOp('applyDraft', false, performance.now() - t0, '', '无 draft', '', eventId)
      return false
    }
    // 本地状态 draft (AI_SUGGEST/DISMISS) 不是写操作, 不进 patch 链
    if (LOCAL_ONLY_OPCODES.has(draft.opcode)) {
      get()._logOp('applyDraft', true, performance.now() - t0, 'local-only', '', draft.opcode, eventId)
      return true
    }

    let patch: Record<string, unknown>
    try {
      patch = patchDraftToApiFormat(draft)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      set({ error: `补丁应用失败: ${msg}` })
      if (!silent) recordUserAction('applied', `事件 ${eventId}`, `补丁应用失败: ${msg}`, 'failed')
      get()._logOp('applyDraft', false, performance.now() - t0, '', msg, draft.opcode, eventId)
      return false
    }
    const ws = get().workspace

    // 后端失败必须响亮 — 不记录本地、保留 draft 供重试 (禁止兜底)
    let res: Response
    try {
      res = await fetch('/api/timeline/patch/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace: ws, patch }),
      })
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      set({ error: `补丁应用失败: ${msg}` })
      if (!silent) recordUserAction('applied', `事件 ${eventId}`, `补丁应用失败: ${msg}`, 'failed')
      get()._logOp('applyDraft', false, performance.now() - t0, '', msg, draft.opcode, eventId)
      return false
    }
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}))
      const msg = (detail as any).detail || (detail as any).error || `HTTP ${res.status}`
      set({ error: `补丁应用失败: ${msg}` })
      if (!silent) recordUserAction('applied', `事件 ${eventId}`, `补丁应用失败: ${msg}`, 'failed')
      get()._logOp('applyDraft', false, performance.now() - t0, '', msg, draft.opcode, eventId)
      return false
    }

    // Record as applied patch + 局部刷新 (P3-D)
    const data = await res.json()
    const applied: TimelinePatchData = {
      patch_id: patch.patch_id as string,
      opcode: patch.opcode as string,
      targets: patch.targets as string[],
      payload: patch.payload as Record<string, unknown>,
      reason: (patch.reason as string[]) || ['user edit'],
      score: (patch.score as number) || 1.0,
      confidence: (patch.confidence as number) || 1.0,
      parent_version: (patch.parent_version as string) || '',
      idempotency_key: (patch.idempotency_key as string) || '',
      author: 'user',
      timestamp: patch.timestamp as string,
    }
    const patches = [...get().appliedPatches, applied]
    if (patches.length > 50) patches.shift()

    const next = new Map(get().pendingDrafts)
    next.delete(eventId)
    // 用 apply 响应的事件快照更新本地 (不再全量 loadWorkspace 7 请求)
    const serverEvents = (data.events || {}) as Record<string, EventViewModel>
    const newEvents = Object.values(serverEvents).sort((a, b) => a.start - b.start)
    set({ pendingDrafts: next, appliedPatches: patches, events: newEvents })
    // 说话人 lane 本地同步 (零请求): 拖拽/resize/assign 改变事件边界与归属
    get().syncSpeakerLanesFromEvents(serverEvents)

    // review flags 是唯一随编辑变化的派生数据 — 单独轻量刷新
    if (ws) await get().fetchReviewFlags(ws)
    if (!silent) recordUserAction('applied', `事件 ${eventId}`, `应用补丁 ${draft.opcode}`)
    get()._logOp('applyDraft', true, performance.now() - t0,
      `${Object.keys(serverEvents).length} events`, '', draft.opcode, eventId)
    return true
  },

  discardDraft: (eventId) => {
    const next = new Map(get().pendingDrafts)
    next.delete(eventId)
    set({ pendingDrafts: next })
  },

  applyAllDrafts: async () => {
    const t0 = performance.now()
    const drafts = get().pendingDrafts
    if (drafts.size === 0) return 0
    const ws = get().workspace
    const now = new Date().toISOString()
    const newPatches: TimelinePatchData[] = []
    const failedIds: string[] = []
    let latestEvents: Record<string, EventViewModel> | null = null

    for (const [eventId, draft] of drafts) {
      // 本地状态 draft 跳过: 预览/丢弃不是写操作, 不提交也不删
      if (LOCAL_ONLY_OPCODES.has(draft.opcode)) continue
      let patch: Record<string, unknown>
      try {
        patch = patchDraftToApiFormat(draft)
      } catch (e) {
        failedIds.push(eventId)
        continue
      }
      try {
        const res = await fetch('/api/timeline/patch/apply', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ workspace: ws, patch }),
        })
        if (!res.ok) { failedIds.push(eventId); continue }
        // P3-D: 收集最后一个 apply 响应的事件快照 (批量不逐条 reload)
        const data = await res.json()
        if (data.events) latestEvents = data.events as Record<string, EventViewModel>
      } catch { failedIds.push(eventId); continue }

      newPatches.push({
        patch_id: patch.patch_id as string,
        opcode: patch.opcode as string,
        targets: patch.targets as string[],
        payload: patch.payload as Record<string, unknown>,
        reason: (patch.reason as string[]) || ['user batch apply'],
        score: (patch.score as number) || 1.0,
        confidence: (patch.confidence as number) || 1.0,
        parent_version: (patch.parent_version as string) || '',
        idempotency_key: (patch.idempotency_key as string) || '',
        author: 'user',
        timestamp: now,
      })
    }

    // 失败的草案保留供重试, 本地状态 draft 保留, 成功的移除 (禁止兜底: 部分失败必须响亮)
    const nextDrafts = new Map<string, PatchDraft>()
    for (const [id, draft] of drafts) {
      if (LOCAL_ONLY_OPCODES.has(draft.opcode) || failedIds.includes(id)) {
        nextDrafts.set(id, draft)
      }
    }

    const history = [...get().appliedPatches, ...newPatches].slice(-50)
    // P3-D 局部刷新: 用 apply 响应快照更新本地, 不再全量 loadWorkspace
    set({
      pendingDrafts: nextDrafts,
      appliedPatches: history,
      ...(latestEvents
        ? { events: Object.values(latestEvents).sort((a, b) => a.start - b.start) }
        : {}),
    })
    // 说话人 lane 本地同步 (零请求): 批量操作同样改变事件边界/归属
    if (latestEvents) get().syncSpeakerLanesFromEvents(latestEvents)
    if (ws && newPatches.length > 0 && latestEvents) {
      await get().fetchReviewFlags(ws)
    }
    const submittedCount = Array.from(drafts.values())
      .filter(d => !LOCAL_ONLY_OPCODES.has(d.opcode)).length
    if (failedIds.length > 0) {
      set({ error: `批量应用失败 ${failedIds.length}/${submittedCount} 条 (${failedIds.join(', ')})，失败条目已保留` })
    }
    recordUserAction('applied', undefined,
      `批量应用补丁: ${newPatches.length}/${submittedCount} 成功${failedIds.length ? `, ${failedIds.length} 失败` : ''}`,
      failedIds.length > 0 ? 'failed' : 'ok')
    get()._logOp('applyAllDrafts', failedIds.length === 0, performance.now() - t0,
      `${newPatches.length}/${submittedCount} 成功${failedIds.length ? `, ${failedIds.length} 失败` : ''}`,
      failedIds.length > 0 ? `失败: ${failedIds.join(', ')}` : '')
    return newPatches.length
  },

  discardAllDrafts: () => {
    const n = get().pendingDrafts.size
    set({ pendingDrafts: new Map() })
    get()._logOp('discardAllDrafts', true, 0, `${n} drafts 丢弃`)
  },

  undoLastPatch: async () => {
    const t0 = performance.now()
    const patches = get().appliedPatches
    if (patches.length === 0) {
      get()._logOp('undoLastPatch', false, performance.now() - t0, '', '无已应用补丁')
      return { ok: false, patch: null }
    }
    const removed = patches[patches.length - 1]
    const ws = get().workspace

    // 后端失败必须响亮 — 不删本地 appliedPatches, 保持与后端一致 (禁止兜底)
    let res: Response
    try {
      res = await fetch('/api/timeline/patch/undo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace: ws }),
      })
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      set({ error: `撤销失败: ${msg}` })
      get()._logOp('undoLastPatch', false, performance.now() - t0, '', msg, removed.opcode, removed.targets?.[0])
      return { ok: false, patch: null }
    }
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}))
      const msg = (detail as any).detail || (detail as any).error || `HTTP ${res.status}`
      set({ error: `撤销失败: ${msg}` })
      get()._logOp('undoLastPatch', false, performance.now() - t0, '', msg, removed.opcode, removed.targets?.[0])
      return { ok: false, patch: null }
    }

    // P3-D 局部刷新: undo 响应带回滚后的事件快照 (不再全量 reload)
    const data = await res.json()
    const serverEvents = (data.events || {}) as Record<string, EventViewModel>
    const undoneEvents = Object.values(serverEvents).sort((a, b) => a.start - b.start)
    set({ appliedPatches: patches.slice(0, -1), events: undoneEvents })

    // 撤销后刷新 — fetchPatchLog/fetchSpeakerLanes 内部已响亮, 不再静默吞 rejection
    get().fetchPatchLog()
    // undo 可能回退 speaker 操作 (lane 名字/颜色变化), lanes 需刷新; review flags 轻量刷新
    get().fetchSpeakerLanes(ws)
    get().fetchReviewFlags(ws)

    get()._logOp('undoLastPatch', true, performance.now() - t0,
      `${Object.keys(serverEvents).length} events`, '', removed.opcode, removed.targets?.[0])
    return { ok: true, patch: removed }
  },

  // ── Patches ──
  setUnappliedPatches: (patches) => set({ unappliedPatches: patches }),

  fetchPatchLog: async () => {
    const ws = get().workspace
    if (!ws) return
    // 失败必须响亮 — 静默返回会让补丁历史显示为空 (用户误以为无编辑记录)
    let res: Response
    try {
      res = await fetch(`/api/timeline/patch/log?workspace=${encodeURIComponent(ws)}`)
    } catch (e) {
      set({ error: `补丁历史加载失败: ${e instanceof Error ? e.message : String(e)}` })
      return
    }
    if (!res.ok) {
      set({ error: `补丁历史加载失败: HTTP ${res.status}` })
      return
    }
    const data = await res.json()
    set({ appliedPatches: (data.patches || []).map((p: any) => ({
      patch_id: p.patch_id || '',
      opcode: p.opcode || '',
      targets: p.targets || [],
      payload: p.payload || {},
      reason: p.reason || [],
      score: p.score || 0,
      confidence: p.confidence || 0,
      parent_version: p.parent_version || '',
      idempotency_key: p.idempotency_key || '',
      author: p.author || 'system',
      timestamp: p.timestamp || '',
    })) })
  },

  fetchReviewFlags: async (workspace?: string) => {
    const ws = workspace || get().workspace
    if (!ws) return
    // 失败必须响亮 (P3-B) — 静默会让校验标记显示为空
    let res: Response
    try {
      res = await fetch(`/api/timeline/review/flags?workspace=${encodeURIComponent(ws)}`)
    } catch (e) {
      set({ error: `校验标记加载失败: ${e instanceof Error ? e.message : String(e)}` })
      return
    }
    if (!res.ok) {
      set({ error: `校验标记加载失败: HTTP ${res.status}` })
      return
    }
    const flagData = await res.json()
    const SEVERITY: Record<string, 'warning' | 'error'> = { speaker_conflict: 'error' }
    const reviewFlags = (flagData.flags || []).flatMap((f: any) =>
      (f.flags || []).map((t: string) => ({
        eventId: f.event_id,
        type: t as IssueItem['type'],
        severity: SEVERITY[t] || ('warning' as const),
        message: f.reason || '',
        detail: { text: f.text, translation: f.translation },
        start: f.start || 0,
        end: f.end || 0,
      }))
    )
    set({ reviewFlags })
  },

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
  syncSpeakerLanesFromEvents: (serverEvents) => {
    // P3-E2: apply 响应快照本地重建 lanes (零请求) — 拖拽/resize/assign 改变事件
    // 边界与归属, 说话人界面以 speakerLanes 渲染, 不刷则"只有 patch 没有 UI 变化"
    if (Object.keys(serverEvents).length === 0) return
    set(state => {
      const events = Object.values(serverEvents) as EventViewModel[]
      const byId = new Map(events.map(e => [e.id, e]))
      // 保留原 lane 顺序与元数据 (display_name/color/voice_id); segments 以快照为准
      // 重建 — 快照是编辑后全量事件 (唯一事实源的投影)
      const lanes = state.speakerLanes.map(lane => {
        const segs = lane.segments.flatMap(seg => {
          const ev = byId.get(seg.eventId || seg.id || '')
          if (!ev) return []
          if (ev.speaker && ev.speaker !== lane.speaker) return []  // 换 lane 的段移走
          return [{
            ...seg,
            start: ev.start, end: ev.end,
            text: ev.text, translation: ev.translation,
            confidence: ev.confidence ?? seg.confidence,
          }]
        })
        return { ...lane, segments: segs }
      })
      // 快照中出现在新 lane 的事件 (speaker 变更) 追加到目标 lane
      const LANE_COLORS = ['#FF9800', '#2196F3', '#4CAF50', '#9C27B0', '#E91E63', '#00BCD4']
      for (const ev of events) {
        const spk = ev.speaker || 'UNKNOWN'
        let lane = lanes.find(l => l.speaker === spk)
        if (!lane) {
          lane = {
            speaker: spk, display_name: ev.displayName || spk,
            voice_id: '', color: LANE_COLORS[lanes.length % LANE_COLORS.length],
            segments: [], segment_count: 0, total_duration: 0,
          }
          lanes.push(lane)
        }
        if (lane.segments.some(s => (s.eventId || s.id) === ev.id)) continue
        lane.segments.push({
          id: ev.id, eventId: ev.id, start: ev.start, end: ev.end,
          text: ev.text, translation: ev.translation,
          confidence: ev.confidence ?? 0.9,
        })
      }
      for (const lane of lanes) {
        lane.segment_count = lane.segments.length
        lane.total_duration = lane.segments.reduce((s, x) => s + (x.end - x.start), 0)
      }
      return { speakerLanes: lanes }
    })
  },
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
    const name = get().speakerLanes.find(l => l.speaker === speakerId)?.display_name || speakerId
    recordUserAction(voiceId ? 'bound' : 'unbound', `说话人 ${name}`,
      voiceId ? `绑定声线 ${voiceId}` : '解绑声线')
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
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      const lanes: SpeakerLaneData[] = (data.speaker_lanes || []).map((l: any, i: number) => ({
        ...l,
        color: l.color || LANE_COLORS[i % LANE_COLORS.length],
        segment_count: l.segment_count ?? (l.segments || []).length,
        total_duration: l.total_duration ?? (l.segments || []).reduce((sum: number, s: any) => sum + ((s.end || 0) - (s.start || 0)), 0),
        segments: (l.segments || []).map((s: any, j: number) => ({
          id: s.eventId || s.id || `${l.speaker}_seg_${j}`,
          start: s.start ?? 0,
          end: s.end ?? 0,
          text: s.text || '',
          translation: s.translation || '',
          confidence: s.confidence ?? 0.9,
          eventId: s.eventId || s.id || `${l.speaker}_seg_${j}`,
        })),
      }))
      set({ speakerLanes: lanes })
      if (data.voice_presets) set({ voicePresets: data.voice_presets })
    } catch (err) {
      // 禁止兜底: 失败清空并响亮报错, 绝不回退 mock 假数据
      set({
        speakerLanes: [],
        voicePresets: [],
        error: `说话人数据加载失败: ${err instanceof Error ? err.message : String(err)}`,
      })
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
    const t0 = performance.now()
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

      // Step 2: Load events via timeline/load (P3-C: timeline.json 唯一事实源,
      // 不再经 speaker/diarization/load 拿主数据)
      const loadRes = await fetch('/api/timeline/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace: workspacePath }),
      })
      if (!loadRes.ok) {
        const errData = await loadRes.json().catch(() => ({}))
        throw new Error((errData as any).detail || '无法加载时间轴数据')
      }
      const loadData = await loadRes.json()

      const events = (Object.values(loadData.inspector_data || {}) as EventViewModel[])
        .sort((a, b) => a.start - b.start)

      // Step 3-5: 辅助数据加载失败必须响亮 (禁止兜底 — 静默会显示为空数据误导用户)
      const loadErrors: string[] = []

      // Step 3: Load waveform
      let waveform: WaveformData | null = null
      try {
        const wfRes = await fetch(
          `/api/speaker/diarization/waveform?workspace=${encodeURIComponent(workspacePath)}`
        )
        if (wfRes.ok) waveform = await wfRes.json()
        else loadErrors.push('波形')
      } catch { loadErrors.push('波形') }

      // Step 4: Load patch log
      let appliedPatches: TimelinePatchData[] = []
      try {
        const patchRes = await fetch(
          `/api/timeline/patch/log?workspace=${encodeURIComponent(workspacePath)}`
        )
        if (patchRes.ok) {
          const patchData = await patchRes.json()
          appliedPatches = (patchData.patches || []).map((p: any) => ({
            patch_id: p.patch_id || '',
            opcode: p.opcode || '',
            targets: p.targets || [],
            payload: p.payload || {},
            reason: p.reason || [],
            score: p.score || 0,
            confidence: p.confidence || 0,
            parent_version: p.parent_version || '',
            idempotency_key: p.idempotency_key || '',
            author: p.author || 'system',
            timestamp: p.timestamp || '',
          }))
        } else loadErrors.push('补丁历史')
      } catch { loadErrors.push('补丁历史') }

      // Step 5: Load review flags
      let reviewFlags: IssueItem[] = []
      try {
        const flagRes = await fetch(
          `/api/timeline/review/flags?workspace=${encodeURIComponent(workspacePath)}`
        )
        if (flagRes.ok) {
          const flagData = await flagRes.json()
          const SEVERITY: Record<string, 'warning' | 'error'> = { speaker_conflict: 'error' }
          reviewFlags = (flagData.flags || []).flatMap((f: any) =>
            (f.flags || []).map((t: string) => ({
              eventId: f.event_id,
              type: t as IssueItem['type'],
              severity: SEVERITY[t] || ('warning' as const),
              message: f.reason || '',
              detail: { text: f.text, translation: f.translation },
              start: f.start || 0,
              end: f.end || 0,
            }))
          )
        } else loadErrors.push('校验标记')
      } catch { loadErrors.push('校验标记') }

      set({
        workspace: workspacePath,
        events,
        waveform,
        appliedPatches,
        reviewFlags,
        manifest: manifestData.manifest,
        loading: false,
        error: null,
      })
      // 部分数据失败在成功态之后设置, 避免被 set 的 error: null 吞掉
      if (loadErrors.length > 0) {
        set({ error: `部分数据加载失败: ${loadErrors.join('、')}` })
      }
      get()._logOp('loadWorkspace', loadErrors.length === 0, performance.now() - t0,
        `${events.length} events${loadErrors.length ? `, 部分失败: ${loadErrors.join('、')}` : ''}`,
        loadErrors.length > 0 ? `部分数据加载失败: ${loadErrors.join('、')}` : '')
      recordUserAction('opened', workspacePath.split(/[/\\]/).pop() || workspacePath,
        `打开项目 · ${events.length} 个事件${loadErrors.length ? `（${loadErrors.join('、')}加载失败）` : ''}`,
        loadErrors.length > 0 ? 'failed' : 'ok')
    } catch (err) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : '未知错误',
      })
      recordUserAction('opened', workspacePath.split(/[/\\]/).pop() || workspacePath,
        `打开项目失败: ${err instanceof Error ? err.message : '未知错误'}`, 'failed')
      get()._logOp('loadWorkspace', false, performance.now() - t0, '',
        err instanceof Error ? err.message : '未知错误')
    }
  },

  reloadEvents: async () => {
    const ws = get().workspace
    if (!ws) return
    // 编辑后刷新失败必须响亮 — 静默会让用户看到旧数据误以为编辑已生效
    let res: Response
    try {
      res = await fetch('/api/timeline/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace: ws }),
      })
    } catch (e) {
      set({ error: `事件刷新失败: ${e instanceof Error ? e.message : String(e)}` })
      return
    }
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}))
      set({ error: `事件刷新失败: ${(detail as any).detail || `HTTP ${res.status}`}` })
      return
    }
    const data = await res.json()
    const events = (Object.values(data.inspector_data || {}) as EventViewModel[])
      .sort((a, b) => a.start - b.start)
    set({ events })
  },

  clearWorkspace: () => set({
    dataSource: 'mock',
    workspace: '',
    events: [],
    waveform: null,
    ttsWaveforms: null,
    reviewFlags: [],
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

  loadReviewEntries: async (workspaceOverride) => {
    const ws = workspaceOverride || get().workspace
    if (!ws) return
    // 失败必须响亮 — 旧实现回退本地 events 合成条目是静默假数据
    // (后端 review/load 含 SRT 关联/审核状态, 本地合成语义不同)
    let res: Response
    try {
      res = await fetch('/api/subtitle/review/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace: ws }),
      })
    } catch (e) {
      set({ error: `评审条目加载失败: ${e instanceof Error ? e.message : String(e)}` })
      return
    }
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}))
      set({ error: `评审条目加载失败: ${(detail as any).detail || `HTTP ${res.status}`}` })
      return
    }
    const data = await res.json()
    set({
      reviewEntries: data.entries || [],
      reviewTranslatedSrtPath: data.translatedSrtPath || '',
    })
  },

  saveReviewEntries: async () => {
    const { reviewEntries, reviewTranslatedSrtPath } = get()
    const modified = reviewEntries.filter(e => e.reviewStatus === 'modified')
    if (modified.length === 0) return
    // 预解析事件 ID: 写 SRT 前验证全部条目可关联 timeline 事件 —
    // 后端 review/load 已按时间匹配, 此处兜底 + 拒绝伪造 entry_N (禁止兜底)
    const resolved: { entry: SubtitleEntry; eventId: string }[] = modified.map(entry => {
      let eventId = entry.eventId
      if (!eventId) {
        const matched = get().events.find(ev =>
          Math.abs(ev.start * 1000 - entry.startMs) <= 500
        )
        eventId = matched?.id
      }
      if (!eventId) {
        throw new Error(`评审保存失败: 第 ${entry.index} 条无法关联 timeline 事件 (startMs=${entry.startMs})`)
      }
      return { entry, eventId }
    })
    try {
      const res = await fetch('/api/subtitle/review/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          translated_srt: reviewTranslatedSrtPath,
          entries: modified,
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      // Mark saved entries as approved
      set(state => ({
        reviewEntries: state.reviewEntries.map(e =>
          e.reviewStatus === 'modified' ? { ...e, reviewStatus: 'approved' as const } : e
        ),
      }))
      // Record patches for each modified entry
      for (const { entry, eventId } of resolved) {
        const store = get()
        store.addDraft({
          eventId,
          opcode: 'SET_TRANSLATION',
          payload: { translation: entry.translatedText },
          before: { translation: entry.sourceText },
          after: { translation: entry.translatedText },
          timestamp: Date.now(),
        })
        const ok = await store.applyDraft(eventId, true)
        if (!ok) {
          throw new Error(`评审保存失败: 第 ${entry.index} 条补丁未应用 (${get().error || '未知错误'})`)
        }
      }
      recordUserAction('saved', undefined, `保存字幕校验: ${data.updated} 条`)
      console.log(`Review saved: ${data.updated} entries → ${data.output_path}`)
    } catch (err) {
      recordUserAction('saved', undefined,
        `保存字幕校验失败: ${err instanceof Error ? err.message : String(err)}`, 'failed')
      console.error('Review save failed:', err)
      throw err
    }
  },

  // ── Hub Actions (Phase 1) ──

  fetchWorkflowPresets: async () => {
    // 失败必须响亮 — 静默会让预设列表显示为空 (用户误以为无预设)
    let res: Response
    try {
      res = await fetch('/api/workflow/presets')
    } catch (e) {
      set({ error: `工作流预设加载失败: ${e instanceof Error ? e.message : String(e)}` })
      return
    }
    if (!res.ok) {
      set({ error: `工作流预设加载失败: HTTP ${res.status}` })
      return
    }
    const data = await res.json()
    set({ workflowPresets: data.presets || [] })
  },

  fetchWorkspaceList: async () => {
    // 失败必须响亮 — 静默会让工作区列表显示为空 (用户误以为无项目)
    let res: Response
    try {
      res = await fetch('/api/workspaces')
    } catch (e) {
      set({ error: `工作区列表加载失败: ${e instanceof Error ? e.message : String(e)}` })
      return
    }
    if (!res.ok) {
      set({ error: `工作区列表加载失败: HTTP ${res.status}` })
      return
    }
    const data = await res.json()
    set({ workspaceList: data.workspaces || [] })
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
      recordUserAction('created', name || data.workspace, `创建项目 ${name || data.workspace}`)
      return data.workspace as string
    } catch (err) {
      set({ loading: false, error: err instanceof Error ? err.message : '未知错误' })
      throw err
    }
  },
}))
