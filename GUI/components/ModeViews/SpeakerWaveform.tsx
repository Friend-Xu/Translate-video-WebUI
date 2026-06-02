import { useRef, useEffect, useCallback } from 'react'
import { Box } from '@mui/material'

interface Props {
  workspace: string
  totalDuration: number
  pixelsPerSec: number
  scrollLeft: number
  containerWidth: number
  height?: number
}

export default function SpeakerWaveform({
  workspace,
  totalDuration,
  pixelsPerSec,
  scrollLeft,
  containerWidth,
  height = 48,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const peaksRef = useRef<Float32Array | null>(null)
  const animRef = useRef<number>(0)

  useEffect(() => {
    let cancelled = false
    async function load() {
      const params = new URLSearchParams({ workspace })
      try {
        const res = await fetch(`/api/speaker/diarization/waveform?${params}`)
        if (!res.ok || cancelled) return
        const data = await res.json()
        if (!cancelled && data.peaks) {
          peaksRef.current = new Float32Array(data.peaks)
        }
      } catch {
        // Waveform unavailable — render empty
      }
    }
    load()
    return () => { cancelled = true }
  }, [workspace])

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const w = canvas.clientWidth
    const h = canvas.clientHeight
    canvas.width = w * dpr
    canvas.height = h * dpr
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, w, h)

    const peaks = peaksRef.current
    if (!peaks || peaks.length === 0) return

    const viewStart = scrollLeft / pixelsPerSec
    const viewWidth = w / pixelsPerSec
    const peaksPerSec = peaks.length / totalDuration
    const startIdx = Math.floor(viewStart * peaksPerSec)
    const endIdx = Math.ceil((viewStart + viewWidth) * peaksPerSec)
    const visiblePeaks = Math.max(1, endIdx - startIdx)

    const midY = h / 2
    ctx.strokeStyle = '#94a3b8'
    ctx.lineWidth = Math.max(0.5, (w / visiblePeaks) * 0.85)

    ctx.beginPath()
    for (let i = 0; i < visiblePeaks; i++) {
      const pi = startIdx + i
      if (pi >= peaks.length) break
      const x = (pi / peaksPerSec - viewStart) * pixelsPerSec
      const amp = peaks[pi] * midY * 0.88
      ctx.moveTo(x, midY - amp)
      ctx.lineTo(x, midY + amp)
    }
    ctx.stroke()
  }, [pixelsPerSec, scrollLeft, totalDuration])

  useEffect(() => {
    animRef.current = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(animRef.current)
  }, [draw, scrollLeft, pixelsPerSec, containerWidth])

  useEffect(() => {
    const onResize = () => draw()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [draw])

  return (
    <Box sx={{
      width: '100%', height, minHeight: height,
      bgcolor: '#dce2f0', position: 'relative',
      borderBottom: '1px solid #c8cdd8',
    }}>
      <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block' }} />
    </Box>
  )
}
