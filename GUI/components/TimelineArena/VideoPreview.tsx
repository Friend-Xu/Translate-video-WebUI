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
  const [collapsed, setCollapsed] = useState(true)
  const [duration, setDuration] = useState(0)

  const currentTimeRef = useRef(currentTime)
  currentTimeRef.current = currentTime

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    if (isPlaying) {
      video.currentTime = currentTimeRef.current
      video.play().catch(() => {})
    } else {
      video.pause()
    }
  }, [isPlaying])

  useEffect(() => {
    const video = videoRef.current
    if (!video || !isPlaying) return
    if (Math.abs(video.currentTime - currentTime) > 0.3) {
      video.currentTime = currentTime
    }
  }, [currentTime, isPlaying])

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
    <Box sx={{
      borderBottom: 1, borderColor: 'divider', bgcolor: '#000',
    }}>
      <Box sx={{
        display: 'flex', alignItems: 'center', px: 1, height: 24,
        bgcolor: 'grey.900', color: 'text.secondary', cursor: 'pointer',
      }} onClick={() => setCollapsed(c => !c)}>
        <Typography variant="caption" sx={{ fontSize: '0.6rem' }}>
          视频预览
        </Typography>
        <Box sx={{ flexGrow: 1 }} />
        <Tooltip title={collapsed ? '展开视频' : '折叠视频'}>
          <IconButton size="small" sx={{ color: 'text.secondary', p: 0 }}>
            {collapsed ? <ExpandMoreIcon sx={{ fontSize: 14 }} /> : <ExpandLessIcon sx={{ fontSize: 14 }} />}
          </IconButton>
        </Tooltip>
      </Box>

      <Collapse in={!collapsed}>
        <Box sx={{ position: 'relative', width: '100%', bgcolor: '#000' }}>
          {videoSrc ? (
            <video
              ref={videoRef}
              src={videoSrc}
              onLoadedMetadata={onLoadedMetadata}
              onTimeUpdate={onVideoTimeUpdate}
              style={{ width: '100%', height: 180, display: 'block', objectFit: 'contain' }}
            />
          ) : (
            <Box sx={{
              width: '100%', height: 120, display: 'flex',
              alignItems: 'center', justifyContent: 'center',
            }}>
              <Typography variant="caption" color="grey.600">
                {activeEvent
                  ? activeEvent.translation || activeEvent.text
                  : '选择一个事件以查看详情'}
              </Typography>
            </Box>
          )}

          {videoSrc && (
            <Box sx={{
              position: 'absolute', bottom: 2, right: 4,
              bgcolor: 'rgba(0,0,0,0.7)', px: 0.75, py: 0.25, borderRadius: 0.5,
            }}>
              <Typography variant="caption" color="white" sx={{ fontSize: '0.6rem', fontFamily: 'monospace' }}>
                {formatTime(currentTime)} / {formatTime(duration)}
              </Typography>
            </Box>
          )}

          {videoSrc && activeEvent && (
            <Box sx={{
              position: 'absolute', bottom: 28, left: 0, right: 0,
              display: 'flex', flexDirection: 'column', alignItems: 'center', px: 1,
            }}>
              <Box sx={{
                bgcolor: 'rgba(0,0,0,0.75)', px: 1, py: 0.25, borderRadius: 0.5,
                maxWidth: '95%', textAlign: 'center',
              }}>
                <Typography variant="caption" color="white" sx={{ fontSize: '0.7rem', fontWeight: 500 }}>
                  {activeEvent.translation || activeEvent.text}
                </Typography>
              </Box>
            </Box>
          )}
        </Box>
      </Collapse>
    </Box>
  )
}
