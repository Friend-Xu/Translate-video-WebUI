/**
 * modes.ts — 模式切换协议与布局预设类型
 *
 * 所有新组件的 Props 类型从此文件或 types.ts 中导出，
 * 不自行发明不兼容的数据结构。
 */

// ── Mode ──

export type Mode = 'timeline' | 'review' | 'patch' | 'speaker' | 'ops'

export const ALL_MODES: Mode[] = ['timeline', 'review', 'patch', 'speaker', 'ops']

// ── Mode Metadata ──

export interface ModeMeta {
  label: string
  labelEn: string
  accentColor: string       // CSS 变量名，如 'var(--mode-timeline)'
  hexColor: string           // 备用 hex，如 '#2196F3'
  icon: string               // MUI icon name
  defaultShortcuts: Record<string, string>  // key → description
  defaultIssueFilter: IssueFilter
  defaultDockView: 'log' | 'execution' | 'patchHistory'
}

export const MODE_META: Record<Mode, ModeMeta> = {
  timeline: {
    label: '时间轴',
    labelEn: 'Timeline',
    accentColor: 'var(--mode-timeline)',
    hexColor: '#2196F3',
    icon: 'Timeline',
    defaultShortcuts: {
      'Space': '播放 / 暂停',
      'ArrowLeft': '后退 1 秒',
      'ArrowRight': '前进 1 秒',
      'Shift+ArrowLeft': '后退 5 秒',
      'Shift+ArrowRight': '前进 5 秒',
      'Ctrl+Z': '撤销',
      'Ctrl+K': '命令面板',
    },
    defaultIssueFilter: { types: [], severity: 'all' },
    defaultDockView: 'log',
  },
  review: {
    label: '审核',
    labelEn: 'Review',
    accentColor: 'var(--mode-review)',
    hexColor: '#FF9800',
    icon: 'RateReview',
    defaultShortcuts: {
      'N': '下一问题',
      'Shift+N': '上一问题',
      'Enter': '应用修复建议',
      'Escape': '关闭诊断卡',
      'Ctrl+K': '命令面板',
    },
    defaultIssueFilter: { types: ['low_confidence', 'misaligned', 'cps_high', 'term_conflict', 'speaker_drift'], severity: 'all' },
    defaultDockView: 'log',
  },
  patch: {
    label: '补丁',
    labelEn: 'Patch',
    accentColor: 'var(--mode-patch)',
    hexColor: '#9C27B0',
    icon: 'Build',
    defaultShortcuts: {
      'Enter': '应用当前草案',
      'Escape': '放弃当前草案',
      'Ctrl+Enter': '应用全部草案',
      'Ctrl+Shift+Z': '回滚上一个补丁',
      'Ctrl+K': '命令面板',
    },
    defaultIssueFilter: { types: [], severity: 'all' },
    defaultDockView: 'patchHistory',
  },
  speaker: {
    label: '说话人',
    labelEn: 'Speaker',
    accentColor: 'var(--mode-speaker)',
    hexColor: '#4CAF50',
    icon: 'RecordVoiceOver',
    defaultShortcuts: {
      'Tab': '切换说话人焦点',
      'R': '重命名说话人',
      'M': '合并到上一轨道',
      'Ctrl+K': '命令面板',
    },
    defaultIssueFilter: { types: [], severity: 'all' },
    defaultDockView: 'log',
  },
  ops: {
    label: '运维',
    labelEn: 'Ops',
    accentColor: 'var(--mode-ops)',
    hexColor: '#607D8B',
    icon: 'Terminal',
    defaultShortcuts: {
      'Ctrl+R': '重试失败任务',
      'Ctrl+C': '取消运行中任务',
      'Ctrl+K': '命令面板',
    },
    defaultIssueFilter: { types: [], severity: 'all' },
    defaultDockView: 'execution',
  },
}

// ── Layout Preset ──

export type InspectorTab = 'text' | 'time' | 'speaker' | 'tts' | 'patch' | 'history'
export const ALL_INSPECTOR_TABS: InspectorTab[] = ['text', 'time', 'speaker', 'tts', 'patch', 'history']

export interface LayoutPreset {
  railComponent: string | null     // 组件名，null 表示该模式无左侧 Rail
  inspectorTabs: InspectorTab[]    // 右侧 Inspector 显示的页签
  defaultDockView: 'log' | 'execution' | 'patchHistory'
}

export const LAYOUT_PRESETS: Record<Mode, LayoutPreset> = {
  timeline: {
    railComponent: null,
    inspectorTabs: ['text', 'time', 'speaker', 'tts', 'patch', 'history'],
    defaultDockView: 'log',
  },
  review: {
    railComponent: 'IssueQueue',
    inspectorTabs: ['text', 'time', 'patch', 'history'],
    defaultDockView: 'log',
  },
  patch: {
    railComponent: 'PatchRail',
    inspectorTabs: ['text', 'time', 'patch', 'history'],
    defaultDockView: 'patchHistory',
  },
  speaker: {
    railComponent: 'SpeakerRail',
    inspectorTabs: ['speaker', 'tts', 'text', 'time'],
    defaultDockView: 'log',
  },
  ops: {
    railComponent: 'OpsRail',
    inspectorTabs: ['text', 'time', 'history'],
    defaultDockView: 'execution',
  },
}

// ── Issue / Filter ──

export type IssueType = 'low_confidence' | 'misaligned' | 'cps_high' | 'duration_short' | 'duration_long' | 'term_conflict' | 'speaker_drift'

export interface IssueFilter {
  types: IssueType[]
  severity: 'warning' | 'error' | 'all'
}

export interface IssueItem {
  eventId: string
  type: IssueType
  severity: 'warning' | 'error'
  message: string
  detail: Record<string, unknown>
  start: number
  end: number
}

// ── Draft ──

export interface PatchDraft {
  eventId: string
  opcode: string
  payload: Record<string, unknown>
  before: Record<string, unknown>
  after: Record<string, unknown>
  timestamp: number
}

// ── Voice / Speaker ──

export interface VoiceCard {
  id: string
  name: string
  language: string
  sampleText: string
  engine: 'edge' | 'chattts' | 'cosyvoice' | 'indextts'
  locked: boolean
}

// ── Job ──

export interface JobState {
  jobId: string
  eventId: string
  status: 'running' | 'completed' | 'failed'
  progress: number
}
