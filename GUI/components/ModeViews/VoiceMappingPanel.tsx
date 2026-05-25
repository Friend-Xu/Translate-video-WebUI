import { useState } from 'react'
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button, Box, Typography,
  FormControl, Select, MenuItem, Chip, IconButton, Tooltip,
} from '@mui/material'
import PlayArrowIcon from '@mui/icons-material/PlayArrowRounded'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHighRounded'
import WarningIcon from '@mui/icons-material/WarningRounded'
import { useAppStore } from '../../store/useAppStore'

interface Props {
  open: boolean
  onClose: () => void
}

export default function VoiceMappingPanel({ open, onClose }: Props) {
  const speakerLanes = useAppStore(s => s.speakerLanes)
  const voicePresets = useAppStore(s => s.voicePresets)
  const bindVoice = useAppStore(s => s.bindVoice)
  const [auditionLoading, setAuditionLoading] = useState<string | null>(null)

  const voiceUsage = new Map<string, string[]>()
  for (const lane of speakerLanes) {
    if (lane.voice_id) {
      const existing = voiceUsage.get(lane.voice_id) || []
      existing.push(lane.speaker)
      voiceUsage.set(lane.voice_id, existing)
    }
  }
  const conflicts = new Set<string>()
  for (const [, speakers] of voiceUsage) {
    if (speakers.length > 1) for (const s of speakers) conflicts.add(s)
  }

  const handleAutoMap = () => {
    for (const lane of speakerLanes) {
      if (lane.voice_id) continue
      const zhVoice = voicePresets.find(v => v.language === 'zh-CN' && v.id && !voiceUsage.has(v.id))
      const voice = zhVoice || voicePresets[0]
      if (voice) bindVoice(lane.speaker, voice.id)
    }
  }

  const handleAudition = async (voiceId: string) => {
    setAuditionLoading(voiceId)
    try {
      const res = await fetch('/api/tts/preview-chattts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: '试听', seed: 1 }),
      })
      if (res.ok) {
        const blob = await res.blob()
        const audio = new Audio(URL.createObjectURL(blob))
        audio.play()
      }
    } finally { setAuditionLoading(null) }
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>声线映射</Typography>
        <Button size="small" variant="outlined" startIcon={<AutoFixHighIcon />}
          onClick={handleAutoMap} sx={{ fontSize: '0.7rem' }}>
          自动映射
        </Button>
      </DialogTitle>
      <DialogContent dividers>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          <Box sx={{ display: 'flex', px: 1, gap: 2 }}>
            <Typography variant="caption" color="text.secondary" sx={{ width: 140, fontSize: '0.65rem' }}>说话人</Typography>
            <Typography variant="caption" color="text.secondary" sx={{ flexGrow: 1, fontSize: '0.65rem' }}>绑定声线</Typography>
            <Typography variant="caption" color="text.secondary" sx={{ width: 60, fontSize: '0.65rem' }}>试听</Typography>
          </Box>

          {speakerLanes.map(lane => {
            const hasConflict = conflicts.has(lane.speaker)
            return (
              <Box key={lane.speaker} sx={{
                display: 'flex', alignItems: 'center', gap: 2, px: 1, py: 0.5,
                borderRadius: 1, bgcolor: hasConflict ? 'rgba(255,152,0,0.08)' : 'transparent',
                border: hasConflict ? '1px solid rgba(255,152,0,0.3)' : '1px solid transparent',
              }}>
                <Box sx={{ width: 140, display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: lane.color }} />
                  <Typography variant="body2" noWrap sx={{ fontSize: '0.72rem' }}>{lane.display_name}</Typography>
                  {hasConflict && (
                    <Tooltip title="声线冲突：多个说话人绑定同一声线">
                      <WarningIcon sx={{ fontSize: 14, color: 'warning.main' }} />
                    </Tooltip>
                  )}
                </Box>

                <FormControl size="small" sx={{ flexGrow: 1 }}>
                  <Select value={lane.voice_id || ''} onChange={(e) => bindVoice(lane.speaker, e.target.value)}
                    displayEmpty sx={{ fontSize: '0.7rem' }}>
                    <MenuItem value="" sx={{ fontSize: '0.7rem' }}><em>未绑定</em></MenuItem>
                    {voicePresets.map(v => (
                      <MenuItem key={v.id} value={v.id} sx={{ fontSize: '0.7rem' }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
                          <span>{v.name}</span>
                          <Chip label={v.engine} size="small"
                            color={v.engine === 'chattts' ? 'primary' : v.engine === 'cosyvoice' ? 'secondary' : 'default'}
                            sx={{ fontSize: '0.55rem', height: 16, ml: 'auto' }} />
                        </Box>
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>

                <Box sx={{ width: 60, display: 'flex', justifyContent: 'center' }}>
                  {lane.voice_id ? (
                    <Tooltip title="试听">
                      <IconButton size="small" onClick={() => handleAudition(lane.voice_id)}
                        disabled={auditionLoading !== null} sx={{ p: 0.5 }}>
                        {auditionLoading === lane.voice_id
                          ? <Typography variant="caption" sx={{ fontSize: '0.55rem' }}>...</Typography>
                          : <PlayArrowIcon sx={{ fontSize: 16 }} />}
                      </IconButton>
                    </Tooltip>
                  ) : (
                    <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.55rem' }}>—</Typography>
                  )}
                </Box>
              </Box>
            )
          })}

          {speakerLanes.length === 0 && (
            <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
              暂无说话人数据
            </Typography>
          )}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button size="small" onClick={onClose}>关闭</Button>
      </DialogActions>
    </Dialog>
  )
}
