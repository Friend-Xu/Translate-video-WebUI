export interface PipelineConfig {
  videoPath: string
  lang: 'auto' | 'en' | 'zh' | 'ja'
  targetLang: 'zh-CN' | 'en' | 'ja' | 'ko' | 'auto'
  model: 'tiny' | 'base' | 'small' | 'medium' | 'turbo' | 'large-v3'
  device: 'cpu' | 'cuda'
  computeType: 'int8' | 'float32' | 'float16' | 'int8_float16'
  engine: 'edge' | 'chattts' | 'cosyvoice' | 'indextts'
  chatttsSpeakerSeed: number | null
  chatttsSpeakerPt: string
  chatttsModelSource: 'local' | 'custom'
  chatttsModelPath: string
  chatttsPreviewAudio: string
  chatttsPreviewSeed: number | null
  chatttsSpkEmb: string
  loudnessNormEnabled: boolean
  loudnessTargetAuto: boolean
  loudnessTargetLufs: number
  cosyvoiceTtsModelVersion: 'v2' | 'v3'
  cosyvoiceTtsModelPath: string
  cosyvoiceTtsPromptAudio: string
  cosyvoiceTtsPromptText: string
  cosyvoiceTtsFp16: boolean
  cosyvoiceTtsWorkers: number
  cosyvoiceTtsSpeed: number
  cosyvoiceTtsMode: 'cross_lingual'
  cosyvoiceTtsLang: string
  indexttsFp16: boolean
  indexttsEnableClone: boolean
  indexttsSpeakerAudio: string
  indexttsCheckpointsDir: string
  voice: string
  speechRate: number
  maxSpeed: number
  videoSpeedMin: number
  videoSpeedMax: number
  apiKey: string
  apiType: string
  maxTokens: number
  apiProvider: 'deepseek' | 'kimi' | 'xiaomi' | 'custom'
  apiBaseUrl: string
  apiModel: string
  apiTemperature: number
  apiTopP: number
  enableSemanticValidation: boolean
  enableNaturalnessCheck: boolean
  naturalnessThreshold: number
  jointVerification: boolean
  verificationMode: "joint_formula" | "logic_gate"
  simDropLimit: number
  enableTermReplacement: boolean
  enableReviewAfterTranslate: boolean
  enableDemucs: boolean
  enableSubtitleOverlay: boolean
  enableVideoMerge: boolean
  outputPath: string
  videoCodec: 'libx264' | 'h265'
  audioCodec: 'aac'
  enableEmotionClone: boolean
  emotionRefAudio: string
  defaultEmotion: string
  enableVoiceClone: boolean
  voiceCloneEngine: 'openvoice' | 'cosyvoice' | 'none'
  voiceCloneDevice: 'auto' | 'cuda:0' | 'cpu'
  voiceCloneConcurrency: number
  cosyvoiceMode: 'local' | 'docker'
  cosyvoiceModelVersion: 'v2' | 'v3'
  voiceCloneSample: string
  concurrency: number
  numWorkers: number
  ttsWorkers: number
  chatttsWorkers: number
  enableCheckpoint: boolean
  enableDefectCheck: boolean
  enableExtract: boolean
  enableTranslate: boolean
  enableTTS: boolean
  forceRetry: boolean
  enableAlignment: boolean
  alignmentLanguage: string
  defaultVideoDir: string
  captionFont: string
  captionFontSizeMode: 'adaptive' | 'fixed'
  captionFontSize: number
  captionFontColor: string
  captionStrokeWidth: number
  captionStrokeColor: string
  captionBgColor: string
  captionAlignment: 'center' | 'left' | 'right'
  captionPosition: 'bottom' | 'top'
  captionMaxLines: number
  captionMaxFontSize: number
  captionFontSizeFactor: number
  captionWidthRatio: number
  enableSubtitleOptimization: boolean
  subtitleEngine: 'pil' | 'imagemagick'
  bgmVolume: number
  customPromptEnabled: boolean
  customSystemPrompt: string
  customBatchPrompt: string
  customSinglePrompt: string
  customSemanticRetryPrompt: string
  customNaturalnessRetryPrompt: string
  splitBrainEnabled: boolean
  activeGlossary: string[]
  multiAgentEnabled: boolean
  mqmEnabled: boolean
  mqmThreshold: number
  /** 启用说话人分离 */
  enableSpeakerDiarization: boolean
  speakerOverlapStrategy: 'dominant_energy' | 'split_sequential' | 'mark_for_review'
}

