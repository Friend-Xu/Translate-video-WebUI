import { useRef, useCallback, useState, useEffect } from 'react'
import { Box, Typography } from '@mui/material'
import CloudUploadOutlined from '@mui/icons-material/CloudUploadOutlined'
import { useTimelineCoordinates } from '../../hooks/useTimelineCoordinates'
import { useAppStore } from '../../store/useAppStore'
import TrackSystem from './TrackSystem'
import TimelineMinimap from './TimelineMinimap'
import ZoomPresets from './ZoomPresets'
import TimelineToolbar from './TimelineToolbar'
import VideoPreview from './VideoPreview'
import ReviewTable from './ReviewTable'
import SpeakerReviewView from '../ModeViews/SpeakerReviewView'
import ImpactIndicator from '../ImpactIndicator'
import RubberBandSelect from './RubberBandSelect'
import EventContextMenu from './EventContextMenu'
import FilterBar, { type FilterState, DEFAULT_FILTER, applyFilter } from './FilterBar'
import PatchDiffPopover from './PatchDiffPopover'
import type { EventViewModel, WaveformData, TrackWaveformData } from '../../types'

interface Props {
  events: EventViewModel[]
  waveform: WaveformData | null
  totalDuration: number
  ttsWaveforms?: TrackWaveformData[]
  videoSrc?: string | null
  onDropVideo?: (file: File) => void
}

