import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import {
  Box, Typography, Chip, IconButton, Tooltip, Button, Divider,
  MenuItem, Select, FormControl,
  Dialog, DialogTitle, DialogContent, DialogActions, CircularProgress,
} from '@mui/material'
import PersonIcon from '@mui/icons-material/PersonRounded'
import OpenInNewIcon from '@mui/icons-material/OpenInNewRounded'
import PlayArrowIcon from '@mui/icons-material/PlayArrowRounded'
import MergeIcon from '@mui/icons-material/MergeRounded'
import LockIcon from '@mui/icons-material/LockRounded'
import EditIcon from '@mui/icons-material/EditRounded'
import WarningIcon from '@mui/icons-material/WarningRounded'
import VoiceIcon from '@mui/icons-material/RecordVoiceOverRounded'
import { useAppStore } from '../../store/useAppStore'
import { useTimelineCoordinates } from '../../hooks/useTimelineCoordinates'
import { MOCK_SPEAKER_LOAD } from '../../mocks/mockData'
import type { EventViewModel } from '../../types'
import type { SpeakerLaneData, SpeakerQuality } from '../../types/modes'

const LANE_COLORS = ['#FF9800', '#2196F3', '#4CAF50', '#9C27B0', '#E91E63', '#00BCD4']
const LANE_HEIGHT = 64
const LABEL_WIDTH = 140

interface Props {
  events: EventViewModel[]
  totalDuration: number
}

