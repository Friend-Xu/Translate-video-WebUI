import { useState, useCallback, useRef, useMemo, useEffect, Fragment } from 'react'
import {
  Box, Typography, Chip, IconButton, Tooltip, Button, Divider,
  MenuItem, Select, FormControl,
  Dialog, DialogTitle, DialogContent, DialogActions, CircularProgress, Menu,
} from '@mui/material'
import PersonAddIcon from '@mui/icons-material/PersonAddRounded'
import PlayArrowIcon from '@mui/icons-material/PlayArrowRounded'
import ZoomInIcon from '@mui/icons-material/ZoomInRounded'
import ZoomOutIcon from '@mui/icons-material/ZoomOutRounded'
import MergeIcon from '@mui/icons-material/MergeRounded'
import LockIcon from '@mui/icons-material/LockRounded'
import EditIcon from '@mui/icons-material/EditRounded'
import WarningIcon from '@mui/icons-material/WarningRounded'
import VoiceIcon from '@mui/icons-material/RecordVoiceOverRounded'
import { useAppStore } from '../../store/useAppStore'
import { useTimelineCoordinates } from '../../hooks/useTimelineCoordinates'
import SpeakerWaveform from './SpeakerWaveform'
import type { EventViewModel } from '../../types'
import type { SpeakerQuality } from '../../types/modes'

const LANE_COLORS = ['#FF9800', '#2196F3', '#4CAF50', '#9C27B0', '#E91E63', '#00BCD4',
  '#F44336', '#795548', '#607D8B', '#CDDC39', '#03A9F4', '#FF5722']
const LANE_HEIGHT = 64
const TIME_RULER_H = 20

interface SpeakerSegment {
  id: string
  start: number
  end: number
  text: string
  translation: string | object
  confidence: number
  eventId: string
}

interface SpeakerLane {
  speaker: string
  display_name: string
  voice_id: string
  color: string
  segments: SpeakerSegment[]
  segment_count: number
  total_duration: number
}

interface Props {
  events: EventViewModel[]
  speakers?: SpeakerLane[]
  onSeek?: (time: number) => void
}