export interface StageInfo {
  status: 'pending' | 'running' | 'completed' | 'failed'
  label: string
  percent: number
  current_item?: number
  total_items?: number
  elapsed?: number
  started_at?: number
  message?: string
}

export interface PipelineStatus {
  state: 'idle' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  currentStep: string
  jobId: string | null
  detail: string
  stages: Record<string, StageInfo>
}

export interface LogEntry {
  _id?: number   // monotonic counter for stable react keys
  level: 'INFO' | 'WARN' | 'ERROR' | 'STAGE'
  message: string
  timestamp: string
}

export interface ProviderPreset {
  name: string
  baseUrl: string
  models: string[]
}

export const PROVIDER_PRESETS: Record<string, ProviderPreset> = {
  deepseek: { name: 'DeepSeek', baseUrl: 'https://api.deepseek.com', models: ['deepseek-chat', 'deepseek-reasoner'] },
  kimi: { name: 'Kimi (月之暗面)', baseUrl: 'https://api.moonshot.ai/v1', models: ['moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k', 'kimi-latest'] },
  xiaomi: { name: '小米 MiMo', baseUrl: 'https://api.xiaomimimo.com/v1', models: ['mimo-latest'] },
  custom: { name: '自定义', baseUrl: '', models: [] },
}

export const DEFAULT_CONFIG: PipelineConfig = {
  videoPath: '',
  lang: 'auto',
  targetLang: 'zh-CN',
  model: 'turbo',
  device: 'cuda',
  computeType: 'float16',
  engine: 'edge',
  chatttsSpeakerSeed: 2,
  chatttsSpeakerPt: '',
  chatttsModelSource: 'local',
  chatttsModelPath: '',
  chatttsPreviewAudio: '',
  chatttsPreviewSeed: null,
  chatttsSpkEmb: '',
  loudnessNormEnabled: true,
  loudnessTargetAuto: true,
  loudnessTargetLufs: -16.0,
  cosyvoiceTtsModelVersion: 'v2',
  cosyvoiceTtsModelPath: '',
  cosyvoiceTtsPromptAudio: '',
  cosyvoiceTtsPromptText: '',
  cosyvoiceTtsFp16: true,
  cosyvoiceTtsWorkers: 0,
  cosyvoiceTtsSpeed: 1.0,
  cosyvoiceTtsMode: 'cross_lingual',
  cosyvoiceTtsLang: '',
  indexttsFp16: true,
  indexttsEnableClone: true,
  indexttsSpeakerAudio: '',
  indexttsCheckpointsDir: '',
  voice: 'zh-CN-XiaoxiaoNeural',
  speechRate: 40,
  maxSpeed: 100,
  videoSpeedMin: 0.60,
  videoSpeedMax: 2.00,
  apiKey: '',
  apiType: 'deepseek',
  maxTokens: 4000,
  apiProvider: 'deepseek',
  apiBaseUrl: 'https://api.deepseek.com',
  apiModel: 'deepseek-chat',
  apiTemperature: 0.1,
  apiTopP: 0.9,
  enableSemanticValidation: true,
  enableNaturalnessCheck: true,
  naturalnessThreshold: 3.0,
  jointVerification: false,
  verificationMode: "joint_formula",
  simDropLimit: 0.05,
  enableTermReplacement: true,
  enableReviewAfterTranslate: true,
  enableDemucs: true,
  enableSubtitleOverlay: true,
  enableVideoMerge: true,
  outputPath: '',
  videoCodec: 'libx264',
  audioCodec: 'aac',
  enableEmotionClone: false,
  emotionRefAudio: '',
  defaultEmotion: 'neutral',
  enableVoiceClone: false,
  voiceCloneEngine: 'openvoice',
  voiceCloneDevice: 'auto',
  voiceCloneConcurrency: 1,
  cosyvoiceMode: 'local',
  cosyvoiceModelVersion: 'v2',
  voiceCloneSample: '',
  concurrency: 3,
  numWorkers: 1,
  ttsWorkers: 7,
  chatttsWorkers: 0,  // 0 = VRAM自动
  enableCheckpoint: true,
  enableDefectCheck: true,
  enableExtract: true,
  enableTranslate: true,
  enableTTS: true,
  forceRetry: false,
  enableAlignment: false,
  alignmentLanguage: 'ja',
  defaultVideoDir: '',
  captionFont: '',
  captionFontSizeMode: 'adaptive',
  captionFontSize: 0,
  captionFontColor: '#ffffff',
  captionStrokeWidth: 0,
  captionStrokeColor: '#000000',
  captionBgColor: 'rgba(0,0,0,128)',
  captionAlignment: 'center',
  captionPosition: 'bottom',
  captionMaxLines: 2,
  captionMaxFontSize: 0,
  captionFontSizeFactor: 0.030,
  captionWidthRatio: 0.85,
  enableSubtitleOptimization: true,
  subtitleEngine: 'pil',
  bgmVolume: 1.0,
  customPromptEnabled: false,
  customSystemPrompt: '',
  customBatchPrompt: '',
  customSinglePrompt: '',
  customSemanticRetryPrompt: '',
  customNaturalnessRetryPrompt: '',
  splitBrainEnabled: false,
  activeGlossary: ['minecraft.json'],
  multiAgentEnabled: false,
  mqmEnabled: false,
  mqmThreshold: 0.6,
  enableSpeakerDiarization: false,
  speakerOverlapStrategy: 'dominant_energy' as const,
}

