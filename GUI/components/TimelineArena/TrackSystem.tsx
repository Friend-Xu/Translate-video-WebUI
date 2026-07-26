import { useRef, useCallback, useState, useMemo } from 'react'
import { Box } from '@mui/material'
import { useAppStore } from '../../store/useAppStore'
import type { TimelineCoordAPI } from '../../hooks/useTimelineCoordinates'
import type { EventViewModel, WaveformData, TrackWaveformData } from '../../types'
import TimeRuler from './TimeRuler'
import TrackHeader from './TrackHeader'
import TrackLayer from './TrackLayer'

const HEADER_W = 120

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
  const setPlayhead = useAppStore(s => s.setPlayhead)
  const [scrubTime, setScrubTime] = useState<number | null>(null)

  const trackAreaRef = useRef<HTMLDivElement | null>(null)

  const playheadX = coord.timeToPixel(playheadPosition)

  // Semantic markers from events
  const markers = useMemo(() => {
    const result: Array<{ time: number; label: string; color: string }> = []
    for (const evt of events) {
      if (evt.confidence < 0.5) {
        result.push({ time: evt.start, label: `低置信度: ${evt.confidence.toFixed(2)}`, color: '#F44336' })
      } else if (evt.confidence < 0.7) {
        result.push({ time: evt.start, label: `中置信度: ${evt.confidence.toFixed(2)}`, color: '#FF9800' })
      }
      if (evt.visualState?.hasAiSuggestion) {
        result.push({ time: evt.start, label: 'AI 建议', color: '#FFEB3B' })
      }
      if (evt.visualState?.hasPatches) {
        result.push({ time: evt.start, label: '有补丁', color: '#4CAF50' })
      }
      if (evt.end - evt.start > 8) {
        result.push({ time: evt.start, label: '超长段', color: '#9C27B0' })
      }
    }
    return result
  }, [events])

  // Playhead drag
  const handlePlayheadMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const rect = trackAreaRef.current?.getBoundingClientRect()
    if (!rect) return
    const contentLeft = rect.left + HEADER_W

    const onMove = (ev: MouseEvent) => {
      const x = ev.clientX - contentLeft
      const t = Math.max(0, Math.min(totalDuration, coord.pixelToTime(x)))
      setPlayhead(t)
    }

    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [coord, totalDuration, setPlayhead])

  // Time ruler click to seek — set playhead and scroll view
  const handleRulerClick = useCallback((time: number) => {
    setPlayhead(time)
    coord.scrollToTime(time)
  }, [setPlayhead, coord])

  // Time ruler hover — show scrub line
  const handleRulerHover = useCallback((time: number | null) => {
    setScrubTime(time)
  }, [])

  const scrubX = scrubTime != null ? coord.timeToPixel(scrubTime) : null

  return (
    <Box ref={trackAreaRef} sx={{ height: '100%', width: '100%', position: 'relative', overflow: 'hidden' }}>
      {/* Time ruler row */}
      <Box sx={{ display: 'flex', flexShrink: 0 }}>
        <Box sx={{ width: HEADER_W, minWidth: HEADER_W, bgcolor: '#1e1e1e', borderBottom: '1px solid rgba(255,255,255,0.08)' }} />
        <Box sx={{ flexGrow: 1 }}>
          <TimeRuler
            coord={coord}
            totalDuration={totalDuration}
            canvasWidth={canvasWidth}
            onClick={handleRulerClick}
            onHover={handleRulerHover}
            scrubX={scrubX}
            markers={markers}
            onMarkerClick={(t) => setPlayhead(t)}
          />
        </Box>
      </Box>

      {/* Track rows */}
      <Box sx={{ display: 'flex', overflow: 'hidden' }}>
        <TrackHeader />
        <Box sx={{ flexGrow: 1, overflow: 'hidden' }}>
          {tracks.map(track => (
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

      {/* Playhead — draggable handle + line */}
      <Box sx={{
        position: 'absolute', top: 0, bottom: 0,
        left: HEADER_W + playheadX,
        width: 0, zIndex: 25, pointerEvents: 'none',
        display: 'flex', flexDirection: 'column', alignItems: 'center',
      }}>
        {/* Drag handle — triangle */}
        <Box
          onMouseDown={handlePlayheadMouseDown}
          sx={{
            width: 0, height: 0,
            borderLeft: '7px solid transparent',
            borderRight: '7px solid transparent',
            borderTop: '10px solid #FF5252',
            cursor: 'col-resize',
            pointerEvents: 'auto',
            filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.5))',
          }}
        />
        {/* Vertical line */}
        <Box sx={{
          width: 2,
          flex: 1,
          bgcolor: '#FF5252',
          boxShadow: '0 0 6px rgba(255,82,82,0.6)',
        }} />
      </Box>
    </Box>
  )
}
