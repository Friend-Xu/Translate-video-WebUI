import { Popover, Box, Typography, Button, Chip, Divider } from '@mui/material'
import CheckIcon from '@mui/icons-material/CheckRounded'
import CloseIcon from '@mui/icons-material/CloseRounded'
import ArrowForwardIcon from '@mui/icons-material/ArrowForwardRounded'
import { useAppStore } from '../../store/useAppStore'
import type { EventViewModel } from '../../types'

interface Props {
  event: EventViewModel | null
  anchorEl: HTMLElement | null
  onClose: () => void
}

export default function PatchDiffPopover({ event, anchorEl, onClose }: Props) {
  const addDraft = useAppStore(s => s.addDraft)
  const open = Boolean(anchorEl) && event !== null && event.visualState.hasAiSuggestion

  if (!event) return null

  const handleApply = () => {
    addDraft({
      eventId: event.id,
      opcode: 'APPLY_AI_SUGGESTION',
      payload: { translation: event.translation },
      before: { translation: event.translation },
      after: { translation: event.translation },
      timestamp: Date.now(),
    })
    onClose()
  }

  const handleDismiss = () => {
    addDraft({
      eventId: event.id,
      opcode: 'DISMISS_AI_SUGGESTION',
      payload: {},
      before: {},
      after: {},
      timestamp: Date.now(),
    })
    onClose()
  }

  const duration = event.end - event.start
  const estSpeechDuration = event.text ? event.text.length * 0.25 : 0
  const driftPct = duration > 0 ? ((estSpeechDuration - duration) / duration * 100) : 0

  return (
    <Popover
      open={open}
      anchorEl={anchorEl}
      onClose={onClose}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      transformOrigin={{ vertical: 'top', horizontal: 'center' }}
      slotProps={{ paper: { sx: { maxWidth: 420, p: 2, bgcolor: 'grey.900', border: '1px solid rgba(255,255,255,0.1)' } } }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
        <Chip label="AI 建议" size="small" color="warning" sx={{ fontSize: '0.65rem', height: 20 }} />
        <Typography variant="caption" color="text.secondary">
          {event.id} · {event.start.toFixed(1)}s–{event.end.toFixed(1)}s
        </Typography>
      </Box>

      <Box sx={{ display: 'flex', gap: 1, mb: 1.5 }}>
        <Box sx={{ flex: 1, p: 1, borderRadius: 1, bgcolor: 'rgba(255,255,255,0.05)' }}>
          <Typography variant="caption" color="text.disabled" sx={{ display: 'block', mb: 0.5 }}>
            当前译文
          </Typography>
          <Typography variant="body2" sx={{ fontSize: '0.72rem', color: 'text.primary' }}>
            {event.translation || event.text}
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center' }}>
          <ArrowForwardIcon sx={{ fontSize: 16, color: 'text.disabled' }} />
        </Box>
        <Box sx={{ flex: 1, p: 1, borderRadius: 1, bgcolor: 'rgba(255,152,0,0.1)', border: '1px solid rgba(255,152,0,0.2)' }}>
          <Typography variant="caption" color="warning.main" sx={{ display: 'block', mb: 0.5 }}>
            建议译文
          </Typography>
          <Typography variant="body2" sx={{ fontSize: '0.72rem', color: 'warning.light' }}>
            {event.text}
          </Typography>
        </Box>
      </Box>

      <Box sx={{ display: 'flex', gap: 1, mb: 1.5, flexWrap: 'wrap' }}>
        <Chip
          label={`时长: ${duration.toFixed(1)}s → ${estSpeechDuration.toFixed(1)}s (${driftPct > 0 ? '+' : ''}${driftPct.toFixed(0)}%)`}
          size="small" variant="outlined"
          sx={{ fontSize: '0.6rem', height: 20 }}
        />
        <Chip
          label={`置信度: ${event.confidence.toFixed(2)}`}
          size="small" variant="outlined"
          color={event.confidence < 0.5 ? 'error' : event.confidence < 0.7 ? 'warning' : 'success'}
          sx={{ fontSize: '0.6rem', height: 20 }}
        />
      </Box>

      <Divider sx={{ my: 1 }} />

      <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
        <Button
          size="small"
          variant="outlined"
          color="inherit"
          startIcon={<CloseIcon fontSize="small" />}
          onClick={handleDismiss}
          sx={{ fontSize: '0.7rem' }}
        >
          忽略
        </Button>
        <Button
          size="small"
          variant="contained"
          color="success"
          startIcon={<CheckIcon fontSize="small" />}
          onClick={handleApply}
          sx={{ fontSize: '0.7rem' }}
        >
          应用建议
        </Button>
      </Box>
    </Popover>
  )
}