export interface SubtitleIssue {
  type: 'low_similarity' | 'cps_high' | 'duration_short' | 'duration_long' | 'overlap' | 'empty'
  message: string
  severity: 'warning' | 'error'
}

export interface DimensionScore {
  value: number
  threshold: number
  flagged: boolean
  confidence: number
  label: string
  detail?: string
}

export interface QualityScores {
  semantic: DimensionScore
  naturalness: DimensionScore
  structural: DimensionScore
  mqm?: DimensionScore
}

export type QualityTier = 'pass' | 'glance' | 'review' | 'critical'

export interface SubtitleEntry {
  index: number
  start: string
  end: string
  startMs: number
  endMs: number
  sourceText: string
  translatedText: string
  reviewStatus: 'pending' | 'approved' | 'modified' | 'flagged'
  issues: SubtitleIssue[]
  similarity?: number
  semanticFlagged?: {
    similarity: number
    retried: boolean
    kept: string
    improvement?: number
    retriedSimilarity?: number
    retriedText?: string
    originalText?: string
  } | null
  quality?: QualityScores
  tier?: QualityTier
  tierReason?: string
  /** 说话人 ID（多说话人视频） */
  speakerId?: string
  /** 关联的 timeline event ID */
  eventId?: string
}

export interface ReviewSession {
  videoPath: string
  sourceSrtPath: string
  translatedSrtPath: string
  entries: SubtitleEntry[]
  filterMode: 'all' | 'pending' | 'flagged' | 'semantic' | 'naturalness' | 'review_critical'
  qualitySummary?: {
    total: number
    tier_pass: number
    tier_glance: number
    tier_review: number
    tier_critical: number
    naturalness_baseline_ppl: number
  }
  promptManifest?: {
    version: number
    templates: Record<string, { template: string; is_custom: boolean }>
    config_snapshot: Record<string, unknown>
  }
}

export interface ChatTTSSpeaker {
  id: string
  name: string
  gender: string
  age: string
  features: string
  rank_long: number
  rank_multi: number
  rank_single: number
  pt_file: string
}

export interface SystemInfo {
  cpuCount: number
  hasGpu: boolean
  gpuName: string
  gpuVramMb: number
  recommendedConcurrency: number
  defaultVideoDir: string
  chatttsWorkers: number
}

export interface VideoInfo {
  width: number
  height: number
  duration: number
  durationStr: string
}

export type PipelineMode = 'single' | 'batch'

export interface BatchVideoItem {
  video_path: string
  video_name: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  current_step: string
  job_id: string | null
}

export interface BatchStatus {
  batch_id: string | null
  status: 'idle' | 'running' | 'completed' | 'partial' | 'cancelled' | 'failed'
  current_index: number
  total_count: number
  completed_count: number
  failed_count: number
  videos: BatchVideoItem[]
  logs: string[]
  created_at: string
}

