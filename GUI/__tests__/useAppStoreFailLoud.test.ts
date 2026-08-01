/**
 * 契约测试 — 前端吞错修复 (P1, 禁止兜底)
 *
 * 锁死结论:
 *   1. applyDraft/undoLastPatch 后端失败 → 设置 store.error + 保留本地状态,
 *      绝不"本地照常记录" (旧行为: 刷新后编辑静默丢失)
 *   2. applyAllDrafts 部分失败 → 失败草案保留供重试, 成功草案移除
 *   3. fetchSpeakerLanes 失败 → 清空 lanes + 响亮报错, 绝不回退 mock 假数据
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { useAppStore } from '../store/useAppStore'
import type { PatchDraft } from '../types/modes'

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function mockFetchByUrl(handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  vi.stubGlobal('fetch', vi.fn((input: unknown, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : (input as Request).url
    return Promise.resolve(handler(url, init))
  }))
}

/** 成功的 loadWorkspace 响应面 (apply 成功后的 reload 需要全部端点) */
function okWorkspaceResponses(): Response {
  const body = {
    manifest: { video_path: 'x.mp4', pipeline: {} },
    inspector_data: {},
    speaker_lanes: [],
    voice_presets: [],
    // patch log 模拟后端已持久化刚应用的补丁 (reload 会用它覆盖 appliedPatches)
    patches: [{
      patch_id: 'p1', opcode: 'SET_TRANSLATION', targets: ['evt_001'],
      payload: {}, reason: [], score: 1, confidence: 1,
      parent_version: '', idempotency_key: '', author: 'user', timestamp: '',
    }],
    flags: [],
  }
  return jsonResponse(body)
}

const draftFactory = (overrides = {}): PatchDraft => ({
  eventId: 'evt_001', opcode: 'SET_TRANSLATION',
  payload: { translation: '你好' },
  before: { translation: 'Hello' },
  after: { translation: '你好' },
  timestamp: Date.now(),
  ...overrides,
})

const resetStore = () => useAppStore.setState({
  workspace: 'test_ws',
  pendingDrafts: new Map(),
  appliedPatches: [],
  speakerLanes: [],
  voicePresets: [],
  error: null,
  events: [],
  reviewEntries: [],
  reviewTranslatedSrtPath: '',
})

beforeEach(resetStore)
afterEach(() => vi.unstubAllGlobals())

describe('applyDraft 失败必须响亮 (禁止兜底)', () => {
  it('网络失败 → error 设置、draft 保留、不进 appliedPatches、返回 false', async () => {
    mockFetchByUrl(() => { throw new TypeError('fetch failed') })
    useAppStore.getState().addDraft(draftFactory())

    const ok = await useAppStore.getState().applyDraft('evt_001')

    expect(ok).toBe(false)
    expect(useAppStore.getState().error).toContain('补丁应用失败')
    expect(useAppStore.getState().pendingDrafts.has('evt_001')).toBe(true)
    expect(useAppStore.getState().appliedPatches).toHaveLength(0)
  })

  it('HTTP 422 → 错误含后端 detail、draft 保留 (旧行为: 静默记为已应用)', async () => {
    mockFetchByUrl(() => jsonResponse({ detail: '不支持的 opcode' }, 422))
    useAppStore.getState().addDraft(draftFactory())

    const ok = await useAppStore.getState().applyDraft('evt_001')

    expect(ok).toBe(false)
    expect(useAppStore.getState().error).toContain('不支持的 opcode')
    expect(useAppStore.getState().pendingDrafts.has('evt_001')).toBe(true)
    expect(useAppStore.getState().appliedPatches).toHaveLength(0)
  })

  it('成功 → draft 删除、记录 appliedPatches、返回 true', async () => {
    mockFetchByUrl((url) => {
      if (url.includes('/patch/apply')) return jsonResponse({ status: 'applied' })
      return okWorkspaceResponses()
    })
    useAppStore.getState().addDraft(draftFactory())

    const ok = await useAppStore.getState().applyDraft('evt_001')

    expect(ok).toBe(true)
    expect(useAppStore.getState().pendingDrafts.size).toBe(0)
    expect(useAppStore.getState().appliedPatches).toHaveLength(1)
    expect(useAppStore.getState().appliedPatches[0].opcode).toBe('SET_TRANSLATION')
  })
})

