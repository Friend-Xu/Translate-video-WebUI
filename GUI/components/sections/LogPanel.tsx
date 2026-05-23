import { useRef, useState, useCallback, useMemo } from 'react'
import { Box, Typography, Card, CardContent, IconButton, Tooltip, Button, Chip, Stack } from '@mui/material'
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDownRounded'
import RateReviewIcon from '@mui/icons-material/RateReviewRounded'
import { Virtuoso, VirtuosoHandle } from 'react-virtuoso'
import { SectionHeader } from '../SectionHeader'
import type { LogEntry } from '../../types'

interface LogPanelProps {
  logs: LogEntry[]
  showTitle?: boolean
  headerLabel?: string
  reviewEnabled?: boolean
  onStartReview?: () => void
  connectionState?: 'connected' | 'reconnecting' | 'closed'
  /** Global index of logs[0] in the full log file (for virtual window scrolling) */
  logFirstIndex?: number
  /** Approximate total lines in the log file */
  logTotal?: number
  /** Callback when user scrolls to top — load older entries */
  onLoadOlder?: () => void
}

const LEVEL_FILTERS = ['ALL', 'STAGE', 'WARN', 'ERROR'] as const
type LevelFilter = typeof LEVEL_FILTERS[number]

const levelColor: Record<string, string> = {
  INFO: 'text.secondary',
  WARN: '#d97706',
  ERROR: '#dc2626',
  STAGE: '#2563eb',
}

const connectionLabel: Record<string, { text: string; color: string }> = {
  connected: { text: '实时', color: '#22c55e' },
  reconnecting: { text: '重连中...', color: '#f59e0b' },
  closed: { text: '已断开', color: '#ef4444' },
}

export function LogPanel({
  logs, showTitle = true, headerLabel,
  reviewEnabled = false, onStartReview,
  connectionState = 'connected',
  logFirstIndex, logTotal: _logTotal, onLoadOlder,
}: LogPanelProps) {
  const [isAtBottom, setIsAtBottom] = useState(true)
  const [filter, setFilter] = useState<LevelFilter>('ALL')
  const virtuosoRef = useRef<VirtuosoHandle>(null)

  const filteredLogs = useMemo(() => {
    if (filter === 'ALL') return logs
    return logs.filter(l => l.level === filter)
  }, [logs, filter])

  const warnings = logs.filter(l => l.level === 'WARN' || l.level === 'ERROR')

  const itemContent = useCallback(
    (_index: number, entry: LogEntry) => (
      <Box sx={{
        color: levelColor[entry.level] || 'text.secondary',
        lineHeight: 1.8,
        fontWeight: entry.level === 'STAGE' ? 700 : 400,
        bgcolor: entry.level === 'STAGE' ? 'rgba(37,99,235,0.08)' : 'transparent',
        borderLeft: entry.level === 'STAGE' ? '3px solid #2563eb' : 'none',
        pl: entry.level === 'STAGE' ? 0.8 : 0,
        py: entry.level === 'STAGE' ? 0.2 : 0,
        my: entry.level === 'STAGE' ? 0.3 : 0,
        borderRadius: entry.level === 'STAGE' ? '0 4px 4px 0' : 0,
        px: 0.5,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-all',
      }}>
        <Typography component="span" variant="caption" color="text.disabled" sx={{ mr: 1, fontSize: '0.65rem', userSelect: 'none' }}>
          {entry.timestamp}
        </Typography>
        {entry.level === 'STAGE' ? '' : `[${entry.level}] `}{entry.message}
      </Box>
    ),
    [],
  )

  const handleBackToBottom = useCallback(() => {
    virtuosoRef.current?.scrollToIndex({ index: 'LAST', behavior: 'smooth' })
  }, [])

  const conn = connectionLabel[connectionState]

  return (
    <>
      {showTitle && <SectionHeader title="日志与反馈 (Log & Feedback)" />}
      <Card sx={{ height: 'clamp(250px, 55vh, 650px)', mt: showTitle ? 2 : 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <CardContent sx={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, pb: '8px !important' }}>
          {/* Header bar: label + connection + filters + review button */}
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5, flexShrink: 0, flexWrap: 'wrap', gap: 0.5 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              {headerLabel && (
                <Typography variant="caption" color="primary.main" fontWeight={500}>
                  {headerLabel}
                </Typography>
              )}
              <Box component="span" sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: conn.color, display: 'inline-block' }} />
              <Typography variant="caption" color="text.secondary" sx={{ userSelect: 'none' }}>{conn.text}</Typography>
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Stack direction="row" spacing={0.5}>
                {LEVEL_FILTERS.map(lv => {
                  const count = lv === 'ALL' ? logs.length : logs.filter(l => l.level === lv).length
                  return (
                    <Chip
                      key={lv}
                      label={`${lv === 'ALL' ? '全部' : lv}${count > 0 ? ` ${count}` : ''}`}
                      size="small"
                      variant={filter === lv ? 'filled' : 'outlined'}
                      color={lv === 'ERROR' ? 'error' : lv === 'WARN' ? 'warning' : lv === 'STAGE' ? 'primary' : 'default'}
                      onClick={() => setFilter(lv)}
                      sx={{ fontSize: '0.65rem', height: 22 }}
                    />
                  )
                })}
              </Stack>
              {onStartReview && (
                <Button
                  size="small"
                  variant={reviewEnabled ? 'contained' : 'outlined'}
                  color={reviewEnabled ? 'primary' : 'inherit'}
                  startIcon={<RateReviewIcon />}
                  disabled={!reviewEnabled}
                  onClick={onStartReview}
                  sx={{ whiteSpace: 'nowrap', minWidth: 'auto', ml: 0.5 }}
                >
                  字幕校验
                </Button>
              )}
            </Box>
          </Box>

          {/* Virtual log list */}
          <Box sx={{ position: 'relative', flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <Box sx={{
              flex: 1,
              bgcolor: 'grey.100',
              borderRadius: 2,
              overflow: 'hidden',
              fontFamily: 'monospace',
              fontSize: '0.8rem',
            }}>
              {filteredLogs.length === 0 ? (
                <Box sx={{ p: 1.5 }}>
                  <Typography variant="body2" color="text.secondary">等待任务开始...</Typography>
                </Box>
              ) : (
                <Virtuoso
                  ref={virtuosoRef}
                  data={filteredLogs}
                  firstItemIndex={logFirstIndex ?? 0}
                  itemContent={itemContent}
                  followOutput={isAtBottom ? 'auto' : false}
                  atBottomStateChange={setIsAtBottom}
                  atBottomThreshold={60}
                  startReached={onLoadOlder}
                  style={{ height: '100%' }}
                  increaseViewportBy={{ top: 200, bottom: 200 }}
                  computeItemKey={(_i, entry) => entry._id ?? `${entry.timestamp}-${_i}`}
                />
              )}
            </Box>
            {!isAtBottom && filteredLogs.length > 0 && (
              <Tooltip title="回到底部" placement="left">
                <IconButton
                  size="small"
                  onClick={handleBackToBottom}
                  sx={{
                    position: 'absolute', bottom: 8, right: 8, zIndex: 10,
                    bgcolor: 'background.paper', boxShadow: 2,
                    '&:hover': { bgcolor: 'grey.200' },
                  }}
                >
                  <KeyboardArrowDownIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
          </Box>

          {/* Warnings panel */}
          <Box sx={{ flexShrink: 0, mt: 1 }}>
            <Typography variant="body2" fontWeight={500}>
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