export type PipelineStage =
  | 'media_analysis' | 'audio_extract' | 'asr' | 'translation'
  | 'speaker_diarization' | 'tts' | 'alignment' | 'render' | 'package'

export interface StageProgress {
  stage: PipelineStage
  label: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  startedAt?: string
  completedAt?: string
  durationMs?: number
  retryCount: number
}

export const PIPELINE_STAGES: { stage: PipelineStage; label: string; order: number }[] = [
  { stage: 'media_analysis', label: '媒体分析', order: 0 },
  { stage: 'audio_extract', label: '音频抽取', order: 1 },
  { stage: 'asr', label: 'ASR', order: 2 },
  { stage: 'speaker_diarization', label: '说话人识别', order: 3 },
  { stage: 'translation', label: '翻译', order: 4 },
  { stage: 'alignment', label: '对齐', order: 5 },
  { stage: 'tts', label: 'TTS', order: 6 },
  { stage: 'render', label: '渲染', order: 7 },
  { stage: 'package', label: '打包', order: 8 },
]

/** 单个说话人轮次 */
export interface SpeakerTurn {
  speaker: string
  start: number
  end: number
  confidence: number
}

/** 说话人汇总 */
export interface SpeakerInfo {
  totalDur: number
  segments: number
  samplePath?: string
}

/** 说话人验证问题 */
export interface SpeakerVerificationIssue {
  layer: number
  severity: 'error' | 'warning' | 'info'
  message: string
  detail: Record<string, unknown>
}

/** 说话人分离验证报告 */
export interface SpeakerVerification {
  passesAll: boolean
  summary: {
    totalIssues: number
    errors: number
    warnings: number
    info: number
    speakers: number
    turns: number
  }
  issues: SpeakerVerificationIssue[]
}

/** 说话人审核会话 */
export interface DiarizationSession {
  workspace: string
  vocalPath: string
  speakers: string[]
  timeline: SpeakerTurn[]
  verification: SpeakerVerification | null
  speakerNames: Record<string, string>
}

/** Speaker merge request */
export interface SpeakerMergeRequest {
  workspace: string
  source: string
  target: string
}

/** Speaker split request */
export interface SpeakerSplitRequest {
  workspace: string
  speaker: string
  split_index: number
}

/** Speaker rename request */
export interface SpeakerRenameRequest {
  workspace: string
  speaker: string
  display_name: string
}

// ── Timeline Patch types (TASK 15) ──

export interface TimelinePatchData {
  /** 对应 patch_log.schema.json §PatchEntry */
  patch_id: string
  opcode: string
  targets: string[]
  payload: Record<string, any>
  reason: string[]
  score: number
  confidence: number
  parent_version: string
  idempotency_key: string
  author: string
  timestamp: string
  /** v2.0 新增: schema 版本标识 */
  schema_version?: string
  status?: 'draft' | 'applied' | 'rolled_back' | 'failed' | 'conflict'
  dependencies?: string[]
  conflicts?: string[]
}

export interface PatchGenerateResponse {
  patches: TimelinePatchData[]
  high: TimelinePatchData[]
  medium: TimelinePatchData[]
  low: TimelinePatchData[]
}

export interface PatchApplyRequest {
  workspace: string
  patch: TimelinePatchData
}

export interface PatchApplyResponse {
  status: string
  patch_id?: string
  diff?: Record<string, any>
  reason?: string
}

export interface PatchLogResponse {
  patches: TimelinePatchData[]
  count: number
}

// ── Timeline IR v2 前端类型 (UI底层设计.md §二) ──

/** EventBlock ViewModel — 渲染单个时间轴事件的完整视图模型 */
export interface EventViewModel {
  id: string
  start: number; end: number
  speaker: string | null
  displayName: string
  text: string
  translation: string
  source: string
  confidence: number
  visualState: {
    hasPatches: boolean
    hasAiSuggestion: boolean
    isSelected: boolean
    isMultiSelected: boolean
  }
  patches: TimelinePatchData[]
  passTrace: string[]
  words?: { word: string; start: number; end: number; confidence?: number }[]
}

