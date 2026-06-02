import { useRef, useCallback } from 'react'
import { Box } from '@mui/material'
import { useAppStore } from '../../store/useAppStore'
import type { TimelineCoordAPI } from '../../hooks/useTimelineCoordinates'
import type { EventViewModel } from '../../types'
import type { TrackDefinition } from '../../types/timeline'

const GAP = 1

const MINIMAP_TRACKS: Array<{ type: TrackDefinition['type']; label: string }> = [
  { type: 'source', label: '原文' },
  { type: 'translation', label: '译文' },
  { type: 'speaker', label: '说话人' },
]

const SPEAKER_COLORS = ['#2196F3', '#4CAF50', '#FF9800', '#9C27B0', '#00BCD4', '#E91E63']

interface SpeakerMinimapLane {
  speaker: string
  displayName: string
  color: string
  segments: Array<{ start: number; end: number }>
}

interface Props {
  events: EventViewModel[]
  coord: TimelineCoordAPI
  totalDuration: number
  canvasWidth: number
  /** When provided, viewport position is read from DOM scroll instead of coord.visibleRange */
  scrollContainerRef?: React.RefObject<HTMLDivElement | null>
  /** Speaker lanes — when provided, minimap renders speaker-colored rows instead of event tracks */
  speakerLanes?: SpeakerMinimapLane[]
  /** Explicit scroll position — bypasses DOM ref read for better sync */
  domScrollLeft?: number
  domClientWidth?: number
  /** Callback for click/drag navigation — when provided, replaces direct DOM scroll manipulation */
  onNavigate?: (time: number) => void
  /** Hide the track-type label column (useful when embedded in non-timeline views) */
  hideLabels?: boolean
}

function confidenceColor(conf: number): string {
  if (conf >= 0.9) return '#4CAF50'
  if (conf >= 0.7) return '#FFC107'
  if (conf >= 0.5) return '#FF9800'
  return '#F44336'
}