export default function SpeakerReviewView({ events, speakers: externalSpeakers, onSeek }: Props) {
  const storeSpeakerLanes = useAppStore(s => s.speakerLanes)
  const selectedSpeakerId = useAppStore(s => s.selectedSpeakerId)
  const selectedSpeakerIds = useAppStore(s => s.selectedSpeakerIds)
  const setSelectedSpeaker = useAppStore(s => s.setSelectedSpeaker)
  const toggleSpeakerSelection = useAppStore(s => s.toggleSpeakerSelection)
  const addDraft = useAppStore(s => s.addDraft)
  const setMode = useAppStore(s => s.setMode)
  const workspace = useAppStore(s => s.workspace)
  const playheadPosition = useAppStore(s => s.playheadPosition)
  const setPlayhead = useAppStore(s => s.setPlayhead)
  const selectEvent = useAppStore(s => s.selectEvent)
  const trackScrollLeft = useAppStore(s => s.trackScrollLeft)
  const setTrackScrollLeft = useAppStore(s => s.setTrackScrollLeft)

  const [mergeDialogOpen, setMergeDialogOpen] = useState(false)
  const [mergeTarget, setMergeTarget] = useState<string | null>(null)
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [createName, setCreateName] = useState('')
  const [sortBy, setSortBy] = useState<'duration' | 'confidence' | 'conflict'>('duration')
  const [editingName, setEditingName] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [selectedSegmentId, setSelectedSegmentId] = useState<string | null>(null)
  const [contextMenu, setContextMenu] = useState<{x: number, y: number, segmentId: string} | null>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const resizeRef = useRef<{ segId: string; edge: 'left' | 'right'; startX: number; origStart: number; origEnd: number; lane: string } | null>(null)
  const [resizePreview, setResizePreview] = useState<{ segId: string; left: number; width: number } | null>(null)
  const [overlaps, setOverlaps] = useState<Array<{start: number, end: number, speakers: string[], duration: number}>>([])
  const [dragSegmentId, setDragSegmentId] = useState<string | null>(null)
  const [dubLoading, setDubLoading] = useState(false)
  const [screeningResults, setScreeningResults] = useState<{
    issues: Array<{segment_id: string, rule: string, severity: string, start: number, end: number, message: string, detail: any}>
  } | null>(null)
  const [crossModelResults, setCrossModelResults] = useState<{
    divergences: Array<{segment_id: string, pyannote_label: string, wespeaker_label: string, start: number, end: number, confidence: number, message: string}>
  } | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const rulerRef = useRef<HTMLDivElement | null>(null)
  const centerRef = useRef<HTMLDivElement | null>(null)
  const justSeekedRef = useRef(false)
  const speakerColorMap = useRef<Record<string, string>>({})

  const speakerLanes: SpeakerLane[] = useMemo(() => {
    if (externalSpeakers && externalSpeakers.length > 0) return externalSpeakers
    if (storeSpeakerLanes.length > 0) {
      // Sync colors from store into stable map
      for (const l of storeSpeakerLanes) {
        if ((l as any).color) speakerColorMap.current[l.speaker] = (l as any).color
      }
      return storeSpeakerLanes as unknown as SpeakerLane[]
    }
    const spkMap: Record<string, SpeakerSegment[]> = {}
    for (const evt of events) {
      const spk = (evt as any).speaker || 'UNKNOWN'
      if (!spkMap[spk]) spkMap[spk] = []
      spkMap[spk].push({
        id: evt.id, start: evt.start, end: evt.end,
        text: evt.text || '',
        translation: evt.translation || '',
        confidence: (evt as any).confidence || 0.9,
        eventId: evt.id,
      })
    }
    // Assign stable colors: reuse known speakers, assign new colors for new ones
    const usedColors = new Set(Object.values(speakerColorMap.current))
    const available = LANE_COLORS.filter(c => !usedColors.has(c))
    let availIdx = 0
    return Object.entries(spkMap).map(([spk, segs]) => {
      let color = speakerColorMap.current[spk]
      if (!color) {
        color = available[availIdx % available.length] || LANE_COLORS[Object.keys(speakerColorMap.current).length % LANE_COLORS.length]
        speakerColorMap.current[spk] = color
        usedColors.add(color)
        availIdx++
      }
      return {
        speaker: spk, display_name: spk, voice_id: '',
        color,
        segments: segs, segment_count: segs.length,
        total_duration: segs.reduce((sum, s) => sum + (s.end - s.start), 0),
      }
    })
  }, [events, externalSpeakers, storeSpeakerLanes])

  const speakerQualities = useMemo(() => {
    const result: Record<string, SpeakerQuality> = {}
    for (const lane of speakerLanes) {
      const segs = lane.segments
      if (segs.length === 0) continue
      const avgConf = segs.reduce((s, seg) => s + seg.confidence, 0) / segs.length
      let overlapTime = 0
      const totalTime = segs[segs.length - 1].end - segs[0].start
      for (const other of speakerLanes) {
        if (other.speaker === lane.speaker) continue
        for (const s of segs)
          for (const o of other.segments) {
            const oS = Math.max(s.start, o.start), oE = Math.min(s.end, o.end)
            if (oE > oS) overlapTime += oE - oS
          }
      }
      const conflictRate = totalTime > 0 ? Math.min(1, overlapTime / totalTime) : 0
      const sorted = [...segs].sort((a, b) => a.start - b.start)
      let totalGaps = 0
      for (let i = 1; i < sorted.length; i++) {
        const gap = sorted[i].start - sorted[i - 1].end
        if (gap > 0) totalGaps += gap
      }
      const span = sorted[sorted.length - 1].end - sorted[0].start
      const continuityScore = span > 0 ? 1 - Math.min(1, totalGaps / span) : 1
      result[lane.speaker] = {
        speakerId: lane.speaker, avgConfidence: avgConf, conflictRate,
        switchFrequency: span > 0 ? segs.length / (span / 60) : 0, continuityScore,
      }
    }
    return result
  }, [speakerLanes])

  // Sort speakers by chosen criteria
  const sortedSpeakers = useMemo(() => {
    const arr = [...speakerLanes]
    const qs = speakerQualities
    switch (sortBy) {
      case 'duration': arr.sort((a, b) => b.total_duration - a.total_duration); break
      case 'confidence': arr.sort((a, b) => (qs[a.speaker]?.avgConfidence || 0) - (qs[b.speaker]?.avgConfidence || 0)); break
      case 'conflict': arr.sort((a, b) => (qs[b.speaker]?.conflictRate || 0) - (qs[a.speaker]?.conflictRate || 0)); break
    }
    return arr
  }, [speakerLanes, speakerQualities, sortBy])

  const totalDuration = useMemo(() => Math.max(...events.map(e => e.end), 80), [events])
  const canvasW = typeof window !== 'undefined' ? window.innerWidth - 520 : 600
  const coord = useTimelineCoordinates(totalDuration, canvasW, trackScrollLeft, setTrackScrollLeft)

  // Find active segment at playhead position for playback-following highlight
  const activeSegmentRef = useMemo(() => {
    for (const lane of speakerLanes) {
      for (const seg of lane.segments) {
        if (playheadPosition >= seg.start && playheadPosition <= seg.end) {
          return { seg, lane }
        }
      }
    }
    return null
  }, [speakerLanes, playheadPosition])

  // Auto-scroll to keep active segment visible (skipped after user clicks ruler OR drags scrollbar)
  const sliderDraggingRef = useRef(false)
  useEffect(() => {
    if (!autoScroll || !activeSegmentRef || !scrollRef.current || justSeekedRef.current || sliderDraggingRef.current) return
    const lanesDiv = scrollRef.current
    const segX = activeSegmentRef.seg.start * coord.pixelsPerSec
    const segW = (activeSegmentRef.seg.end - activeSegmentRef.seg.start) * coord.pixelsPerSec
    const segCenter = segX + segW / 2
    const viewStart = trackScrollLeft
    const viewEnd = viewStart + lanesDiv.clientWidth

    if (segCenter < viewStart + 100 || segCenter > viewEnd - 100) {
      setTrackScrollLeft(Math.max(0, segCenter - lanesDiv.clientWidth / 2))
    }
  }, [activeSegmentRef, autoScroll, coord.pixelsPerSec, trackScrollLeft, setTrackScrollLeft])

  // Load overlap + screening data
  useEffect(() => {
    if (!workspace) return
    const params = new URLSearchParams({ workspace })
    fetch(`/api/speaker/diarization/overlaps?${params}`)
      .then(r => r.json()).then(data => {
        if (data.overlaps) setOverlaps(data.overlaps)
      }).catch(() => {})
    fetch('/api/speaker/screening/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, include_cross_model: true }),
    }).then(r => r.json()).then(data => {
      if (data.screening) setScreeningResults(data.screening)
      if (data.cross_model) setCrossModelResults(data.cross_model)
    }).catch(() => {})
  }, [workspace])

  const handleSelectSpeaker = useCallback((speakerId: string, e: React.MouseEvent) => {
    if (e.ctrlKey || e.metaKey) {
      toggleSpeakerSelection(speakerId)
    } else {
      setSelectedSpeaker(speakerId)
    }
  }, [setSelectedSpeaker, toggleSpeakerSelection])

  const handleMerge = useCallback(async () => {
    if (!mergeTarget || selectedSpeakerIds.length < 2) return
    const source = selectedSpeakerIds.find(id => id !== mergeTarget)
    if (!source) return
    // P2 收敛: 统一走 patch (MergeEngine MERGE_SPEAKERS) — 端点写路径退役
    const store = useAppStore.getState()
    store.addDraft({
      eventId: source, opcode: 'MERGE_SPEAKERS',
      payload: { source, target: mergeTarget },
      before: {}, after: {}, timestamp: Date.now(),
    })
    const ok = await store.applyDraft(source)
    if (ok) {
      const ws = store.workspace || ''
      await store.fetchSpeakerLanes(ws)
    }
    setMergeDialogOpen(false)
    setMergeTarget(null)
  }, [mergeTarget, selectedSpeakerIds])

  const handleCreateSpeaker = useCallback(async () => {
    if (!createName.trim()) return
    addDraft({
      eventId: `SPEAKER_${Date.now()}`, opcode: 'CREATE_SPEAKER',
      payload: { display_name: createName.trim() },
      before: {}, after: { display_name: createName.trim() }, timestamp: Date.now(),
    })
    setCreateDialogOpen(false)
    setCreateName('')
  }, [createName])

  const handleLockSpeaker = useCallback((speakerId: string) => {
    addDraft({
      eventId: speakerId, opcode: 'LOCK_SPEAKER',
      payload: { speaker: speakerId }, before: {}, after: {}, timestamp: Date.now(),
    })
  }, [addDraft])

  const handleRename = useCallback(async (speakerId: string) => {
    if (!editValue.trim()) { setEditingName(null); return }
    const newName = editValue.trim()
    // P2 收敛: 统一走 patch (UPDATE_SPEAKER) — rename 端点写路径退役
    const store = useAppStore.getState()
    store.addDraft({
      eventId: speakerId, opcode: 'RENAME_SPEAKER',
      payload: { newName },
      before: {}, after: { displayName: newName }, timestamp: Date.now(),
    })
    const ok = await store.applyDraft(speakerId)
    if (ok) {
      const ws = store.workspace || ''
      await store.fetchSpeakerLanes(ws)
    }
    setEditingName(null)
  }, [editValue])

  const handleSegmentClick = useCallback((_eventId: string, startTime: number) => {
    setPlayhead(startTime)
    onSeek?.(startTime)
  }, [setPlayhead, onSeek])

  // Segment resize handlers
  const handleResizeStart = useCallback((segId: string, edge: 'left' | 'right', e: React.MouseEvent, seg: SpeakerSegment, laneSpeaker: string) => {
    e.preventDefault(); e.stopPropagation()
    const startX = e.clientX
    resizeRef.current = { segId, edge, startX, origStart: seg.start, origEnd: seg.end, lane: laneSpeaker }
    setResizePreview({ segId, left: coord.timeToPixel(seg.start), width: Math.max(2, (seg.end - seg.start) * coord.pixelsPerSec) })

    const onMove = (ev: MouseEvent) => {
      const r = resizeRef.current; if (!r) return
      const dx = (ev.clientX - startX) / coord.pixelsPerSec
      let newStart = r.origStart; let newEnd = r.origEnd
      if (r.edge === 'left') newStart = Math.max(0, Math.min(r.origEnd - 0.1, r.origStart + dx))
      else newEnd = Math.max(r.origStart + 0.1, r.origEnd + dx)
      // Store final values for commit
      ;(r as any).finalStart = newStart; (r as any).finalEnd = newEnd
      setResizePreview({ segId: r.segId, left: coord.timeToPixel(newStart), width: Math.max(2,(newEnd - newStart) * coord.pixelsPerSec) })
    }
    const onUp = async () => {
      const r: any = resizeRef.current
      if (r && r.finalStart != null) {
        // Record patch (sole mutation path)
        const store = useAppStore.getState()
        store.addDraft({
          eventId: segId, opcode: 'RESIZE_SEGMENT',
          payload: { new_start: r.finalStart, new_end: r.finalEnd },
          before: { start: r.origStart, end: r.origEnd },
          after: { start: r.finalStart, end: r.finalEnd },
          timestamp: Date.now(),
        })
        await store.applyDraft(segId)
      }
      resizeRef.current = null; setResizePreview(null)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [coord.pixelsPerSec])

  const handleSegmentSelect = useCallback((segId: string, e: React.MouseEvent) => {
    if (e.ctrlKey || e.metaKey) {
      e.stopPropagation()
      setSelectedSegmentId(prev => prev === segId ? null : segId)
    } else {
      setSelectedSegmentId(segId)
    }
    // Sync to store inspector — find the eventId if this is a real event
    for (const lane of speakerLanes) {
      const seg = lane.segments.find(s => (s.eventId || s.id || '') === segId)
      if (seg && seg.eventId) { selectEvent(seg.eventId); break }
    }
  }, [speakerLanes, selectEvent])

  const handleSegmentRightClick = useCallback((segId: string, e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setSelectedSegmentId(segId)
    setContextMenu({ x: e.clientX, y: e.clientY, segmentId: segId })
  }, [])

  // Reassign a single segment to a different speaker
  const handleReassignSegment = useCallback(async (segId: string, targetSpeaker: string) => {
    const sourceLane = speakerLanes.find(l => l.segments.some(s => (s.eventId || s.id || '') === segId))
    if (!sourceLane || sourceLane.speaker === targetSpeaker) return
    setContextMenu(null)
    try {
      const store = useAppStore.getState()
      store.addDraft({
        eventId: segId, opcode: 'ASSIGN_SPEAKER',
        payload: { new_speaker: targetSpeaker, source_speaker: sourceLane.speaker },
        before: { speaker: sourceLane.speaker }, after: { speaker: targetSpeaker },
        timestamp: Date.now(),
      })
      await store.applyDraft(segId)
    } catch {}
  }, [speakerLanes, workspace])

  // Load vocal audio for playback
  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !workspace) return
    audio.src = `/api/speaker/diarization/waveform?workspace=${encodeURIComponent(workspace)}`
    audio.load()
  }, [workspace])

  // ── Patch helpers (IR mutation must go through patch system) ──

  const recordPatch = useCallback(async (eventId: string, opcode: string, payload: Record<string, unknown>, before: Record<string, unknown>, after: Record<string, unknown>) => {
    const store = useAppStore.getState()
    store.addDraft({ eventId, opcode, payload, before, after, timestamp: Date.now() })
    await store.applyDraft(eventId)
  }, [])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT'
          || target.isContentEditable) return

      const audio = audioRef.current

      switch (e.key) {
        case ' ':
          e.preventDefault()
          if (audio) {
            if (audio.paused) { audio.play().catch(() => {}) }
            else { audio.pause() }
          }
          break
        case 'Escape':
          setSelectedSegmentId(null)
          setContextMenu(null)
          break
        case 'Tab':
          e.preventDefault()
          if (speakerLanes.length === 0) break
          {
            const allSegs = speakerLanes.flatMap(l =>
              l.segments.map(s => ({ ...s, speaker: l.speaker })))
            allSegs.sort((a, b) => a.start - b.start)
            const curIdx = allSegs.findIndex(s => s.eventId === selectedSegmentId)
            const next = e.shiftKey
              ? (curIdx <= 0 ? allSegs[allSegs.length - 1] : allSegs[curIdx - 1])
              : (curIdx >= allSegs.length - 1 ? allSegs[0] : allSegs[curIdx + 1])
            if (next) {
              setSelectedSegmentId(next.eventId)
              setSelectedSpeaker(next.speaker)
              setPlayhead(next.start)
              onSeek?.(next.start)
            }
          }
          break
        case 'Backspace':
        case 'Delete':
          if (!selectedSegmentId) break
          e.preventDefault()
          recordPatch(selectedSegmentId, 'ANNOTATE', { key: 'deleted', value: true }, {}, { deleted: true })
          setSelectedSegmentId(null)
          break
        case 'ArrowLeft':
        case 'ArrowRight':
          if (!selectedSegmentId) {
            // Move playhead
            const dt = e.shiftKey ? 1 : 0.1
            const newT = e.key === 'ArrowLeft' ? playheadPosition - dt : playheadPosition + dt
            setPlayhead(Math.max(0, Math.min(totalDuration, newT)))
          } else {
            // Adjust segment boundary
            const dt = e.shiftKey ? 0.5 : 0.05
            const dir = e.key === 'ArrowLeft' ? -dt : dt
            // Boundary adjustment via split API
            const seg = speakerLanes
              .flatMap(l => l.segments.map(s => ({ ...s, speaker: l.speaker })))
              .find(s => s.eventId === selectedSegmentId)
            if (seg) {
              recordPatch(selectedSegmentId, 'RESIZE_SEGMENT',
                { new_end: Math.max(0, seg.end + dir) },
                { end: seg.end }, { end: Math.max(0, seg.end + dir) })
            }
          }
          e.preventDefault()
          break
        case 'Enter':
          if (e.shiftKey && selectedSegmentId) {
            e.preventDefault()
            const segToSplit = speakerLanes.flatMap(l => l.segments).find(s => (s.eventId || s.id || '') === selectedSegmentId)
            if (segToSplit && playheadPosition > segToSplit.start + 0.1 && playheadPosition < segToSplit.end - 0.1) {
              recordPatch(selectedSegmentId, 'SPLIT_SEGMENT', { split_point: playheadPosition }, {}, { split_point: playheadPosition })
            }
          }
          break
      }
    }

    const closeMenu = () => setContextMenu(null)
    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('click', closeMenu)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('click', closeMenu)
    }
  }, [speakerLanes, selectedSegmentId, selectedSpeakerId, playheadPosition, totalDuration, setPlayhead, onSeek, workspace, recordPatch])

  const handleRulerClick = useCallback((e: React.MouseEvent) => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    const x = e.clientX - rect.left
    const t = Math.max(0, Math.min(totalDuration, coord.pixelToTime(x)))
    setPlayhead(t)
    onSeek?.(t)
    justSeekedRef.current = true
    setTimeout(() => { justSeekedRef.current = false }, 300)
  }, [coord, totalDuration, setPlayhead, onSeek])

  // Zoom
  const handleZoomIn = useCallback(() => coord.zoomIn(), [coord])
  const handleZoomOut = useCallback(() => coord.zoomOut(), [coord])

  // Wheel → zoom (ctrl) or scroll — native listener for non-passive support
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault()
        if (e.deltaY < 0) coord.zoomIn()
        else coord.zoomOut()
      } else {
        e.preventDefault()
        const totalW = totalDuration * coord.pixelsPerSec
        const clientW = scrollRef.current?.clientWidth || canvasW
        const maxS = Math.max(0, totalW - clientW)
        setTrackScrollLeft(Math.max(0, Math.min(maxS, trackScrollLeft + e.deltaY)))
      }
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [totalDuration, coord, canvasW, trackScrollLeft, setTrackScrollLeft])

  // Time ruler ticks
  const timeRulerTicks = useMemo(() => {
    const ticks: number[] = []
    const step = coord.pixelsPerSec >= 200 ? 0.5 : coord.pixelsPerSec >= 60 ? 1 : coord.pixelsPerSec >= 20 ? 5 : 10
    for (let t = 0; t <= totalDuration; t += step) ticks.push(t)
    return ticks
  }, [totalDuration, coord.pixelsPerSec])

  return (
    <Box sx={{ height: '100%', width: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden', pb: 0.5 }}>
      {/* Header */}
      <Box sx={{
        p: 1.5, borderBottom: '1px solid #d0d5e0',
        bgcolor: '#e8ecf4', display: 'flex', alignItems: 'center', gap: 2,
      }}>
        <Box>
          <Typography variant="subtitle2">说话人审核</Typography>
          <Typography variant="caption" color="text.secondary">
            {speakerLanes.length} 个说话人 · {speakerLanes.reduce((s, l) => s + l.segment_count, 0)} 个片段
          </Typography>
        </Box>
        <Box sx={{ flexGrow: 1 }} />

        {/* Zoom */}
        <Tooltip title="缩小 (Ctrl+滚轮)">
          <IconButton size="small" onClick={handleZoomOut}
            sx={{ color: '#475569', '&:hover': { color: '#1e293b' } }}>
            <ZoomOutIcon sx={{ fontSize: 16 }} />
          </IconButton>
        </Tooltip>
        <Tooltip title="放大 (Ctrl+滚轮)">
          <IconButton size="small" onClick={handleZoomIn}
            sx={{ color: '#475569', '&:hover': { color: '#1e293b' } }}>
            <ZoomInIcon sx={{ fontSize: 16 }} />
          </IconButton>
        </Tooltip>

        <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />

        <FormControl size="small" sx={{ minWidth: 100 }}>
          <Select value={sortBy} onChange={(e) => setSortBy(e.target.value as any)}
            sx={{ fontSize: '0.7rem' }}>
            <MenuItem value="duration" sx={{ fontSize: '0.7rem' }}>按时长</MenuItem>
            <MenuItem value="confidence" sx={{ fontSize: '0.7rem' }}>按置信度</MenuItem>
            <MenuItem value="conflict" sx={{ fontSize: '0.7rem' }}>按冲突率</MenuItem>
          </Select>
        </FormControl>

        <Tooltip title={autoScroll ? '自动跟随: 开' : '自动跟随: 关'}>
          <Chip label="跟随" size="small"
            variant={autoScroll ? 'filled' : 'outlined'}
            color={autoScroll ? 'primary' : 'default'}
            onClick={() => setAutoScroll(v => !v)}
            sx={{ fontSize: '0.65rem', height: 24, cursor: 'pointer' }} />
        </Tooltip>

        <Tooltip title="新建说话人">
          <IconButton size="small" onClick={() => { setCreateName(''); setCreateDialogOpen(true) }}
            sx={{ color: '#475569', '&:hover': { color: '#6366f1' } }}>
            <PersonAddIcon sx={{ fontSize: 16 }} />
          </IconButton>
        </Tooltip>

        {selectedSpeakerIds.length >= 2 && (
          <Button size="small" variant="outlined" color="warning" startIcon={<MergeIcon />}
            onClick={() => setMergeDialogOpen(true)} sx={{ fontSize: '0.7rem' }}>
            合并选中 ({selectedSpeakerIds.length})
          </Button>
        )}
        {selectedSpeakerIds.length >= 1 && (
          <Button size="small" variant="outlined" startIcon={<LockIcon />}
            onClick={() => selectedSpeakerIds.forEach(handleLockSpeaker)} sx={{ fontSize: '0.7rem' }}>
            锁定选中
          </Button>
        )}

        <Box sx={{ flexGrow: 1 }} />

        {/* 继续配音按钮 — 说话人校验完成后触发 TRANSLATE → TTS → EXPORT */}
        <Button size="small" variant="contained" color="primary"
          startIcon={dubLoading ? <CircularProgress size={14} /> : <VoiceIcon />}
          disabled={dubLoading}
          onClick={async () => {
            setDubLoading(true)
            try {
              const res = await fetch('/api/speaker/diarization/continue-dub', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ workspace }),
              })
              const data = await res.json()
              if (data.job_id) {
                setMode('hub')
              }
            } catch (e) { console.error('continue dub failed:', e) }
            finally { setDubLoading(false) }
          }}
          sx={{ fontSize: '0.7rem', mr: 1 }}>
          开始配音
        </Button>
      </Box>

      <Box sx={{ flexGrow: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Left: Speaker list */}
        <Box sx={{
          width: 200, minWidth: 200, borderRight: '1px solid #d0d5e0',
          overflow: 'hidden', bgcolor: '#e8ecf4', flexShrink: 0,
        }}>
          {/* Spacer matching time ruler height */}
          <Box sx={{ height: TIME_RULER_H, minHeight: TIME_RULER_H, borderBottom: '1px solid #c8cdd8' }} />
          {/* Spacer matching waveform height */}
          <Box sx={{ height: 48, minHeight: 48, bgcolor: '#dce2f0', borderBottom: '1px solid #c8cdd8' }} />
          {sortedSpeakers.map((lane) => {
            const quality = speakerQualities[lane.speaker]
            const isSelected = selectedSpeakerId === lane.speaker
            const isMulti = selectedSpeakerIds.includes(lane.speaker)
            return (
              <Box key={lane.speaker} onClick={(e) => handleSelectSpeaker(lane.speaker, e)}
                sx={{
                  p: 1, cursor: 'pointer', height: LANE_HEIGHT,
                  display: 'flex', flexDirection: 'column', justifyContent: 'center',
                  borderBottom: '1px solid #d0d5e0',
                  bgcolor: isSelected ? 'rgba(99,102,241,0.12)' : isMulti ? 'rgba(99,102,241,0.06)' : 'transparent',
                  '&:hover': { bgcolor: 'rgba(99,102,241,0.08)' },
                }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                  <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: lane.color, flexShrink: 0 }} />
                  {editingName === lane.speaker ? (
                    <input value={editValue}
                      onChange={e => setEditValue(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') handleRename(lane.speaker); if (e.key === 'Escape') setEditingName(null) }}
                      onBlur={() => handleRename(lane.speaker)}
                      onClick={e => e.stopPropagation()}
                      autoFocus
                      style={{ width: '100%', background: 'transparent', border: '1px solid #94a3b8', color: '#1e293b', fontSize: '0.7rem', padding: '1px 4px', borderRadius: 2 }} />
                  ) : (
                    <Typography variant="body2" noWrap sx={{ fontSize: '0.78rem', fontWeight: isSelected ? 600 : 400, flexGrow: 1, minWidth: 0 }}>
                      {lane.display_name}
                    </Typography>
                  )}
                  <Tooltip title="试听原声">
                    <IconButton size="small" onClick={async (e) => {
                      e.stopPropagation()
                      const segs = lane.segments
                      if (segs.length === 0) return
                      const idx = Math.floor(segs.length / 2)
                      const s = segs[idx]
                      const dur = Math.min(5, s.end - s.start)
                      const path = workspace ? `${workspace}/01_extract/vocals.wav` : ''
                      if (!path) return
                      const params = new URLSearchParams({ path, start: String(s.start), end: String(s.start + dur) })
                      try {
                        const res = await fetch(`/api/speaker/audio/preview?${params}`)
                        if (!res.ok) return
                        const data = await res.json()
                        const audio = audioRef.current
                        if (audio) {
                          audio.src = `data:audio/wav;base64,${data.audio_base64}`
                          audio.play().catch(() => {})
                        }
                      } catch {}
                    }}
                      sx={{ p: 0, color: 'text.disabled', flexShrink: 0, '&:hover': { color: '#f59e0b' } }}>
                      <PlayArrowIcon sx={{ fontSize: 12 }} />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title="重命名">
                    <IconButton size="small" onClick={(e) => { e.stopPropagation(); setEditingName(lane.speaker); setEditValue(lane.display_name) }}
                      sx={{ p: 0, color: 'text.disabled', flexShrink: 0, '&:hover': { color: '#6366f1' } }}>
                      <EditIcon sx={{ fontSize: 12 }} />
                    </IconButton>
                  </Tooltip>
                </Box>
                <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', ml: 2.5 }}>
                  <Chip label={`${lane.segment_count}段`} size="small"
                    sx={{ fontSize: '0.55rem', height: 16, bgcolor: 'rgba(99,102,241,0.08)' }} />
                  <Chip label={`${(lane.total_duration ?? 0).toFixed(0)}s`} size="small" variant="outlined"
                    sx={{ fontSize: '0.55rem', height: 16 }} />
                  {quality && quality.avgConfidence < 0.7 && (
                    <Chip icon={<WarningIcon sx={{ fontSize: 10 }} />} label="低置信度" size="small" color="warning"
                      sx={{ fontSize: '0.55rem', height: 16 }} />
                  )}
                  {lane.voice_id && (
                    <Chip icon={<VoiceIcon sx={{ fontSize: 10 }} />} label="已绑定" size="small" color="success"
                      variant="outlined" sx={{ fontSize: '0.55rem', height: 16 }} />
                  )}
                </Box>
              </Box>
            )
          })}
        </Box>

        {/* Center: Speaker timeline */}
        <Box ref={centerRef} sx={{ flex: '1 1 0%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Time ruler */}
          <Box ref={rulerRef} onClick={handleRulerClick} sx={{
            position: 'relative', height: TIME_RULER_H, minHeight: TIME_RULER_H,
            bgcolor: '#dce2f0', borderBottom: '1px solid #c8cdd8',
            overflow: 'hidden', cursor: 'pointer',
          }}>
            <Box sx={{ position: 'relative', width: totalDuration * coord.pixelsPerSec, height: '100%', transform: 'none', willChange: 'transform' }}>
              {timeRulerTicks.map(t => {
                const x = coord.timeToPixel(t)
                return (
                  <Box key={t} sx={{
                    position: 'absolute', left: x, top: 0, width: 1, height: 8,
                    bgcolor: '#94a3b8',
                  }}>
                    <Typography sx={{
                      position: 'absolute', left: 3, top: 8,
                      fontSize: 8, color: '#64748b', whiteSpace: 'nowrap', lineHeight: '12px',
                    }}>
                      {Number.isInteger(t) ? `${t}s` : t.toFixed(1) + 's'}
                    </Typography>
                  </Box>
                )
              })}
            </Box>
          </Box>

          {/* Waveform */}
          <SpeakerWaveform
            workspace={workspace}
            totalDuration={totalDuration}
            pixelsPerSec={coord.pixelsPerSec}
            scrollLeft={trackScrollLeft}
            containerWidth={centerRef.current?.clientWidth || 600}
          />

          {/* Lanes */}
          <Box ref={scrollRef}
            sx={{ flexGrow: 1, overflow: "hidden", position: "relative", bgcolor: "#f1f5f9" }}>
            <Box sx={{
              width: totalDuration * coord.pixelsPerSec, minWidth: '100%',
              position: 'relative', minHeight: speakerLanes.length * LANE_HEIGHT,
              transform: `translateX(${-trackScrollLeft}px)`, willChange: 'transform',
            }}>
              {/* Playhead line */}
              <Box sx={{
                position: 'absolute',
                left: playheadPosition * coord.pixelsPerSec,
                top: 0, bottom: 0, width: 2, bgcolor: '#FF5252', zIndex: 20, pointerEvents: 'none',
              }} />
              {/* Overlap markers */}
              {overlaps.map((ov, i) => {
                const ol = ov.start * coord.pixelsPerSec
                const ow = Math.max(2, (ov.end - ov.start) * coord.pixelsPerSec)
                return (
                  <Box key={`ov_${i}`} sx={{
                    position: 'absolute',
                    left: ol, top: 0, bottom: 0, width: ow,
                    bgcolor: 'rgba(239,68,68,0.12)',
                    backgroundImage: 'repeating-linear-gradient(-45deg, transparent, transparent 3px, rgba(239,68,68,0.15) 3px, rgba(239,68,68,0.15) 6px)',
                    zIndex: 5, pointerEvents: 'none',
                  }}>
                    <Tooltip title={`重叠: ${ov.speakers.join(', ')}\n${ov.duration.toFixed(1)}s`}>
                      <Box sx={{ width: '100%', height: '100%' }} />
                    </Tooltip>
                  </Box>
                )
              })}
              {sortedSpeakers.map((lane) => (
                <Box key={lane.speaker} sx={{
                  height: LANE_HEIGHT,
                  borderBottom: '1px solid #d0d5e0',
                  bgcolor: selectedSpeakerId === lane.speaker ? 'rgba(99,102,241,0.06)'
                    : dragSegmentId ? 'rgba(255,152,0,0.04)' : 'transparent',
                  position: 'relative',
                  transition: 'background-color 0.15s',
                }}
                  onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move' }}
                  onDrop={(e) => {
                    e.preventDefault()
                    const segId = e.dataTransfer.getData('text/plain') || dragSegmentId
                    console.log('🟢 DROP', segId, '→', lane.speaker)
                    if (segId) handleReassignSegment(segId, lane.speaker)
                    setDragSegmentId(null)
                  }}>
                  {lane.segments.map((seg, j) => {
                    const left = seg.start * coord.pixelsPerSec
                    const width = Math.max(2, (seg.end - seg.start) * coord.pixelsPerSec)
                    const conf = seg.confidence
                    const segId = seg.eventId || `${lane.speaker}_seg_${j}`
                    const isSegSelected = selectedSegmentId === segId
                    const isPlaying = activeSegmentRef?.seg === seg && activeSegmentRef?.lane.speaker === lane.speaker
                    const bgColor = isSegSelected ? `${lane.color}FF`
                      : isPlaying ? `${lane.color}DD`
                      : conf >= 0.9 ? `${lane.color}CC` : conf >= 0.7 ? `${lane.color}88` : `${lane.color}55`
                    // Screening / cross-model flags
                    const screeningFlags = (screeningResults?.issues || []).filter(
                      (iss: any) => iss.segment_id === segId || iss.segment_id === seg.id)
                    const crossFlags = (crossModelResults?.divergences || []).filter(
                      (d: any) => d.segment_id === segId || d.segment_id === seg.id)
                    const hasCritical = screeningFlags.some((f: any) => f.severity === 'critical')
                    const hasWarning = screeningFlags.some((f: any) => f.severity === 'warning')
                    const hasDivergence = crossFlags.length > 0
                    const markerColor = hasCritical ? '#EF4444' : hasWarning ? '#F59E0B' : hasDivergence ? '#8B5CF6' : null
                    const isResizing = resizePreview?.segId === segId
                    const displayLeft = isResizing ? resizePreview!.left : left
                    const displayWidth = isResizing ? resizePreview!.width : width
                    return (<Fragment key={j}>
                      <Tooltip title={`${(seg.text || '').slice(0, 80)}\n${(seg.start ?? 0).toFixed(1)}s-${(seg.end ?? 0).toFixed(1)}s | conf=${(conf ?? 0).toFixed(2)}`}
                        disableHoverListener={dragSegmentId !== null || resizePreview !== null}>
                        <Box sx={{
                          position: 'absolute', left: displayLeft, top: 10, height: LANE_HEIGHT - 20, width: displayWidth,
                          bgcolor: bgColor, borderRadius: 0.5,
                          borderLeft: `2px solid ${lane.color}`,
                          border: isSegSelected ? `2px solid ${lane.color}` : 'none',
                          boxShadow: isSegSelected ? `0 0 0 2px rgba(99,102,241,0.4)`
                            : isPlaying ? `0 0 4px 2px rgba(255,82,82,0.4)` : 'none',
                          cursor: isResizing ? 'col-resize' : 'pointer', zIndex: isSegSelected ? 4 : isPlaying ? 2 : 1,
                          '&:hover': { filter: 'brightness(1.2)', zIndex: 3 },
                          opacity: dragSegmentId === segId ? 0.4 : 1,
                        }}
                          onClick={(e) => {
                            if (isResizing) return
                            handleSegmentSelect(segId, e)
                            handleSegmentClick(segId, seg.start)
                          }}
                          onContextMenu={(e) => handleSegmentRightClick(segId, e)}
                          draggable
                          onDragStart={(e) => {
                            console.log('🔵 DRAG_START', segId)
                            setDragSegmentId(segId)
                            e.dataTransfer.effectAllowed = 'move'
                            e.dataTransfer.setData('text/plain', segId)
                          }}
                          onDragEnd={() => {
                            console.log('🔴 DRAG_END', segId)
                            setDragSegmentId(null)
                          }}
                        />
                      </Tooltip>
                      {/* Resize handles — rendered as siblings ABOVE the segment for reliable hit-testing */}
                      <Box onMouseDown={(e) => handleResizeStart(segId, 'left', e, seg, lane.speaker)} sx={{
                        position: 'absolute', left: displayLeft, top: 10, height: LANE_HEIGHT - 20, width: '12px',
                        cursor: 'col-resize',
                        bgcolor: 'rgba(0,0,0,0.18)',
                        '&:hover': { bgcolor: 'rgba(255,255,255,0.4)' },
                        zIndex: 8,
                      }} />
                      <Box onMouseDown={(e) => handleResizeStart(segId, 'right', e, seg, lane.speaker)} sx={{
                        position: 'absolute', left: displayLeft + displayWidth - 12, top: 10, height: LANE_HEIGHT - 20, width: '12px',
                        cursor: 'col-resize',
                        bgcolor: 'rgba(0,0,0,0.18)',
                        '&:hover': { bgcolor: 'rgba(255,255,255,0.4)' },
                        zIndex: 8,
                      }} />
                      {markerColor && (
                        <Box sx={{
                          position: 'absolute', left: left + width - 6, top: 3,
                          width: 8, height: 8, borderRadius: '50%',
                          bgcolor: markerColor, border: '1px solid #fff', zIndex: 10,
                        }} />
                      )}
                    </Fragment>)
                  })}
                </Box>
              ))}
              {speakerLanes.length === 0 && (
                <Box sx={{ p: 4, textAlign: 'center' }}>
                  <Typography variant="body2" color="text.secondary">未加载说话人数据</Typography>
                </Box>
              )}
            </Box>
          </Box>
        </Box>
      </Box>

      {/* Native scrollbar — outside flex row, like timeline pattern */}
      <SpeakerScrollbar
          totalDuration={totalDuration}
          pixelsPerSec={coord.pixelsPerSec}
          trackScrollLeft={trackScrollLeft}
          setTrackScrollLeft={setTrackScrollLeft}
          containerWidth={centerRef.current?.clientWidth || 600}
          onDragStart={() => { sliderDraggingRef.current = true }}
          onDragEnd={() => { sliderDraggingRef.current = false }}
        />

        <audio ref={audioRef} style={{ display: 'none' }} />

      {/* Create speaker dialog */}
      <Dialog open={createDialogOpen} onClose={() => setCreateDialogOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontSize: '0.9rem' }}>新建说话人</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            创建一个新的说话人标识。之后可将片段分配到此说话人。
          </Typography>
          <input value={createName}
            onChange={e => setCreateName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleCreateSpeaker(); if (e.key === 'Escape') setCreateDialogOpen(false) }}
            autoFocus
            placeholder="输入说话人名称"
            style={{ width: '100%', padding: '8px 12px', fontSize: '0.85rem', border: '1px solid #c8cdd8', borderRadius: 4, outline: 'none' }} />
        </DialogContent>
        <DialogActions>
          <Button size="small" onClick={() => setCreateDialogOpen(false)}>取消</Button>
          <Button size="small" variant="contained" onClick={handleCreateSpeaker} disabled={!createName.trim()}>创建</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={mergeDialogOpen} onClose={() => setMergeDialogOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontSize: '0.9rem' }}>合并说话人</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            选择合并目标，其他选中的说话人将被合并到目标说话人。
          </Typography>
          <FormControl fullWidth size="small">
            <Select value={mergeTarget || ''} onChange={(e) => setMergeTarget(e.target.value)} displayEmpty>
              <MenuItem value="" disabled><em>选择目标说话人</em></MenuItem>
              {selectedSpeakerIds.map(id => {
                const lane = speakerLanes.find(l => l.speaker === id)
                return <MenuItem key={id} value={id}>{lane?.display_name || id}</MenuItem>
              })}
            </Select>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button size="small" onClick={() => setMergeDialogOpen(false)}>取消</Button>
          <Button size="small" variant="contained" color="warning" onClick={handleMerge} disabled={!mergeTarget}>合并</Button>
        </DialogActions>
      </Dialog>

      {/* Context Menu */}
      <Menu
        open={contextMenu !== null}
        onClose={() => setContextMenu(null)}
        anchorReference="anchorPosition"
        anchorPosition={contextMenu ? { top: contextMenu.y, left: contextMenu.x } : undefined}
      >
        <MenuItem dense onClick={() => {
          const seg = speakerLanes.flatMap(l =>
            l.segments.map(s => ({ ...s, speaker: l.speaker })))
            .find(s => (s.eventId || s.id || '') === (contextMenu?.segmentId || ''))
          if (seg && contextMenu) {
            setEditingName(seg.speaker)
            setEditValue(seg.speaker)
          }
          setContextMenu(null)
        }} sx={{ fontSize: '0.75rem' }}>
          重命名说话人
        </MenuItem>
        <MenuItem dense onClick={async () => {
          if (contextMenu?.segmentId) {
            const segId = contextMenu.segmentId
            // Record patch
            const store = useAppStore.getState()
            store.addDraft({
              eventId: segId, opcode: 'SPLIT_SEGMENT',
              payload: { split_point: playheadPosition },
              before: {}, after: { split_point: playheadPosition },
              timestamp: Date.now(),
            })
            await store.applyDraft(segId)
          }
          setContextMenu(null)
        }} sx={{ fontSize: '0.75rem' }}
          disabled={(() => {
            if (!contextMenu?.segmentId) return true
            const seg = speakerLanes.flatMap(l => l.segments).find(s => (s.eventId || s.id || '') === contextMenu.segmentId)
            if (!seg) return true
            return playheadPosition <= seg.start + 0.1 || playheadPosition >= seg.end - 0.1
          })()}
        >
          在播放头处拆分
        </MenuItem>
        <Divider />
        <MenuItem dense disabled sx={{ fontSize: '0.7rem', opacity: 0.6 }}>
          分配给说话人...
        </MenuItem>
        {speakerLanes.filter(l => {
          const segLane = speakerLanes.find(ll => ll.segments.some(s => {
            const sid = s.eventId || s.id || ''
            return sid === (contextMenu?.segmentId || '')
          }))
          return l.speaker !== (segLane?.speaker || '')
        }).map(l => (
          <MenuItem key={l.speaker} dense sx={{ fontSize: '0.7rem', pl: 3 }}
            onClick={() => handleReassignSegment(contextMenu?.segmentId || '', l.speaker)}>
            <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: l.color, mr: 1, flexShrink: 0 }} />
            {l.display_name}
          </MenuItem>
        ))}
        <Divider />
        <MenuItem dense onClick={() => {
          if (contextMenu?.segmentId) {
            // Find adjacent segment in same lane and merge
            const lane = speakerLanes.find(l =>
              l.segments.some(s => (s.eventId || s.id || '') === contextMenu.segmentId))
            if (lane) {
              const sorted = [...lane.segments].sort((a, b) => a.start - b.start)
              const idx = sorted.findIndex(s => (s.eventId || s.id || '') === contextMenu.segmentId)
              if (idx >= 0 && idx < sorted.length - 1) {
                const next = sorted[idx + 1]
                // Record patch for merge
                const store = useAppStore.getState()
                store.addDraft({
                  eventId: contextMenu.segmentId, opcode: 'MERGE',
                  payload: { merge_with: next.eventId || next.id || '' },
                  before: {}, after: { merged: true },
                  timestamp: Date.now(),
                })
                store.applyDraft(contextMenu.segmentId)
              }
            }
          }
          setContextMenu(null)
        }} sx={{ fontSize: '0.75rem' }}>
          与下一段合并
        </MenuItem>
        <Divider />
        <MenuItem dense onClick={async () => {
          if (contextMenu?.segmentId) {
            const segId = contextMenu.segmentId
            setSelectedSegmentId(null)
            // Record patch
            const store = useAppStore.getState()
            store.addDraft({
              eventId: segId, opcode: 'ANNOTATE',
              payload: { key: 'deleted', value: true },
              before: {}, after: { deleted: true },
              timestamp: Date.now(),
            })
            await store.applyDraft(segId)
          }
          setContextMenu(null)
        }} sx={{ fontSize: '0.75rem', color: 'error.main' }}>
          删除此段
        </MenuItem>
      </Menu>
    </Box>
  )
}

