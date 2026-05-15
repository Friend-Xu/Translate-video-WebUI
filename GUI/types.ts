export interface PipelineConfig {
  videoPath: string
  lang: 'auto' | 'en' | 'zh' | 'ja'
  targetLang: 'zh-CN' | 'en' | 'ja' | 'ko' | 'auto'
  model: 'tiny' | 'base' | 'small' | 'medium' | 'turbo' | 'large-v3'
  device: 'cpu' | 'cuda'
  computeType: 'int8' | 'float32' | 'float16' | 'int8_float16'
  engine: 'edge' | 'chattts' | 'cosyvoice'
  chatttsSpeakerSeed: number | null
  chatttsSpeakerPt: string
  chatttsModelSource: 'local' | 'custom'
  chatttsModelPath: string
  chatttsPreviewAudio: string
  chatttsPreviewSeed: number | null
  chatttsSpkEmb: string
  cosyvoiceTtsModelVersion: 'v2' | 'v3'
  cosyvoiceTtsModelPath: string
  cosyvoiceTtsPromptAudio: string
  cosyvoiceTtsPromptText: string
  cosyvoiceTtsFp16: boolean
  cosyvoiceTtsWorkers: number
  cosyvoiceTtsSpeed: number
  cosyvoiceTtsMode: 'auto' | 'zero_shot' | 'cross_lingual'
  cosyvoiceTtsLang: string
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
}

export interface PipelineStatus {
  state: 'idle' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  currentStep: string
  jobId: string | null
  detail: string
}

export interface LogEntry {
  level: 'INFO' | 'WARN' | 'ERROR'
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
  cosyvoiceTtsModelVersion: 'v2',
  cosyvoiceTtsModelPath: '',
  cosyvoiceTtsPromptAudio: '',
  cosyvoiceTtsPromptText: '',
  cosyvoiceTtsFp16: true,
  cosyvoiceTtsWorkers: 0,
  cosyvoiceTtsSpeed: 1.0,
  cosyvoiceTtsMode: 'auto',
  cosyvoiceTtsLang: '',
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
  reviewStatus: 'pending' | 'approved' | 'modified'
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
}

export interface ReviewSession {
  videoPath: string
  sourceSrtPath: string
  translatedSrtPath: string
  entries: SubtitleEntry[]
  filterMode: 'all' | 'pending' | 'flagged' | 'semantic' | 'review_critical'
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
