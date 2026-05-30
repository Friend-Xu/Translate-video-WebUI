import { useRef, useEffect, useState, useCallback } from 'react'
import { Box, Typography, IconButton, Tooltip } from '@mui/material'
import PlayArrowIcon from '@mui/icons-material/PlayArrowRounded'
import PauseIcon from '@mui/icons-material/PauseRounded'
import SkipPreviousIcon from '@mui/icons-material/SkipPreviousRounded'
import SkipNextIcon from '@mui/icons-material/SkipNextRounded'
import { useAppStore } from '../../store/useAppStore'
import type { EventViewModel } from '../../types'

interface Props {
  videoSrc: string | null
  currentTime: number
  events: EventViewModel[]
  onTimeUpdate?: (time: number) => void
  onDurationChange?: (duration: number) => void
}

const btnSx = {
  color: '#475569', p: 0.25, '&:hover': { color: '#1e293b', bgcolor: 'rgba(99,102,241,0.08)' },
}

export default function VideoPreview({
  videoSrc,
  currentTime,
  events,
  onTimeUpdate,
  onDurationChange,
}: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [duration, setDuration] = useState(0)

  const currentTimeRef = useRef(currentTime)
  currentTimeRef.current = currentTime

  const playheadPosition = useAppStore(s => s.playheadPosition)
  const setPlayhead = useAppStore(s => s.setPlayhead)

  // Video playback control
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

  // Seek video to store playhead when not playing
  useEffect(() => {
    const video = videoRef.current
    if (!video || isPlaying) return
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

  // Store playhead sync
  useEffect(() => {
    const video = videoRef.current
    if (!video || !isPlaying) return
    const iv = setInterval(() => {
      const t = video.currentTime
      if (t > 0) setPlayhead(t)
    }, 100)
    return () => clearInterval(iv)
  }, [isPlaying, setPlayhead])

  const handlePlayPause = useCallback(() => {
    setIsPlaying(p => {
      if (!p) {
        const video = videoRef.current
        if (video) video.currentTime = playheadPosition
      }
      return !p
    })
  }, [playheadPosition])

  const handleJumpPrev = useCallback(() => {
    const prev = events.filter(e => e.end <= playheadPosition).sort((a, b) => b.end - a.end)[0]
    if (prev) {
      setPlayhead(prev.start)
      if (videoRef.current) videoRef.current.currentTime = prev.start
    }
  }, [events, playheadPosition, setPlayhead])

  const handleJumpNext = useCallback(() => {
    const next = events.filter(e => e.start >= playheadPosition).sort((a, b) => a.start - b.start)[0]
    if (next) {
      setPlayhead(next.start)
      if (videoRef.current) videoRef.current.currentTime = next.start
    }
  }, [events, playheadPosition, setPlayhead])


  const activeEvent = events.find(e => playheadPosition >= e.start && playheadPosition <= e.end) || null

  const formatTime = (t: number) => {
    const m = Math.floor(t / 60)
    const s = Math.floor(t % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  return (
    <Box sx={{
      bgcolor: '#e8ecf4', borderBottom: '1px solid #d0d5e0',
    }}>
      <Box sx={{ position: 'relative', bgcolor: '#dce2f0' }}>
        {videoSrc ? (
          <video
            ref={videoRef}
            src={videoSrc}
            onLoadedMetadata={onLoadedMetadata}
            onTimeUpdate={onVideoTimeUpdate}
            style={{ width: '100%', height: 170, display: 'block', objectFit: 'contain' }}
          />
        ) : (
          <Box sx={{
            width: '100%', height: 120, display: 'flex',
            alignItems: 'center', justifyContent: 'center',
            bgcolor: '#dce2f0',
          }}>
            <Typography variant="caption" color="text.secondary">
              {activeEvent
                ? activeEvent.translation || activeEvent.text
                : '选择一个事件以查看详情'}
            </Typography>
          </Box>
        )}

        {/* Time overlay */}
        {videoSrc && (
          <Box sx={{
            position: 'absolute', bottom: 2, right: 4,
            bgcolor: 'rgba(0,0,0,0.8)', px: 0.75, py: 0.25, borderRadius: 0.5,
          }}>
            <Typography variant="caption" color="white" sx={{ fontSize: '0.6rem', fontFamily: 'monospace' }}>
              {formatTime(playheadPosition)} / {formatTime(duration)}
            </Typography>
          </Box>
        )}

        {/* Subtitle overlay */}
        {videoSrc && activeEvent && (
          <Box sx={{
            position: 'absolute', bottom: 28, left: 0, right: 0,
            display: 'flex', flexDirection: 'column', alignItems: 'center', px: 1,
          }}>
            <Box sx={{
              bgcolor: 'rgba(0,0,0,0.8)', px: 1, py: 0.25, borderRadius: 0.5,
              maxWidth: '95%', textAlign: 'center',
            }}>
              <Typography variant="caption" color="white" sx={{ fontSize: '0.7rem', fontWeight: 500 }}>
                {activeEvent.translation || activeEvent.text}
              </Typography>
            </Box>
          </Box>
        )}
      </Box>

      {/* Player controls */}
      <Box sx={{
        display: 'flex', alignItems: 'center', px: 0.5, py: 0.25, gap: 0,
        bgcolor: '#e8ecf4', height: 28,
      }}>
        <Tooltip title={isPlaying ? '暂停' : '播放'}>
          <IconButton size="small" sx={btnSx} onClick={handlePlayPause}>
            {isPlaying ? <PauseIcon sx={{ fontSize: 16 }} /> : <PlayArrowIcon sx={{ fontSize: 16 }} />}
          </IconButton>
        </Tooltip>
        <Tooltip title="上一个事件"><span>
          <IconButton size="small" sx={btnSx} onClick={handleJumpPrev}>
            <SkipPreviousIcon sx={{ fontSize: 16 }} />
          </IconButton>
        </span></Tooltip>
        <Tooltip title="下一个事件"><span>
          <IconButton size="small" sx={btnSx} onClick={handleJumpNext}>
            <SkipNextIcon sx={{ fontSize: 16 }} />
          </IconButton>
        </span></Tooltip>
        <Box sx={{ flexGrow: 1 }} />
      </Box>
    </Box>
  )
}
