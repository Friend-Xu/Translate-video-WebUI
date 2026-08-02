/**
 * LogsView — 控制台式日志视图 (P5-B + Console 升级)
 *
 * 统一时间线: 机器日志 (SSE 实时 / 文件轮询兜底) + 用户操作 (会话级埋点) 混排。
 * 信息量优化: 虚拟化 + 级别/来源过滤 + 文本搜索 + 重复行折叠 [xN] + 跟随控制。
 */
import { useState, useCallback, useEffect, useRef, useMemo } from 'react'
import { Box, Typography, Button, IconButton, Tooltip, TextField, Chip, Stack, InputAdornment } from '@mui/material'
import RefreshIcon from '@mui/icons-material/RefreshRounded'
import SearchIcon from '@mui/icons-material/SearchRounded'
import PersonIcon from '@mui/icons-material/PersonRounded'
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDownRounded'
import { Virtuoso, VirtuosoHandle } from 'react-virtuoso'
import { useAppStore } from '../../store/useAppStore'
import { subscribeActivity, recordLog, clearActivitySource, getActivity, type ActivityEntry } from '../../activityLog'
import type { LogEntry } from '../../types'
import type { ConnectionState } from '../../hooks/useSSE'

interface Props {
  logs?: LogEntry[]
  connectionState?: ConnectionState
}

const LEVELS = ['ALL', 'INFO', 'WARN', 'ERROR', 'STAGE'] as const
type LevelFilter = typeof LEVELS[number]

const levelColor: Record<string, string> = {
  INFO: '#c9d1d9',
  WARN: '#d29922',
  ERROR: '#f85149',
  STAGE: '#58a6ff',
}

const levelLabel: Record<string, string> = {
  ALL: '全部', INFO: 'INFO', WARN: 'WARN', ERROR: 'ERROR', STAGE: 'STAGE',
}

const VERB_LABEL: Record<string, string> = {
  edited: '编辑', applied: '应用补丁', discarded: '丢弃草案', bound: '绑定声线',
  unbound: '解绑声线', created: '创建', opened: '打开项目', saved: '保存',
  rolled_back: '回滚',
}