/** 磁盘 timeline.json v2.0 的结构（对应 schemas/timeline.schema.json） */
export interface TimelineJsonV2 {
  schema_version: '2.0'
  project: {
    id: string; source_video: string
    source_lang: string; target_lang: string
    created_at?: string; updated_at?: string
  }
  events: {
    id: string; start: number; end: number
    text: string; translation?: string
    speaker?: string | null; tts_voice_id?: string | null
    confidence?: number
    words?: { word: string; start: number; end: number; confidence?: number }[]
    review_status?: 'pending' | 'approved' | 'modified' | 'flagged'
    patch_ids?: string[]
    source?: 'asr' | 'alignment' | 'manual' | 'imported'
    overlap?: { prev_event_id?: string | null; next_event_id?: string | null; overlap_duration?: number }
  }[]
  speakers?: Record<string, {
    id: string; name?: string | null
    voice_id?: string | null; color?: string
    is_locked?: boolean
    total_duration?: number; segment_count?: number
  }>
  metadata?: {
    total_duration?: number; event_count?: number
    speaker_count?: number; pipeline_version?: string
  }
}

/** 右键上下文菜单 */
export interface ContextMenuState {
  mouseX: number; mouseY: number
  event: EventViewModel | null
}

/** Patch 预览 (before/after) */
export interface PatchPreview {
  draft: TimelinePatchData
  before: Partial<EventViewModel>
  after: Partial<EventViewModel>
}

/** 波形数据 */
export interface WaveformData {
  peaks: number[]
  duration: number
  sampleRate: number
}

/** 按轨道的波形数据（TTS 引擎独立波形） */
export interface TrackWaveformData {
  trackId: string
  peaks: number[]
  duration: number
  sampleRate: number
  engine?: 'edge' | 'chattts' | 'cosyvoice'
  silenceRanges?: { start: number; end: number }[]
}

/** SpeakerLoad 响应扩展 */
export interface SpeakerLoadResponse {
  audio_id: string; version: string
  speaker_lanes: any[]
  patches: PatchGenerateResponse | null
  patch_log: TimelinePatchData[]
  pass_trace: string[]
  inspector_data: Record<string, EventViewModel>
  speakerNames: Record<string, string>
}

// ── Export Settings 类型 (Phase 8) ──

export interface VideoExportConfig {
  container: 'mp4' | 'mkv'
  videoCodec: 'libx264' | 'h265'
  audioCodec: 'aac'
  reencode: boolean
  preserveResolution: boolean
  preserveFramerate: boolean
  targetWidth?: number
  targetHeight?: number
}

export interface SubtitleExportConfig {
  mode: 'burned' | 'soft' | 'none' | 'external'
  bilingual: boolean
  font: string
  fontSizeMode: 'adaptive' | 'fixed'
  fontSize: number
  fontColor: string
  strokeWidth: number
  strokeColor: string
  bgColor: string
  alignment: 'center' | 'left' | 'right'
  position: 'bottom' | 'top'
  maxLines: number
  maxFontSize: number
  fontSizeFactor: number
  widthRatio: number
  externalFormat?: 'srt' | 'ass' | 'vtt'
}

export interface AudioExportConfig {
  strategy: 'dubbed_only' | 'original_only' | 'mixed' | 'multi_track'
  bgmVolume: number
  preserveOriginal: boolean
  separateTracks: boolean
}

export interface OutputNamingConfig {
  baseDir: string
  pattern: string
  createDateSubdir: boolean
  includeConfigSnapshot: boolean
  includeExportLog: boolean
}

export interface QualityExportConfig {
  videoBitrate: string
  audioBitrate: string
  crf: number
  preset: 'ultrafast' | 'fast' | 'medium' | 'slow'
  compatibility: 'desktop' | 'mobile' | 'both'
}

export interface ExportPreset {
  id: string
  name: string
  description: string
  isBuiltin: boolean
  createdAt: string
  updatedAt: string
  video: VideoExportConfig
  subtitle: SubtitleExportConfig
  audio: AudioExportConfig
  output: OutputNamingConfig
  quality: QualityExportConfig
}

export interface ExportReadinessWarning {
  severity: 'error' | 'warning' | 'info'
  message: string
  action?: { label: string; mode: import('./types/modes').Mode }
}

export interface ExportReadinessCheck {
  totalEvents: number
  lowConfidenceCount: number
  unappliedPatches: number
  unboundSpeakers: number
  failedBatchTasks: number
  warnings: ExportReadinessWarning[]
  isReady: boolean
}

