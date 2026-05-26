import { describe, it, expect } from 'vitest'
import { BUILTIN_EXPORT_PRESETS, DEFAULT_CONFIG, PIPELINE_STAGES } from '../types'

describe('BUILTIN_EXPORT_PRESETS', () => {
  it('contains 3 built-in presets', () => {
    expect(BUILTIN_EXPORT_PRESETS).toHaveLength(3)
  })

  it('all presets have unique ids', () => {
    const ids = BUILTIN_EXPORT_PRESETS.map(p => p.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('all builtins have isBuiltin = true', () => {
    BUILTIN_EXPORT_PRESETS.forEach(p => expect(p.isBuiltin).toBe(true))
  })

  it('all presets have required sub-configs and valid values', () => {
    BUILTIN_EXPORT_PRESETS.forEach(p => {
      expect(['mp4', 'mkv']).toContain(p.video.container)
      expect(['libx264', 'h265']).toContain(p.video.videoCodec)
      expect(['burned', 'soft', 'none', 'external']).toContain(p.subtitle.mode)
      expect(['dubbed_only', 'original_only', 'mixed', 'multi_track']).toContain(p.audio.strategy)
      expect(p.quality.crf).toBeGreaterThanOrEqual(0)
      expect(p.quality.crf).toBeLessThanOrEqual(51)
      expect(p.name).toBeTruthy()
    })
  })
})

describe('PIPELINE_STAGES', () => {
  it('has 9 stages with sequential orders 0-8', () => {
    expect(PIPELINE_STAGES).toHaveLength(9)
    const orders = PIPELINE_STAGES.map(s => s.order).sort((a, b) => a - b)
    expect(orders).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8])
  })

  it('has correct first and last stage', () => {
    expect(PIPELINE_STAGES[0].stage).toBe('media_analysis')
    expect(PIPELINE_STAGES[8].stage).toBe('package')
  })
})

describe('DEFAULT_CONFIG', () => {
  it('has expected defaults', () => {
    expect(DEFAULT_CONFIG.device).toBe('cuda')
    expect(DEFAULT_CONFIG.lang).toBe('auto')
    expect(DEFAULT_CONFIG.targetLang).toBe('zh-CN')
    expect(DEFAULT_CONFIG.model).toBe('turbo')
  })
})
