import { useState, useCallback, useEffect, useRef } from 'react'
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, Box, Chip, Typography, IconButton, Divider,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/CloseRounded'
import PlayArrowIcon from '@mui/icons-material/PlayArrowRounded'
import PauseIcon from '@mui/icons-material/PauseRounded'
import { useAppStore } from '../../store/useAppStore'

interface WordTimestamp {
  word: string; start: number; end: number; confidence?: number
}

interface EventWithWords {
  id: string; text: string; start: number; end: number
  words?: WordTimestamp[]
}

interface Props {
  event: EventWithWords | null
  open: boolean
  onClose: () => void
}

function findClosestBoundary(words: WordTimestamp[], targetTime: number): number {
  if (!words || words.length < 2) return 0
  let bestIdx = 0; let bestDist = Infinity
  for (let i = 0; i < words.length - 1; i++) {
    const boundary = (words[i].end + words[i + 1].start) / 2
    const dist = Math.abs(boundary - targetTime)
    if (dist < bestDist) { bestDist = dist; bestIdx = i }
  }
  return bestIdx
}

export default function WordSplitDialog({ event, open, onClose }: Props) {
  const manifest = useAppStore(s => s.manifest)
  const addDraft = useAppStore(s => s.addDraft)
  const applyDraft = useAppStore(s => s.applyDraft)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [selectedIdx, setSelectedIdx] = useState(0)
  const [playing, setPlaying] = useState(false)

  const words = event?.words || []
  const hasWords = words.length >= 2

  const videoSrc = manifest?.video_path
    ? `/api/files/video?path=${encodeURIComponent(manifest.video_path)}`
    : null

  useEffect(() => {
    if (event && words.length >= 2) {
      const midpoint = (event.start + event.end) / 2
      setSelectedIdx(findClosestBoundary(words, midpoint))
    } else {
      setSelectedIdx(0)
    }
  }, [event, words])

  const splitPoint = hasWords && selectedIdx < words.length - 1
    ? (words[selectedIdx].end + words[selectedIdx + 1].start) / 2
    : (event ? (event.start + event.end) / 2 : 0)

  // Seek video when split point changes
  useEffect(() => {
    const video = videoRef.current
    if (video && videoSrc) {
      video.currentTime = splitPoint
    }
  }, [splitPoint, videoSrc])

  // Stop play timer
  const playTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const playingRef = useRef(false)
  const splitRef = useRef(splitPoint)
  splitRef.current = splitPoint

  const handlePlayPause = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    if (playingRef.current) {
      video.pause()
      playingRef.current = false
      setPlaying(false)
      clearTimeout(playTimerRef.current)
    } else {
      video.currentTime = Math.max(0, splitRef.current)
      video.play().catch(() => {})
      playingRef.current = true
      setPlaying(true)
      clearTimeout(playTimerRef.current)
      playTimerRef.current = setTimeout(() => {
        video.pause()
        playingRef.current = false
        setPlaying(false)
      }, 2000)
    }
  }, [])

  const handleConfirm = useCallback(() => {
    if (!event) return
    addDraft({
      eventId: event.id,
      opcode: 'SPLIT_SEGMENT',
      payload: { split_point: splitPoint },
      before: { start: event.start, end: event.end },
      after: { split_point: splitPoint },
      timestamp: Date.now(),
    })
    applyDraft(event.id).then(ok => { if (ok) onClose() })
  }, [event, splitPoint, onClose, addDraft, applyDraft])

  // Intercept Space key to prevent SpeakerReviewView from toggling play
  useEffect(() => {
    if (!open) {
      clearTimeout(playTimerRef.current)
      playingRef.current = false
      setPlaying(false)
      return
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === ' ') {
        e.preventDefault()
        e.stopImmediatePropagation()
        handlePlayPause()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => {
      window.removeEventListener('keydown', onKey, true)
      clearTimeout(playTimerRef.current)
    }
  }, [open, handlePlayPause])

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth
      disableRestoreFocus
      PaperProps={{ sx: { maxHeight: '95vh' } }}
    >
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, pb: 0.5 }}>
        <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>
          切分: {event?.text?.slice(0, 40)}{(event?.text?.length || 0) > 40 ? '...' : ''}
        </Typography>
        <IconButton size="small" onClick={onClose}><CloseIcon fontSize="small" /></IconButton>
      </DialogTitle>

      <DialogContent sx={{ pt: 1 }}>
        {/* Video player */}
        <Box sx={{
          width: '100%', bgcolor: '#000', borderRadius: 1,
          mb: 2, overflow: 'hidden', position: 'relative',
          aspectRatio: '16/9', maxHeight: 240,
        }}>
          {videoSrc ? (
            <video
              ref={videoRef}
              src={videoSrc}
              style={{ width: '100%', height: '100%', objectFit: 'contain' }}
              preload="auto"
            />
          ) : (
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
              <Typography variant="body2" color="grey.500">视频不可用</Typography>
            </Box>
          )}
          {/* Time overlay */}
          <Box sx={{
            position: 'absolute', bottom: 4, right: 8,
            bgcolor: 'rgba(0,0,0,0.7)', color: '#ff9800',
            px: 1, py: 0.3, borderRadius: 0.5,
            fontSize: '0.8rem', fontFamily: 'monospace', fontWeight: 700,
          }}>
            {splitPoint.toFixed(2)}s
          </Box>
        </Box>

        {/* Play button */}
        <Box sx={{ display: 'flex', justifyContent: 'center', mb: 2 }}>
          <Button
            variant="contained"
            size="small"
            startIcon={playing ? <PauseIcon /> : <PlayArrowIcon />}
            onClick={handlePlayPause}
            disabled={!videoSrc}
            sx={{ minWidth: 120 }}
          >
            {playing ? '暂停' : `试听切分点 (${splitPoint.toFixed(1)}s)`}
          </Button>
        </Box>

        {/* Word boundary split lines */}
        {hasWords ? (
          <Box>
            <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5, display: 'block' }}>
              点击词间 ▏ 选择切分点 — 视频自动跳转
            </Typography>

            <Box sx={{
              display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end',
              gap: 0.5, maxHeight: 160, overflowY: 'auto',
              p: 1, bgcolor: 'grey.900', borderRadius: 1, mb: 1,
            }}>
              {words.map((w, i) => (
                <Box key={i} sx={{ display: 'flex', alignItems: 'flex-end', gap: 0 }}>
                  <Chip
                    label={w.word}
                    size="small"
                    variant="outlined"
                    sx={{
                      fontSize: '0.72rem', borderRadius: 1,
                      borderColor: selectedIdx === i || selectedIdx + 1 === i
                        ? '#ff9800' : 'grey.600',
                      color: selectedIdx === i || selectedIdx + 1 === i
                        ? '#ffb74d' : 'grey.300',
                    }}
                  />
                  {i < words.length - 1 && (
                    <Box
                      onClick={() => setSelectedIdx(i)}
                      sx={{
                        width: 8, alignSelf: 'stretch',
                        cursor: 'pointer', borderRadius: 1,
                        bgcolor: selectedIdx === i ? '#ff9800' : 'grey.700',
                        transition: 'background-color 0.15s',
                        '&:hover': { bgcolor: selectedIdx === i ? '#ffb74d' : 'grey.500' },
                        flexShrink: 0,
                      }}
                      title={`${w.word}→${words[i+1].word} @ ${((w.end + words[i+1].start)/2).toFixed(2)}s`}
                    />
                  )}
                </Box>
              ))}
            </Box>

            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
              <Typography variant="caption" color="text.secondary">
                {words[selectedIdx]?.word} ({words[selectedIdx]?.end.toFixed(2)}s)
                {' → '}
                {words[selectedIdx + 1]?.word} ({words[selectedIdx + 1]?.start.toFixed(2)}s)
              </Typography>
              <Chip label={`切分点: ${splitPoint.toFixed(2)}s`} size="small"
                color="warning" variant="outlined" sx={{ fontSize: '0.7rem' }} />
            </Box>
          </Box>
        ) : (
          <Box sx={{ py: 3, textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              {words.length === 0 ? '此片段无词级时间戳数据' : '需要至少 2 个词才能切分'}
            </Typography>
          </Box>
        )}
      </DialogContent>

      <Divider />
      <DialogActions sx={{ px: 2, py: 1, justifyContent: 'flex-end', gap: 1 }}>
        <Button size="small" onClick={onClose}>取消</Button>
        <Button size="small" variant="contained" color="warning" onClick={handleConfirm}>
          确认切分 @ {splitPoint.toFixed(2)}s
        </Button>
      </DialogActions>
    </Dialog>
  )
}
