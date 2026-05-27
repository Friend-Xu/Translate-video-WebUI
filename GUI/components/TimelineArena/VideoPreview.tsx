import { useRef, useEffect, useState, useCallback } from 'react'
import { Box, Typography, IconButton, Tooltip, Collapse } from '@mui/material'
import ExpandLessIcon from '@mui/icons-material/ExpandLessRounded'
import ExpandMoreIcon from '@mui/icons-material/ExpandMoreRounded'
import type { EventViewModel } from '../../types'

interface Props {
  videoSrc: string | null
  currentTime: number
  events: EventViewModel[]
  isPlaying?: boolean
  onTimeUpdate?: (time: number) => void
  onDurationChange?: (duration: number) => void
}

export default function VideoPreview({
  videoSrc,
  currentTime,
  events,
  isPlaying,
  onTimeUpdate,
  onDurationChange,
}: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [collapsed, setCollapsed] = useState(false)
  const [duration, setDuration] = useState(0)

  // Control video playback
  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    if (isPlaying) {
      video.play().catch(() => {})
    } else {
      video.pause()
    }
  }, [isPlaying])

  useEffect(() => {
    const video = videoRef.current
    if (!video || video.seeking) return
    if (Math.abs(video.currentTime - currentTime) > 0.5) {
      video.currentTime = currentTime
    }
  }, [currentTime])

  const onLoadedMetadata = useCallback(() => {
    const d = videoRef.current?.duration || 0
    setDuration(d)
    onDurationChange?.(d)
  }, [onDurationChange])

  const onVideoTimeUpdate = useCallback(() => {
    const t = videoRef.current?.currentTime || 0
    onTimeUpdate?.(t)
  }, [onTimeUpdate])

  const activeEvent = events.find(e => currentTime >= e.start && currentTime <= e.end) || null

  const formatTime = (t: number) => {
    const m = Math.floor(t / 60)
    const s = Math.floor(t % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  return (
    <Box sx={{ borderBottom: 1, borderColor: 'divider', bgcolor: '#000' }}>
      <Box sx={{
        display: 'flex', alignItems: 'center', px: 1, height: 28,
        bgcolor: 'grey.900', color: 'text.secondary',
      }}>
        <Typography variant="caption" sx={{ fontSize: '0.65rem' }}>
          视频预览
        </Typography>
        <Box sx={{ flexGrow: 1 }} />
        <Tooltip title={collapsed ? '展开视频' : '折叠视频'}>
          <IconButton size="small" onClick={() => setCollapsed(c => !c)}
            sx={{ color: 'text.secondary', p: 0 }}>
            {collapsed ? <ExpandMoreIcon fontSize="small" /> : <ExpandLessIcon fontSize="small" />}
          </IconButton>
        </Tooltip>
      </Box>

      <Collapse in={!collapsed}>
        <Box sx={{ position: 'relative', width: '100%', maxHeight: 280, bgcolor: '#000' }}>
          {videoSrc ? (
            <video
              ref={videoRef}
              src={videoSrc}
              onLoadedMetadata={onLoadedMetadata}
              onTimeUpdate={onVideoTimeUpdate}
              style={{ width: '100%', maxHeight: 252, display: 'block', objectFit: 'contain' }}
              muted
            />
          ) : (
            <Box sx={{
              width: '100%', height: 200, display: 'flex',
              alignItems: 'center', justifyContent: 'center',
            }}>
              <Typography variant="body2" color="grey.600">
                未加载视频
              </Typography>
            </Box>
          )}

          {/* Time overlay */}
          <Box sx={{
            position: 'absolute', bottom: 4, right: 8,
            bgcolor: 'rgba(0,0,0,0.7)', px: 1, py: 0.25, borderRadius: 1,
          }}>
            <Typography variant="caption" color="white" sx={{ fontSize: '0.7rem', fontFamily: 'monospace' }}>
              {formatTime(currentTime)} / {formatTime(duration)}
            </Typography>
          </Box>

          {/* Subtitle overlay */}
          {activeEvent && (
            <Box sx={{
              position: 'absolute', bottom: 36, left: 0, right: 0,
              display: 'flex', flexDirection: 'column', alignItems: 'center', px: 2,
            }}>
              <Box sx={{
                bgcolor: 'rgba(0,0,0,0.75)', px: 1.5, py: 0.5, borderRadius: 1,
                maxWidth: '90%', textAlign: 'center',
              }}>
                <Typography variant="caption" color="white" sx={{ fontSize: '0.8rem', fontWeight: 500 }}>
                  {activeEvent.translation || activeEvent.text}
                </Typography>
              </Box>
              {activeEvent.translation && (
                <Typography variant="caption" color="rgba(255,255,255,0.5)" sx={{ fontSize: '0.6rem', mt: 0.25 }}>
                  {activeEvent.text}
                </Typography>
              )}
              {activeEvent.speaker && (
                <Typography variant="caption" color="primary.light" sx={{ fontSize: '0.6rem', mt: 0.25 }}>
                  {activeEvent.displayName || activeEvent.speaker}
                </Typography>
              )}
            </Box>
          )}
        </Box>
      </Collapse>
    </Box>
  )
}