export default function SpeakerReviewView({ totalDuration: _totalDuration }: Props) {
  const speakerLanes = useAppStore(s => s.speakerLanes)
  const setSpeakerLanes = useAppStore(s => s.setSpeakerLanes)
  const selectedSpeakerId = useAppStore(s => s.selectedSpeakerId)
  const selectedSpeakerIds = useAppStore(s => s.selectedSpeakerIds)
  const setSelectedSpeaker = useAppStore(s => s.setSelectedSpeaker)
  const toggleSpeakerSelection = useAppStore(s => s.toggleSpeakerSelection)
  const voicePresets = useAppStore(s => s.voicePresets)
  const setVoicePresets = useAppStore(s => s.setVoicePresets)
  const bindVoice = useAppStore(s => s.bindVoice)
  const addDraft = useAppStore(s => s.addDraft)
  const navigateToEvent = useAppStore(s => s.navigateToEvent)
  const playheadPosition = useAppStore(s => s.playheadPosition)
  const setPlayhead = useAppStore(s => s.setPlayhead)

  const [loading, setLoading] = useState(true)
  const [auditionLoading, setAuditionLoading] = useState<string | null>(null)
  const [mergeDialogOpen, setMergeDialogOpen] = useState(false)
  const [mergeTarget, setMergeTarget] = useState<string | null>(null)
  const [editingName, setEditingName] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  const totalDuration = _totalDuration || 80
  const coord = useTimelineCoordinates(totalDuration, typeof window !== 'undefined' ? window.innerWidth - 520 : 600)

  // Load speaker data: try API first, fallback to mock
  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      try {
        const res = await fetch('/api/speaker/diarization/load', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        })
        if (!res.ok) throw new Error('API not available')
        const data = await res.json()
        if (!cancelled) {
          const lanes: SpeakerLaneData[] = (data.speaker_lanes || []).map((l: any, i: number) => ({
            ...l,
            color: l.color || LANE_COLORS[i % LANE_COLORS.length],
            segments: (l.segments || []).map((s: any, j: number) => ({
              ...s,
              eventId: s.eventId || `${l.speaker}_seg_${j}`,
            })),
          }))
          setSpeakerLanes(lanes)
          if (data.voice_presets) setVoicePresets(data.voice_presets)
        }
      } catch {
        // Fallback to mock data
        if (cancelled) return
        const mock = MOCK_SPEAKER_LOAD
        const lanes: SpeakerLaneData[] = mock.speaker_lanes.map((l: any, i: number) => ({
          speaker: l.speaker,
          display_name: mock.speakerNames[l.speaker] || l.speaker,
          voice_id: '',
          color: LANE_COLORS[i % LANE_COLORS.length],
          segments: (l.segments || []).map((s: any, j: number) => ({
            start: s.start, end: s.end,
            text: s.text || '',
            translation: s.translation,
            confidence: s.confidence || 0.9,
            eventId: s.eventId || `${l.speaker}_seg_${j}`,
          })),
          segment_count: l.segments?.length || 0,
          total_duration: l.segments ? l.segments.reduce((sum: number, s: any) => sum + (s.end - s.start), 0) : 0,
        }))
        setSpeakerLanes(lanes)
        // Use mock voice presets
        setVoicePresets([
          { id: 'vc_001', name: '晓晓 (女声)', language: 'zh-CN', sampleText: '你好，欢迎使用语音合成系统。', engine: 'edge', locked: false },
          { id: 'vc_002', name: '云希 (男声)', language: 'zh-CN', sampleText: '这是来自微软的边缘语音合成。', engine: 'edge', locked: false },
          { id: 'vc_004', name: 'ChatTTS Seed 2', language: 'zh-CN', sampleText: 'ChatTTS 多样本音色。', engine: 'chattts', locked: false },
          { id: 'vc_005', name: 'CosyVoice v2 Default', language: 'zh-CN', sampleText: 'CosyVoice 跨语言合成。', engine: 'cosyvoice', locked: true },
        ])
      }
      if (!cancelled) setLoading(false)
    }
    load()
    return () => { cancelled = true }
  }, [setSpeakerLanes, setVoicePresets])

  // Compute speaker qualities (frontend)
  const speakerQualities = useMemo(() => {
    const result: Record<string, SpeakerQuality> = {}
    for (const lane of speakerLanes) {
      const segs = lane.segments
      if (segs.length === 0) continue
      const avgConf = segs.reduce((s, seg) => s + seg.confidence, 0) / segs.length
      // Conflict rate: % time overlapping with other speakers
      let overlapTime = 0
      const totalTime = segs[segs.length - 1].end - segs[0].start
      for (const other of speakerLanes) {
        if (other.speaker === lane.speaker) continue
        for (const s of segs) {
          for (const o of other.segments) {
            const overlapStart = Math.max(s.start, o.start)
            const overlapEnd = Math.min(s.end, o.end)
            if (overlapEnd > overlapStart) overlapTime += overlapEnd - overlapStart
          }
        }
      }
      const conflictRate = totalTime > 0 ? Math.min(1, overlapTime / totalTime) : 0
      // Continuity score: 1 - (gaps / total span)
      const sorted = [...segs].sort((a, b) => a.start - b.start)
      let totalGaps = 0
      for (let i = 1; i < sorted.length; i++) {
        const gap = sorted[i].start - sorted[i - 1].end
        if (gap > 0) totalGaps += gap
      }
      const span = sorted[sorted.length - 1].end - sorted[0].start
      const continuityScore = span > 0 ? 1 - Math.min(1, totalGaps / span) : 1
      result[lane.speaker] = {
        speakerId: lane.speaker,
        avgConfidence: avgConf,
        conflictRate,
        switchFrequency: span > 0 ? segs.length / (span / 60) : 0,
        continuityScore,
      }
    }
    return result
  }, [speakerLanes])

  const selectedLane = speakerLanes.find(l => l.speaker === selectedSpeakerId) || null
  const selectedQuality = selectedSpeakerId ? speakerQualities[selectedSpeakerId] : null

  // Handlers
  const handleSelectSpeaker = useCallback((speakerId: string, e: React.MouseEvent) => {
    if (e.ctrlKey || e.metaKey) {
      toggleSpeakerSelection(speakerId)
    } else {
      setSelectedSpeaker(speakerId)
    }
  }, [setSelectedSpeaker, toggleSpeakerSelection])

  const handleNavigateToTimeline = useCallback(() => {
    if (selectedLane && selectedLane.segments.length > 0) {
      const first = selectedLane.segments[0]
      navigateToEvent(first.eventId || `${selectedLane.speaker}_seg_0`, first.start, 'timeline')
    }
  }, [selectedLane, navigateToEvent])

  const handleAudition = useCallback(async (voiceId: string) => {
    const voice = voicePresets.find(v => v.id === voiceId)
    if (!voice) return
    setAuditionLoading(voiceId)
    try {
      if (voice.engine === 'chattts') {
        const res = await fetch('/api/tts/preview-chattts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: '你好，这是声线试听。', seed: 2 }),
        })
        if (res.ok) {
          const blob = await res.blob()
          const url = URL.createObjectURL(blob)
          if (audioRef.current) {
            audioRef.current.src = url
            audioRef.current.play()
          }
        }
      } else {
        // Mock playback for non-ChatTTS engines
        if (audioRef.current) {
          audioRef.current.src = 'data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACAf39/f4B/f3+Af39/gH9/f4B/f3+Af39/gH9/f4B/f3+Af39/gH9/f4B/f3+Af39/gH9/f4B/f3+Af39/gH9/f4B/f3+Af39/gH9/f4B/f3+Af39/gH9/f4B/f3+Af39/gH9/f4B/f3+Af39/gH9/f4B/f3+Af39/gH9/f4B/f3+Af39/gH9/f4B/f3+Af39/gH9/f4B/f3+Af39/gH9/f4B/f3+AA=='
          audioRef.current.play().catch(() => {})
        }
      }
    } finally {
      setAuditionLoading(null)
    }
  }, [voicePresets])

  const handleMerge = useCallback(async () => {
    if (!mergeTarget || selectedSpeakerIds.length < 2) return
    const source = selectedSpeakerIds.find(id => id !== mergeTarget)
    if (!source) return
    try {
      await fetch('/api/speaker/diarization/merge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_speaker: source, target_speaker: mergeTarget }),
      })
    } catch { /* API unavailable — generate draft instead */ }
    // Generate draft for local state update
    addDraft({
      eventId: source,
      opcode: 'MERGE_SPEAKERS',
      payload: { source, target: mergeTarget },
      before: {}, after: {},
      timestamp: Date.now(),
    })
    setMergeDialogOpen(false)
    setMergeTarget(null)
  }, [mergeTarget, selectedSpeakerIds, addDraft])

  const handleRename = useCallback((speakerId: string) => {
    if (!editValue.trim()) return
    addDraft({
      eventId: speakerId,
      opcode: 'RENAME_SPEAKER',
      payload: { newName: editValue.trim() },
      before: { displayName: selectedLane?.display_name },
      after: { displayName: editValue.trim() },
      timestamp: Date.now(),
    })
    // Try real API
    fetch('/api/speaker/diarization/rename', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ speaker: speakerId, new_name: editValue.trim() }),
    }).catch(() => {})
    setEditingName(null)
  }, [editValue, selectedLane, addDraft])

  const handleLockSpeaker = useCallback((speakerId: string) => {
    addDraft({
      eventId: speakerId,
      opcode: 'LOCK_SPEAKER',
      payload: {},
      before: {},
      after: {},
      timestamp: Date.now(),
    })
  }, [addDraft])

  const handleSegmentClick = useCallback((eventId: string, startTime: number) => {
    setPlayhead(startTime)
    navigateToEvent(eventId, startTime, 'timeline')
  }, [setPlayhead, navigateToEvent])

  if (loading) {
    return (
      <Box sx={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <CircularProgress size={24} />
      </Box>
    )
  }

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <Box sx={{ p: 1.5, borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper', display: 'flex', alignItems: 'center', gap: 2 }}>
        <Box>
          <Typography variant="subtitle2">说话人审核</Typography>
          <Typography variant="caption" color="text.secondary">
            {speakerLanes.length} 个说话人 · {speakerLanes.reduce((s, l) => s + l.segment_count, 0)} 个片段
          </Typography>
        </Box>
        <Box sx={{ flexGrow: 1 }} />
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
      </Box>

      <Box sx={{ flexGrow: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Left: Speaker list */}
        <Box sx={{
          width: 200, minWidth: 200, borderRight: 1, borderColor: 'divider',
          overflow: 'hidden auto', bgcolor: 'rgba(0,0,0,0.2)',
        }}>
          {speakerLanes.map((lane) => {
            const quality = speakerQualities[lane.speaker]
            const isSelected = selectedSpeakerId === lane.speaker
            const isMulti = selectedSpeakerIds.includes(lane.speaker)
            return (
              <Box
                key={lane.speaker}
                onClick={(e) => handleSelectSpeaker(lane.speaker, e)}
                sx={{
                  p: 1, cursor: 'pointer', borderBottom: '1px solid rgba(255,255,255,0.05)',
                  bgcolor: isSelected ? 'action.selected' : isMulti ? 'action.hover' : 'transparent',
                  '&:hover': { bgcolor: 'action.hover' },
                }}
              >
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                  <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: lane.color, flexShrink: 0 }} />
                  <Typography variant="body2" noWrap sx={{ fontSize: '0.78rem', fontWeight: isSelected ? 600 : 400 }}>
                    {lane.display_name}
                  </Typography>
                </Box>
                <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', ml: 2.5 }}>
                  <Chip label={`${lane.segment_count}段`} size="small" sx={{ fontSize: '0.55rem', height: 16 }} />
                  <Chip label={`${lane.total_duration.toFixed(0)}s`} size="small" variant="outlined" sx={{ fontSize: '0.55rem', height: 16 }} />
                  {quality && quality.avgConfidence < 0.7 && (
                    <Chip icon={<WarningIcon sx={{ fontSize: 10 }} />} label="低置信度" size="small" color="warning"
                      sx={{ fontSize: '0.55rem', height: 16 }} />
                  )}
                  {lane.voice_id && (
                    <Chip icon={<VoiceIcon sx={{ fontSize: 10 }} />} label="已绑定声线" size="small" color="success"
                      variant="outlined" sx={{ fontSize: '0.55rem', height: 16 }} />
                  )}
                </Box>
              </Box>
            )
          })}
        </Box>

        {/* Center: Speaker timeline */}
        <Box ref={scrollRef} sx={{ flexGrow: 1, overflow: 'hidden auto', position: 'relative', bgcolor: 'background.default' }}>
          {/* Playhead line */}
          <Box sx={{
            position: 'absolute', left: LABEL_WIDTH + coord.timeToPixel(playheadPosition),
            top: 0, bottom: 0, width: 2, bgcolor: '#FF5252', zIndex: 20, pointerEvents: 'none',
          }} />

          {speakerLanes.map((lane) => (
            <Box key={lane.speaker} sx={{
              display: 'flex', height: LANE_HEIGHT,
              borderBottom: '1px solid rgba(255,255,255,0.05)',
              bgcolor: selectedSpeakerId === lane.speaker ? 'rgba(255,255,255,0.03)' : 'transparent',
            }}>
              {/* Lane label */}
              <Box sx={{
                width: LABEL_WIDTH, minWidth: LABEL_WIDTH,
                display: 'flex', alignItems: 'center', gap: 0.5, px: 1,
                bgcolor: 'rgba(0,0,0,0.3)', borderRight: '1px solid rgba(255,255,255,0.1)',
              }}>
                <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: lane.color, flexShrink: 0 }} />
                <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                  {editingName === lane.speaker ? (
                    <input
                      value={editValue}
                      onChange={e => setEditValue(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') handleRename(lane.speaker); if (e.key === 'Escape') setEditingName(null) }}
                      onBlur={() => handleRename(lane.speaker)}
                      autoFocus
                      style={{ width: '100%', background: 'transparent', border: '1px solid #666', color: '#fff', fontSize: '0.7rem', padding: '1px 4px', borderRadius: 2 }}
                    />
                  ) : (
                    <Typography variant="caption" noWrap sx={{ fontSize: '0.65rem', color: 'common.white', cursor: 'pointer' }}
                      onDoubleClick={() => { setEditingName(lane.speaker); setEditValue(lane.display_name) }}>
                      {lane.display_name}
                    </Typography>
                  )}
                </Box>
                <Tooltip title="编辑名称">
                  <IconButton size="small" onClick={() => { setEditingName(lane.speaker); setEditValue(lane.display_name) }}
                    sx={{ p: 0, color: 'text.disabled' }}>
                    <EditIcon sx={{ fontSize: 12 }} />
                  </IconButton>
                </Tooltip>
              </Box>

              {/* Segment blocks */}
              <Box sx={{ flexGrow: 1, position: 'relative', overflow: 'hidden' }}>
                {lane.segments.map((seg, j) => {
                  const left = coord.timeToPixel(seg.start)
                  const width = Math.max(2, (seg.end - seg.start) * coord.pixelsPerSec)
                  const conf = seg.confidence
                  const bgColor = conf >= 0.9 ? `${lane.color}99` : conf >= 0.7 ? `${lane.color}66` : `${lane.color}44`
                  return (
                    <Tooltip key={j} title={`${seg.text}\n${seg.start.toFixed(1)}s-${seg.end.toFixed(1)}s | conf=${conf.toFixed(2)}`}>
                      <Box sx={{
                        position: 'absolute', left, top: 10, height: LANE_HEIGHT - 20, width,
                        bgcolor: bgColor, borderRadius: 0.5,
                        borderLeft: `2px solid ${lane.color}`,
                        cursor: 'pointer',
                        '&:hover': { filter: 'brightness(1.3)', zIndex: 3 },
                      }}
                        onClick={() => handleSegmentClick(seg.eventId || `${lane.speaker}_seg_${j}`, seg.start)}
                      />
                    </Tooltip>
                  )
                })}
              </Box>
            </Box>
          ))}

          {speakerLanes.length === 0 && (
            <Box sx={{ p: 4, textAlign: 'center' }}>
              <Typography variant="body2" color="text.secondary">
                未加载说话人数据
              </Typography>
            </Box>
          )}
        </Box>

        {/* Right: Speaker Inspector */}
        <Box sx={{
          width: 280, minWidth: 280, borderLeft: 1, borderColor: 'divider',
          overflow: 'hidden auto', bgcolor: 'background.paper', p: 1.5,
        }}>
          {selectedLane ? (
            <>
              {/* Identity */}
              <Typography variant="subtitle2" sx={{ fontSize: '0.8rem', mb: 1 }}>
                {selectedLane.display_name}
              </Typography>

              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 1.5 }}>
                <Chip label={selectedLane.speaker} size="small" variant="outlined" sx={{ fontSize: '0.6rem', height: 20 }} />
                <Chip label={`${selectedLane.segment_count} 段`} size="small" sx={{ fontSize: '0.6rem', height: 20 }} />
                <Chip label={`${selectedLane.total_duration.toFixed(1)}s`} size="small" variant="outlined" sx={{ fontSize: '0.6rem', height: 20 }} />
              </Box>

              {/* Quality */}
              {selectedQuality && (
                <Box sx={{ mb: 1.5 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                    质量评分
                  </Typography>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography variant="caption" sx={{ fontSize: '0.6rem', width: 60 }}>置信度</Typography>
                      <Box sx={{ flexGrow: 1, height: 4, borderRadius: 1, bgcolor: 'grey.800' }}>
                        <Box sx={{ height: '100%', borderRadius: 1, width: `${selectedQuality.avgConfidence * 100}%`,
                          bgcolor: selectedQuality.avgConfidence >= 0.9 ? '#4CAF50' : selectedQuality.avgConfidence >= 0.7 ? '#FF9800' : '#F44336' }} />
                      </Box>
                      <Typography variant="caption" sx={{ fontSize: '0.6rem' }}>{(selectedQuality.avgConfidence * 100).toFixed(0)}%</Typography>
                    </Box>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography variant="caption" sx={{ fontSize: '0.6rem', width: 60 }}>连续性</Typography>
                      <Box sx={{ flexGrow: 1, height: 4, borderRadius: 1, bgcolor: 'grey.800' }}>
                        <Box sx={{ height: '100%', borderRadius: 1, width: `${selectedQuality.continuityScore * 100}%`,
                          bgcolor: selectedQuality.continuityScore >= 0.8 ? '#4CAF50' : '#FF9800' }} />
                      </Box>
                      <Typography variant="caption" sx={{ fontSize: '0.6rem' }}>{(selectedQuality.continuityScore * 100).toFixed(0)}%</Typography>
                    </Box>
                    {selectedQuality.conflictRate > 0 && (
                      <Chip icon={<WarningIcon sx={{ fontSize: 10 }} />}
                        label={`冲突率: ${(selectedQuality.conflictRate * 100).toFixed(0)}%`}
                        size="small" color="warning" sx={{ fontSize: '0.6rem', height: 20 }} />
                    )}
                  </Box>
                </Box>
              )}

              <Divider sx={{ my: 1 }} />

              {/* Voice binding */}
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                声线绑定
              </Typography>
              <FormControl size="small" fullWidth sx={{ mb: 1 }}>
                <Select
                  value={selectedLane.voice_id || ''}
                  onChange={(e) => bindVoice(selectedLane.speaker, e.target.value)}
                  displayEmpty
                  sx={{ fontSize: '0.7rem' }}
                >
                  <MenuItem value="" sx={{ fontSize: '0.7rem' }}>
                    <em>未绑定</em>
                  </MenuItem>
                  {voicePresets.map(v => (
                    <MenuItem key={v.id} value={v.id} sx={{ fontSize: '0.7rem' }}>
                      {v.name} ({v.engine})
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              {selectedLane.voice_id && (
                <Button
                  size="small" variant="outlined"
                  startIcon={auditionLoading === selectedLane.voice_id ? <CircularProgress size={12} /> : <PlayArrowIcon />}
                  onClick={() => handleAudition(selectedLane.voice_id)}
                  disabled={auditionLoading !== null}
                  fullWidth sx={{ fontSize: '0.7rem', mb: 1 }}
                >
                  试听声线
                </Button>
              )}

              <Divider sx={{ my: 1 }} />

              {/* Actions */}
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                <Button size="small" variant="outlined" startIcon={<EditIcon />}
                  onClick={() => { setEditingName(selectedLane.speaker); setEditValue(selectedLane.display_name) }}
                  fullWidth sx={{ fontSize: '0.7rem', justifyContent: 'flex-start' }}>
                  重命名
                </Button>
                <Button size="small" variant="outlined" startIcon={<LockIcon />}
                  onClick={() => handleLockSpeaker(selectedLane.speaker)}
                  fullWidth sx={{ fontSize: '0.7rem', justifyContent: 'flex-start' }}>
                  锁定说话人
                </Button>
                <Button size="small" variant="outlined" startIcon={<OpenInNewIcon />}
                  onClick={handleNavigateToTimeline}
                  fullWidth sx={{ fontSize: '0.7rem', justifyContent: 'flex-start' }}>
                  在 Timeline 中定位
                </Button>
              </Box>

              {/* Low-confidence segments */}
              {selectedLane.segments.filter(s => s.confidence < 0.7).length > 0 && (
                <>
                  <Divider sx={{ my: 1 }} />
                  <Typography variant="caption" color="warning.main" sx={{ display: 'block', mb: 0.5 }}>
                    低置信度片段 ({selectedLane.segments.filter(s => s.confidence < 0.7).length})
                  </Typography>
                  {selectedLane.segments.filter(s => s.confidence < 0.7).slice(0, 5).map((s, j) => (
                    <Box key={j} sx={{
                      p: 0.5, mb: 0.5, borderRadius: 0.5, bgcolor: 'rgba(255,152,0,0.1)',
                      cursor: 'pointer', '&:hover': { bgcolor: 'rgba(255,152,0,0.2)' },
                    }}
                      onClick={() => handleSegmentClick(s.eventId || `${selectedLane.speaker}_low_${j}`, s.start)}>
                      <Typography variant="caption" sx={{ fontSize: '0.6rem', display: 'block' }} noWrap>
                        {s.text.slice(0, 40)}{s.text.length > 40 ? '…' : ''}
                      </Typography>
                      <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.55rem' }}>
                        {s.start.toFixed(1)}s-{s.end.toFixed(1)}s · conf={s.confidence.toFixed(2)}
                      </Typography>
                    </Box>
                  ))}
                </>
              )}
            </>
          ) : (
            <Box sx={{ textAlign: 'center', py: 4 }}>
              <PersonIcon sx={{ fontSize: 40, color: 'text.disabled', mb: 1 }} />
              <Typography variant="body2" color="text.secondary">
                选择一个说话人以查看详情
              </Typography>
              <Typography variant="caption" color="text.disabled">
                可进行声线绑定、重命名、试听等操作
              </Typography>
            </Box>
          )}
        </Box>
      </Box>

      {/* Hidden audio element */}
      <audio ref={audioRef} style={{ display: 'none' }} />

      {/* Merge dialog */}
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
          <Button size="small" variant="contained" color="warning" onClick={handleMerge} disabled={!mergeTarget}>
            合并
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
