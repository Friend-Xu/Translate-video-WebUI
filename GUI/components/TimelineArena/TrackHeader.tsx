import { Box, IconButton } from '@mui/material'
import VisibilityIcon from '@mui/icons-material/VisibilityRounded'
import VisibilityOffIcon from '@mui/icons-material/VisibilityOffRounded'
import LockIcon from '@mui/icons-material/LockRounded'
import LockOpenIcon from '@mui/icons-material/LockOpenRounded'
import VolumeOffIcon from '@mui/icons-material/VolumeOffRounded'
import VolumeUpIcon from '@mui/icons-material/VolumeUpRounded'
import type { TrackDefinition } from '../../types/timeline'

interface Props {
  tracks: TrackDefinition[]
  onToggleVisibility: (id: string) => void
  onToggleLock: (id: string) => void
  onToggleSolo: (id: string) => void
  onToggleMute: (id: string) => void
}

const HEADER_W = 48
const ICON_SIZE = 14

export default function TrackHeader({ tracks, onToggleVisibility, onToggleLock, onToggleSolo, onToggleMute }: Props) {
  return (
    <Box sx={{ width: HEADER_W, minWidth: HEADER_W, bgcolor: 'rgba(0,0,0,0.4)' }}>
      {tracks.map(track => (
        <Box key={track.id} sx={{
          height: track.height, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', gap: 0,
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          px: 0.25,
        }}>
          <Box sx={{ display: 'flex', gap: 0 }}>
            <IconButton size="small" onClick={() => onToggleVisibility(track.id)}
              sx={{ p: 0.1, '& .MuiSvgIcon-root': { fontSize: ICON_SIZE } }}>
              {track.visible ? <VisibilityIcon fontSize="inherit" /> : <VisibilityOffIcon fontSize="inherit" />}
            </IconButton>
            <IconButton size="small" onClick={() => onToggleLock(track.id)}
              sx={{ p: 0.1, '& .MuiSvgIcon-root': { fontSize: ICON_SIZE } }}>
              {track.locked ? <LockIcon fontSize="inherit" /> : <LockOpenIcon fontSize="inherit" />}
            </IconButton>
          </Box>
          <Box sx={{ display: 'flex', gap: 0 }}>
            <IconButton size="small" onClick={() => onToggleSolo(track.id)}
              sx={{
                p: 0.1, fontSize: '0.55rem', fontWeight: 700, minWidth: 16,
                color: track.solo ? 'warning.main' : 'text.secondary',
              }}>
              <span style={{ fontSize: '0.55rem', lineHeight: 1 }}>S</span>
            </IconButton>
            {(track.type === 'tts' || track.type === 'speaker') && (
              <IconButton size="small" onClick={() => onToggleMute(track.id)}
                sx={{ p: 0.1, '& .MuiSvgIcon-root': { fontSize: ICON_SIZE } }}>
                {track.muted ? <VolumeOffIcon fontSize="inherit" /> : <VolumeUpIcon fontSize="inherit" />}
              </IconButton>
            )}
          </Box>
        </Box>
      ))}
    </Box>
  )
}
