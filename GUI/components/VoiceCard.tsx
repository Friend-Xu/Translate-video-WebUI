import { Box, Typography, Button, Chip, Paper } from '@mui/material'
import PlayArrowIcon from '@mui/icons-material/PlayArrowRounded'
import LockIcon from '@mui/icons-material/LockRounded'
import LockOpenIcon from '@mui/icons-material/LockOpenRounded'
import type { VoiceCard as VoiceCardType } from '../types/modes'

interface Props {
  voice: VoiceCardType
  selected?: boolean
  onSelect?: (voice: VoiceCardType) => void
  onPreview?: (voice: VoiceCardType) => void
  onToggleLock?: (voice: VoiceCardType) => void
}

const ENGINE_COLORS: Record<string, string> = {
  edge: '#0078D4', chattts: '#9C27B0', cosyvoice: '#4CAF50', indextts: '#FF9800',
}

export default function VoiceCardComp({ voice, selected, onSelect, onPreview, onToggleLock }: Props) {
  return (
    <Paper sx={{
      p: 1.5, cursor: 'pointer',
      border: selected ? 2 : 1, borderColor: selected ? 'primary.main' : 'divider',
      bgcolor: selected ? 'action.selected' : 'background.paper',
      '&:hover': { bgcolor: 'action.hover' },
    }} onClick={() => onSelect?.(voice)}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
        <Typography variant="body2" sx={{ fontWeight: 600, fontSize: '0.78rem', flexGrow: 1 }}>
          {voice.name}
        </Typography>
        {voice.locked ? <LockIcon sx={{ fontSize: 14, color: 'text.disabled' }} /> : <LockOpenIcon sx={{ fontSize: 14, color: 'text.disabled' }} />}
      </Box>
      <Box sx={{ display: 'flex', gap: 0.5, mb: 1 }}>
        <Chip label={voice.language} size="small" sx={{ fontSize: '0.6rem', height: 18 }} />
        <Chip label={voice.engine} size="small"
          sx={{ fontSize: '0.6rem', height: 18, bgcolor: ENGINE_COLORS[voice.engine] || '#666', color: '#fff' }} />
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, fontSize: '0.65rem' }}>
        {voice.sampleText}
      </Typography>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        <Button size="small" variant="outlined" startIcon={<PlayArrowIcon sx={{ fontSize: 14 }} />}
          onClick={(e) => { e.stopPropagation(); onPreview?.(voice) }}
          sx={{ fontSize: '0.65rem', py: 0.25 }}>试听</Button>
        <Button size="small" variant="text"
          onClick={(e) => { e.stopPropagation(); onToggleLock?.(voice) }}
          sx={{ fontSize: '0.65rem', py: 0.25 }}>{voice.locked ? '解锁' : '锁定'}</Button>
      </Box>
    </Paper>
  )
}
