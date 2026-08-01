/**
 * LogsView — 全屏日志视图 (P5-B)
 *
 * 日志按钮不再"形同虚设": 显示当前 workspace 的 pipeline.log (有 workspace 时)
 * 或 GUI/logs/ 最新 server 进程日志 (无 job 也有内容)。10s 自动刷新。
 */
import { useState, useCallback, useEffect, useRef } from 'react'
import { Box, Typography, Button, IconButton, Tooltip } from '@mui/material'
import RefreshIcon from '@mui/icons-material/RefreshRounded'
import { useAppStore } from '../../store/useAppStore'

export default function LogsView() {
  const workspace = useAppStore(s => s.workspace)
  const [lines, setLines] = useState<string[]>([])
  const [source, setSource] = useState('')
  const [total, setTotal] = useState(0)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams()
      if (workspace) params.set('workspace', workspace)
      const res = await fetch(`/api/logs/recent?${params}`)
      if (!res.ok) return
      const data = await res.json()
      setLines(data.lines || [])
      setSource(data.source || '')
      setTotal(data.total || 0)
    } catch { /* 服务未启动时保持旧内容 */ }
  }, [workspace])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (!autoRefresh) return
    const timer = setInterval(load, 10000)
    return () => clearInterval(timer)
  }, [autoRefresh, load])

  // 新内容到达时自动滚到底部
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lines])

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', bgcolor: '#0d1117' }}>
      {/* Header */}
      <Box sx={{
        px: 3, py: 1.5, display: 'flex', alignItems: 'center', gap: 2,
        borderBottom: '1px solid', borderColor: 'divider', bgcolor: 'background.paper',
      }}>
        <Typography variant="h6" fontWeight={600}>日志</Typography>
        <Typography variant="caption" color="text.secondary">
          来源: {source === 'workspace' ? '当前工作区 pipeline.log' : 'server 进程日志'}
          {total > 0 && ` · 共 ${total} 行`}
        </Typography>
        <Box sx={{ flex: 1 }} />
        <Tooltip title="10s 自动刷新">
          <IconButton size="small" color={autoRefresh ? 'primary' : 'default'} onClick={() => setAutoRefresh(v => !v)}>
            <RefreshIcon sx={{ fontSize: 18 }} />
          </IconButton>
        </Tooltip>
        <Button size="small" variant="outlined" startIcon={<RefreshIcon />} onClick={load}>刷新</Button>
      </Box>

      {/* Log lines */}
      <Box ref={scrollRef} sx={{ flex: 1, overflow: 'auto', p: 2, fontFamily: 'Consolas, monospace', fontSize: '0.75rem' }}>
        {lines.length === 0 ? (
          <Typography variant="body2" color="text.disabled" sx={{ p: 2 }}>
            暂无日志 — 运行 pipeline 或执行操作后这里会显示日志
          </Typography>
        ) : (
          lines.map((l, i) => (
            <Box key={i} sx={{
              whiteSpace: 'pre-wrap', wordBreak: 'break-all', lineHeight: 1.6,
              color: l.includes('[ERROR]') || l.includes(' ERROR ') ? '#f85149'
                : l.includes('[WARN]') || l.includes(' WARN ') ? '#d29922'
                : '#c9d1d9',
            }}>
              {l}
            </Box>
          ))
        )}
      </Box>
    </Box>
  )
}
