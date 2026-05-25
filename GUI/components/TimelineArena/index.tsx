import { useRef, useCallback, useState, useEffect } from 'react'
import { Box, Typography } from '@mui/material'
import CloudUploadOutlined from '@mui/icons-material/CloudUploadOutlined'
import { useTimelineCoordinates } from '../../hooks/useTimelineCoordinates'
import { useAppStore } from '../../store/useAppStore'
import TrackSystem from './TrackSystem'
import ZoomScrollbar from './ZoomScrollbar'
import ZoomPresets from './ZoomPresets'
import ImpactIndicator from '../ImpactIndicator'
import type { EventViewModel, WaveformData } from '../../types'

interface Props {
  events: EventViewModel[]
  waveform: WaveformData | null
  totalDuration: number
  onDropVideo?: (file: File) => void
}

export default function TimelineArena({ events, totalDuration, onDropVideo }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [canvasW, setCanvasW] = useState(1200)
  const [dragOver, setDragOver] = useState(false)

  const selectedEventIds = useAppStore(s => s.selectedEventIds)
  const selectEvent = useAppStore(s => s.selectEvent)
  const pendingDrafts = useAppStore(s => s.pendingDrafts)
  const setTrackScrollLeft = useAppStore(s => s.setTrackScrollLeft)

  const coord = useTimelineCoordinates(totalDuration || 80, canvasW)

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
      const rect = containerRef.current?.getBoundingClientRect()
      const mouseX = rect ? e.clientX - rect.left : canvasW / 2
      const centerTime = coord.pixelToTime(mouseX)
      if (e.deltaY < 0) coord.zoomIn(centerTime)
      else coord.zoomOut(centerTime)
    } else {
      const newScroll = coord.timeToPixel(0) + e.deltaY
      const totalW = totalDuration * coord.pixelsPerSec
      const maxS = Math.max(0, totalW - canvasW)
      const clamped = Math.max(0, Math.min(maxS, newScroll))
      setTrackScrollLeft(clamped)
    }
  }, [coord, totalDuration, canvasW, setTrackScrollLeft])

  // Click arena background → deselect
  const handleArenaClick = useCallback((e: React.MouseEvent) => {
    const target = e.target as HTMLElement
    if (target === containerRef.current || (target as HTMLElement).dataset?.arena === 'true') {
      selectEvent(null)
    }
  }, [selectEvent])

  // Event click
  const handleEventClick = useCallback((eventId: string, e: React.MouseEvent) => {
    if (e.ctrlKey || e.metaKey) {
      useAppStore.getState().toggleEventSelection(eventId)
    } else if (e.shiftKey && selectedEventIds.length > 0) {
      const anchor = events.find(ev => ev.id === selectedEventIds[0])
      const clicked = events.find(ev => ev.id === eventId)
      if (anchor && clicked) {
        const minT = Math.min(anchor.start, clicked.start)
        const maxT = Math.max(anchor.end, clicked.end)
        const rangeIds = events.filter(ev => ev.start >= minT && ev.start <= maxT).map(ev => ev.id)
        useAppStore.getState().selectAllVisible(rangeIds)
      }
    } else {
      selectEvent(eventId)
    }
    const ev = events.find(x => x.id === eventId)
    if (ev) coord.scrollToTime(ev.start)
  }, [selectedEventIds, selectEvent, events, coord])

  // Double click
  const handleEventDoubleClick = useCallback((eventId: string) => {
    const ev = events.find(x => x.id === eventId)
    if (ev) useAppStore.getState().setPlayhead(ev.start)
  }, [events])

  // Drag & drop video
  const onDragOver = useCallback((e: React.DragEvent) => { e.preventDefault(); setDragOver(true) }, [])
  const onDragLeave = useCallback(() => setDragOver(false), [])
  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file && onDropVideo) onDropVideo(file)
  }, [onDropVideo])

  const isEmpty = events.length === 0

  // Keyboard shortcuts for zoom
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Don't intercept when focus is in an input
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (e.key === '\\') { e.preventDefault(); coord.zoomToFit(0.05) }
      if (e.key === '+' || e.key === '=') { e.preventDefault(); coord.zoomIn() }
      if (e.key === '-') { e.preventDefault(); coord.zoomOut() }
      if (e.key === '0' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); coord.zoomTo(1) }
      if (e.key === 'a' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault()
        useAppStore.getState().selectAllVisible(events.map(ev => ev.id))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [coord, events])

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
        overflow: 'hidden', bgcolor: 'background.default',
        cursor: dragOver ? 'copy' : 'default',
      }}
    >
      {!isEmpty ? (
        <>
          <TrackSystem
            events={events}
            totalDuration={totalDuration || 80}
            canvasWidth={canvasW}
            coord={coord}
            onEventClick={handleEventClick}
            onEventDblClick={handleEventDoubleClick}
          />

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
        </>
      ) : (
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
        position: 'absolute', bottom: 20, left: 0, right: 0, zIndex: 25,
        display: 'flex', alignItems: 'center', gap: 1, px: 1,
      }}>
        <ZoomPresets coord={coord} />
        <Box sx={{ flexGrow: 1 }}>
          <ZoomScrollbar coord={coord} totalDuration={totalDuration || 80} canvasWidth={canvasW} />
        </Box>
        <Box sx={{ display: 'flex', gap: 0.5 }}>
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
    </Box>
  )
}
