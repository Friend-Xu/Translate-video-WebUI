import { useRef, useEffect } from 'react'
import { Box, Typography, Card, CardContent } from '@mui/material'
import { SectionHeader } from '../SectionHeader'
import type { LogEntry } from '../../types'

interface LogPanelProps {
  logs: LogEntry[]
  showTitle?: boolean
}

const levelColor: Record<string, string> = {
  INFO: 'text.secondary',
  WARN: '#d97706',
  ERROR: '#dc2626',
}

export function LogPanel({ logs, showTitle = true }: LogPanelProps) {
  const logEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  const warnings = logs.filter(l => l.level === 'WARN' || l.level === 'ERROR')

  return (
    <>
      {showTitle && <SectionHeader title="日志与反馈 (Log & Feedback)" />}
      <Card sx={{ height: '100%', mt: showTitle ? 2 : 0 }}>
        <CardContent>
          <Typography variant="body2" fontWeight={500} gutterBottom>日志输出</Typography>
          <Box sx={{
            p: 1.5, bgcolor: 'grey.100', borderRadius: 2, mb: 2,
            height: 300, overflow: 'auto',
            fontFamily: 'monospace', fontSize: '0.8rem',
          }}>
            {logs.length === 0 ? (
              <Typography variant="body2" color="text.secondary">等待任务开始...</Typography>
            ) : (
              logs.map((entry, i) => (
                <Box key={i} sx={{ color: levelColor[entry.level] || 'text.secondary', lineHeight: 1.8 }}>
                  [{entry.level}] {entry.message}
                </Box>
              ))
            )}
            <div ref={logEndRef} />
          </Box>

          <Typography variant="body2" fontWeight={500} gutterBottom>错误与警告信息</Typography>
          <Box sx={{
            p: 1.5, bgcolor: 'error.light', borderRadius: 2,
            height: 120, overflow: 'auto',
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
        </CardContent>
      </Card>
    </>
  )
}
