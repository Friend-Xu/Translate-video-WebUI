import { useMemo } from 'react'
import {
  Box, Typography, List, ListItemButton, ListItemIcon, ListItemText,
  Chip, Button, Divider,
} from '@mui/material'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import NavigateNextIcon from '@mui/icons-material/NavigateNextRounded'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHighRounded'
import { useAppStore } from '../store/useAppStore'
import type { EventViewModel } from '../types'
import type { IssueItem, IssueType } from '../types/modes'
import { MOCK_ISSUES } from '../mocks/mockData'

interface Props {
  events: EventViewModel[]
}

const ISSUE_ICONS: Record<IssueType, typeof ErrorOutlineIcon> = {
  low_confidence: WarningAmberIcon,
  misaligned: ErrorOutlineIcon,
  cps_high: WarningAmberIcon,
  duration_short: WarningAmberIcon,
  duration_long: WarningAmberIcon,
  term_conflict: ErrorOutlineIcon,
  speaker_drift: WarningAmberIcon,
}

const ISSUE_LABELS: Record<IssueType, string> = {
  low_confidence: '低置信度',
  misaligned: '未对齐',
  cps_high: '字幕过长',
  duration_short: '太短',
  duration_long: '太长',
  term_conflict: '术语冲突',
  speaker_drift: '说话人波动',
}

function computeIssues(events: EventViewModel[]): IssueItem[] {
  const eventIds = new Set(events.map(e => e.id))
  const mockIssues = MOCK_ISSUES.filter(i => eventIds.has(i.eventId))

  const dynamicIssues: IssueItem[] = []
  for (const evt of events) {
    if (evt.confidence < 0.5 && !mockIssues.some(i => i.eventId === evt.id && i.type === 'low_confidence')) {
      dynamicIssues.push({
        eventId: evt.id, type: 'low_confidence', severity: 'warning',
        message: `ASR 置信度过低 (${evt.confidence.toFixed(2)})`,
        detail: { confidence: evt.confidence, threshold: 0.5 },
        start: evt.start, end: evt.end,
      })
    }
    if (evt.patches.length > 0) {
      dynamicIssues.push({
        eventId: evt.id, type: 'term_conflict', severity: 'warning',
        message: `存在 ${evt.patches.length} 个待应用补丁`,
        detail: { patchCount: evt.patches.length },
        start: evt.start, end: evt.end,
      })
    }
  }

  return [...mockIssues, ...dynamicIssues]
}

export default function IssueQueue({ events }: Props) {
  const selectEvent = useAppStore(s => s.selectEvent)
  const selectedEventId = useAppStore(s => s.selectedEventId)

  const issues = useMemo(() => computeIssues(events), [events])

  const handleClickIssue = (eventId: string) => {
    selectEvent(eventId)
  }

  const errorCount = issues.filter(i => i.severity === 'error').length
  const warnCount = issues.filter(i => i.severity === 'warning').length

  if (issues.length === 0) {
    return (
      <Box sx={{ p: 2, textAlign: 'center' }}>
        <Typography variant="body2" color="text.secondary">未发现问题</Typography>
      </Box>
    )
  }

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Box sx={{ p: 1, display: 'flex', alignItems: 'center', gap: 1, borderBottom: 1, borderColor: 'divider' }}>
        <Typography variant="subtitle2" sx={{ fontSize: '0.8rem' }}>问题列表</Typography>
        {errorCount > 0 && <Chip label={`${errorCount} 错误`} size="small" color="error" sx={{ fontSize: '0.65rem' }} />}
        {warnCount > 0 && <Chip label={`${warnCount} 警告`} size="small" color="warning" sx={{ fontSize: '0.65rem' }} />}
        <Box sx={{ flexGrow: 1 }} />
        <Button size="small" startIcon={<AutoFixHighIcon />} sx={{ fontSize: '0.7rem' }}>批量修复</Button>
      </Box>
      <Divider />
      <List dense sx={{ flexGrow: 1, overflow: 'auto', py: 0 }}>
        {issues.map(issue => {
          const Icon = ISSUE_ICONS[issue.type] || WarningAmberIcon
          const isSelected = selectedEventId === issue.eventId
          return (
            <ListItemButton
              key={`${issue.eventId}_${issue.type}`}
              selected={isSelected}
              onClick={() => handleClickIssue(issue.eventId)}
              sx={{ borderLeft: 3, borderColor: isSelected ? 'primary.main' : 'transparent' }}
            >
              <ListItemIcon sx={{ minWidth: 28 }}>
                <Icon sx={{ fontSize: 18, color: issue.severity === 'error' ? 'error.main' : 'warning.main' }} />
              </ListItemIcon>
              <ListItemText
                primary={
                  <Typography variant="body2" sx={{ fontSize: '0.72rem', fontWeight: isSelected ? 600 : 400 }}>
                    {issue.message}
                  </Typography>
                }
                secondary={
                  <Box sx={{ display: 'flex', gap: 0.5, mt: 0.25 }}>
                    <Chip label={ISSUE_LABELS[issue.type]} size="small" sx={{ fontSize: '0.6rem', height: 18 }} />
                    <Typography variant="caption" color="text.secondary">
                      {issue.start.toFixed(1)}s - {issue.end.toFixed(1)}s
                    </Typography>
                  </Box>
                }
                disableTypography
              />
              <NavigateNextIcon sx={{ fontSize: 16, color: 'text.disabled' }} />
            </ListItemButton>
          )
        })}
      </List>
      <Box sx={{ p: 1, borderTop: 1, borderColor: 'divider' }}>
        <Button size="small" fullWidth variant="text" startIcon={<NavigateNextIcon />} sx={{ fontSize: '0.72rem' }}>
          下一问题 (N)
        </Button>
      </Box>
    </Box>
  )
}
