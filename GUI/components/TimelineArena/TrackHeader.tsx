import { Box, Typography, IconButton, Tooltip } from '@mui/material'
import VisibilityIcon from '@mui/icons-material/VisibilityRounded'
import VisibilityOffIcon from '@mui/icons-material/VisibilityOffRounded'
import LockIcon from '@mui/icons-material/LockRounded'
import LockOpenIcon from '@mui/icons-material/LockOpenRounded'
import VolumeOffIcon from '@mui/icons-material/VolumeOffRounded'
import VolumeUpIcon from '@mui/icons-material/VolumeUpRounded'
import { useAppStore } from '../../store/useAppStore'
import type { TrackDefinition } from '../../types/timeline'
import type { EventViewModel } from '../../types'
import { SPEAKER_TRACK_PRESET, TRACK_VISIBILITY_MAP } from '../../types/timeline'

const HEADER_W = 120
const ICON_SIZE = 16

function TrackHeaderRow({ track, events }: { track: TrackDefinition; events: EventViewModel[] }) {
  const toggleVisibility = useAppStore(s => s.toggleTrackVisibility)
  const toggleLock = useAppStore(s => s.toggleTrackLock)
  const toggleSolo = useAppStore(s => s.toggleTrackSolo)
  const toggleMute = useAppStore(s => s.toggleTrackMute)
  const resizeTrack = useAppStore(s => s.resizeTrack)
  const timelineFocus = useAppStore(s => s.timelineFocus)
  const mode = useAppStore(s => s.mode)

  const speakerPreset = SPEAKER_TRACK_PRESET[track.type]
  const isFocusOverridden =
    (timelineFocus === 'speaker' && speakerPreset && speakerPreset.visible === false) || false
  const modePreset = TRACK_VISIBILITY_MAP[mode]?.[track.type]
  const isModeHidden = modePreset && !modePreset.visible
  const isManualHidden = !track.visible

  const dimmed = isFocusOverridden || isModeHidden
  const hidden = isManualHidden && !dimmed

  // Speaker track height matches TrackLayer calculation
  const rowHeight = (() => {
    if (track.renderer !== 'speaker-lane') return track.height
    const speakerCount = new Set(events.map(e => e.speaker).filter(Boolean)).size
    if (speakerCount === 0) return track.height
    const laneH = timelineFocus === 'speaker' ? 80 : Math.max(24, Math.floor(track.height / speakerCount))
    return Math.max(track.height, speakerCount * laneH)
  })()

  const handleResizeStart = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const startY = e.clientY
    const startH = track.height

    const onMove = (ev: MouseEvent) => {
      const newH = Math.max(track.minHeight, Math.min(track.maxHeight ?? 200, startH + (ev.clientY - startY)))
      resizeTrack(track.id, newH)
    }

    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  return (
    <Box sx={{
      height: rowHeight, display: 'flex', alignItems: 'center', gap: 0,
      borderBottom: '1px solid rgba(255,255,255,0.06)',
      px: 0.5, opacity: hidden ? 0.3 : dimmed ? 0.4 : 1,
      transition: 'opacity 0.2s',
      bgcolor: hidden ? 'transparent' : 'rgba(255,255,255,0.02)',
      position: 'relative',
    }}>
      {/* Color indicator */}
      <Box sx={{
        width: 4, height: 14, borderRadius: 1,
        bgcolor: track.color || 'grey.500',
        flexShrink: 0, mr: 0.75,
      }} />

      {/* Track label */}
      <Typography noWrap sx={{
        fontSize: '0.7rem', color: 'grey.300', fontWeight: 500,
        flex: 1, minWidth: 0, mr: 0.5,
        userSelect: 'none',
      }}>
        {track.label}
      </Typography>

      {/* Visibility + Lock */}
      <Box sx={{ display: 'flex', gap: 0, flexShrink: 0 }}>
        <Tooltip title={track.visible ? '隐藏轨道' : '显示轨道'} placement="top">
          <IconButton size="small" onClick={() => toggleVisibility(track.id)}
            sx={{ p: 0.1, '& .MuiSvgIcon-root': { fontSize: ICON_SIZE } }}>
            {track.visible ? <VisibilityIcon fontSize="inherit" /> : <VisibilityOffIcon fontSize="inherit" />}
          </IconButton>
        </Tooltip>
        <Tooltip title={track.locked ? '解锁轨道' : '锁定轨道'} placement="top">
          <IconButton size="small" onClick={() => toggleLock(track.id)}
            sx={{ p: 0.1, '& .MuiSvgIcon-root': { fontSize: ICON_SIZE } }}>
            {track.locked ? <LockIcon fontSize="inherit" /> : <LockOpenIcon fontSize="inherit" />}
          </IconButton>
        </Tooltip>
      </Box>

      {/* Solo + Mute */}
      <Box sx={{ display: 'flex', gap: 0, flexShrink: 0 }}>
        <Tooltip title={track.solo ? '取消独奏' : '独奏此轨道'} placement="top">
          <IconButton size="small" onClick={() => toggleSolo(track.id)}
            sx={{
              p: 0.1, minWidth: 16,
              color: track.solo ? 'warning.main' : 'text.secondary',
            }}>
            <span style={{ fontSize: '0.55rem', fontWeight: 700, lineHeight: 1 }}>S</span>
          </IconButton>
        </Tooltip>
        {(track.type === 'tts' || track.type === 'speaker') && (
          <Tooltip title={track.muted ? '取消静音' : '静音'} placement="top">
            <IconButton size="small" onClick={() => toggleMute(track.id)}
              sx={{ p: 0.1, '& .MuiSvgIcon-root': { fontSize: ICON_SIZE } }}>
              {track.muted ? <VolumeOffIcon fontSize="inherit" /> : <VolumeUpIcon fontSize="inherit" />}
            </IconButton>
          </Tooltip>
        )}
      </Box>

      {/* Resize handle — visible line + invisible hit area */}
      <Box
        onMouseDown={handleResizeStart}
        sx={{
          position: 'absolute', bottom: -3, left: 0, right: 0, height: 8,
          cursor: 'row-resize', zIndex: 1,
        }}
      />
      {/* Visible bottom border as resize cue */}
      <Box sx={{
        position: 'absolute', bottom: -1, left: 8, right: 8, height: 1,
        bgcolor: 'rgba(255,255,255,0.2)',
        pointerEvents: 'none',
      }} />
    </Box>
  )
}

export default function TrackHeader({ events }: { events: EventViewModel[] }) {
  const tracks = useAppStore(s => s.tracks)

  return (
    <Box sx={{ width: HEADER_W, minWidth: HEADER_W, bgcolor: 'rgba(255,255,255,0.02)' }} data-track-header="true">
      {tracks.map(track => (
        <TrackHeaderRow key={track.id} track={track} events={events} />
      ))}
    </Box>
  )
}