export default function TimelineArena({ events, totalDuration, waveform, ttsWaveforms, videoSrc, onDropVideo }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const canvasW = (() => { return 1200 })()
  const [_canvasWState, setCanvasW] = useState(1200)
  const [dragOver, setDragOver] = useState(false)
  const [isPlaying, setIsPlaying] = useState(false)
  const [loopEnabled, setLoopEnabled] = useState(false)
  const [videoCurrentTime, setVideoCurrentTime] = useState(0)
  const [contextMenuAnchor, setContextMenuAnchor] = useState<HTMLElement | null>(null)
  const [contextMenuEvent, setContextMenuEvent] = useState<EventViewModel | null>(null)
  const [lockedEventIds, setLockedEventIds] = useState<Set<string>>(new Set())
  const [filterState, setFilterState] = useState<FilterState>(DEFAULT_FILTER)
  const [filterBarOpen, setFilterBarOpen] = useState(false)
  const [diffPopoverAnchor, setDiffPopoverAnchor] = useState<HTMLElement | null>(null)
  const [diffPopoverEvent, setDiffPopoverEvent] = useState<EventViewModel | null>(null)
  const [dismissedSuggestionIds] = useState<Set<string>>(new Set())
  const timelineViewMode = useAppStore(s => s.timelineViewMode)

  const selectedEventIds = useAppStore(s => s.selectedEventIds)
  const selectEvent = useAppStore(s => s.selectEvent)
  const pendingDrafts = useAppStore(s => s.pendingDrafts)
  const setTrackScrollLeft = useAppStore(s => s.setTrackScrollLeft)
  const trackScrollLeft = useAppStore(s => s.trackScrollLeft)

  const coord = useTimelineCoordinates(totalDuration || 80, canvasW, trackScrollLeft)

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
    if (ev) {
      coord.scrollToTime(ev.start)
      if (ev.visualState.hasAiSuggestion && !dismissedSuggestionIds.has(eventId)) {
        setDiffPopoverAnchor(e.currentTarget as HTMLElement)
        setDiffPopoverEvent(ev)
      } else {
        setDiffPopoverAnchor(null)
        setDiffPopoverEvent(null)
      }
    }
  }, [selectedEventIds, selectEvent, events, coord])

  // Double click
  const handleEventDoubleClick = useCallback((eventId: string) => {
    const ev = events.find(x => x.id === eventId)
    if (ev) useAppStore.getState().setPlayhead(ev.start)
  }, [events])

  // Context menu
  const handleEventContextMenu = useCallback((eventId: string, e: React.MouseEvent) => {
    const ev = events.find(x => x.id === eventId)
    if (ev) {
      setContextMenuEvent(ev)
      setContextMenuAnchor(e.currentTarget as HTMLElement)
    }
  }, [events])

  const handleCloseContextMenu = useCallback(() => {
    setContextMenuAnchor(null)
    setContextMenuEvent(null)
  }, [])

  const handleCloseDiffPopover = useCallback(() => {
    if (diffPopoverEvent) dismissedSuggestionIds.add(diffPopoverEvent.id)
    setDiffPopoverAnchor(null)
    setDiffPopoverEvent(null)
  }, [diffPopoverEvent])

  const handleToggleEventLock = useCallback((eventId: string) => {
    setLockedEventIds(prev => {
      const next = new Set(prev)
      if (next.has(eventId)) next.delete(eventId)
      else next.add(eventId)
      return next
    })
  }, [])

  const handleToggleFilter = useCallback(() => setFilterBarOpen(p => !p), [])

  const handleRetrigger = useCallback(() => {
    const selected = useAppStore.getState().selectedEventIds
    const store = useAppStore.getState()
    const targets = selected.length > 0 ? selected : events.map(e => e.id)
    for (const id of targets) {
      store.addDraft({
        eventId: id,
        opcode: 'RETRIGGER',
        payload: {},
        before: {},
        after: {},
        timestamp: Date.now(),
      })
    }
  }, [events])

  const handleRequestAiAssist = useCallback(async () => {
    const store = useAppStore.getState()
    const selected = store.selectedEventIds
    const targets = selected.length > 0
      ? events.filter(e => selected.includes(e.id))
      : events.filter(e => e.confidence < 0.7)

    const ws = store.workspace || ''
    const targetLang = store.manifest?.target_lang || 'zh'

    for (const evt of targets) {
      const sourceText = evt.text || ''
      const currentTrans = evt.translation || ''
      if (!sourceText.trim() || !currentTrans.trim()) continue

      try {
        const res = await fetch('/api/timeline/ai/suggest', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            event_id: evt.id,
            workspace: ws,
            source_text: sourceText,
            current_translation: currentTrans,
            target_lang: targetLang,
          }),
        })
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}))
          const detail = (errData as any).detail || `HTTP ${res.status}`
          store.addDraft({
            eventId: evt.id,
            opcode: 'AI_SUGGEST',
            payload: { suggestion: `[AI 请求失败] ${detail}`, error: true },
            before: { translation: currentTrans },
            after: {},
            timestamp: Date.now(),
          })
          continue
        }
        const data = await res.json()
        store.addDraft({
          eventId: evt.id,
          opcode: 'AI_SUGGEST',
          payload: {
            suggestion: data.suggestion,
            reasoning: data.reasoning,
            diff: data.diff,
          },
          before: { translation: currentTrans },
          after: { translation: data.suggestion },
          timestamp: Date.now(),
        })
      } catch (e) {
        store.addDraft({
          eventId: evt.id,
          opcode: 'AI_SUGGEST',
          payload: { suggestion: `[网络错误] ${e}`, error: true },
          before: { translation: currentTrans },
          after: {},
          timestamp: Date.now(),
        })
      }
    }
  }, [events])

  // Apply filters
  const { visible: filteredEvents, dimmed: dimmedEventIds } = applyFilter(events, filterState)

  // Drag & drop video
  const onDragOver = useCallback((e: React.DragEvent) => { e.preventDefault(); setDragOver(true) }, [])
  const onDragLeave = useCallback(() => setDragOver(false), [])
  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file && onDropVideo) onDropVideo(file)
  }, [onDropVideo])

  // Playback handlers
  const handlePlayPause = useCallback(() => {
    setIsPlaying(p => {
      if (!p) {
        // Seek video to playhead before starting playback
        setVideoCurrentTime(useAppStore.getState().playheadPosition)
      }
      return !p
    })
  }, [])

  const handleJumpPrev = useCallback(() => {
    const playhead = useAppStore.getState().playheadPosition
    const prev = events.filter(e => e.end <= playhead).sort((a, b) => b.end - a.end)[0]
    if (prev) useAppStore.getState().setPlayhead(prev.start)
  }, [events])

  const handleJumpNext = useCallback(() => {
    const playhead = useAppStore.getState().playheadPosition
    const next = events.filter(e => e.start >= playhead).sort((a, b) => a.start - b.start)[0]
    if (next) useAppStore.getState().setPlayhead(next.start)
  }, [events])

  const handleToggleLoop = useCallback(() => setLoopEnabled(l => !l), [])

  const handleScrollToPlayhead = useCallback(() => {
    const playhead = useAppStore.getState().playheadPosition
    coord.scrollToTime(playhead)
  }, [coord])

  const handleVideoTimeUpdate = useCallback((t: number) => {
    setVideoCurrentTime(t)
    useAppStore.getState().setPlayhead(t)
  }, [])

  const handleVideoDurationChange = useCallback((_d: number) => {
    // duration tracked by VideoPreview internally
  }, [])

  const isEmpty = events.length === 0

  // Keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Don't intercept when focus is in an input
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (e.key === ' ') { e.preventDefault(); handlePlayPause() }
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
        display: 'flex', flexDirection: 'column',
        cursor: dragOver ? 'copy' : 'default',
      }}
    >
      <TimelineToolbar
        isPlaying={isPlaying}
        onPlayPause={handlePlayPause}
        onJumpPrev={handleJumpPrev}
        onJumpNext={handleJumpNext}
        loopEnabled={loopEnabled}
        onToggleLoop={handleToggleLoop}
        onZoomIn={() => coord.zoomIn()}
        onZoomOut={() => coord.zoomOut()}
        onZoomToFit={() => coord.zoomToFit(0.05)}
        onScrollToPlayhead={handleScrollToPlayhead}
        filterBarOpen={filterBarOpen}
        onToggleFilter={handleToggleFilter}
        onRetrigger={handleRetrigger}
        onRequestAiAssist={handleRequestAiAssist}
      />
      <FilterBar
        open={filterBarOpen}
        filter={filterState}
        onChange={setFilterState}
        onClose={() => setFilterBarOpen(false)}
        events={events}
      />
      <VideoPreview
        videoSrc={videoSrc || null}
        currentTime={videoCurrentTime}
        events={filteredEvents}
        isPlaying={isPlaying}
        onTimeUpdate={handleVideoTimeUpdate}
        onDurationChange={handleVideoDurationChange}
      />
      {!isEmpty && timelineViewMode === 'timeline' ? (
          <>
            <RubberBandSelect
              events={filteredEvents}
              pixelToTime={coord.pixelToTime}
              containerRef={containerRef}
            >
              <TrackSystem
                events={filteredEvents}
                totalDuration={totalDuration || 80}
                canvasWidth={canvasW}
                coord={coord}
                waveformData={waveform}
                ttsWaveforms={ttsWaveforms}
                dimmedEventIds={dimmedEventIds}
                onEventClick={handleEventClick}
                onEventDblClick={handleEventDoubleClick}
                onEventContextMenu={handleEventContextMenu}
              />
            </RubberBandSelect>
            {Array.from(pendingDrafts.values())
              .filter(d => d.opcode === 'SPLIT' || d.payload.start || d.payload.end)
              .map(d => {
                const evt = events.find(e => e.id === d.eventId)
                if (!evt) return null
                const startX = coord.timeToPixel(evt.end)
                const affectedIds = events.filter(e => e.start >= evt.end).slice(0, 5).map(e => e.id)
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
        ) : timelineViewMode === 'table' ? (
          <Box sx={{ flex: '1 1 0', overflow: 'auto', minHeight: 0 }}>
            <ReviewTable
              events={filteredEvents}
              onSeek={(time: number) => {
                useAppStore.getState().setPlayhead(time)
                setVideoCurrentTime(time)
              }}
            />
          </Box>
        ) : timelineViewMode === 'speaker-timeline' ? (
          <SpeakerReviewView
            events={filteredEvents}
            onSeek={(time: number) => {
              useAppStore.getState().setPlayhead(time)
              setVideoCurrentTime(time)
            }}
          />
        ) : (
          <Box sx={{
            flexGrow: 1, display: 'flex',
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
        )
      }

      {/* Context menu */}
      <EventContextMenu
        anchorEl={contextMenuAnchor}
        event={contextMenuEvent}
        events={events}
        playheadTime={useAppStore.getState().playheadPosition}
        onClose={handleCloseContextMenu}
        lockedEventIds={lockedEventIds}
        onToggleLock={handleToggleEventLock}
      />

      {/* AI suggestion diff popover */}
      <PatchDiffPopover
        event={diffPopoverEvent}
        anchorEl={diffPopoverAnchor}
        onClose={handleCloseDiffPopover}
      />

      {/* Zoom controls + Minimap — 表格模式下隐藏小地图 */}
      {timelineViewMode !== 'table' && (
        <Box sx={{
          display: 'flex', flexDirection: 'column',
          borderTop: '1px solid rgba(255,255,255,0.1)',
          bgcolor: '#1a1a1a',
          flexShrink: 0,
        }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1, py: 0.5 }}>
            <ZoomPresets coord={coord} />
            <Box sx={{ flexGrow: 1 }} />
            <Box sx={{ display: 'flex', gap: 0.5 }}>
              <Box component="button" onClick={() => coord.zoomOut()} aria-label="缩小"
                sx={{ width: 24, height: 24, border: '1px solid rgba(255,255,255,0.5)', borderRadius: 1, bgcolor: '#333', color: '#fff', cursor: 'pointer', fontSize: '0.9rem', p: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                −
              </Box>
              <Box component="button" onClick={() => coord.zoomIn()} aria-label="放大"
                sx={{ width: 24, height: 24, border: '1px solid rgba(255,255,255,0.5)', borderRadius: 1, bgcolor: '#333', color: '#fff', cursor: 'pointer', fontSize: '0.9rem', p: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                +
              </Box>
            </Box>
          </Box>
          <TimelineMinimap
            events={events}
            coord={coord}
            totalDuration={totalDuration || 80}
            canvasWidth={canvasW}
          />
        </Box>
      )}
    </Box>
  )
}
