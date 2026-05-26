import { Box, Typography, Button, Divider, Chip } from '@mui/material'
import CheckIcon from '@mui/icons-material/CheckRounded'
import CloseIcon from '@mui/icons-material/CloseRounded'
import { useAppStore } from '../store/useAppStore'
import type { PatchDraft } from '../types/modes'

interface Props {
  draft: PatchDraft | null
  onApply?: () => void
  onReject?: () => void
}

export default function PatchDiffPanel({ draft, onApply, onReject }: Props) {
  const discardDraft = useAppStore(s => s.discardDraft)

  if (!draft) {
    return (
      <Box sx={{ p: 3, textAlign: 'center' }}>
        <Typography variant="body2" color="text.secondary">
          选择一个草案以预览差异
        </Typography>
      </Box>
    )
  }

  const handleApply = () => {
    onApply?.()
    discardDraft(draft.eventId)
  }

  const handleReject = () => {
    onReject?.()
    discardDraft(draft.eventId)
  }

  return (
    <Box sx={{ p: 1.5 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
        <Chip label={draft.opcode} size="small" color="primary" variant="outlined" />
        <Typography variant="caption" color="text.secondary">
          {new Date(draft.timestamp).toLocaleTimeString()}
        </Typography>
      </Box>
      <Divider sx={{ mb: 1.5 }} />

      {Object.entries(draft.before).map(([key, value]) => (
        <Box key={key} sx={{ mb: 1.5 }}>
          <Chip label={`${key} (修改前)`} size="small" color="default" variant="outlined" sx={{ mb: 0.5 }} />
          <Typography variant="body2" sx={{
            fontSize: '0.72rem', p: 0.5, borderRadius: 0.5,
            bgcolor: 'grey.100', wordBreak: 'break-word',
          }}>
            {String(value || '(空)')}
          </Typography>
          <Typography variant="body2" sx={{
            fontSize: '0.72rem', p: 0.5, mt: 0.25, borderRadius: 0.5,
            bgcolor: 'success.light', wordBreak: 'break-word',
            border: '1px solid #c8e6c9',
          }}>
            → {String(draft.after[key] || '(空)')}
          </Typography>
        </Box>
      ))}

      <Box sx={{ display: 'flex', gap: 1, mt: 2 }}>
        <Button size="small" variant="contained" color="primary" startIcon={<CheckIcon />}
          onClick={handleApply} fullWidth>
          应用草案
        </Button>
        <Button size="small" variant="outlined" color="error" startIcon={<CloseIcon />}
          onClick={handleReject} fullWidth>
          放弃
        </Button>
      </Box>
    </Box>
  )
}