function fmtTime(ts: number): string {
  const d = new Date(ts)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

function parseFileLevel(raw: string): LogEntry['level'] {
  if (raw.includes('[ERROR]') || raw.includes(' ERROR ')) return 'ERROR'
  if (raw.includes('[WARN]') || raw.includes(' WARN ')) return 'WARN'
  if (raw.includes('[STAGE]')) return 'STAGE'
  return 'INFO'
}

const MAX_ENTRIES = 1500

export default function LogsView({ logs = [], connectionState = 'closed' }: Props) {
  const workspace = useAppStore(s => s.workspace)
  const [entries, setEntries] = useState<ActivityEntry[]>(() => getActivity())
  const [filter, setFilter] = useState<LevelFilter>('ALL')
  const [sourceFilter, setSourceFilter] = useState<'all' | 'user' | 'system'>('all')
  const [search, setSearch] = useState('')
  const [autoFollow, setAutoFollow] = useState(true)
  const [isAtBottom, setIsAtBottom] = useState(true)
  const virtuosoRef = useRef<VirtuosoHandle>(null)

  // live 日志去重游标 (LogEntry._id 单调递增)
  const lastLiveId = useRef(0)
  const fileCursor = useRef<string>('')
  const fileTimer = useRef<ReturnType<typeof setInterval> | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  const isLive = logs.length > 0

  // Ctrl+F 聚焦搜索
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f'
        && !searchRef.current?.contains(document.activeElement)) {
        e.preventDefault()
        searchRef.current?.focus()
        searchRef.current?.select()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // 订阅活动日志 (用户操作 + recordLog 注入的机器日志)
  useEffect(() => {
    const unsub = subscribeActivity(() => {
      setEntries(() => {
        const next = getActivity()
        return next.length > MAX_ENTRIES ? next.slice(next.length - MAX_ENTRIES) : next
      })
    })
    return unsub
  }, [])

  // SSE 实时日志增量注入 — 只处理 _id 大于游标的新条目
  useEffect(() => {
    for (const entry of logs) {
      const id = entry._id ?? 0
      if (id <= lastLiveId.current) continue
      lastLiveId.current = id
      recordLog(entry, 'sse')
    }
  }, [logs])

  // 文件轮询兜底 — 仅在无 live 日志时启用
  const loadFile = useCallback(async () => {
    try {
      const params = new URLSearchParams()
      if (workspace) params.set('workspace', workspace)
      const res = await fetch(`/api/logs/recent?${params}`)
      if (!res.ok) return
      const data = await res.json()
      const lines: string[] = data.lines || []
      if (lines.length === 0) return
      const toLog = (l: string) => recordLog({ level: parseFileLevel(l), message: l, timestamp: '' }, 'file')
      if (!fileCursor.current) {
        lines.forEach(toLog)
      } else {
        const idx = lines.indexOf(fileCursor.current)
        if (idx >= 0) {
          lines.slice(idx + 1).forEach(toLog)
        } else {
          // 游标滚出窗口 → 全量替换文件条目 (用户操作保留)
          clearActivitySource('file')
          lines.forEach(toLog)
        }
      }
      fileCursor.current = lines[lines.length - 1]
    } catch { /* 服务未启动时保持旧内容 */ }
  }, [workspace])

  useEffect(() => {
    if (isLive) return
    clearActivitySource('file')
    fileCursor.current = ''
    loadFile()
    fileTimer.current = setInterval(loadFile, 5000)
    return () => {
      if (fileTimer.current) clearInterval(fileTimer.current)
    }
  }, [isLive, loadFile])

  // 切工作区: 清空文件日志, 保持用户操作 (会话级审计)
  useEffect(() => {
    clearActivitySource('file')
    fileCursor.current = ''
    lastLiveId.current = 0
  }, [workspace])

  // 过滤 + 连续重复折叠 (信息量优化)
  const viewItems = useMemo(() => {
    let list = entries
    if (sourceFilter !== 'all') list = list.filter(e => e.actor === sourceFilter)
    if (filter !== 'ALL') list = list.filter(e => e.level === filter)
    const q = search.trim().toLowerCase()
    if (q) {
      list = list.filter(e =>
        e.summary.toLowerCase().includes(q)
        || (e.module || '').toLowerCase().includes(q)
        || (e.target || '').toLowerCase().includes(q)
      )
    }
    const out: { entry: ActivityEntry; count: number }[] = []
    for (const e of list) {
      const last = out[out.length - 1]
      if (last && last.entry.actor === 'system' && e.actor === 'system'
        && last.entry.summary === e.summary && last.entry.level === e.level) {
        last.count++
      } else {
        out.push({ entry: e, count: 1 })
      }
    }
    return out
  }, [entries, filter, sourceFilter, search])

  const handleBackToBottom = useCallback(() => {
    virtuosoRef.current?.scrollToIndex({ index: 'LAST', behavior: 'smooth' })
  }, [])

  const itemContent = useCallback((_index: number, item: { entry: ActivityEntry; count: number }) => {
    const e = item.entry
    const isUser = e.source === 'user'
    return (
      <Box sx={{
        display: 'flex', alignItems: 'baseline', gap: 0.75,
        px: 0.5, py: 0.15, lineHeight: 1.7,
        bgcolor: isUser ? 'rgba(99,102,241,0.06)' : 'transparent',
        borderLeft: isUser ? '2px solid #6366f1' : e.level === 'STAGE' ? '2px solid #58a6ff' : '2px solid transparent',
        borderRadius: '0 4px 4px 0',
        my: isUser ? 0.3 : 0,
      }}>
        <Typography component="span" sx={{
          fontSize: '0.62rem', color: 'text.disabled', flexShrink: 0,
          fontVariantNumeric: 'tabular-nums', userSelect: 'none',
        }}>
          {fmtTime(e.ts)}
        </Typography>
        {isUser ? (
          <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', flexShrink: 0 }}>
            <PersonIcon sx={{ fontSize: 12, color: '#6366f1' }} />
          </Box>
        ) : (
          <Typography component="span" sx={{
            fontSize: '0.6rem', fontWeight: 600, flexShrink: 0, userSelect: 'none',
            px: 0.5, borderRadius: 0.75, lineHeight: '16px', height: 16,
            bgcolor: e.level === 'STAGE' ? 'rgba(88,166,255,0.15)' : e.level === 'WARN' ? 'rgba(210,153,34,0.15)' : e.level === 'ERROR' ? 'rgba(248,81,73,0.15)' : 'rgba(201,209,217,0.08)',
            color: levelColor[e.level] || '#c9d1d9',
          }}>
            {levelLabel[e.level] || e.level}
          </Typography>
        )}
        {isUser && e.verb && (
          <Typography component="span" sx={{
            fontSize: '0.65rem', fontWeight: 600, color: '#6366f1', flexShrink: 0,
          }}>
            {VERB_LABEL[e.verb] || e.verb}
          </Typography>
        )}
        {!isUser && e.module && (
          <Typography component="span" sx={{
            fontSize: '0.62rem', color: 'text.disabled', flexShrink: 0,
            '&:hover': { color: 'text.secondary' },
          }}>
            {e.module}
          </Typography>
        )}
        <Typography component="span" sx={{
          fontSize: '0.75rem', color: isUser ? 'text.primary' : levelColor[e.level] || '#c9d1d9',
          fontWeight: e.level === 'STAGE' ? 700 : 400,
          whiteSpace: 'pre-wrap', wordBreak: 'break-all', flexGrow: 1,
        }}>
          {e.summary}
          {item.count > 1 && (
            <Box component="span" sx={{
              ml: 1, fontSize: '0.62rem', color: 'text.secondary',
              bgcolor: 'rgba(255,255,255,0.08)', px: 0.5, borderRadius: 0.75,
              border: '1px solid', borderColor: 'divider',
            }}>
              [x{item.count}]
            </Box>
          )}
        </Typography>
      </Box>
    )
  }, [])

  const liveLabel = isLive
    ? (connectionState === 'connected' ? '实时 (SSE)' : '实时 (SSE 重连中)')
    : '文件尾部 · 5s 轮询'

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', bgcolor: '#0d1117' }}>
      {/* Header */}
      <Box sx={{
        px: 2, py: 1, display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap',
        borderBottom: '1px solid', borderColor: 'divider', bgcolor: 'background.paper',
      }}>
        <Typography variant="h6" fontWeight={600} sx={{ fontSize: '1rem' }}>日志</Typography>
        <Box component="span" sx={{
          display: 'inline-flex', alignItems: 'center', gap: 0.5,
          fontSize: '0.65rem', color: 'text.secondary',
        }}>
          <Box component="span" sx={{
            width: 7, height: 7, borderRadius: '50%',
            bgcolor: connectionState === 'connected' ? '#22c55e' : connectionState === 'reconnecting' ? '#f59e0b' : '#8b949e',
          }} />
          {liveLabel}
        </Box>
        <Box component="span" sx={{ fontSize: '0.65rem', color: 'text.disabled' }}>
          {entries.length} 条
        </Box>

        <Box sx={{ flex: 1 }} />

        <TextField
          size="small" placeholder="搜索日志... (Ctrl+F)"
          value={search} onChange={e => setSearch(e.target.value)}
          inputRef={searchRef}
          sx={{ width: 200, '& .MuiInputBase-root': { fontSize: '0.72rem', bgcolor: 'grey.50' } }}
          InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon sx={{ fontSize: 15, color: 'text.disabled' }} /></InputAdornment> }}
        />

        <Stack direction="row" spacing={0.5}>
          {(['all', 'user', 'system'] as const).map(s => (
            <Chip key={s} label={s === 'all' ? '全部' : s === 'user' ? '用户' : '机器'}
              size="small" variant={sourceFilter === s ? 'filled' : 'outlined'}
              color={s === 'user' ? 'primary' : s === 'system' ? 'default' : 'default'}
              onClick={() => setSourceFilter(s)}
              sx={{ fontSize: '0.62rem', height: 22 }} />
          ))}
        </Stack>

        <Stack direction="row" spacing={0.5}>
          {LEVELS.map(lv => {
            const count = lv === 'ALL' ? entries.length : entries.filter(e => e.level === lv).length
            return (
              <Chip key={lv} label={`${levelLabel[lv]}${count > 0 ? ` ${count}` : ''}`}
                size="small" variant={filter === lv ? 'filled' : 'outlined'}
                color={lv === 'ERROR' ? 'error' : lv === 'WARN' ? 'warning' : lv === 'STAGE' ? 'primary' : 'default'}
                onClick={() => setFilter(lv)}
                sx={{ fontSize: '0.62rem', height: 22 }} />
            )
          })}
        </Stack>

        <Tooltip title={autoFollow ? '自动跟随底部 (点击暂停)' : '跟随已暂停'}>
          <IconButton size="small" color={autoFollow ? 'primary' : 'default'}
            onClick={() => setAutoFollow(v => !v)}>
            <KeyboardArrowDownIcon sx={{ fontSize: 17 }} />
          </IconButton>
        </Tooltip>
        {!isLive && (
          <Button size="small" variant="outlined" startIcon={<RefreshIcon sx={{ fontSize: 15 }} />}
            onClick={loadFile} sx={{ fontSize: '0.68rem', minWidth: 'auto', px: 1 }}>
            刷新
          </Button>
        )}
      </Box>

      {/* Timeline */}
      <Box sx={{ flex: 1, overflow: 'hidden', position: 'relative', fontFamily: 'Consolas, monospace' }}>
        {viewItems.length === 0 ? (
          <Box sx={{ p: 2 }}>
            <Typography variant="body2" color="text.disabled" sx={{ fontSize: '0.75rem' }}>
              {search || filter !== 'ALL' || sourceFilter !== 'all'
                ? '没有匹配的日志条目'
                : '暂无日志 — 运行 pipeline 或执行操作后这里会显示日志'}
            </Typography>
          </Box>
        ) : (
          <Virtuoso
            ref={virtuosoRef}
            data={viewItems}
            itemContent={itemContent}
            followOutput={autoFollow && isAtBottom ? 'auto' : false}
            atBottomStateChange={setIsAtBottom}
            atBottomThreshold={60}
            computeItemKey={(_i, item) => item.entry.id}
            style={{ height: '100%' }}
          />
        )}
        {!isAtBottom && viewItems.length > 0 && (
          <Tooltip title="回到底部" placement="left">
            <IconButton size="small" onClick={handleBackToBottom} sx={{
              position: 'absolute', bottom: 16, right: 16, zIndex: 10,
              bgcolor: 'background.paper', boxShadow: 2,
              '&:hover': { bgcolor: 'grey.200' },
            }}>
              <KeyboardArrowDownIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        )}
      </Box>
    </Box>
  )
}
