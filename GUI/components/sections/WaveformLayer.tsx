import { useRef, useEffect } from 'react'

interface Props {
  width: number
  height: number
  peaks: number[]
  duration: number
  pixelsPerSec: number
}

export default function WaveformLayer({ width, height, peaks, duration, pixelsPerSec }: Props) {
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
    ctx.strokeStyle = 'rgba(150,150,150,0.25)'
    ctx.lineWidth = 0.5

    const samplesPerPx = (duration / width) * pixelsPerSec
    for (let x = 0; x < width; x += 2) {
      const si = Math.floor(x * samplesPerPx)
      const peak = peaks[Math.min(si, peaks.length - 1)] || 0
      const h = peak * mid * 0.8
      ctx.beginPath()
      ctx.moveTo(x, mid - h)
      ctx.lineTo(x, mid + h)
      ctx.stroke()
    }
  }, [width, height, peaks, duration, pixelsPerSec])

  return (
    <canvas
      ref={canvasRef}
      style={{ width, height, position: 'absolute', top: 0, left: 0, pointerEvents: 'none' }}
    />
  )
}
