import { Box } from '@mui/material'
import { useAppStore } from '../../store/useAppStore'
import type { TrackDefinition } from '../../types/timeline'
import type { EventViewModel, WaveformData, TrackWaveformData } from '../../types'
import type { TimelineCoordAPI } from '../../hooks/useTimelineCoordinates'
import SpeakerLane from '../SpeakerLane'
import WaveformLayer from '../sections/WaveformLayer'
import EventDragHandler from './EventDragHandler'
import TTSWaveformTrack from './TTSWaveformTrack'
import { useVirtualEvents } from '../../hooks/useVirtualEvents'

interface Props {
  track: TrackDefinition
  coord: TimelineCoordAPI
  events: EventViewModel[]
  totalDuration: number
  canvasWidth: number
  waveformData?: WaveformData | null
  ttsWaveforms?: TrackWaveformData[]
  dimmedEventIds?: Set<string>
  onEventClick: (eventId: string, e: React.MouseEvent) => void
  onEventDblClick: (eventId: string) => void
  onEventContextMenu: (eventId: string, e: React.MouseEvent) => void
}

const LANE_COLORS = ['#2196F3', '#4CAF50', '#FF9800', '#9C27B0', '#00BCD4', '#E91E63']

export default function TrackLayer({ track, coord, events, totalDuration, canvasWidth, waveformData, ttsWaveforms, dimmedEventIds, onEventClick, onEventDblClick, onEventContextMenu }: Props) {
  const selectedEventIds = useAppStore(s => s.selectedEventIds)
  const speakerFocus = useAppStore(s => s.speakerFocus)
  const pendingDrafts = useAppStore(s => s.pendingDrafts)
  const appliedPatches = useAppStore(s => s.appliedPatches)
  const trackScrollLeft = useAppStore(s => s.trackScrollLeft)
  const tracks = useAppStore(s => s.tracks)

  const appliedEventIds = new Set(appliedPatches.flatMap(p => p.targets))

  const hasSoloTrack = tracks.some(t => t.solo)
  const isDimmed = hasSoloTrack && !track.solo
  const timelineFocus = useAppStore(s => s.timelineFocus)

  // Compute actual container height for speaker lanes
  const containerHeight = (() => {
    if (track.renderer !== 'speaker-lane') return track.height
    const speakerCount = new Set(events.map(e => e.speaker).filter(Boolean)).size
    if (speakerCount === 0) return track.height
    const rowH = timelineFocus === 'speaker' ? 80 : Math.max(24, Math.floor(track.height / speakerCount))
    return Math.max(track.height, speakerCount * rowH)
  })()

  // Compute virtual events at top level (hooks must not be conditional)
  const baseEvents = track.type === 'diff'
    ? events.filter(e => pendingDrafts.has(e.id))
    : events
  const { virtualEvents } = useVirtualEvents({
    events: baseEvents,
    visibleStartTime: coord.visibleRange.startTime,
    visibleEndTime: coord.visibleRange.endTime,
    bufferSec: 2,
    totalDuration,
    pixelsPerSec: coord.pixelsPerSec,
  })

  const renderContent = () => {
    switch (track.renderer) {
      case 'event-block': {
        return (
          <Box sx={{
            position: 'relative', width: totalDuration * coord.pixelsPerSec, height: track.height,
            transform: `translateX(${-trackScrollLeft}px)`,
          }}>
            {virtualEvents.map(evt => {
              // Off-screen culling by time
              const vs = coord.visibleRange.startTime
              const ve = coord.visibleRange.endTime
              if (evt.end < vs - 5 || evt.start > ve + 5) return null

              const laneIdx = evt.speaker === 'SPEAKER_00' ? 0 : evt.speaker === 'SPEAKER_01' ? 1 : 0
              const hasDraft = pendingDrafts.has(evt.id)
              const isSelected = selectedEventIds.includes(evt.id)
              const dimmed = timelineFocus === 'speaker' && speakerFocus != null && evt.speaker !== (speakerFocus as any)?.speaker
              const filtered = dimmedEventIds?.has(evt.id) ?? false

              return (
                <EventDragHandler
                  key={evt.id}
                  event={evt}
                  coord={coord}
                  laneColor={LANE_COLORS[laneIdx % LANE_COLORS.length]}
                  laneHeight={track.height}
                  isSelected={isSelected}
                  isMultiSelected={dimmed || isDimmed || filtered}
                  hasDraft={hasDraft}
                  allEvents={events}
                  hasAppliedPatch={appliedEventIds.has(evt.id)}
                  isOverlong={evt.end - evt.start > 8}
                  readOnly={track.locked}
                  onClick={(e) => onEventClick(evt.id, e)}
                  onDoubleClick={() => onEventDblClick(evt.id)}
                  onContextMenu={(e) => { e.preventDefault(); onEventContextMenu(evt.id, e) }}
                />
              )
            })}
          </Box>
        )
      }

      case 'speaker-lane': {
        const bySpeaker = new Map<string, EventViewModel[]>()
        for (const evt of events) {
          const key = evt.speaker || ''
          if (!key) continue
          if (!bySpeaker.has(key)) bySpeaker.set(key, [])
          bySpeaker.get(key)!.push(evt)
        }
        // No real speakers — show placeholder
        if (bySpeaker.size === 0) {
          return (
            <SpeakerLane
              lanes={[]}
              timeToPixel={(t: number) => coord.timeToPixel(t) + trackScrollLeft}
              pixelsPerSec={coord.pixelsPerSec}
              laneHeight={track.height}
            />
          )
        }
        const lanes = Array.from(bySpeaker.entries()).map(([speaker, evts], i) => ({
          speaker,
          displayName: evts[0]?.displayName || speaker,
          color: LANE_COLORS[i % LANE_COLORS.length],
          locked: track.locked,
          events: evts,
        }))
        const totalH = Math.max(track.height, lanes.length * (timelineFocus === 'speaker' ? 80 : track.height))
        return (
          <SpeakerLane
            lanes={lanes}
            timeToPixel={(t: number) => coord.timeToPixel(t) + trackScrollLeft}
            pixelsPerSec={coord.pixelsPerSec}
            laneHeight={timelineFocus === 'speaker' ? 80 : Math.max(24, Math.floor(track.height / lanes.length))}
            expanded={timelineFocus === 'speaker'}
          />
        )
      }

      case 'waveform':
        return (
          <WaveformLayer
            width={canvasWidth}
            height={track.height}
            peaks={waveformData?.peaks || []}
            duration={totalDuration}
            pixelsPerSec={coord.pixelsPerSec}
          />
        )

      case 'tts-waveform':
        return (
          <TTSWaveformTrack
            track={track}
            coord={coord}
            canvasWidth={canvasWidth}
            waveforms={ttsWaveforms || []}
            onToggleMute={(id) => useAppStore.getState().toggleTrackMute(id)}
          />
        )

      default:
        return null
    }
  }

  return (
    <Box sx={{
      height: containerHeight, position: 'relative',
      borderBottom: '1px solid rgba(255,255,255,0.06)',
      opacity: !track.visible ? 0 : isDimmed ? 0.2 : track.muted ? 0.5 : 1,
      pointerEvents: !track.visible ? 'none' : track.locked || track.muted ? 'none' : isDimmed ? 'none' : 'auto',
      overflow: 'hidden',
    }}>
      {track.visible ? renderContent() : null}
      {track.locked && (
        <Box sx={{
          position: 'absolute', inset: 0, bgcolor: 'rgba(0,0,0,0.15)', zIndex: 5,
          pointerEvents: 'none',
        }} />
      )}
    </Box>
  )
}
