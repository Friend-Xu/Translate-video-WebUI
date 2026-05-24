import { Box, Typography, Collapse, Paper, Chip, Breadcrumbs, IconButton, Button, Divider } from '@mui/material'
import CloseIcon from '@mui/icons-material/CloseRounded'
import SplitIcon from '@mui/icons-material/CallSplitRounded'
import MergeIcon from '@mui/icons-material/MergeRounded'
import EditIcon from '@mui/icons-material/EditRounded'
import VoiceIcon from '@mui/icons-material/RecordVoiceOverRounded'
import type { EventViewModel } from '../../types'

interface Props {
  event: EventViewModel | null
  open: boolean
  onClose: () => void
  onSplit: () => void
  onMergePrev: () => void
  onEditTranslation: () => void
  onRetagSpeaker: () => void
}

export default function EventInspector({
  event, open, onClose, onSplit, onMergePrev, onEditTranslation, onRetagSpeaker,
}: Props) {
  if (!event) return null

  return (
    <Collapse in={open}>
      <Paper sx={{ m: 1, p: 2, bgcolor: '#fafafa', border: '1px solid #e0e0e0' }}>
        {/* Header */}
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
          <Typography variant="subtitle2" sx={{ mr: 1 }}>
            Inspector: {event.id}
          </Typography>
          <Chip
            label={`${event.start.toFixed(1)}s - ${event.end.toFixed(1)}s`}
            size="small" variant="outlined" sx={{ mr: 1 }}
          />
          <Chip
            label={event.displayName}
            size="small"
            sx={{ mr: 1, bgcolor: event.visualState.hasPatches ? '#FF9800' : '#9E9E9E', color: '#fff' }}
          />
          <Box sx={{ flexGrow: 1 }} />
          <IconButton size="small" onClick={onClose}><CloseIcon fontSize="small" /></IconButton>
        </Box>

        <Divider sx={{ mb: 1 }} />

        {/* Payload (只读) */}
        <Box sx={{ mb: 1 }}>
          <Chip label="RAW (Payload)" size="small" color="default" variant="outlined" sx={{ mr: 1 }} />
          <Typography variant="body2" sx={{ mt: 0.5, color: 'text.secondary', fontStyle: 'italic' }}>
            {event.text}
          </Typography>
        </Box>

        {/* Derivative */}
        <Box sx={{ mb: 1 }}>
          <Chip label="PASS (Derivative)" size="small" color="primary" variant="outlined" sx={{ mr: 1 }} />
          <Typography variant="body2" sx={{ mt: 0.5 }}>
            translation: {event.translation || '(未翻译)'}
          </Typography>
        </Box>

        {/* Patches */}
        {event.patches.length > 0 && (
          <Box sx={{ mb: 1 }}>
            <Chip
              label={`PATCHED (${event.patches.length})`}
              size="small" color="warning" variant="outlined" sx={{ mr: 1 }}
            />
            <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 0.5 }}>
              {event.patches.map(p => (
                <Chip key={p.patch_id} label={`${p.opcode} · ${p.author}`}
                  size="small" sx={{ fontSize: '0.65rem' }} />
              ))}
            </Box>
          </Box>
        )}

        {/* Pass Trace */}
        <Box sx={{ mb: 1 }}>
          <Typography variant="caption" color="text.secondary">Pass Trace:</Typography>
          <Breadcrumbs separator="→" sx={{ fontSize: '0.7rem' }}>
            {event.passTrace.length > 0
              ? event.passTrace.map(name => (
                <Chip key={name} label={name} size="small" variant="outlined" sx={{ fontSize: '0.6rem' }} />
              ))
              : <Typography variant="caption" color="text.secondary">(无)</Typography>
            }
          </Breadcrumbs>
        </Box>

        {/* Action buttons */}
        <Box sx={{ display: 'flex', gap: 1, mt: 2 }}>
          <Button size="small" variant="outlined" startIcon={<SplitIcon />} onClick={onSplit}>切分</Button>
          <Button size="small" variant="outlined" startIcon={<MergeIcon />} onClick={onMergePrev}>合并上文</Button>
          <Button size="small" variant="outlined" startIcon={<EditIcon />} onClick={onEditTranslation}>编辑翻译</Button>
          <Button size="small" variant="outlined" startIcon={<VoiceIcon />} onClick={onRetagSpeaker}>重标说话人</Button>
        </Box>
      </Paper>
    </Collapse>
  )
}
