import type { TimelineCoordAPI } from '../../hooks/useTimelineCoordinates'

interface Props {
  coord: TimelineCoordAPI
  totalDuration: number
  canvasWidth: number
  markers?: { time: number; label: string; color: string }[]
  onMarkerClick?: (time: number) => void
  onClick?: (time: number) => void
  onHover?: (time: number | null) => void
  scrubX?: number | null
}

export default function TimeRuler({ coord, totalDuration, canvasWidth, markers, onMarkerClick, onClick, onHover, scrubX }: Props) {
  const { timeToPixel, pixelsPerSec } = coord
  const showMs = pixelsPerSec >= 200
  const interval = showMs ? 0.5 : 1
  const w = canvasWidth || 1200

  const handleClick = (e: React.MouseEvent) => {
    if (!onClick) return
    const rect = e.currentTarget.getBoundingClientRect()
    const x = e.clientX - rect.left
    onClick(coord.pixelToTime(x))
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!onHover) return
    const rect = e.currentTarget.getBoundingClientRect()
    const x = e.clientX - rect.left
    onHover(coord.pixelToTime(x))
  }

  const ticks: React.ReactNode[] = []
  for (let i = 0; i < totalDuration; i += interval) {
    const x = timeToPixel(i)
    if (x < -40 || x > w + 40) continue
    const major = i % 1 === 0
    ticks.push(
      <div key={i} style={{
        position: 'absolute', left: x, bottom: 0,
        width: 1, height: major ? 14 : 8,
        backgroundColor: major ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.2)',
      }}>
        {major && (
          <span style={{
            position: 'absolute', top: 0, left: 4,
            fontSize: 9, color: '#aaa',
            whiteSpace: 'nowrap', lineHeight: '14px',
          }}>
            {showMs ? `${i.toFixed(1)}s` : `${i}s`}
          </span>
        )}
      </div>
    )
  }

  return (
    <div
      onClick={handleClick}
      onMouseMove={handleMouseMove}
      onMouseLeave={() => onHover?.(null)}
      style={{
        height: 22, width: w, position: 'relative',
        backgroundColor: '#1a1a1a',
        borderBottom: '1px solid #333',
        cursor: onClick ? 'pointer' : 'default',
        overflow: 'hidden',
      }}
    >
      {ticks}
      {markers?.map((m, idx) => {
        const x = timeToPixel(m.time)
        if (x < -5 || x > w + 5) return null
        return (
          <div key={`m${idx}`} onClick={(e) => { e.stopPropagation(); onMarkerClick?.(m.time) }} style={{
            position: 'absolute', left: x - 4, top: 3,
            width: 8, height: 8, borderRadius: '50%',
            backgroundColor: m.color, cursor: 'pointer',
            border: '1px solid rgba(255,255,255,0.6)', zIndex: 2,
          }} />
        )
      })}
      {scrubX != null && scrubX >= 0 && scrubX <= w && (
        <div style={{
          position: 'absolute', left: scrubX, top: 0, bottom: 0,
          width: 1, backgroundColor: 'rgba(255,255,255,0.3)',
          pointerEvents: 'none', zIndex: 5,
        }} />
      )}
    </div>
  )
}
