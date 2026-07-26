import { Box } from '@mui/material'
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
  totalDuration: number
  canvasWidth: number
  speakerLanes?: SpeakerMinimapLane[]
  hideLabels?: boolean
}

function confidenceColor(conf: number): string {
  if (conf >= 0.9) return '#4CAF50'
  if (conf >= 0.7) return '#FFC107'
  if (conf >= 0.5) return '#FF9800'
  return '#F44336'
}

export default function TimelineMinimap({ events, totalDuration, canvasWidth, speakerLanes, hideLabels }: Props) {
  const isSpeakerMode = speakerLanes && speakerLanes.length > 0

  const visibleMinimapTracks = isSpeakerMode
    ? speakerLanes.map(l => ({ type: l.speaker as TrackDefinition['type'], label: l.displayName || l.speaker, color: l.color }))
    : MINIMAP_TRACKS

  const labelW = hideLabels ? 0 : isSpeakerMode ? 64 : 36

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
        if (trackType === 'source') color = confidenceColor(evt.confidence ?? 0.9)
        else if (trackType === 'translation') {
          if (evt.visualState?.hasAiSuggestion) color = '#FF9800'
          else if (evt.visualState?.hasPatches) color = '#4CAF50'
          else color = 'rgba(255,255,255,0.12)'
        } else if (trackType === 'speaker') {
          const spIdx = (evt.speaker || '0').charCodeAt(0) || 0
          color = SPEAKER_COLORS[spIdx % SPEAKER_COLORS.length]
        }
      }

      if (color !== lastColor) {
        if (lastColor && segStart < px) segs.push({ x: segStart, w: px - segStart, color: lastColor })
        segStart = px
        lastColor = color
      }
    }
    if (lastColor && segStart < canvasWidth) segs.push({ x: segStart, w: canvasWidth - segStart, color: lastColor })
    return segs
  }

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
    <Box sx={{
      height: totalH, minHeight: totalH,
      width: '100%', position: 'relative',
      bgcolor: '#e8ecf4',
      borderTop: '1px solid #d0d5e0',
      flexShrink: 0,
    }}>
      <Box sx={{
        position: 'absolute', left: 0, top: 0, bottom: 0,
        width: labelW, display: 'flex', flexDirection: 'column',
        justifyContent: 'center', gap: 0.25, px: 0.5,
        bgcolor: isSpeakerMode ? '#dce2f0' : 'rgba(0,0,0,0.6)',
        zIndex: 3, overflow: 'hidden',
      }}>
        {visibleMinimapTracks.map(mt => {
          const color = (mt as any).color || 'grey.600'
          return isSpeakerMode ? (
            <Box key={mt.type} sx={{ display: 'flex', alignItems: 'center', gap: 0.5, height: rowH, minHeight: rowH }}>
              <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: color, flexShrink: 0 }} />
              <Box component="span" sx={{ fontSize: '0.55rem', color: '#1e293b', lineHeight: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {(mt as any).label || mt.type}
              </Box>
            </Box>
          ) : (
            <Box key={mt.type} sx={{ width: '100%', height: rowH, borderRadius: 0.5, bgcolor: color }} />
          )
        })}
      </Box>

      <Box sx={{ position: 'absolute', left: labelW + 2, top: 2, right: 2, bottom: 2 }}>
        {visibleMinimapTracks.map((mt, rowIdx) => {
          const y = rowIdx * (rowH + GAP)
          const segs = isSpeakerMode
            ? buildSpeakerSegments((mt as any).color || SPEAKER_COLORS[rowIdx % SPEAKER_COLORS.length], (speakerLanes![rowIdx]?.segments || []))
            : buildSegments(mt.type)
          return (
            <Box key={mt.type} sx={{ position: 'absolute', left: 0, top: y, width: '100%', height: rowH }}>
              <svg width="100%" height={rowH} style={{ display: 'block' }}>
                {segs.map((s, i) => <rect key={i} x={s.x} y={0} width={Math.max(1, s.w)} height={rowH} fill={s.color} rx={0.5} />)}
              </svg>
            </Box>
          )
        })}
      </Box>
    </Box>
  )
}
