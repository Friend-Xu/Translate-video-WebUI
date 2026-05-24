import { Box, Typography, Chip, Button, Divider } from '@mui/material'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHighRounded'
import ReplayIcon from '@mui/icons-material/ReplayRounded'
import type { IssueItem } from '../types/modes'

interface Props {
  issue: IssueItem
  onFix?: (issue: IssueItem) => void
}

const FIX_SUGGESTIONS: Record<string, { label: string; action: string }[]> = {
  low_confidence: [
    { label: '重新语音识别', action: 're-ASR' },
    { label: '手动修正原文', action: 'edit-text' },
  ],
  misaligned: [
    { label: '重新对齐', action: 'realign' },
    { label: '微调时间边界', action: 'adjust-bounds' },
  ],
  cps_high: [
    { label: '拆分字幕', action: 'split' },
    { label: '精简译文', action: 'shorten' },
  ],
  term_conflict: [
    { label: '统一术语翻译', action: 'unify-term' },
    { label: '添加到术语表', action: 'add-glossary' },
  ],
  speaker_drift: [
    { label: '重新说话人识别', action: 're-diarize' },
    { label: '手动标定说话人', action: 'manual-speaker' },
  ],
}

export default function DiagnosisCard({ issue, onFix }: Props) {
  const Icon = issue.severity === 'error' ? ErrorOutlineIcon : WarningAmberIcon
  const suggestions = FIX_SUGGESTIONS[issue.type] || [
    { label: '手动修复', action: 'manual' },
  ]

  return (
    <Box sx={{
      mt: 1.5, p: 1.5, borderRadius: 1.5,
      border: '1px solid',
      borderColor: issue.severity === 'error' ? 'error.light' : 'warning.light',
      bgcolor: issue.severity === 'error' ? '#ffebee' : '#fff8e1',
    }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
        <Icon sx={{
          fontSize: 20,
          color: issue.severity === 'error' ? 'error.main' : 'warning.main',
        }} />
        <Typography variant="subtitle2" sx={{ fontSize: '0.8rem' }}>诊断</Typography>
      </Box>
      <Divider sx={{ mb: 1 }} />
      <Typography variant="body2" sx={{ fontSize: '0.72rem', mb: 1, color: 'text.secondary' }}>
        {issue.message}
      </Typography>
      {Object.keys(issue.detail).length > 0 && (
        <Box sx={{ mb: 1, display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
          {Object.entries(issue.detail).map(([key, value]) => (
            <Chip
              key={key}
              label={`${key}: ${typeof value === 'number' ? (value as number).toFixed(2) : String(value)}`}
              size="small" variant="outlined"
              sx={{ fontSize: '0.6rem', height: 20 }}
            />
          ))}
        </Box>
      )}
      <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5, display: 'block' }}>
        建议修复方案:
      </Typography>
      <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
        {suggestions.map(s => (
          <Button
            key={s.action}
            size="small" variant="outlined"
            color={issue.severity === 'error' ? 'error' : 'warning'}
            startIcon={s.action === 're-ASR' || s.action === 'realign' ? <ReplayIcon /> : <AutoFixHighIcon />}
            onClick={() => onFix?.(issue)}
            sx={{ fontSize: '0.65rem', py: 0.25 }}
          >
            {s.label}
          </Button>
        ))}
      </Box>
    </Box>
  )
}