export interface ExportResult {
  success: boolean
  outputDir: string
  files: { path: string; name: string; sizeMb: number; type: string }[]
  durationSec: number
  logPath?: string
}

export const DEFAULT_VIDEO_EXPORT: VideoExportConfig = {
  container: 'mp4', videoCodec: 'libx264', audioCodec: 'aac',
  reencode: false, preserveResolution: true, preserveFramerate: true,
}

export const DEFAULT_SUBTITLE_EXPORT: SubtitleExportConfig = {
  mode: 'burned', bilingual: true,
  font: '', fontSizeMode: 'adaptive', fontSize: 0,
  fontColor: '#ffffff', strokeWidth: 0, strokeColor: '#000000',
  bgColor: 'rgba(0,0,0,128)', alignment: 'center', position: 'bottom',
  maxLines: 2, maxFontSize: 0, fontSizeFactor: 0.030, widthRatio: 0.85,
}

export const DEFAULT_AUDIO_EXPORT: AudioExportConfig = {
  strategy: 'dubbed_only', bgmVolume: 1.0,
  preserveOriginal: false, separateTracks: false,
}

export const DEFAULT_OUTPUT_NAMING: OutputNamingConfig = {
  baseDir: '', pattern: '{project}_{lang}',
  createDateSubdir: false, includeConfigSnapshot: true, includeExportLog: true,
}

export const DEFAULT_QUALITY_EXPORT: QualityExportConfig = {
  videoBitrate: '8M', audioBitrate: '192k', crf: 23,
  preset: 'medium', compatibility: 'desktop',
}

export const BUILTIN_EXPORT_PRESETS: ExportPreset[] = [
  {
    id: 'builtin-release',
    name: '平台发布版', description: '烧录硬字幕 + H.264 + 仅配音轨，适合最终发布',
    isBuiltin: true,
    createdAt: '2025-01-01T00:00:00Z', updatedAt: '2025-01-01T00:00:00Z',
    video: { ...DEFAULT_VIDEO_EXPORT, container: 'mp4', videoCodec: 'libx264', reencode: false },
    subtitle: { ...DEFAULT_SUBTITLE_EXPORT, mode: 'burned', bilingual: false },
    audio: { ...DEFAULT_AUDIO_EXPORT, strategy: 'dubbed_only', bgmVolume: 1.0 },
    output: { ...DEFAULT_OUTPUT_NAMING, pattern: '{project}_{lang}_release' },
    quality: { ...DEFAULT_QUALITY_EXPORT, videoBitrate: '8M', crf: 23, preset: 'medium', compatibility: 'desktop' },
  },
  {
    id: 'builtin-review',
    name: '内部审校版', description: '软字幕 + 双语 + 保留原声，适合团队审校',
    isBuiltin: true,
    createdAt: '2025-01-01T00:00:00Z', updatedAt: '2025-01-01T00:00:00Z',
    video: { ...DEFAULT_VIDEO_EXPORT, container: 'mp4', videoCodec: 'libx264', reencode: false },
    subtitle: { ...DEFAULT_SUBTITLE_EXPORT, mode: 'soft', bilingual: true },
    audio: { ...DEFAULT_AUDIO_EXPORT, strategy: 'multi_track', preserveOriginal: true, bgmVolume: 0.8 },
    output: { ...DEFAULT_OUTPUT_NAMING, pattern: '{project}_{lang}_review' },
    quality: { ...DEFAULT_QUALITY_EXPORT, videoBitrate: '4M', crf: 26, preset: 'fast', compatibility: 'both' },
  },
  {
    id: 'builtin-preview',
    name: '低码率预览版', description: '720p + CRF 28 + 快速编码，适合快速预览分享',
    isBuiltin: true,
    createdAt: '2025-01-01T00:00:00Z', updatedAt: '2025-01-01T00:00:00Z',
    video: { ...DEFAULT_VIDEO_EXPORT, container: 'mp4', videoCodec: 'libx264', reencode: true, preserveResolution: false, targetWidth: 1280, targetHeight: 720 },
    subtitle: { ...DEFAULT_SUBTITLE_EXPORT, mode: 'burned', bilingual: false },
    audio: { ...DEFAULT_AUDIO_EXPORT, strategy: 'dubbed_only', bgmVolume: 1.0 },
    output: { ...DEFAULT_OUTPUT_NAMING, pattern: '{project}_{lang}_preview' },
    quality: { ...DEFAULT_QUALITY_EXPORT, videoBitrate: '2M', crf: 28, preset: 'ultrafast', compatibility: 'mobile' },
  },
]

