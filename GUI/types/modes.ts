/**
 * modes.ts — 模式切换协议与布局预设类型
 */

export type Mode = 'timeline' | 'speaker' | 'patch' | 'batch' | 'export'

/** 跨模式导航上下文 — 从辅助模式一键跳回 Timeline 时携带 */
export interface CrossModeContext {
  eventId: string
  sourceMode: Mode
  playheadTarget: number
  timestamp: number
}

export const ALL_MODES: Mode[] = ['timeline', 'speaker', 'patch', 'batch', 'export']

export interface ModeMeta {
  label: string
  labelEn: string
  accentColor: string
  hexColor: string
  icon: string
  defaultShortcuts: Record<string, string>
  defaultIssueFilter: IssueFilter
  defaultDockView: 'log' | 'aiTrace' | 'patchDiff' | 'taskOutput' | 'debug'
}

export const MODE_META: Record<Mode, ModeMeta> = {
  timeline: {
    label: 'Timeline Studio', labelEn: 'Timeline Studio',
    accentColor: 'var(--mode-timeline)', hexColor: '#2196F3', icon: 'Timeline',
    defaultShortcuts: { 'Space': '播放 / 暂停', 'Ctrl+Z': '撤销', 'Ctrl+K': '命令面板' },
    defaultIssueFilter: { types: [], severity: 'all' }, defaultDockView: 'log',
  },
  speaker: {
    label: 'Speaker Review', labelEn: 'Speaker Review',
    accentColor: 'var(--mode-speaker)', hexColor: '#FF9800', icon: 'RecordVoiceOver',
    defaultShortcuts: { 'Tab': '切换说话人焦点', 'N': '下一问题', 'R': '重命名说话人', 'Ctrl+K': '命令面板' },
    defaultIssueFilter: { types: ['low_confidence', 'misaligned', 'cps_high', 'term_conflict', 'speaker_drift'], severity: 'all' },
    defaultDockView: 'log',
  },
  patch: {
    label: 'Patch Management', labelEn: 'Patch Management',
    accentColor: 'var(--mode-patch)', hexColor: '#9C27B0', icon: 'Build',
    defaultShortcuts: { 'Enter': '应用当前草案', 'Escape': '放弃当前草案', 'Ctrl+Enter': '应用全部草案', 'Ctrl+Shift+Z': '回滚上一个补丁', 'Ctrl+K': '命令面板' },
    defaultIssueFilter: { types: [], severity: 'all' }, defaultDockView: 'patchDiff',
  },
  batch: {
    label: 'Batch Queue', labelEn: 'Batch Queue',
    accentColor: 'var(--mode-ops)', hexColor: '#607D8B', icon: 'QueuePlayNext',
    defaultShortcuts: { 'Ctrl+R': '重试失败任务', 'Ctrl+C': '取消运行中任务', 'Ctrl+K': '命令面板' },
    defaultIssueFilter: { types: [], severity: 'all' }, defaultDockView: 'taskOutput',
  },
  export: {
    label: 'Export', labelEn: 'Export',
    accentColor: 'var(--mode-export)', hexColor: '#00BCD4', icon: 'IosShare',
    defaultShortcuts: { 'Ctrl+E': '导出视频', 'Ctrl+K': '命令面板' },
    defaultIssueFilter: { types: [], severity: 'all' }, defaultDockView: 'log',
  },
}

export type InspectorTab = 'content' | 'timing' | 'speaker' | 'tts' | 'patch' | 'history'
export const ALL_INSPECTOR_TABS: InspectorTab[] = ['content', 'timing', 'speaker', 'tts', 'patch', 'history']

export interface LayoutPreset {
  railComponent: string | null
  inspectorTabs: InspectorTab[]
  defaultDockView: 'log' | 'aiTrace' | 'patchDiff' | 'taskOutput' | 'debug'
}

export const LAYOUT_PRESETS: Record<Mode, LayoutPreset> = {
  timeline: { railComponent: null, inspectorTabs: ALL_INSPECTOR_TABS, defaultDockView: 'log' },
  speaker: { railComponent: null, inspectorTabs: ['speaker', 'tts', 'content', 'timing'], defaultDockView: 'log' },
  patch: { railComponent: null, inspectorTabs: ['patch', 'content', 'timing', 'history'], defaultDockView: 'patchDiff' },
  batch: { railComponent: null, inspectorTabs: ['content', 'timing', 'history'], defaultDockView: 'taskOutput' },
  export: { railComponent: null, inspectorTabs: ['content', 'timing'], defaultDockView: 'log' },
}

export type IssueType = 'low_confidence' | 'misaligned' | 'cps_high' | 'duration_short' | 'duration_long' | 'term_conflict' | 'speaker_drift'

export interface IssueFilter { types: IssueType[]; severity: 'warning' | 'error' | 'all' }
export interface IssueItem { eventId: string; type: IssueType; severity: 'warning' | 'error'; message: string; detail: Record<string, unknown>; start: number; end: number }
export interface PatchDraft { eventId: string; opcode: string; payload: Record<string, unknown>; before: Record<string, unknown>; after: Record<string, unknown>; timestamp: number }
export interface VoiceCard { id: string; name: string; language: string; sampleText: string; engine: 'edge' | 'chattts' | 'cosyvoice' | 'indextts'; locked: boolean }
export interface JobState { jobId: string; eventId: string; status: 'running' | 'completed' | 'failed'; progress: number }

// ── Speaker Review 类型 ──

/** 对齐后端 /api/speaker/diarization/load 响应中的 speaker_lane */
export interface SpeakerLaneData {
  speaker: string
  display_name: string
  voice_id: string
  color: string
  segments: SpeakerSegmentData[]
  segment_count: number
  total_duration: number
}

export interface SpeakerSegmentData {
  start: number; end: number
  text: string
  translation?: string
  confidence: number
  eventId?: string
}

/** 说话人质量评分（前端计算） */
export interface SpeakerQuality {
  speakerId: string
  avgConfidence: number
  conflictRate: number
  switchFrequency: number
  continuityScore: number
}

/** ChatTTS speaker preset（对齐 /api/tts/speakers 响应） */
export interface ChatTTSSpeaker {
  id: string; name: string
  seed?: number; spk_emb?: string; speaker_pt?: string
}
