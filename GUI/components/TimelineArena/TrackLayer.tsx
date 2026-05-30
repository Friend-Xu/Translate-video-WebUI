import { Box } from '@mui/material'
import { useEffect } from 'react'
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
  const setPlayhead = useAppStore(s => s.setPlayhead)
  const resizeTrack = useAppStore(s => s.resizeTrack)

  const MIN_SPEAKER_HEIGHT = 40

  // Auto-resize speaker track height based on speaker count
  const speakerCount = track.renderer === 'speaker-lane'
    ? new Set(events.map(e => e.speaker).filter(Boolean)).size
    : 0
  useEffect(() => {
    if (track.renderer !== 'speaker-lane' || speakerCount <= 1) return
    if (timelineFocus === 'speaker') return // don't override focus mode
    const needed = speakerCount * MIN_SPEAKER_HEIGHT
    if (track.height !== needed) {
      resizeTrack(track.id, needed)
    }
  }, [track.renderer, speakerCount, timelineFocus, track.id, track.height, resizeTrack])

  const containerHeight = track.renderer === 'speaker-lane' && speakerCount > 1 && timelineFocus === 'speaker'
    ? speakerCount * 80
    : track.height

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
        if (bySpeaker.size === 0) {
          return (
            <SpeakerLane lanes={[]} timeToPixel={(t: number) => coord.timeToPixel(t) + trackScrollLeft}
              pixelsPerSec={coord.pixelsPerSec} laneHeight={track.height} />
          )
        }
        // Focus mode: expanded SpeakerLane
        if (timelineFocus === 'speaker') {
          const lanes = Array.from(bySpeaker.entries()).map(([speaker, evts], i) => ({
            speaker, displayName: evts[0]?.displayName || speaker,
            color: LANE_COLORS[i % LANE_COLORS.length], locked: track.locked, events: evts,
          }))
          return (
            <SpeakerLane lanes={lanes} timeToPixel={(t: number) => coord.timeToPixel(t) + trackScrollLeft}
              pixelsPerSec={coord.pixelsPerSec} laneHeight={80} expanded />
          )
        }
        // Normal mode: each speaker = name row + blocks row, stacked
        const speakers = Array.from(bySpeaker.entries()).map(([speaker, evts], i) => ({
          speaker,
          displayName: evts[0]?.displayName || speaker,
          color: LANE_COLORS[i % LANE_COLORS.length],
          events: evts,
        }))
        const spH = Math.floor(track.height / speakers.length)
        const labelH = Math.max(10, Math.floor(spH * 0.5))
        const blockH = spH - labelH
        const canvasW = totalDuration * coord.pixelsPerSec
        return (
          <Box sx={{ height: track.height, position: 'relative', width: canvasW,
            transform: `translateX(${-trackScrollLeft}px)`, overflow: 'hidden' }}>
            {speakers.map((sp, si) => {
              const top = si * spH
              return (
                <Box key={sp.speaker}>
                  {/* Name row */}
                  <Box sx={{
                    position: 'absolute', left: 0, top, height: labelH, width: canvasW,
                    display: 'flex', alignItems: 'center',
                  }}>
                    <Box sx={{
                      position: 'sticky', left: 0,
                      px: 0.5, fontSize: '0.7rem', color: sp.color, fontWeight: 600,
                      bgcolor: 'rgba(0,0,0,0.6)', borderRadius: 0.5,
                      whiteSpace: 'nowrap', lineHeight: `${labelH}px`,
                      zIndex: 2,
                    }}>
                      {sp.displayName}
                    </Box>
                  </Box>
                  {/* Blocks row */}
                  <Box sx={{ position: 'absolute', left: 0, top: top + labelH, height: blockH, width: canvasW }}>
                    {sp.events.map(evt => {
                      const left = coord.timeToPixel(evt.start)
                      const w = Math.max(2, (evt.end - evt.start) * coord.pixelsPerSec)
                      if (left + w < 0 || left > canvasW + 100) return null
                      return (
                        <Box key={evt.id} sx={{
                          position: 'absolute', left, top: 0, height: '100%', width: w,
                          bgcolor: `${sp.color}66`, borderRadius: 0.25,
                          borderLeft: `2px solid ${sp.color}`,
                          cursor: 'pointer',
                          '&:hover': { filter: 'brightness(1.4)', zIndex: 3 },
                        }}
                          onClick={(e) => { setPlayhead(evt.start); onEventClick(evt.id, e) }}
                          onDoubleClick={() => onEventDblClick(evt.id)}
                          onContextMenu={(e) => { e.preventDefault(); onEventContextMenu(evt.id, e) }}
                        />
                      )
                    })}
                  </Box>
                </Box>
              )
            })}
          </Box>
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
      borderBottom: '1px solid #d0d5e0',
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
