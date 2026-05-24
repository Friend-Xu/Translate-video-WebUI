import { useRef, useEffect } from 'react'

interface Props {
  width: number
  height: number
  peaks: number[]
  duration: number
  pixelsPerSec: number
  playheadPosition?: number
  silenceThreshold?: number
}

export default function WaveformLayer({
  width, height, peaks, duration, pixelsPerSec,
  playheadPosition = -1, silenceThreshold = 0.05,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || peaks.length === 0) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = width * dpr
    canvas.height = height * dpr
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, width, height)

    const mid = height / 2
    const samplesPerPx = (duration / width) * (peaks.length / duration)

    for (let x = 0; x < width; x++) {
      const si = Math.floor(x * samplesPerPx)
      const peak = peaks[Math.min(si, peaks.length - 1)] || 0

      if (peak < silenceThreshold) {
        ctx.fillStyle = 'rgba(255, 255, 255, 0.03)'
        ctx.fillRect(x, 0, 1, height)
      } else {
        const h = peak * mid * 0.8
        ctx.strokeStyle = 'rgba(150,150,150,0.25)'
        ctx.lineWidth = 0.5
        ctx.beginPath()
        ctx.moveTo(x, mid - h)
        ctx.lineTo(x, mid + h)
        ctx.stroke()
      }
    }

    // Playhead line
    if (playheadPosition >= 0) {
      const px = playheadPosition * pixelsPerSec
      ctx.strokeStyle = '#FF5252'
      ctx.lineWidth = 1.5
      ctx.setLineDash([4, 4])
      ctx.beginPath()
      ctx.moveTo(px, 0)
      ctx.lineTo(px, height)
      ctx.stroke()
      ctx.setLineDash([])
    }
  }, [width, height, peaks, duration, pixelsPerSec, silenceThreshold, playheadPosition])

  return (
    <canvas
      ref={canvasRef}
      style={{ width, height, position: 'absolute', top: 0, left: 0, pointerEvents: 'none' }}
    />
  )
}