export default function TimelineMinimap({ events, coord, totalDuration, canvasWidth, scrollContainerRef, speakerLanes, domScrollLeft: explicitScrollLeft, domClientWidth: explicitClientWidth, onNavigate, hideLabels }: Props) {
  const tracks = useAppStore(s => s.tracks)
  const barRef = useRef<HTMLDivElement | null>(null)
  const dragRef = useRef(false)

  const { visibleRange } = coord

  // Stable refs for values used in drag handler (prevents re-creation on every render)
  const coordRef = useRef(coord)
  coordRef.current = coord
  const viewRef = useRef({ viewStartTime: 0, viewEndTime: 0 })
  viewRef.current = { viewStartTime: visibleRange.startTime, viewEndTime: visibleRange.endTime }

  // When explicit scroll props are provided, use them (better sync).
  // Otherwise fall back to DOM ref read or coord.visibleRange.
  const containerEl = scrollContainerRef?.current ?? null
  const domScrollLeft = explicitScrollLeft ?? containerEl?.scrollLeft ?? 0
  const domClientWidth = explicitClientWidth ?? containerEl?.clientWidth ?? canvasWidth
  const totalCanvasW = totalDuration * coord.pixelsPerSec

  const viewStartTime = containerEl
    ? (totalCanvasW > 0 ? (domScrollLeft / totalCanvasW) * totalDuration : 0)
    : visibleRange.startTime
  const viewEndTime = containerEl
    ? (totalCanvasW > 0 ? ((domScrollLeft + domClientWidth) / totalCanvasW) * totalDuration : totalDuration)
    : visibleRange.endTime

  const viewLeft = Math.max(0, Math.min(canvasWidth - 4, (viewStartTime / totalDuration) * canvasWidth))
  const viewWidth = Math.max(4, Math.min(canvasWidth - viewLeft, ((viewEndTime - viewStartTime) / totalDuration) * canvasWidth))

  const isSpeakerMode = speakerLanes && speakerLanes.length > 0

  const visibleMinimapTracks = isSpeakerMode
    ? speakerLanes.map(l => ({ type: l.speaker as TrackDefinition['type'], label: l.displayName || l.speaker, color: l.color }))
    : MINIMAP_TRACKS.filter(mt => {
        const t = tracks.find(tr => tr.type === mt.type)
        return t?.visible !== false
      })
  const labelW = hideLabels ? 0 : isSpeakerMode ? 64 : 36

  const handleClick = useCallback((e: React.MouseEvent) => {
    if (dragRef.current) { dragRef.current = false; return }
    const rect = barRef.current?.getBoundingClientRect()
    if (!rect) return
    const x = e.clientX - rect.left - labelW
    if (x < 0) return
    const t = Math.max(0, Math.min(totalDuration, (x / (canvasWidth - labelW)) * totalDuration))
    if (onNavigate) {
      onNavigate(t)
    } else if (scrollContainerRef?.current) {
      const tw = totalDuration * coordRef.current.pixelsPerSec
      scrollContainerRef.current.scrollLeft = (t / totalDuration) * tw - (scrollContainerRef.current.clientWidth / 2)
    } else {
      coordRef.current.centerOnTime(t)
    }
  }, [totalDuration, canvasWidth, labelW, scrollContainerRef, onNavigate])

  const handleViewDrag = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    dragRef.current = false
    const c = coordRef.current
    const v = viewRef.current
    const startX = e.clientX
    const startTime = v.viewStartTime
    const viewDuration = v.viewEndTime - v.viewStartTime
    const minimapW = canvasWidth - labelW

    const onMove = (ev: MouseEvent) => {
      dragRef.current = true
      const dx = ev.clientX - startX
      const dt = (dx / minimapW) * totalDuration
      const newStart = Math.max(0, Math.min(totalDuration - viewDuration, startTime + dt))

      if (onNavigate) {
        onNavigate(newStart + viewDuration / 2)
      } else if (scrollContainerRef?.current) {
        const tw = totalDuration * c.pixelsPerSec
        scrollContainerRef.current.scrollLeft = (newStart / totalDuration) * tw
      } else {
        c.centerOnTime(newStart + viewDuration / 2)
      }
    }

    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [totalDuration, canvasWidth, labelW, scrollContainerRef, onNavigate])

  // Build colored segments for a track type
  const buildSegments = (trackType: string) => {
    const step = Math.max(2, Math.floor(canvasWidth / 300))
    const segs: Array<{ x: number; w: number; color: string }> = []
    let lastColor = ''
    let segStart = 0

    for (let px = 0; px < canvasWidth; px += step) {
      const t = (px / canvasWidth) * totalDuration
      const evt = events.find(e => t >= e.start && t < e.end)
      let color = 'transparent'

      if (evt) {
        if (trackType === 'source') {
          color = confidenceColor(evt.confidence ?? 0.9)
        } else if (trackType === 'translation') {
          if (evt.visualState?.hasAiSuggestion) color = '#FF9800'
          else if (evt.visualState?.hasPatches) color = '#4CAF50'
          else color = 'rgba(255,255,255,0.12)'
        } else if (trackType === 'speaker') {
          const spIdx = (evt.speaker || '0').charCodeAt(0) || 0
          color = SPEAKER_COLORS[spIdx % SPEAKER_COLORS.length]
        }
      }

      if (color !== lastColor) {
        if (lastColor && segStart < px) {
          segs.push({ x: segStart, w: px - segStart, color: lastColor })
        }
        segStart = px
        lastColor = color
      }
    }
    if (lastColor && segStart < canvasWidth) {
      segs.push({ x: segStart, w: canvasWidth - segStart, color: lastColor })
    }
    return segs
  }

  // Build colored segments for speaker lanes (faster: O(segments) vs O(pixels))
  const buildSpeakerSegments = (laneColor: string, segments: Array<{ start: number; end: number }>) => {
    return segments.map((seg, i) => ({
      x: (seg.start / totalDuration) * canvasWidth,
      w: Math.max(1, ((seg.end - seg.start) / totalDuration) * canvasWidth),
      color: laneColor,
      key: i,
    }))
  }

  const rowH = isSpeakerMode ? 14 : 5
  const totalH = visibleMinimapTracks.length * (rowH + GAP) + 4

  return (
    <Box
      ref={barRef}
      onClick={handleClick}
      sx={{
        height: totalH, minHeight: totalH,
        width: '100%', position: 'relative',
        bgcolor: '#e8ecf4',
        borderTop: '1px solid #d0d5e0',
        cursor: 'pointer',
        flexShrink: 0,
      }}
    >
      {/* Labels */}
      <Box sx={{
        position: 'absolute', left: 0, top: 0, bottom: 0,
        width: labelW, display: 'flex', flexDirection: 'column',
        justifyContent: 'center', gap: 0.25, px: 0.5,
        bgcolor: isSpeakerMode ? '#dce2f0' : 'rgba(0,0,0,0.6)',
        zIndex: 3, overflow: 'hidden',
      }}>
        {visibleMinimapTracks.map(mt => {
          const color = (mt as any).color || tracks.find(t => t.type === mt.type)?.color || 'grey.600'
          return isSpeakerMode ? (
            <Box key={mt.type} sx={{
              display: 'flex', alignItems: 'center', gap: 0.5,
              height: rowH, minHeight: rowH,
            }}>
              <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: color, flexShrink: 0 }} />
              <Box component="span" sx={{
                fontSize: '0.55rem', color: '#1e293b', lineHeight: 1,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {(mt as any).label || mt.type}
              </Box>
            </Box>
          ) : (
            <Box key={mt.type} sx={{
              width: '100%', height: rowH, borderRadius: 0.5,
              bgcolor: color,
            }} />
          )
        })}
      </Box>

      {/* Track rows */}
      <Box sx={{ position: 'absolute', left: labelW + 2, top: 2, right: 2, bottom: 2 }}>
        {visibleMinimapTracks.map((mt, rowIdx) => {
          const y = rowIdx * (rowH + GAP)
          const segs = isSpeakerMode
            ? buildSpeakerSegments((mt as any).color || SPEAKER_COLORS[rowIdx % SPEAKER_COLORS.length], (speakerLanes![rowIdx]?.segments || []))
            : buildSegments(mt.type)
          return (
            <Box key={mt.type} sx={{ position: 'absolute', left: 0, top: y, width: '100%', height: rowH }}>
              <svg width="100%" height={rowH} style={{ display: 'block' }}>
                {segs.map((s, i) => (
                  <rect key={i} x={s.x} y={0} width={Math.max(1, s.w)} height={rowH} fill={s.color} rx={0.5} />
                ))}
              </svg>
            </Box>
          )
        })}
      </Box>

      {/* Viewport indicator */}
      <Box
        onMouseDown={handleViewDrag}
        sx={{
          position: 'absolute', left: labelW + viewLeft, top: 0, bottom: 0,
          width: Math.max(viewWidth, 2),
          bgcolor: 'rgba(100,180,255,0.25)',
          borderLeft: '2px solid rgba(100,180,255,0.7)',
          borderRight: '2px solid rgba(100,180,255,0.7)',
          cursor: 'grab',
          zIndex: 2,
          '&:hover': { bgcolor: 'rgba(100,180,255,0.35)' },
        }}
      />
    </Box>
  )
}
