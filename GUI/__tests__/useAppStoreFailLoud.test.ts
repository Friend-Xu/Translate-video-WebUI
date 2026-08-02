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
import type { EventViewModel } from '../types'

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
  uiOps: [],
})

beforeEach(() => {
  resetStore()
  localStorage.clear()
})
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
      if (url.includes('/timeline/load')) {
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
      if (url.includes('/timeline/load')) {
        return jsonResponse({ inspector_data: {} })
      }
      return jsonResponse({})
    })

    await useAppStore.getState().loadWorkspace('test_ws')

    expect(useAppStore.getState().error).toContain('补丁历史')
  })

  it('loadWorkspace 事件源走 /api/timeline/load (P3-C: 主数据源不挂 speaker 端点)', async () => {
    const urls: string[] = []
    mockFetchByUrl((url) => {
      urls.push(url)
      if (url.includes('/project/manifest/resolve')) {
        return jsonResponse({ manifest: { video_path: 'x.mp4', pipeline: {} } })
      }
      if (url.includes('/timeline/load')) {
        return jsonResponse({ inspector_data: {} })
      }
      return okWorkspaceResponses()
    })

    await useAppStore.getState().loadWorkspace('test_ws')

    expect(urls.some(u => u.includes('/api/timeline/load'))).toBe(true)
    expect(urls.some(u => u.includes('/speaker/diarization/load'))).toBe(false)
    expect(useAppStore.getState().error).toBeNull()
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

describe('P3-D 局部刷新 (mutation 响应驱动, 借鉴时间轴编辑器本地状态模式)', () => {
  it('applyDraft 成功 → events 用响应快照更新, 不再全量 loadWorkspace', async () => {
    const urls: string[] = []
    mockFetchByUrl((url) => {
      urls.push(url)
      if (url.includes('/patch/apply')) {
        return jsonResponse({
          status: 'applied',
          events: {
            evt_001: { id: 'evt_001', start: 0.5, end: 3.0, text: '新原文', translation: '你好' },
          },
        })
      }
      return okWorkspaceResponses()
    })
    useAppStore.setState({ events: [{ id: 'evt_001', start: 1, end: 2 }] as any })
    useAppStore.getState().addDraft(draftFactory())

    const ok = await useAppStore.getState().applyDraft('evt_001')

    expect(ok).toBe(true)
    const events = useAppStore.getState().events
    expect(events).toHaveLength(1)
    expect(events[0].start).toBe(0.5)
    expect(events[0].translation).toBe('你好')
    // 局部刷新: 不再全量 loadWorkspace (无 /timeline/load 请求)
    expect(urls.some(u => u.includes('/api/timeline/load'))).toBe(false)
    // 只刷新随编辑变化的 review flags
    expect(urls.some(u => u.includes('/api/timeline/review/flags'))).toBe(true)
  })

  it('undoLastPatch 成功 → events 用响应快照更新', async () => {
    const urls: string[] = []
    mockFetchByUrl((url) => {
      urls.push(url)
      if (url.includes('/patch/undo')) {
        return jsonResponse({
          status: 'undone', patch_id: 'p1',
          events: {
            evt_001: { id: 'evt_001', start: 7.0, end: 8.0, text: '回滚后', translation: '' },
          },
        })
      }
      return jsonResponse({ patches: [], flags: [], speaker_lanes: [], voice_presets: [] })
    })
    useAppStore.setState({ appliedPatches: [{
      patch_id: 'p1', opcode: 'SET_TRANSLATION', targets: ['evt_001'],
      payload: {}, reason: [], score: 1, confidence: 1,
      parent_version: '', idempotency_key: '', author: 'user', timestamp: '',
    }] })

    const result = await useAppStore.getState().undoLastPatch()

    expect(result.ok).toBe(true)
    expect(useAppStore.getState().events[0].start).toBe(7.0)
    expect(urls.some(u => u.includes('/api/timeline/load'))).toBe(false)
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

describe('P3-E2 说话人 lane 随编辑本地同步 (拖拽后 UI 必须渲染)', () => {
  const evtFactory = (overrides: Record<string, unknown> = {}): EventViewModel => ({
    id: 'evt_001', start: 1, end: 2, speaker: 'S1', displayName: '说话人一',
    text: 'Hello', translation: '你好', source: '', confidence: 0.9,
    visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false },
    patches: [], passTrace: [], ...overrides,
  })
  const laneFactory = (overrides: Record<string, unknown> = {}) => ({
    speaker: 'S1', display_name: '说话人一', voice_id: 'v1', color: '#FF9800',
    segments: [{ id: 'evt_001', eventId: 'evt_001', start: 1, end: 2, text: 'Hello', translation: '你好', confidence: 0.9 }],
    segment_count: 1, total_duration: 1,
    ...overrides,
  })

  it('sync: 事件边界变化 → lane 段位置/统计更新 (拖拽 resize 的 UI 渲染路径)', () => {
    useAppStore.setState({ speakerLanes: [laneFactory()] })
    useAppStore.getState().syncSpeakerLanesFromEvents({
      evt_001: evtFactory({ start: 7.5, end: 9.0 }),
    })
    const lane = useAppStore.getState().speakerLanes[0]
    expect(lane.segments[0].start).toBe(7.5)
    expect(lane.segments[0].end).toBe(9.0)
    expect(lane.segment_count).toBe(1)
    expect(lane.total_duration).toBeCloseTo(1.5)
    // lane 元数据保留 (显示名/声线/颜色不丢)
    expect(lane.display_name).toBe('说话人一')
    expect(lane.voice_id).toBe('v1')
  })

  it('sync: speaker 归属变化的段移入目标 lane, 原 lane 移除', () => {
    useAppStore.setState({
      speakerLanes: [
        laneFactory(),
        laneFactory({ speaker: 'S2', display_name: '说话人二', segments: [] }),
      ],
    })
    useAppStore.getState().syncSpeakerLanesFromEvents({
      evt_001: evtFactory({ speaker: 'S2' }),
    })
    const lanes = useAppStore.getState().speakerLanes
    const s1 = lanes.find(l => l.speaker === 'S1')!
    const s2 = lanes.find(l => l.speaker === 'S2')!
    expect(s1.segments).toHaveLength(0)
    expect(s2.segments).toHaveLength(1)
    expect(s2.segments[0].eventId).toBe('evt_001')
  })

  it('sync: 快照缺失的段 (merge 删除) 从 lane 移除', () => {
    useAppStore.setState({
      speakerLanes: [
        laneFactory(),
        laneFactory({
          speaker: 'S2', display_name: '说话人二',
          segments: [{ id: 'evt_002', eventId: 'evt_002', start: 5, end: 6, text: 'bye', translation: '再见', confidence: 0.9 }],
        }),
      ],
    })
    useAppStore.getState().syncSpeakerLanesFromEvents({ evt_001: evtFactory() })
    const lanes = useAppStore.getState().speakerLanes
    expect(lanes.find(l => l.speaker === 'S1')!.segments).toHaveLength(1)
    expect(lanes.find(l => l.speaker === 'S2')!.segments).toHaveLength(0)
  })

  it('applyDraft 成功后 lanes 本地更新, 无额外 fetchSpeakerLanes 请求 (2 请求保持)', async () => {
    const urls: string[] = []
    mockFetchByUrl((url) => {
      urls.push(url)
      if (url.includes('/patch/apply')) {
        return jsonResponse({
          status: 'applied',
          events: { evt_001: evtFactory({ start: 0.5, end: 3.0 }) },
        })
      }
      return jsonResponse({ flags: [] })
    })
    useAppStore.setState({ speakerLanes: [laneFactory()] })
    useAppStore.getState().addDraft(draftFactory())

    const ok = await useAppStore.getState().applyDraft('evt_001')

    expect(ok).toBe(true)
    expect(useAppStore.getState().speakerLanes[0].segments[0].start).toBe(0.5)
    // 局部刷新不变: 1 apply + 1 flags, 不触发全量 diarization/load
    expect(urls.some(u => u.includes('/speaker/diarization/load'))).toBe(false)
    expect(urls.filter(u => u.includes('/patch/apply')).length).toBe(1)
  })
})

describe('P3-F 操作审计 ui_ops (调试量化, localStorage 零请求)', () => {
  const lastOp = () => {
    const ops = useAppStore.getState().uiOps
    return ops[ops.length - 1]
  }

  it('applyDraft 成功 → 记录 opcode/耗时/事件数 + localStorage 持久化', async () => {
    mockFetchByUrl((url) => {
      if (url.includes('/patch/apply')) {
        return jsonResponse({ status: 'applied', events: { evt_001: { id: 'evt_001', start: 0.5, end: 3.0 } } })
      }
      return jsonResponse({ flags: [] })
    })
    useAppStore.getState().addDraft(draftFactory())

    const ok = await useAppStore.getState().applyDraft('evt_001')

    expect(ok).toBe(true)
    const op = lastOp()
    expect(op.op).toBe('applyDraft')
    expect(op.ok).toBe(true)
    expect(op.opcode).toBe('SET_TRANSLATION')
    expect(op.eventId).toBe('evt_001')
    expect(op.ms).toBeGreaterThanOrEqual(0)
    expect(op.extra).toContain('1 events')
    const stored = JSON.parse(localStorage.getItem('ui_ops')!)
    expect(stored[stored.length - 1].op).toBe('applyDraft')
  })

  it('applyDraft 失败 → ok:false + error 记录 (失败路径可追溯)', async () => {
    mockFetchByUrl(() => jsonResponse({ detail: 'evt_001 冲突' }, 409))
    useAppStore.getState().addDraft(draftFactory())

    await useAppStore.getState().applyDraft('evt_001')

    const op = lastOp()
    expect(op.ok).toBe(false)
    expect(op.error).toContain('冲突')
    expect(op.opcode).toBe('SET_TRANSLATION')
  })

  it('undoLastPatch 成功 → 记录撤销与事件数', async () => {
    mockFetchByUrl((url) => {
      if (url.includes('/patch/undo')) {
        return jsonResponse({ status: 'undone', patch_id: 'p1', events: { evt_001: { id: 'evt_001', start: 7, end: 8 } } })
      }
      return jsonResponse({ patches: [], flags: [], speaker_lanes: [], voice_presets: [] })
    })
    useAppStore.setState({ appliedPatches: [{
      patch_id: 'p1', opcode: 'SET_TRANSLATION', targets: ['evt_001'],
      payload: {}, reason: [], score: 1, confidence: 1,
      parent_version: '', idempotency_key: '', author: 'user', timestamp: '',
    }] })

    const result = await useAppStore.getState().undoLastPatch()

    expect(result.ok).toBe(true)
    const op = lastOp()
    expect(op.op).toBe('undoLastPatch')
    expect(op.ok).toBe(true)
    expect(op.opcode).toBe('SET_TRANSLATION')
    expect(op.extra).toContain('1 events')
  })

  it('discardAllDrafts → 记录丢弃数量', () => {
    useAppStore.getState().addDraft(draftFactory())
    useAppStore.getState().addDraft(draftFactory({ eventId: 'evt_002' }))

    useAppStore.getState().discardAllDrafts()

    const op = lastOp()
    expect(op.op).toBe('discardAllDrafts')
    expect(op.ok).toBe(true)
    expect(op.extra).toContain('2')
  })

  it('loadWorkspace 部分失败 → ok:false + 失败原因 (首次加载耗时可量化)', async () => {
    mockFetchByUrl((url) => {
      if (url.includes('/project/manifest/resolve')) {
        return jsonResponse({ manifest: { video_path: 'x.mp4', pipeline: {} } })
      }
      if (url.includes('/timeline/load')) {
        return jsonResponse({ inspector_data: { evt_001: { id: 'evt_001', start: 0, end: 1 } } })
      }
      if (url.includes('/speaker/diarization/waveform')) {
        return jsonResponse({ detail: 'boom' }, 500)
      }
      return jsonResponse({ patches: [], flags: [] })
    })

    await useAppStore.getState().loadWorkspace('test_ws')

    const op = lastOp()
    expect(op.op).toBe('loadWorkspace')
    expect(op.ok).toBe(false)
    expect(op.error).toContain('波形')
    expect(op.extra).toContain('1 events')
  })

  it('ui_ops 环形上限 300 条 (内存不膨胀)', () => {
    for (let i = 0; i < 320; i++) {
      useAppStore.getState()._logOp('applyDraft', true, 1, '', '', 'X', 'e')
    }
    expect(useAppStore.getState().uiOps.length).toBe(300)
  })
})

describe('bindVoice 落盘 (P5)', () => {
  it('绑定声线 → 发 BIND_VOICE patch (UPDATE_SPEAKER 写注册表, 不再仅本地)', async () => {
    let sentPatch: any = null
    mockFetchByUrl((url, init) => {
      if (url.includes('/api/timeline/patch/apply')) {
        sentPatch = JSON.parse(String(init?.body))
        return jsonResponse({ status: 'applied', events: {} })
      }
      return jsonResponse({ flags: [] })
    })
    useAppStore.setState({
      speakerLanes: [{ speaker: 'SPK_A', display_name: 'A', voice_id: '', segments: [], segment_count: 0, total_duration: 0 }],
    })

    useAppStore.getState().bindVoice('SPK_A', 'voice_chattts_01')
    await new Promise(r => setTimeout(r, 10))

    expect(sentPatch).not.toBeNull()
    expect(sentPatch.patch.opcode).toBe('BIND_VOICE')
    expect(sentPatch.patch.payload.voice_id).toBe('voice_chattts_01')
    expect(sentPatch.patch.targets).toEqual(['SPK_A'])
    // 本地 lanes 即时反馈
    expect(useAppStore.getState().speakerLanes[0].voice_id).toBe('voice_chattts_01')
  })

  it('后端失败 → store.error 响亮 (绑定不假装成功)', async () => {
    mockFetchByUrl((url) => {
      if (url.includes('/api/timeline/patch/apply')) return jsonResponse({ detail: 'speaker 不存在' }, 422)
      return jsonResponse({ flags: [] })
    })
    useAppStore.setState({
      speakerLanes: [{ speaker: 'SPK_GHOST', display_name: 'G', voice_id: '', segments: [], segment_count: 0, total_duration: 0 }],
    })

    useAppStore.getState().bindVoice('SPK_GHOST', 'voice_x')
    await new Promise(r => setTimeout(r, 10))

    expect(useAppStore.getState().error).toContain('speaker 不存在')
  })
})
