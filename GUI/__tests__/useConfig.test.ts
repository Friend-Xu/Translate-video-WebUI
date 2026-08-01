/**
 * 契约测试 — useConfig 差异层 (P1)
 *
 * 锁死结论:
 *   1. GET /api/config 返回 { config, defaults, overridden }, hook 必须解包 config
 *      子对象 (旧实现把整个响应展开, 嵌套 config 键混入)
 *   2. updateConfig 差异提交: 只发与基线不同的键, 基线已有的键不重复发
 *   3. 无差异不 POST (useConfig 不再全量覆盖 settings.json)
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useConfig } from '../hooks/useConfig'

function jsonResponse(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function mockFetchByUrl(handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  vi.stubGlobal('fetch', vi.fn((input: unknown, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : (input as Request).url
    return Promise.resolve(handler(url, init))
  }))
}

/** 冲洗 microtask 队列 (fetch promise 链) */
async function flush() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}

describe('useConfig (P1 差异层)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('mount 时解包 serverConfig.config, 不混入嵌套对象', async () => {
    mockFetchByUrl((url, init) => {
      if (url === '/api/system/info') return jsonResponse({ recommendedConcurrency: 4, hasGpu: true, defaultVideoDir: 'D:/v' })
      if (url === '/api/config' && (!init || init.method === 'GET')) {
        return jsonResponse({
          config: { tts_engine: 'edge' },
          defaults: { tts_engine: 'chattts' },
          overridden: ['tts_engine'],
        })
      }
      return jsonResponse({})
    })
    const { result } = renderHook(() => useConfig())
    await flush()
    expect(result.current.config).toMatchObject({ tts_engine: 'edge' })
    expect((result.current.config as any).config).toBeUndefined()
    expect((result.current.config as any).defaults).toBeUndefined()
  })

  it('updateConfig 差异提交: 只发与基线不同的键', async () => {
    const posts: any[] = []
    mockFetchByUrl((url, init) => {
      if (url === '/api/system/info') return jsonResponse({})
      if (url === '/api/config' && (!init || init.method === 'GET')) {
        return jsonResponse({ config: { tts_engine: 'edge' }, defaults: {}, overridden: [] })
      }
      if (init?.method === 'POST') {
        posts.push(JSON.parse(String(init.body)))
        return jsonResponse({ status: 'ok' })
      }
      return jsonResponse({})
    })
    const { result } = renderHook(() => useConfig())
    await flush()
    act(() => { result.current.updateConfig('engine', 'cosyvoice') })
    act(() => { vi.advanceTimersByTime(2100) })
    await flush()
    expect(posts).toHaveLength(1)
    expect(posts[0].config.engine).toBe('cosyvoice')
    // 基线已有的键不重复发
    expect(posts[0].config.tts_engine).toBeUndefined()
  })

  it('无差异不 POST', async () => {
    let postCount = 0
    mockFetchByUrl((url, init) => {
      if (url === '/api/system/info') return jsonResponse({})
      if (url === '/api/config' && (!init || init.method === 'GET')) {
        return jsonResponse({ config: { engine: 'edge' }, defaults: {}, overridden: [] })
      }
      if (init?.method === 'POST') { postCount++; return jsonResponse({ status: 'ok' }) }
      return jsonResponse({})
    })
    renderHook(() => useConfig())
    await flush()
    act(() => { vi.advanceTimersByTime(2100) })
    await flush()
    expect(postCount).toBe(0)
  })
})
