import { useRef, useEffect } from 'react'

interface Props {
  width: number
  height: number
  pixelsPerSec: number
  totalDuration: number
  scrollLeft: number
  playheadX: number
  snapLineX: number | null
  selectionRanges: { start: number; end: number }[]
}

export default function BackgroundLayer({
  width, height, pixelsPerSec, totalDuration, scrollLeft, playheadX, snapLineX, selectionRanges,
}: Props) {
  const staticCanvasRef = useRef<HTMLCanvasElement | null>(null)
  const dynamicCanvasRef = useRef<HTMLCanvasElement | null>(null)
  const rafRef = useRef<number>(0)

  // Static layer: grid + scale marks
  useEffect(() => {
    const canvas = staticCanvasRef.current
    if (!canvas) return
    const dpr = window.devicePixelRatio || 1
    canvas.width = width * dpr
    canvas.height = height * dpr
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, width, height)

    ctx.strokeStyle = 'rgba(255,255,255,0.06)'
    ctx.lineWidth = 1
    for (let t = 0; t <= totalDuration; t += 1) {
      const x = t * pixelsPerSec - scrollLeft
      if (x < -10 || x > width + 10) continue
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke()
    }

    ctx.strokeStyle = 'rgba(255,255,255,0.03)'
    for (let t = 0; t <= totalDuration; t += 0.5) {
      const x = t * pixelsPerSec - scrollLeft
      if (x < -10 || x > width + 10) continue
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke()
    }
  }, [width, height, pixelsPerSec, totalDuration, scrollLeft])

  // Dynamic layer: playhead + snap + selection
  useEffect(() => {
    const canvas = dynamicCanvasRef.current
    if (!canvas) return
    const dpr = window.devicePixelRatio || 1
    canvas.width = width * dpr
    canvas.height = height * dpr
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.scale(dpr, dpr)

    const draw = () => {
      ctx.clearRect(0, 0, width, height)

      for (const range of selectionRanges) {
        const x = range.start * pixelsPerSec - scrollLeft
        const w = Math.max(1, (range.end - range.start) * pixelsPerSec)
        if (x + w < 0 || x > width) continue
        ctx.fillStyle = 'rgba(33,150,243,0.08)'
        ctx.fillRect(x, 0, w, height)
      }

      if (snapLineX != null && snapLineX >= 0 && snapLineX <= width) {
        ctx.strokeStyle = 'rgba(255,152,0,0.7)'
        ctx.lineWidth = 1
        ctx.setLineDash([4, 4])
        ctx.beginPath(); ctx.moveTo(snapLineX, 0); ctx.lineTo(snapLineX, height); ctx.stroke()
        ctx.setLineDash([])
      }

      if (playheadX >= 0 && playheadX <= width) {
        ctx.strokeStyle = '#FF5252'
        ctx.lineWidth = 2
        ctx.beginPath(); ctx.moveTo(playheadX, 0); ctx.lineTo(playheadX, height); ctx.stroke()
      }
    }

    cancelAnimationFrame(rafRef.current)
    rafRef.current = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(rafRef.current)
  }, [width, height, pixelsPerSec, scrollLeft, playheadX, snapLineX, selectionRanges])

  return (
    <>
      <canvas ref={staticCanvasRef} style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 0, width, height }} />
      <canvas ref={dynamicCanvasRef} style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 1, width, height }} />
    </>
  )
}
