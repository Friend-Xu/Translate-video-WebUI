/**
 * activityLog.ts — 会话级用户操作日志（event sourcing lite）
 *
 * 只记录改变状态的领域事件（编辑/绑定/应用补丁等），不记录 UI 噪声。
 * 机器日志在 LogsView 中通过 recordLog() 适配为同一 ActivityEntry 结构，
 * 统一时间线按 append 顺序渲染，actor 字段区分来源。
 */
import type { LogEntry } from './types'

export interface ActivityEntry {
  id: number
  ts: number
  actor: 'user' | 'system'
  kind: 'log' | 'action' | 'milestone'
  level: 'INFO' | 'WARN' | 'ERROR' | 'STAGE'
  /** 用户操作小词表: edited/applied/discarded/bound/created/opened/saved/rolled_back */
  verb?: string
  /** 操作对象, 如 "事件 #12"、"说话人 主讲人A" */
  target?: string
  /** 渲染文本（用户操作 = 语义化摘要, 机器日志 = 原始消息） */
  summary: string
  /** 机器日志模块名 (pipeline.video_merger: 中的前缀) */
  module?: string
  /** 数据来源: sse 实时 / 文件轮询 / 用户操作 */
  source: 'sse' | 'file' | 'user'
}

const MAX_ENTRIES = 1000
let _nextId = 1
let entries: ActivityEntry[] = []
const listeners = new Set<() => void>()

export function recordActivity(entry: Omit<ActivityEntry, 'id' | 'ts'>): ActivityEntry {
  const full: ActivityEntry = { id: _nextId++, ts: Date.now(), ...entry }
  entries.push(full)
  if (entries.length > MAX_ENTRIES) entries.splice(0, entries.length - MAX_ENTRIES)
  listeners.forEach(fn => fn())
  return full
}

/** 把机器日志行适配为时间线条目 — LogsView 注入实时/文件日志时使用 */
export function recordLog(entry: LogEntry, source: 'sse' | 'file' = 'sse'): void {
  const m = entry.message.match(/^([\w.]+):\s*(.*)$/s)
  recordActivity({
    actor: 'system',
    kind: entry.level === 'STAGE' ? 'milestone' : 'log',
    level: entry.level,
    summary: m ? m[2] : entry.message,
    module: m?.[1],
    source,
  })
}

/** 用户领域事件 — 在 store action 层调用 */
export function recordUserAction(
  verb: string,
  target: string | undefined,
  summary: string,
  outcome: 'ok' | 'failed' = 'ok',
): void {
  recordActivity({
    actor: 'user',
    kind: 'action',
    level: outcome === 'failed' ? 'ERROR' : 'INFO',
    verb,
    target,
    summary,
    source: 'user',
  })
}

export function subscribeActivity(fn: () => void): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function getActivity(): ActivityEntry[] {
  return entries
}

/** 移除指定来源的条目（如切工作区后清空文件轮询日志）— 用户操作永不清理 */
export function clearActivitySource(source: 'sse' | 'file' | 'user'): void {
  if (source === 'user') return
  const before = entries.length
  entries = entries.filter(e => e.source !== source)
  if (entries.length !== before) listeners.forEach(fn => fn())
}