describe('applyAllDrafts 部分失败 (禁止兜底)', () => {
  it('部分失败 → 失败草案保留、成功草案移除、error 含失败数', async () => {
    mockFetchByUrl((url, init) => {
      if (!url.includes('/patch/apply')) return okWorkspaceResponses()
      const body = JSON.parse(String((init as RequestInit).body))
      // evt_002 失败 (对应 RETAG_SPEAKER 之外的 opcode 无意义, 用 payload 标记)
      return body.patch.targets[0] === 'evt_002'
        ? jsonResponse({ detail: 'evt_002 冲突' }, 409)
        : jsonResponse({ status: 'applied' })
    })
    useAppStore.getState().addDraft(draftFactory())
    useAppStore.getState().addDraft(draftFactory({ eventId: 'evt_002', opcode: 'RETAG_SPEAKER' }))

    const okCount = await useAppStore.getState().applyAllDrafts()

    expect(okCount).toBe(1)
    expect(useAppStore.getState().pendingDrafts.has('evt_001')).toBe(false)
    expect(useAppStore.getState().pendingDrafts.has('evt_002')).toBe(true)
    expect(useAppStore.getState().appliedPatches).toHaveLength(1)
    expect(useAppStore.getState().error).toContain('批量应用失败 1/2')
  })

  it('全部失败 → 全部保留、无 appliedPatches', async () => {
    mockFetchByUrl(() => jsonResponse({ detail: 'x' }, 500))
    useAppStore.getState().addDraft(draftFactory())
    useAppStore.getState().addDraft(draftFactory({ eventId: 'evt_002' }))

    const okCount = await useAppStore.getState().applyAllDrafts()

    expect(okCount).toBe(0)
    expect(useAppStore.getState().pendingDrafts.size).toBe(2)
    expect(useAppStore.getState().appliedPatches).toHaveLength(0)
  })
})

describe('undoLastPatch 失败必须响亮 (禁止兜底)', () => {
  it('后端失败 → appliedPatches 保留、error 设置、{ok:false}', async () => {
    mockFetchByUrl(() => jsonResponse({ detail: 'undo 失败' }, 409))
    useAppStore.getState().addDraft(draftFactory())
    useAppStore.setState({ appliedPatches: [{
      patch_id: 'p1', opcode: 'SET_TRANSLATION', targets: ['evt_001'],
      payload: {}, reason: [], score: 1, confidence: 1,
      parent_version: '', idempotency_key: '', author: 'user', timestamp: '',
    }] })

    const result = await useAppStore.getState().undoLastPatch()

    expect(result.ok).toBe(false)
    expect(useAppStore.getState().error).toContain('撤销失败')
    expect(useAppStore.getState().appliedPatches).toHaveLength(1)
  })

  it('成功 → appliedPatches 减少、{ok:true}', async () => {
    mockFetchByUrl((url) => {
      if (url.includes('/patch/undo')) return jsonResponse({ status: 'ok' })
      return jsonResponse({ patches: [], flags: [], speaker_lanes: [], voice_presets: [] })
    })
    useAppStore.setState({ appliedPatches: [{
      patch_id: 'p1', opcode: 'SET_TRANSLATION', targets: ['evt_001'],
      payload: {}, reason: [], score: 1, confidence: 1,
      parent_version: '', idempotency_key: '', author: 'user', timestamp: '',
    }] })

    const result = await useAppStore.getState().undoLastPatch()

    expect(result.ok).toBe(true)
    expect(result.patch?.patch_id).toBe('p1')
    expect(useAppStore.getState().appliedPatches).toHaveLength(0)
  })
})

