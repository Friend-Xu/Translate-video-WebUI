/**
 * mockHandlers.ts — 开发环境 API Mock 层
 *
 * 对尚未实现的后端接口提供函数级 mock，
 * 在 `import.meta.env.DEV` 下自动启用，生产构建时移除。
 */
import type { PatchApplyResponse, PatchGenerateResponse, PatchLogResponse } from '../types'
import type { VoiceCard } from '../types/modes'
import { MOCK_AI_PATCHES } from './mockData'

const DEV = typeof window !== 'undefined' && window.location.hostname === 'localhost'

// ── 局部重算 ──

export interface LocalRecalcRequest {
  eventId: string
  type: 'realign' | 'retranslate' | 'resynthesize'
}

export interface LocalRecalcResponse {
  jobId: string
  eventId: string
  status: 'started'
}

const mockRecalcJobs: Record<string, { progress: number }> = {}

export async function requestLocalRecalc(req: LocalRecalcRequest): Promise<LocalRecalcResponse> {
  if (!DEV) throw new Error('Mock not available in production')
  await _delay(300)
  const jobId = `local_${req.eventId}_${Date.now()}`
  mockRecalcJobs[jobId] = { progress: 0 }
  return { jobId, eventId: req.eventId, status: 'started' }
}

export async function pollRecalcJob(jobId: string): Promise<{ status: string; progress: number }> {
  if (!DEV) throw new Error('Mock not available in production')
  await _delay(100)
  const job = mockRecalcJobs[jobId]
  if (!job) return { status: 'completed', progress: 100 }
  job.progress = Math.min(100, job.progress + 25)
  return { status: job.progress >= 100 ? 'completed' : 'running', progress: job.progress }
}

// ── Patch Apply ──

export async function mockApplyPatch(patchId: string): Promise<PatchApplyResponse> {
  if (!DEV) throw new Error('Mock not available in production')
  await _delay(200)
  return { status: 'applied', patch_id: patchId, diff: {} }
}

export async function mockUndoPatch(): Promise<{ status: string; patch_id?: string }> {
  if (!DEV) throw new Error('Mock not available in production')
  await _delay(200)
  return { status: 'undone', patch_id: 'last_patch' }
}

export async function mockGeneratePatches(): Promise<PatchGenerateResponse> {
  if (!DEV) throw new Error('Mock not available in production')
  await _delay(500)
  return {
    patches: MOCK_AI_PATCHES,
    high: [MOCK_AI_PATCHES[0]],
    medium: [MOCK_AI_PATCHES[1]],
    low: [MOCK_AI_PATCHES[2]],
  }
}

export async function mockGetPatchLog(): Promise<PatchLogResponse> {
  if (!DEV) throw new Error('Mock not available in production')
  return { patches: MOCK_AI_PATCHES, count: MOCK_AI_PATCHES.length }
}

// ── Voice / Speaker ──

const MOCK_VOICES: VoiceCard[] = [
  { id: 'vc_001', name: '晓晓 (女声)', language: 'zh-CN', sampleText: '你好，欢迎使用语音合成系统。', engine: 'edge', locked: false },
  { id: 'vc_002', name: '云希 (男声)', language: 'zh-CN', sampleText: '这是来自微软的边缘语音合成。', engine: 'edge', locked: false },
  { id: 'vc_003', name: 'Jenny (Female)', language: 'en-US', sampleText: 'Hello, this is a natural sounding voice.', engine: 'edge', locked: true },
  { id: 'vc_004', name: 'ChatTTS Seed 2', language: 'zh-CN', sampleText: '这是ChatTTS生成的语音样本。', engine: 'chattts', locked: false },
  { id: 'vc_005', name: 'CosyVoice v2 Default', language: 'zh-CN', sampleText: '这是CosyVoice跨语言合成。', engine: 'cosyvoice', locked: true },
]

export async function mockGetVoices(language?: string): Promise<VoiceCard[]> {
  if (!DEV) throw new Error('Mock not available in production')
  await _delay(150)
  if (language) return MOCK_VOICES.filter(v => v.language === language)
  return [...MOCK_VOICES]
}

export async function mockLockVoice(voiceId: string, locked: boolean): Promise<VoiceCard> {
  if (!DEV) throw new Error('Mock not available in production')
  await _delay(100)
  const voice = MOCK_VOICES.find(v => v.id === voiceId)
  if (!voice) throw new Error('Voice not found')
  return { ...voice, locked }
}

export async function mockPreviewVoice(voiceId: string): Promise<{ audioUrl: string }> {
  if (!DEV) throw new Error('Mock not available in production')
  await _delay(300)
  return { audioUrl: `mock://voice_preview/${voiceId}` }
}

// ── 系统状态 ──

export async function mockSystemStatus(): Promise<{
  cpuUsage: number
  memUsage: number
  gpuUsage: number | null
  modelsOnline: string[]
}> {
  if (!DEV) throw new Error('Mock not available in production')
  await _delay(50)
  return {
    cpuUsage: 35 + Math.random() * 20,
    memUsage: 60 + Math.random() * 15,
    gpuUsage: 45 + Math.random() * 30,
    modelsOnline: ['faster-whisper-turbo', 'silero-vad', 'chattts'],
  }
}

// ── 辅助 ──

function _delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

export const MOCK_API_ENABLED = DEV
