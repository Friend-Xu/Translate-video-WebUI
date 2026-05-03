export interface PipelineConfig {
  videoPath: string
  lang: 'auto' | 'en' | 'zh' | 'ja'
  model: 'small' | 'medium' | 'large'
  device: 'cpu' | 'gpu'
  computeType: 'int8' | 'float32'
  engine: 'edge' | 'chattts' | 'coqui' | 'azure'
  voice: string
  speechRate: number
  apiKey: string
  apiType: string
  maxTokens: number
  enableSemanticValidation: boolean
  enableTermReplacement: boolean
  enableAudioExtract: boolean
  enableSubtitleOverlay: boolean
  enableVideoMerge: boolean
  outputPath: string
  videoCodec: 'libx264' | 'h265'
  audioCodec: 'aac'
  enableEmotionClone: boolean
  emotionRefAudio: string
  defaultEmotion: string
  enableVoiceClone: boolean
  voiceCloneSample: string
  openvoiceVersion: 'v1' | 'v2'
  concurrency: number
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
  captionFontSize: number
  captionStrokeWidth: number
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

export const DEFAULT_CONFIG: PipelineConfig = {
  videoPath: '',
  lang: 'auto',
  model: 'small',
  device: 'cpu',
  computeType: 'int8',
  engine: 'edge',
  voice: 'zh-CN-XiaoxiaoNeural',
  speechRate: 40,
  apiKey: '',
  apiType: 'deepseek',
  maxTokens: 4000,
  enableSemanticValidation: true,
  enableTermReplacement: true,
  enableAudioExtract: true,
  enableSubtitleOverlay: true,
  enableVideoMerge: true,
  outputPath: '',
  videoCodec: 'libx264',
  audioCodec: 'aac',
  enableEmotionClone: false,
  emotionRefAudio: '',
  defaultEmotion: 'neutral',
  enableVoiceClone: false,
  voiceCloneSample: '',
  openvoiceVersion: 'v2',
  concurrency: 3,
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
  captionFontSize: 0,
  captionStrokeWidth: 0,
}

export interface SystemInfo {
  cpuCount: number
  hasGpu: boolean
  gpuName: string
  recommendedConcurrency: number
  defaultVideoDir: string
}

export interface VideoInfo {
  width: number
  height: number
  duration: number
  durationStr: string
}
