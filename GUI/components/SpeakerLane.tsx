import { Box, Typography, Chip } from '@mui/material'
import LockIcon from '@mui/icons-material/LockRounded'
import type { EventViewModel } from '../types'

interface SpeakerLaneData {
  speaker: string
  displayName: string
  color: string
  locked: boolean
  events: EventViewModel[]
}

interface Props {
  lanes: SpeakerLaneData[]
  timeToPixel: (time: number) => number
  pixelsPerSec: number
  onRenameSpeaker?: (speaker: string) => void
  laneHeight?: number
}

const DEFAULT_LANE_H = 36
const LABEL_WIDTH = 100

export default function SpeakerLane({
  lanes, timeToPixel, pixelsPerSec,
  onRenameSpeaker, laneHeight = DEFAULT_LANE_H,
}: Props) {
  if (lanes.length === 0) {
    return (
      <Box sx={{ p: 2, textAlign: 'center' }}>
        <Typography variant="body2" color="text.secondary">
          未检测到说话人 — 启用说话人分离后显示轨道
        </Typography>
      </Box>
    )
  }

  return (
    <Box>
      {lanes.map(lane => (
        <Box key={lane.speaker} sx={{
          display: 'flex', height: laneHeight,
          borderBottom: '1px solid rgba(255,255,255,0.05)',
          position: 'relative',
        }}>
          <Box sx={{
            width: LABEL_WIDTH, minWidth: LABEL_WIDTH,
            display: 'flex', alignItems: 'center', gap: 0.5, px: 1,
            bgcolor: 'rgba(0,0,0,0.3)', borderRight: '1px solid rgba(255,255,255,0.1)',
          }}>
            <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: lane.color, flexShrink: 0 }} />
            <Typography variant="caption" noWrap
              sx={{
                fontSize: '0.65rem', color: 'common.white', cursor: 'pointer',
                '&:hover': { textDecoration: 'underline' },
              }}
              onClick={() => onRenameSpeaker?.(lane.speaker)}>
              {lane.displayName}
            </Typography>
            {lane.locked && <LockIcon sx={{ fontSize: 10, color: 'grey.400', flexShrink: 0 }} />}
            <Chip label={lane.events.length} size="small"
              sx={{ fontSize: '0.55rem', height: 16, ml: 'auto', flexShrink: 0 }} />
          </Box>
          <Box sx={{ flexGrow: 1, position: 'relative', overflow: 'hidden' }}>
            {lane.events.map(evt => {
              const left = timeToPixel(evt.start)
              const w = Math.max(2, (evt.end - evt.start) * pixelsPerSec)
              return (
                <Box key={evt.id} sx={{
                  position: 'absolute', left, top: 4, height: laneHeight - 8, width: w,
                  bgcolor: `${lane.color}66`, borderRadius: 0.5,
                  borderLeft: `2px solid ${lane.color}`,
                }} />
              )
            })}
          </Box>
        </Box>
      ))}
    </Box>
  )
}
