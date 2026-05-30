import { useRef, useCallback, useState } from 'react'
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

interface Props {
  events: EventViewModel[]
  coord: TimelineCoordAPI
  totalDuration: number
  canvasWidth: number
}

function confidenceColor(conf: number): string {
  if (conf >= 0.9) return '#4CAF50'
  if (conf >= 0.7) return '#FFC107'
  if (conf >= 0.5) return '#FF9800'
  return '#F44336'
}

export default function TimelineMinimap({ events, coord, totalDuration, canvasWidth }: Props) {
  const tracks = useAppStore(s => s.tracks)
  const setPlayhead = useAppStore(s => s.setPlayhead)
  const barRef = useRef<HTMLDivElement | null>(null)
  const [dragging, setDragging] = useState(false)

  const { visibleRange } = coord
  const viewLeft = Math.max(0, Math.min(canvasWidth - 4, (visibleRange.startTime / totalDuration) * canvasWidth))
  const viewWidth = Math.max(4, Math.min(canvasWidth - viewLeft, ((visibleRange.endTime - visibleRange.startTime) / totalDuration) * canvasWidth))

  const visibleMinimapTracks = MINIMAP_TRACKS.filter(mt => {
    const t = tracks.find(tr => tr.type === mt.type)
    return t?.visible !== false
  })
  const labelW = 36

  const handleClick = useCallback((e: React.MouseEvent) => {
    if (dragging) return
    const rect = barRef.current?.getBoundingClientRect()
    if (!rect) return
    const x = e.clientX - rect.left - labelW
    if (x < 0) return
    const t = Math.max(0, Math.min(totalDuration, (x / (canvasWidth - labelW)) * totalDuration))
    setPlayhead(t)
    coord.centerOnTime(t)
  }, [dragging, totalDuration, canvasWidth, setPlayhead, labelW, coord])

  const handleViewDrag = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragging(true)
    const startX = e.clientX
    const startTime = visibleRange.startTime
    const minimapW = canvasWidth - labelW

    const onMove = (ev: MouseEvent) => {
      const dx = ev.clientX - startX
      const dt = (dx / minimapW) * totalDuration
      const newStart = Math.max(0, Math.min(totalDuration - (visibleRange.endTime - visibleRange.startTime), startTime + dt))
      coord.centerOnTime(newStart + (visibleRange.endTime - visibleRange.startTime) / 2)
    }

    const onUp = () => {
      setDragging(false)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [coord, totalDuration, canvasWidth, labelW, visibleRange])

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

  const rowH = 5
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
        bgcolor: 'rgba(0,0,0,0.6)', zIndex: 3,
      }}>
        {visibleMinimapTracks.map(mt => {
          const trk = tracks.find(t => t.type === mt.type)
          return (
            <Box key={mt.type} sx={{
              width: '100%', height: rowH, borderRadius: 0.5,
              bgcolor: trk?.color || 'grey.600',
            }} />
          )
        })}
      </Box>

      {/* Track rows */}
      <Box sx={{ position: 'absolute', left: labelW + 2, top: 2, right: 2, bottom: 2 }}>
        {visibleMinimapTracks.map((mt, rowIdx) => {
          const y = rowIdx * (rowH + GAP)
          const segs = buildSegments(mt.type)
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
