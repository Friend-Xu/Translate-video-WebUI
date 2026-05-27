/**
 * timeline.ts — 轨道系统与吸附系统类型定义
 *
 * 参考 Premiere Pro / DaVinci Resolve 多轨分层架构设计。
 */
import type { Mode } from './modes'

// ── Track ──

export type TrackType = 'source' | 'translation' | 'speaker' | 'tts' | 'diff'
export type TrackRenderer = 'waveform' | 'event-block' | 'speaker-lane' | 'tts-waveform'

export interface TrackDefinition {
  id: string
  type: TrackType
  label: string
  order: number
  visible: boolean
  locked: boolean
  solo?: boolean
  muted?: boolean
  height: number
  minHeight: number
  maxHeight?: number
  renderer: TrackRenderer
  dataSource: string
}

export const DEFAULT_TRACKS: TrackDefinition[] = [
  { id: 'trk_source', type: 'source', label: '原文', order: 0, visible: true, locked: false, height: 50, minHeight: 30, renderer: 'event-block', dataSource: 'events' },
  { id: 'trk_translation', type: 'translation', label: '译文', order: 1, visible: true, locked: false, height: 50, minHeight: 30, renderer: 'event-block', dataSource: 'events' },
  { id: 'trk_diff', type: 'diff', label: '差异', order: 2, visible: false, locked: true, height: 50, minHeight: 30, renderer: 'event-block', dataSource: 'pendingDrafts' },
  { id: 'trk_speaker', type: 'speaker', label: '说话人', order: 3, visible: true, locked: false, height: 40, minHeight: 24, renderer: 'speaker-lane', dataSource: 'events' },
  { id: 'trk_tts', type: 'tts', label: 'TTS 音频', order: 4, visible: false, locked: false, muted: true, height: 50, minHeight: 30, maxHeight: 100, renderer: 'tts-waveform', dataSource: 'waveformByTtsEngine' },
]

// ── Track Visibility Presets per Mode ──

export const TRACK_VISIBILITY_MAP: Record<Mode, Partial<Record<TrackType, { visible: boolean; locked: boolean; solo?: boolean; muted?: boolean }>>> = {
  hub: {},
  timeline: {},
  patch: {
    diff: { visible: true, locked: false, solo: true },
    speaker: { visible: false, locked: true },
  },
  batch: {
    source: { visible: false, locked: true },
    translation: { visible: false, locked: true },
    speaker: { visible: false, locked: true },
    tts: { visible: false, locked: true },
  },
  export: {},
}

// Speaker focus track preset — applied when timelineFocus='speaker'
export const SPEAKER_TRACK_PRESET: Partial<Record<TrackType, { visible: boolean; locked: boolean; solo?: boolean; muted?: boolean }>> = {
  speaker: { visible: true, locked: false, solo: true },
  source: { visible: true, locked: true, muted: true },
  translation: { visible: false, locked: true },
}

// ── Snap ──

export type SnapTargetType = 'playhead' | 'event-boundary' | 'marker' | 'grid'

export interface SnapTarget {
  pixelX: number
  time: number
  type: SnapTargetType
  label?: string
}

export interface SnapResult {
  snappedPixel: number
  snappedTime: number
  type: SnapTargetType
  distancePx: number
}