// ── Config Parameter Types (v3.0 — 定稿 §11.3) ──────────────────────────────

/** Per-slot config override. Stored in IR event state as slot.config */
export interface SlotConfig {
  [key: string]: any
}

/** Resolved config for a single event slot */
export interface ResolvedConfig {
  eventId: string
  slot: string
  resolved: Record<string, any>
  inheritedFrom: 'event' | 'speaker' | 'global'
}

/** Config change request from Inspector Panel */
export interface ConfigChangeRequest {
  eventId: string
  slot: string
  field: string           // dot-separated nested path e.g. "gate.threshold_accept"
  value: any
  op: 'override' | 'set' | 'reset'
}

/** Batch config change */
export interface BatchConfigRequest {
  eventIds: string[]
  slot: string
  configBlock: Record<string, any>
}

/** Full config state for the Inspector Panel */
export interface InspectorConfigState {
  audio: SlotConfig
  asr: SlotConfig
  speaker: SlotConfig
  translation: SlotConfig
  tts: SlotConfig
  emotion: SlotConfig
  review: SlotConfig
  /** Which slots have event-level overrides (not inherited) */
  overriddenSlots: string[]
  /** Loading state per slot */
  loading: Record<string, boolean>
}

/** Default empty config state */
export const DEFAULT_INSPECTOR_CONFIG: InspectorConfigState = {
  audio: {},
  asr: {},
  speaker: {},
  translation: {},
  tts: {},
  emotion: {},
  review: {},
  overriddenSlots: [],
  loading: {},
}

/** Engine option params for TTS sub-engines */
export interface CosyVoiceEngineOptions {
  version: 'v2' | 'v3'
  lang: string
  speed: number
  num_norm: boolean
  fp16: boolean
}

export interface ChatTTSEngineOptions {
  speaker_seed: number
  temperature: number
  top_k: number
  top_p: number
  emotion_injection: boolean
}

export interface EdgeTTSEngineOptions {
  voice: string | null
  pitch: string
  volume: string
  timeout: number
}

/** Slot schema info for dynamic UI rendering */
export interface SlotSchemaInfo {
  title: string
  description: string
  properties: string[]
}

// ── Workspace Data Types (TRV-PLAN-2026-001 §8.1) ──────────────────────────────

/** Workspace manifest as read from project.json */
export interface WorkspaceManifest {
  version: number
  video_path: string
  video_duration?: number
  workflow_preset?: string
  passes?: string[]
  runtime_state?: string
  lang?: string
  target_lang?: string
  created_at: string
  updated_at: string
  pipeline: Record<string, 'completed' | 'running' | 'failed'>
  files: Record<string, string>
}

/** Workspace summary for the selector list */
export interface WorkspaceSummary {
  path: string
  name: string
  updatedAt: string
  runtimeState: string
  pipelineStatus: string
  videoPath: string
  videoName?: string
}

/** Data source mode */
export type DataSource = 'mock' | 'workspace'

// ── Workflow Preset + Runtime State (Phase 0-1) ──────────────────────────────

/** Workflow Preset — a named Pass DAG template for Timeline bootstrap */
export interface WorkflowPreset {
  id: string
  name: string
  nameEn: string
  description: string
  icon: string
  passes: string[]
  tags: string[]
  configDefaults: Record<string, unknown>
}

/** Workspace detail returned by GET /api/workspace/detail */
export interface WorkspaceDetail {
  path: string
  manifest: Record<string, unknown>
  runtimeState: string
  diskUsageBytes: number
  fileCount: number
  files: Array<{ name: string; relativePath: string; size: number }>
  failureReason: string
}

export interface AiSuggestRequest {
  event_id: string
  workspace: string
  source_text: string
  current_translation: string
  target_lang: string
}

export interface AiSuggestResponse {
  suggestion: string
  reasoning: string
  diff: { before: string; after: string }
}

