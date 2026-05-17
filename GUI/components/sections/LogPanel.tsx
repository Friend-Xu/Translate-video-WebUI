import { useRef, useEffect, useState, useCallback } from 'react'
import { Box, Typography, Card, CardContent, IconButton, Tooltip, Button } from '@mui/material'
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDownRounded'
import RateReviewIcon from '@mui/icons-material/RateReviewRounded'
import { SectionHeader } from '../SectionHeader'
import type { LogEntry } from '../../types'

interface LogPanelProps {
  logs: LogEntry[]
  showTitle?: boolean
  headerLabel?: string
  reviewEnabled?: boolean
  onStartReview?: () => void
}

const levelColor: Record<string, string> = {
  INFO: 'text.secondary',
  WARN: '#d97706',
  ERROR: '#dc2626',
  STAGE: '#2563eb',
}

export function LogPanel({ logs, showTitle = true, headerLabel, reviewEnabled = false, onStartReview }: LogPanelProps) {
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
      <Card sx={{ height: 'clamp(250px, 55vh, 650px)', mt: showTitle ? 2 : 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
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
                  <Box key={i} sx={{
                    color: levelColor[entry.level] || 'text.secondary',
                    lineHeight: 1.8,
                    fontWeight: entry.level === 'STAGE' ? 700 : 400,
                    bgcolor: entry.level === 'STAGE' ? 'rgba(37,99,235,0.08)' : 'transparent',
                    borderLeft: entry.level === 'STAGE' ? '3px solid #2563eb' : 'none',
                    pl: entry.level === 'STAGE' ? 0.8 : 0,
                    py: entry.level === 'STAGE' ? 0.2 : 0,
                    my: entry.level === 'STAGE' ? 0.3 : 0,
                    borderRadius: entry.level === 'STAGE' ? '0 4px 4px 0' : 0,
                  }}>
                    {entry.level === 'STAGE' ? '' : `[${entry.level}] `}{entry.message}
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
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
              <Typography variant="body2" fontWeight={500}>
                警告与错误
                {warnings.length > 0 && (
                  <Typography component="span" variant="caption" color="error.main" sx={{ ml: 1 }}>
                    ({warnings.length})
                  </Typography>
                )}
              </Typography>
              {onStartReview && (
                <Button
                  size="small"
                  variant={reviewEnabled ? 'contained' : 'outlined'}
                  color={reviewEnabled ? 'primary' : 'inherit'}
                  startIcon={<RateReviewIcon />}
                  disabled={!reviewEnabled}
                  onClick={onStartReview}
                  sx={{ whiteSpace: 'nowrap', minWidth: 'auto' }}
                >
                  开始字幕校验
                </Button>
              )}
            </Box>
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
                  <Box key={i} sx={{ color: levelColor[entry.level] || 'text.secondary', lineHeight: 1.8 }}>
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