// ── SpeakerScrollbar — pure native DOM drag, no React synthetic events ──

function SpeakerScrollbar({ totalDuration, pixelsPerSec, trackScrollLeft, setTrackScrollLeft, containerWidth, onDragStart, onDragEnd }: {
  totalDuration: number
  pixelsPerSec: number
  trackScrollLeft: number
  setTrackScrollLeft: (v: number) => void
  containerWidth: number
  onDragStart: () => void
  onDragEnd: () => void
}) {
  const barRef = useRef<HTMLDivElement | null>(null)

  const totalW = totalDuration * pixelsPerSec
  const max = Math.max(100, totalW - containerWidth * 0.7)

  return (
    <Box ref={barRef} sx={{
      flexShrink: 0, width: '100%', borderTop: '1px solid #d0d5e0',
      bgcolor: '#e8ecf4', height: 14, position: 'relative', overflow: 'hidden',
    }}>
      <input
        type="range"
        min={0}
        max={max}
        step={1}
        value={Math.min(trackScrollLeft, max)}
        onChange={(e) => setTrackScrollLeft(Number(e.target.value))}
        onMouseDown={onDragStart}
        onMouseUp={onDragEnd}
        style={{
          width: '100%', height: '100%', margin: 0, padding: 0,
          cursor: 'col-resize', accentColor: '#6366F1',
        }}
      />
    </Box>
  )
}
