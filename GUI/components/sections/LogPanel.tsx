import { useRef, useEffect, useState, useCallback } from 'react'
import { Box, Typography, Card, CardContent, IconButton, Tooltip } from '@mui/material'
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDownRounded'
import { SectionHeader } from '../SectionHeader'
import type { LogEntry } from '../../types'

interface LogPanelProps {
  logs: LogEntry[]
  showTitle?: boolean
  headerLabel?: string
}

const levelColor: Record<string, string> = {
  INFO: 'text.secondary',
  WARN: '#d97706',
  ERROR: '#dc2626',
}

export function LogPanel({ logs, showTitle = true, headerLabel }: LogPanelProps) {
  const logContainerRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)

  const isAtBottom = useCallback(() => {
    const el = logContainerRef.current
    if (!el) return true
    return el.scrollHeight - el.scrollTop - el.clientHeight < 40
  }, [])

  const scrollToBottom = useCallback(() => {
    const el = logContainerRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [])

  useEffect(() => {
    if (autoScroll) {
      scrollToBottom()
    }
  }, [logs, autoScroll, scrollToBottom])

  const handleScroll = useCallback(() => {
    setAutoScroll(isAtBottom())
  }, [isAtBottom])

  const handleBackToBottom = useCallback(() => {
    const el = logContainerRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    setAutoScroll(true)
  }, [])

  const warnings = logs.filter(l => l.level === 'WARN' || l.level === 'ERROR')

  return (
    <>
      {showTitle && <SectionHeader title="日志与反馈 (Log & Feedback)" />}
      <Card sx={{ height: '100%', mt: showTitle ? 2 : 0, display: 'flex', flexDirection: 'column' }}>
        <CardContent sx={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, pb: '8px !important' }}>
          {headerLabel && (
            <Typography variant="caption" color="primary.main" fontWeight={500} sx={{ display: 'block', mb: 0.5, flexShrink: 0 }}>
              {headerLabel}
            </Typography>
          )}
          <Box sx={{ position: 'relative', flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <Box
              ref={logContainerRef}
              onScroll={handleScroll}
              sx={{
                p: 1.5, bgcolor: 'grey.100', borderRadius: 2, mb: 1.5, flex: 1,
                overflow: 'auto', fontFamily: 'monospace', fontSize: '0.8rem',
              }}
            >
              {logs.length === 0 ? (
                <Typography variant="body2" color="text.secondary">等待任务开始...</Typography>
              ) : (
                logs.map((entry, i) => (
                  <Box key={i} sx={{ color: levelColor[entry.level] || 'text.secondary', lineHeight: 1.8 }}>
                    [{entry.level}] {entry.message}
                  </Box>
                ))
              )}
            </Box>
            {!autoScroll && (
              <Tooltip title="回到底部" placement="left">
                <IconButton
                  size="small"
                  onClick={handleBackToBottom}
                  sx={{
                    position: 'absolute', bottom: 24, right: 12, zIndex: 10,
                    bgcolor: 'background.paper', boxShadow: 2,
                    '&:hover': { bgcolor: 'grey.200' },
                  }}
                >
                  <KeyboardArrowDownIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
          </Box>

          <Box sx={{ flexShrink: 0 }}>
            <Typography variant="body2" fontWeight={500} gutterBottom>
              警告与错误
              {warnings.length > 0 && (
                <Typography component="span" variant="caption" color="error.main" sx={{ ml: 1 }}>
                  ({warnings.length})
                </Typography>
              )}
            </Typography>
            <Box sx={{
              p: 1.5, bgcolor: 'error.light', borderRadius: 2,
              maxHeight: 120, overflow: 'auto',
              fontFamily: 'monospace', fontSize: '0.8rem',
              color: 'error.dark', border: '1px solid', borderColor: 'error.light',
            }}>
              {warnings.length === 0 ? (
                <Typography variant="body2" color="text.secondary">暂无警告或错误</Typography>
              ) : (
                warnings.map((entry, i) => (
                  <Box key={i} sx={{ lineHeight: 1.8 }}>
                    [{entry.level}] {entry.message}
                  </Box>
                ))
              )}
            </Box>
          </Box>
        </CardContent>
      </Card>
    </>
  )
}
