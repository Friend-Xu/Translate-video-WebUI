import { Box, IconButton } from '@mui/material'
import PlayArrowIcon from '@mui/icons-material/PlayArrowRounded'
import VolumeOffIcon from '@mui/icons-material/VolumeOffRounded'
import VolumeUpIcon from '@mui/icons-material/VolumeUpRounded'
import WaveformLayer from '../sections/WaveformLayer'
import type { TrackDefinition } from '../../types/timeline'
import type { TrackWaveformData } from '../../types'
import type { TimelineCoordAPI } from '../../hooks/useTimelineCoordinates'

interface Props {
  track: TrackDefinition
  coord: TimelineCoordAPI
  canvasWidth: number
  waveforms: TrackWaveformData[]
  onToggleMute: (trackId: string) => void
}

export default function TTSWaveformTrack({ track, coord, canvasWidth, waveforms, onToggleMute }: Props) {
  const trackWaves = waveforms.filter(w => w.trackId === track.id || w.engine)

  return (
    <Box sx={{ height: track.height, position: 'relative', overflow: 'hidden' }}>
      <Box sx={{
        position: 'absolute', left: 4, top: 2, zIndex: 5,
        display: 'flex', gap: 0.25,
      }}>
        <IconButton size="small" sx={{ p: 0.25, '& .MuiSvgIcon-root': { fontSize: 14 } }}>
          <PlayArrowIcon fontSize="inherit" />
        </IconButton>
        <IconButton size="small" onClick={() => onToggleMute(track.id)}
          sx={{ p: 0.25, '& .MuiSvgIcon-root': { fontSize: 14 } }}>
          {track.muted ? <VolumeOffIcon fontSize="inherit" /> : <VolumeUpIcon fontSize="inherit" />}
        </IconButton>
      </Box>

      {trackWaves.length > 0 ? (
        trackWaves.map((w, i) => (
          <Box key={w.trackId || i} sx={{
            position: 'absolute', top: i * (track.height / trackWaves.length),
            left: 0, height: track.height / trackWaves.length,
          }}>
            <WaveformLayer
              width={canvasWidth}
              height={track.height / trackWaves.length}
              peaks={w.peaks}
              duration={w.duration}
              pixelsPerSec={coord.pixelsPerSec}
              silenceThreshold={0.05}
            />
          </Box>
        ))
      ) : (
        <Box sx={{
          height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <span style={{ fontSize: '0.65rem', color: 'rgba(255,255,255,0.3)' }}>
            TTS 波形 — 运行 TTS 后生成
          </span>
        </Box>
      )}
    </Box>
  )
}