describe('fetchSpeakerLanes 禁止 mock 降级', () => {
  it('失败 → lanes 清空 + error 设置 (旧行为: 静默回退 mock 假数据)', async () => {
    mockFetchByUrl(() => jsonResponse({ detail: 'no such workspace' }, 404))
    useAppStore.setState({ speakerLanes: [{ speaker: 'S1', display_name: 'A', voice_id: '', color: '#fff', segments: [], segment_count: 0, total_duration: 0 }] })

    await useAppStore.getState().fetchSpeakerLanes('test_ws')

    expect(useAppStore.getState().speakerLanes).toHaveLength(0)
    expect(useAppStore.getState().voicePresets).toHaveLength(0)
    expect(useAppStore.getState().error).toContain('说话人数据加载失败')
  })
})

describe('P3-B 残留静默失败响亮化', () => {
  it('fetchPatchLog 失败 → error 设置 (旧行为: 静默返回, 历史显示为空)', async () => {
    mockFetchByUrl(() => { throw new TypeError('fetch failed') })
    useAppStore.setState({ appliedPatches: [{
      patch_id: 'p1', opcode: 'SET_TRANSLATION', targets: ['evt_001'],
      payload: {}, reason: [], score: 1, confidence: 1,
      parent_version: '', idempotency_key: '', author: 'user', timestamp: '',
    }] })

    await useAppStore.getState().fetchPatchLog()

    expect(useAppStore.getState().error).toContain('补丁历史加载失败')
    expect(useAppStore.getState().appliedPatches).toHaveLength(1)
  })

  it('loadWorkspace 部分数据失败 → 成功态后设置 error (波形 500)', async () => {
    mockFetchByUrl((url) => {
      if (url.includes('/project/manifest/resolve')) {
        return jsonResponse({ manifest: { video_path: 'x.mp4', pipeline: {} } })
      }
      if (url.includes('/speaker/diarization/load')) {
        return jsonResponse({ inspector_data: {} })
      }
      if (url.includes('/speaker/diarization/waveform')) {
        return jsonResponse({ detail: 'boom' }, 500)
      }
      if (url.includes('/timeline/patch/log')) return jsonResponse({ patches: [] })
      if (url.includes('/timeline/review/flags')) return jsonResponse({ flags: [] })
      return jsonResponse({})
    })

    await useAppStore.getState().loadWorkspace('test_ws')

    expect(useAppStore.getState().error).toContain('部分数据加载失败')
    expect(useAppStore.getState().error).toContain('波形')
    expect(useAppStore.getState().workspace).toBe('test_ws')
  })

  it('loadWorkspace 补丁历史失败 → error 含 补丁历史', async () => {
    mockFetchByUrl((url) => {
      if (url.includes('/timeline/patch/log')) {
        return jsonResponse({ detail: 'no chain' }, 404)
      }
      if (url.includes('/project/manifest/resolve')) {
        return jsonResponse({ manifest: { video_path: 'x.mp4', pipeline: {} } })
      }
      if (url.includes('/speaker/diarization/load')) {
        return jsonResponse({ inspector_data: {} })
      }
      return jsonResponse({})
    })

    await useAppStore.getState().loadWorkspace('test_ws')

    expect(useAppStore.getState().error).toContain('补丁历史')
  })

  it('reloadEvents 失败 → error 设置 (旧行为: 静默, 用户看到旧数据)', async () => {
    mockFetchByUrl(() => jsonResponse({ detail: 'boom' }, 500))

    await useAppStore.getState().reloadEvents()

    expect(useAppStore.getState().error).toContain('事件刷新失败')
  })

  it('loadReviewEntries 失败 → error 设置, 不本地合成条目 (旧行为: events 兜底假数据)', async () => {
    mockFetchByUrl(() => jsonResponse({ detail: 'no srt' }, 404))
    useAppStore.setState({ events: [{ id: 'evt_001', start: 0, end: 1 }] as any })

    await useAppStore.getState().loadReviewEntries('test_ws')

    expect(useAppStore.getState().error).toContain('评审条目加载失败')
    expect(useAppStore.getState().reviewEntries).toHaveLength(0)
  })

  it('fetchWorkspaceList 失败 → error 设置 (旧行为: 静默, 列表显示为空)', async () => {
    mockFetchByUrl(() => { throw new TypeError('fetch failed') })

    await useAppStore.getState().fetchWorkspaceList()

    expect(useAppStore.getState().error).toContain('工作区列表加载失败')
  })
})

