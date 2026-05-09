export interface PipelineConfig {
  videoPath: string
  lang: 'auto' | 'en' | 'zh' | 'ja'
  targetLang: 'zh-CN' | 'en' | 'ja' | 'ko' | 'auto'
  model: 'tiny' | 'base' | 'small' | 'medium' | 'turbo' | 'large-v3'
  device: 'cpu' | 'cuda'
  computeType: 'int8' | 'float32' | 'float16' | 'int8_float16'
  engine: 'edge' | 'chattts' | 'coqui' | 'azure'
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
  enableTermReplacement: boolean
  enableAudioExtract: boolean
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
  splitBrainEnabled: boolean
  activeGlossary: string
  multiAgentEnabled: boolean
  mqmEnabled: boolean
  mqmThreshold: number
}

export interface PipelineStatus {
  state: 'idle' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  currentStep: string
  jobId: string | null
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
  enableTermReplacement: true,
  enableAudioExtract: true,
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
  splitBrainEnabled: false,
  activeGlossary: 'minecraft.json',
  multiAgentEnabled: false,
  mqmEnabled: false,
  mqmThreshold: 0.6,
}

export interface SubtitleIssue {
  type: 'low_similarity' | 'cps_high' | 'duration_short' | 'duration_long' | 'overlap' | 'empty'
  message: string
  severity: 'warning' | 'error'
}

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
}

export interface ReviewSession {
  videoPath: string
  sourceSrtPath: string
  translatedSrtPath: string
  entries: SubtitleEntry[]
  filterMode: 'all' | 'pending' | 'flagged'
}

export interface SystemInfo {
  cpuCount: number
  hasGpu: boolean
  gpuName: string
  gpuVramMb: number
  recommendedConcurrency: number
  defaultVideoDir: string
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
