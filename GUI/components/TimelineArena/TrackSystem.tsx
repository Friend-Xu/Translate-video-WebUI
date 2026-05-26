import { Box } from '@mui/material'
import { useAppStore } from '../../store/useAppStore'
import type { TimelineCoordAPI } from '../../hooks/useTimelineCoordinates'
import type { EventViewModel, WaveformData, TrackWaveformData } from '../../types'
import TimeRuler from './TimeRuler'
import TrackHeader from './TrackHeader'
import TrackLayer from './TrackLayer'

interface Props {
  events: EventViewModel[]
  totalDuration: number
  canvasWidth: number
  coord: TimelineCoordAPI
  waveformData?: WaveformData | null
  ttsWaveforms?: TrackWaveformData[]
  dimmedEventIds?: Set<string>
  onEventClick: (eventId: string, e: React.MouseEvent) => void
  onEventDblClick: (eventId: string) => void
  onEventContextMenu: (eventId: string, e: React.MouseEvent) => void
}

export default function TrackSystem({ events, totalDuration, canvasWidth, coord, waveformData, ttsWaveforms, dimmedEventIds, onEventClick, onEventDblClick, onEventContextMenu }: Props) {
  const tracks = useAppStore(s => s.tracks)
  const playheadPosition = useAppStore(s => s.playheadPosition)
  const toggleTrackVisibility = useAppStore(s => s.toggleTrackVisibility)
  const toggleTrackLock = useAppStore(s => s.toggleTrackLock)
  const toggleTrackSolo = useAppStore(s => s.toggleTrackSolo)
  const toggleTrackMute = useAppStore(s => s.toggleTrackMute)

  const visibleTracks = tracks.filter(t => t.visible)

  const playheadX = coord.timeToPixel(playheadPosition)

  return (
    <Box sx={{ height: '100%', width: '100%', position: 'relative', overflow: 'hidden' }}>
      {/* Time ruler + Track header row */}
      <Box sx={{ display: 'flex', position: 'sticky', top: 0, zIndex: 15 }}>
        <Box sx={{ width: 48, minWidth: 48, bgcolor: 'rgba(0,0,0,0.5)', borderBottom: '1px solid rgba(255,255,255,0.12)' }} />
        <Box sx={{ flexGrow: 1, overflow: 'hidden' }}>
          <TimeRuler coord={coord} totalDuration={totalDuration} canvasWidth={canvasWidth} />
        </Box>
      </Box>

      {/* Track rows */}
      <Box sx={{ display: 'flex', overflow: 'hidden' }}>
        <TrackHeader
          tracks={visibleTracks}
          onToggleVisibility={toggleTrackVisibility}
          onToggleLock={toggleTrackLock}
          onToggleSolo={toggleTrackSolo}
          onToggleMute={toggleTrackMute}
        />
        <Box sx={{ flexGrow: 1, overflow: 'hidden' }}>
          {visibleTracks.map(track => (
            <TrackLayer
              key={track.id}
              track={track}
              coord={coord}
              events={events}
              totalDuration={totalDuration}
              canvasWidth={canvasWidth}
              waveformData={waveformData}
              ttsWaveforms={ttsWaveforms}
              dimmedEventIds={dimmedEventIds}
              onEventClick={onEventClick}
              onEventDblClick={onEventDblClick}
              onEventContextMenu={onEventContextMenu}
            />
          ))}
        </Box>
      </Box>

      {/* Playhead line — spans all tracks */}
      {playheadX >= 0 && playheadX <= canvasWidth && (
        <Box sx={{
          position: 'absolute', top: 22, left: 48 + playheadX, bottom: 0,
          width: 2, bgcolor: '#FF5252', zIndex: 20, pointerEvents: 'none',
          boxShadow: '0 0 6px rgba(255,82,82,0.6)',
        }} />
      )}
    </Box>
  )
}
