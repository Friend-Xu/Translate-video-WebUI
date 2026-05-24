import { useRef, useState, useCallback, useEffect } from 'react'
import { useAppStore } from '../store/useAppStore'

interface PlaybackController {
  isPlaying: boolean
  currentTime: number
  duration: number
  playbackRate: number
  seek: (time: number) => void
  playPause: () => void
  stop: () => void
  setRate: (rate: number) => void
  loadAudio: (url: string) => void
}

export function usePlaybackController(): PlaybackController {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [playbackRate, setPlaybackRate] = useState(1)

  const setPlayhead = useAppStore(s => s.setPlayhead)

  useEffect(() => {
    const audio = new Audio()
    audio.preload = 'auto'
    audioRef.current = audio

    const onTimeUpdate = () => {
      setCurrentTime(audio.currentTime)
      setPlayhead(audio.currentTime)
    }
    const onLoadedMetadata = () => setDuration(audio.duration)
    const onEnded = () => setIsPlaying(false)
    const onPlay = () => setIsPlaying(true)
    const onPause = () => setIsPlaying(false)

    audio.addEventListener('timeupdate', onTimeUpdate)
    audio.addEventListener('loadedmetadata', onLoadedMetadata)
    audio.addEventListener('ended', onEnded)
    audio.addEventListener('play', onPlay)
    audio.addEventListener('pause', onPause)

    return () => {
      audio.removeEventListener('timeupdate', onTimeUpdate)
      audio.removeEventListener('loadedmetadata', onLoadedMetadata)
      audio.removeEventListener('ended', onEnded)
      audio.removeEventListener('play', onPlay)
      audio.removeEventListener('pause', onPause)
      audio.pause()
      audio.src = ''
    }
  }, [setPlayhead])

  const loadAudio = useCallback((url: string) => {
    const audio = audioRef.current
    if (!audio) return
    audio.src = url
    audio.load()
  }, [])

  const seek = useCallback((time: number) => {
    const audio = audioRef.current
    if (!audio) return
    const clamped = Math.max(0, Math.min(time, audio.duration || time))
    audio.currentTime = clamped
    setCurrentTime(clamped)
    setPlayhead(clamped)
  }, [setPlayhead])

  const playPause = useCallback(() => {
    const audio = audioRef.current
    if (!audio) return
    if (audio.paused) {
      audio.play().catch(() => { /* autoplay blocked */ })
    } else {
      audio.pause()
    }
  }, [])

  const stop = useCallback(() => {
    const audio = audioRef.current
    if (!audio) return
    audio.pause()
    audio.currentTime = 0
    setIsPlaying(false)
    setCurrentTime(0)
    setPlayhead(0)
  }, [setPlayhead])

  const setRate = useCallback((rate: number) => {
    const audio = audioRef.current
    if (!audio) return
    audio.playbackRate = rate
    setPlaybackRate(rate)
  }, [])

  return { isPlaying, currentTime, duration, playbackRate, seek, playPause, stop, setRate, loadAudio }
}
