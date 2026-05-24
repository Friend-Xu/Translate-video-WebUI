import { useRef, useCallback, useState } from 'react'
import { Box, Typography } from '@mui/material'
import CloudUploadOutlined from '@mui/icons-material/CloudUploadOutlined'
import { useTimelineCoordinates } from '../../hooks/useTimelineCoordinates'
import { useAppStore } from '../../store/useAppStore'
import WaveformLayer from '../sections/WaveformLayer'
import EventBlock from '../sections/EventBlock'
import ImpactIndicator from '../ImpactIndicator'
import type { EventViewModel, WaveformData } from '../../types'

interface Props {
  events: EventViewModel[]
  waveform: WaveformData | null
  totalDuration: number
  onDropVideo?: (file: File) => void
}

const LANE_HEIGHT = 40
const LANE_COLORS = ['#2196F3', '#4CAF50', '#FF9800', '#9C27B0', '#00BCD4', '#E91E63']

export default function TimelineArena({ events, waveform, totalDuration, onDropVideo }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [canvasW, setCanvasW] = useState(1200)
  const [dragOver, setDragOver] = useState(false)

  const selectedEventId = useAppStore(s => s.selectedEventId)
  const selectEvent = useAppStore(s => s.selectEvent)
  const playheadPosition = useAppStore(s => s.playheadPosition)
  const mode = useAppStore(s => s.mode)
  const speakerFocus = useAppStore(s => s.speakerFocus)
  const pendingDrafts = useAppStore(s => s.pendingDrafts)

  const coord = useTimelineCoordinates(totalDuration || 80, canvasW)

  // Resize observer
  const containerCallback = useCallback((node: HTMLDivElement | null) => {
    containerRef.current = node
    if (node) {
      setCanvasW(node.clientWidth)
      const obs = new ResizeObserver(entries => {
        for (const entry of entries) setCanvasW(entry.contentRect.width)
      })
      obs.observe(node)
    }
  }, [])

  // Wheel → zoom or scroll
  const onWheel = useCallback((e: React.WheelEvent) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault()
      if (e.deltaY < 0) coord.zoomIn()
      else coord.zoomOut()
    } else {
      coord.setScroll(coord.timeToPixel(0) + e.deltaY)
    }
  }, [coord])

  // Click arena background → deselect
  const handleArenaClick = useCallback((e: React.MouseEvent) => {
    const target = e.target as HTMLElement
    if (target === containerRef.current || target.dataset?.arena === 'true') {
      selectEvent(null)
    }
  }, [selectEvent])

  // Event click
  const handleEventClick = useCallback((eventId: string, _e: React.MouseEvent) => {
    selectEvent(selectedEventId === eventId ? null : eventId)
    const ev = events.find(x => x.id === eventId)
    if (ev) coord.scrollToTime(ev.start)
  }, [selectedEventId, selectEvent, events, coord])

  // Double click
  const handleEventDoubleClick = useCallback((eventId: string) => {
    const ev = events.find(x => x.id === eventId)
    if (ev) useAppStore.getState().setPlayhead(ev.start)
  }, [events])

  // Drag & drop
  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(true)
  }, [])
  const onDragLeave = useCallback(() => setDragOver(false), [])
  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file && onDropVideo) onDropVideo(file)
  }, [onDropVideo])

  const playheadX = coord.timeToPixel(playheadPosition)
  const isEmpty = events.length === 0

  return (
    <Box
      ref={containerCallback}
      data-arena="true"
      onClick={handleArenaClick}
      onWheel={onWheel}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      sx={{
        height: '100%', width: '100%', position: 'relative',
        overflow: 'hidden', bgcolor: '#1a1a2e',
        cursor: dragOver ? 'copy' : 'default',
      }}
    >
      {/* Waveform layer */}
      {waveform && waveform.peaks.length > 0 && (
        <WaveformLayer
          width={canvasW}
          height={60}
          peaks={waveform.peaks}
          duration={totalDuration || 80}
          pixelsPerSec={coord.pixelsPerSec}
        />
      )}

      {/* Event layer */}
      <Box sx={{ position: 'absolute', top: 64, left: 0, right: 0, bottom: 0 }}>
        {events.map(evt => {
          const left = coord.timeToPixel(evt.start)
          const width = Math.max(3, (evt.end - evt.start) * coord.pixelsPerSec)
          if (left + width < -50 || left > canvasW + 50) return null

          const laneIdx = evt.speaker === 'SPEAKER_00' ? 0 : evt.speaker === 'SPEAKER_01' ? 1 : 0
          const hasDraft = pendingDrafts.has(evt.id)
          const dimmed = mode === 'speaker' && speakerFocus != null && evt.speaker !== (speakerFocus as any)?.speaker

          return (
            <EventBlock
              key={evt.id}
              event={evt}
              laneColor={LANE_COLORS[laneIdx % LANE_COLORS.length]}
              left={left}
              width={width}
              laneHeight={LANE_HEIGHT}
              isSelected={selectedEventId === evt.id}
              isMultiSelected={dimmed}
              hasDraft={hasDraft}
              onClick={(e) => handleEventClick(evt.id, e)}
              onDoubleClick={() => handleEventDoubleClick(evt.id)}
              onContextMenu={(e) => { e.preventDefault() }}
            />
          )
        })}
      </Box>

      {/* Playhead */}
      {playheadX >= 0 && playheadX <= canvasW && (
        <Box sx={{
          position: 'absolute', top: 0, bottom: 0, left: playheadX,
          width: 2, bgcolor: '#FF5252', zIndex: 20, pointerEvents: 'none',
          boxShadow: '0 0 6px rgba(255,82,82,0.6)',
        }} />
      )}

      {/* Impact indicators for time-shifting drafts */}
      {Array.from(pendingDrafts.values())
        .filter(d => d.opcode === 'SPLIT' || d.payload.start || d.payload.end)
        .map(d => {
          const evt = events.find(e => e.id === d.eventId)
          if (!evt) return null
          const startX = coord.timeToPixel(evt.end)
          const affectedIds = events
            .filter(e => e.start >= evt.end)
            .slice(0, 5)
            .map(e => e.id)
          return (
            <ImpactIndicator
              key={d.eventId}
              affectedEventIds={affectedIds}
              offsetSeconds={0.5}
              startX={startX}
              width={60}
              arenaHeight={typeof window !== 'undefined' ? window.innerHeight - 300 : 400}
            />
          )
        })}

      {/* Time ruler */}
      <Box sx={{
        position: 'absolute', top: 0, left: 0, right: 0, height: 20,
        display: 'flex', alignItems: 'center', px: 1,
        bgcolor: 'rgba(0,0,0,0.4)', zIndex: 10,
        borderBottom: '1px solid rgba(255,255,255,0.1)',
      }}>
        {Array.from({ length: Math.ceil(totalDuration) }).map((_, i) => {
          const x = coord.timeToPixel(i)
          if (x < -10 || x > canvasW + 10) return null
          return (
            <Typography key={i} sx={{
              position: 'absolute', left: x,
              fontSize: '0.55rem', color: 'rgba(255,255,255,0.5)',
            }}>
              {i}s
            </Typography>
          )
        })}
      </Box>

      {/* Empty state */}
      {isEmpty && (
        <Box sx={{
          position: 'absolute', inset: 0, display: 'flex',
          flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          color: 'rgba(255,255,255,0.4)',
        }}>
          <CloudUploadOutlined sx={{ fontSize: 60, mb: 2, opacity: 0.5 }} />
          <Typography variant="h6" sx={{ color: 'rgba(255,255,255,0.6)', fontWeight: 500 }}>
            拖拽视频文件到此处
          </Typography>
          <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.35)', mt: 1 }}>
            抽取事件后将在此处显示时间轴
          </Typography>
        </Box>
      )}

      {/* Zoom controls */}
      <Box sx={{
        position: 'absolute', bottom: 8, right: 8, zIndex: 25,
        display: 'flex', gap: 0.5,
      }}>
        <Box component="button" onClick={() => coord.zoomOut()} aria-label="缩小"
          sx={{ width: 28, height: 28, border: '1px solid rgba(255,255,255,0.3)', borderRadius: 1, bgcolor: 'rgba(0,0,0,0.6)', color: '#fff', cursor: 'pointer', fontSize: '1rem', p: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          −
        </Box>
        <Box component="button" onClick={() => coord.zoomIn()} aria-label="放大"
          sx={{ width: 28, height: 28, border: '1px solid rgba(255,255,255,0.3)', borderRadius: 1, bgcolor: 'rgba(0,0,0,0.6)', color: '#fff', cursor: 'pointer', fontSize: '1rem', p: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          +
        </Box>
      </Box>
    </Box>
  )
}