describe('saveReviewEntries 事件关联 (entry_N 修复)', () => {
  const entryFactory = (overrides = {}) => ({
    index: 1, start: '00:00:00,730', end: '00:00:02,490',
    startMs: 730, endMs: 2490, sourceText: 'こんにちは', translatedText: '修改后译文',
    reviewStatus: 'modified' as const, issues: [], eventId: 'evt_001',
    ...overrides,
  })
  const eventFactory = (overrides = {}) => ({
    id: 'evt_007', start: 7.0, end: 8.0, speaker: null, displayName: '', text: '',
    translation: '', source: '', confidence: 1,
    visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false },
    patches: [], passTrace: [], ...overrides,
  })

  function mockReviewSaveFlow(applyBodies: unknown[]) {
    mockFetchByUrl((url, init) => {
      if (url.includes('/subtitle/review/save')) {
        return jsonResponse({ ok: true, output_path: 'reviewed.srt', updated: 1 })
      }
      if (url.includes('/patch/apply')) {
        applyBodies.push(JSON.parse(String((init as RequestInit).body)))
        return jsonResponse({ status: 'applied' })
      }
      return okWorkspaceResponses()
    })
  }

  it('entry 带 eventId → 保存成功, 状态转 approved, patch target 用真实 id', async () => {
    const applyBodies: unknown[] = []
    mockReviewSaveFlow(applyBodies)
    useAppStore.setState({
      reviewTranslatedSrtPath: '02_translate/machine.srt',
      reviewEntries: [entryFactory()],
    })

    await useAppStore.getState().saveReviewEntries()

    expect(useAppStore.getState().reviewEntries[0].reviewStatus).toBe('approved')
    const body = applyBodies[0] as { patch: { targets: string[] } }
    expect(body.patch.targets[0]).toBe('evt_001')
  })

  it('entry 无 eventId → 按开始时间匹配 store events 兜底', async () => {
    const applyBodies: unknown[] = []
    mockReviewSaveFlow(applyBodies)
    useAppStore.setState({
      events: [eventFactory()],
      reviewTranslatedSrtPath: '02_translate/machine.srt',
      reviewEntries: [entryFactory({ startMs: 7000, endMs: 8000, eventId: undefined })],
    })

    await useAppStore.getState().saveReviewEntries()

    const body = applyBodies[0] as { patch: { targets: string[] } }
    expect(body.patch.targets[0]).toBe('evt_007')
  })

  it('无 eventId 且无匹配 → 响亮抛错, 零写入 (SRT 未保存)', async () => {
    const fetches: string[] = []
    vi.stubGlobal('fetch', vi.fn((input: unknown) => {
      fetches.push(String(input))
      return Promise.resolve(jsonResponse({ ok: true }))
    }))
    useAppStore.setState({
      events: [],
      reviewTranslatedSrtPath: '02_translate/machine.srt',
      reviewEntries: [entryFactory({ startMs: 999999, eventId: undefined })],
    })

    await expect(useAppStore.getState().saveReviewEntries()).rejects.toThrow('无法关联 timeline 事件')
    expect(fetches).toHaveLength(0)
  })
})
