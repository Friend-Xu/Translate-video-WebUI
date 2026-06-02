import { useState, useCallback, useRef, useMemo } from 'react'
import {
  Box, Typography, Chip, IconButton, Tooltip, Button, Divider,
  MenuItem, Select, FormControl,
  Dialog, DialogTitle, DialogContent, DialogActions, CircularProgress,
} from '@mui/material'
import PersonIcon from '@mui/icons-material/PersonRounded'
import PlayArrowIcon from '@mui/icons-material/PlayArrowRounded'
import MergeIcon from '@mui/icons-material/MergeRounded'
import LockIcon from '@mui/icons-material/LockRounded'
import EditIcon from '@mui/icons-material/EditRounded'
import WarningIcon from '@mui/icons-material/WarningRounded'
import VoiceIcon from '@mui/icons-material/RecordVoiceOverRounded'
import { useAppStore } from '../../store/useAppStore'
import { useTimelineCoordinates } from '../../hooks/useTimelineCoordinates'
import type { EventViewModel } from '../../types'
import type { SpeakerQuality } from '../../types/modes'

const LANE_COLORS = ['#FF9800', '#2196F3', '#4CAF50', '#9C27B0', '#E91E63', '#00BCD4']
const LANE_HEIGHT = 64
const LABEL_WIDTH = 140
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
  const voicePresets = useAppStore(s => s.voicePresets)
  const bindVoice = useAppStore(s => s.bindVoice)
  const addDraft = useAppStore(s => s.addDraft)
  const playheadPosition = useAppStore(s => s.playheadPosition)
  const setPlayhead = useAppStore(s => s.setPlayhead)

  const [auditionLoading, setAuditionLoading] = useState<string | null>(null)
  const [mergeDialogOpen, setMergeDialogOpen] = useState(false)
  const [mergeTarget, setMergeTarget] = useState<string | null>(null)
  const [editingName, setEditingName] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [sortBy, setSortBy] = useState<'duration' | 'confidence' | 'conflict'>('duration')
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)

  const speakerLanes: SpeakerLane[] = useMemo(() => {
    if (externalSpeakers && externalSpeakers.length > 0) return externalSpeakers
    if (storeSpeakerLanes.length > 0) return storeSpeakerLanes as unknown as SpeakerLane[]
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
    return Object.entries(spkMap).map(([spk, segs], i) => ({
      speaker: spk, display_name: spk, voice_id: '',
      color: LANE_COLORS[i % LANE_COLORS.length],
      segments: segs, segment_count: segs.length,
      total_duration: segs.reduce((sum, s) => sum + (s.end - s.start), 0),
    }))
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
  const coord = useTimelineCoordinates(totalDuration, typeof window !== 'undefined' ? window.innerWidth - 520 : 600)

  const selectedLane = speakerLanes.find(l => l.speaker === selectedSpeakerId) || null
  const selectedQuality = selectedSpeakerId ? speakerQualities[selectedSpeakerId] : null

  const handleSelectSpeaker = useCallback((speakerId: string, e: React.MouseEvent) => {
    if (e.ctrlKey || e.metaKey) {
      toggleSpeakerSelection(speakerId)
    } else {
      setSelectedSpeaker(speakerId)
    }
  }, [setSelectedSpeaker, toggleSpeakerSelection])

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
          if (audioRef.current) { audioRef.current.src = url; audioRef.current.play() }
        }
      }
    } finally { setAuditionLoading(null) }
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
    } catch { /* API unavailable */ }
    addDraft({
      eventId: source, opcode: 'MERGE_SPEAKERS',
      payload: { source, target: mergeTarget },
      before: {}, after: {}, timestamp: Date.now(),
    })
    setMergeDialogOpen(false)
    setMergeTarget(null)
  }, [mergeTarget, selectedSpeakerIds, addDraft])

  const handleRename = useCallback((speakerId: string) => {
    if (!editValue.trim()) return
    addDraft({
      eventId: speakerId, opcode: 'RENAME_SPEAKER',
      payload: { newName: editValue.trim() },
      before: { displayName: selectedLane?.display_name },
      after: { displayName: editValue.trim() }, timestamp: Date.now(),
    })
    fetch('/api/speaker/diarization/rename', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ speaker: speakerId, new_name: editValue.trim() }),
    }).catch(() => {})
    setEditingName(null)
  }, [editValue, selectedLane, addDraft])

  const handleLockSpeaker = useCallback((speakerId: string) => {
    addDraft({
      eventId: speakerId, opcode: 'LOCK_SPEAKER',
      payload: {}, before: {}, after: {}, timestamp: Date.now(),
    })
  }, [addDraft])

  const handleSegmentClick = useCallback((_eventId: string, startTime: number) => {
    setPlayhead(startTime)
    onSeek?.(startTime)
  }, [setPlayhead, onSeek])

  // Time ruler ticks
  const timeRulerTicks = useMemo(() => {
    const ticks: number[] = []
    const step = coord.pixelsPerSec >= 200 ? 0.5 : coord.pixelsPerSec >= 60 ? 1 : coord.pixelsPerSec >= 20 ? 5 : 10
    for (let t = 0; t <= totalDuration; t += step) ticks.push(t)
    return ticks
  }, [totalDuration, coord.pixelsPerSec])

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
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
        <FormControl size="small" sx={{ minWidth: 100 }}>
          <Select value={sortBy} onChange={(e) => setSortBy(e.target.value as any)}
            sx={{ fontSize: '0.7rem' }}>
            <MenuItem value="duration" sx={{ fontSize: '0.7rem' }}>按时长</MenuItem>
            <MenuItem value="confidence" sx={{ fontSize: '0.7rem' }}>按置信度</MenuItem>
            <MenuItem value="conflict" sx={{ fontSize: '0.7rem' }}>按冲突率</MenuItem>
          </Select>
        </FormControl>
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
          width: 200, minWidth: 200, borderRight: '1px solid #d0d5e0',
          overflow: 'hidden auto', bgcolor: '#e8ecf4',
        }}>
          {sortedSpeakers.map((lane) => {
            const quality = speakerQualities[lane.speaker]
            const isSelected = selectedSpeakerId === lane.speaker
            const isMulti = selectedSpeakerIds.includes(lane.speaker)
            return (
              <Box key={lane.speaker} onClick={(e) => handleSelectSpeaker(lane.speaker, e)}
                sx={{
                  p: 1, cursor: 'pointer',
                  borderBottom: '1px solid #d0d5e0',
                  bgcolor: isSelected ? 'rgba(99,102,241,0.12)' : isMulti ? 'rgba(99,102,241,0.06)' : 'transparent',
                  '&:hover': { bgcolor: 'rgba(99,102,241,0.08)' },
                }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                  <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: lane.color, flexShrink: 0 }} />
                  <Typography variant="body2" noWrap sx={{ fontSize: '0.78rem', fontWeight: isSelected ? 600 : 400 }}>
                    {lane.display_name}
                  </Typography>
                </Box>
                <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', ml: 2.5 }}>
                  <Chip label={`${lane.segment_count}段`} size="small"
                    sx={{ fontSize: '0.55rem', height: 16, bgcolor: 'rgba(99,102,241,0.08)' }} />
                  <Chip label={`${lane.total_duration.toFixed(0)}s`} size="small" variant="outlined"
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
        <Box ref={containerRef} sx={{ flexGrow: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          {/* Time ruler */}
          <Box sx={{
            position: 'relative', height: TIME_RULER_H, minHeight: TIME_RULER_H,
            bgcolor: '#dce2f0', borderBottom: '1px solid #c8cdd8',
            overflow: 'hidden',
          }}>
            <Box sx={{ position: 'relative', width: totalDuration * coord.pixelsPerSec, height: '100%' }}>
              {timeRulerTicks.map(t => {
                const x = coord.timeToPixel(t)
                if (x < -50 || x > (containerRef.current?.clientWidth || 800) + 50) return null
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

          {/* Lanes */}
          <Box ref={scrollRef} sx={{ flexGrow: 1, overflow: 'hidden auto', position: 'relative', bgcolor: '#f1f5f9' }}>
            <Box sx={{
              position: 'absolute',
              left: LABEL_WIDTH + coord.timeToPixel(playheadPosition),
              top: 0, bottom: 0, width: 2, bgcolor: '#FF5252', zIndex: 20, pointerEvents: 'none',
            }} />
            {speakerLanes.map((lane) => (
              <Box key={lane.speaker} sx={{
                display: 'flex', height: LANE_HEIGHT,
                borderBottom: '1px solid #d0d5e0',
                bgcolor: selectedSpeakerId === lane.speaker ? 'rgba(99,102,241,0.06)' : 'transparent',
              }}>
                <Box sx={{
                  width: LABEL_WIDTH, minWidth: LABEL_WIDTH, display: 'flex', alignItems: 'center', gap: 0.5, px: 1,
                  bgcolor: '#e8ecf4', borderRight: '1px solid #d0d5e0',
                }}>
                  <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: lane.color, flexShrink: 0 }} />
                  <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                    {editingName === lane.speaker ? (
                      <input value={editValue}
                        onChange={e => setEditValue(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter') handleRename(lane.speaker); if (e.key === 'Escape') setEditingName(null) }}
                        onBlur={() => handleRename(lane.speaker)}
                        autoFocus
                        style={{ width: '100%', background: 'transparent', border: '1px solid #94a3b8', color: '#1e293b', fontSize: '0.7rem', padding: '1px 4px', borderRadius: 2 }} />
                    ) : (
                      <Typography variant="caption" noWrap sx={{ fontSize: '0.65rem', color: '#1e293b', cursor: 'pointer' }}
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
                <Box sx={{ flexGrow: 1, position: 'relative', overflow: 'hidden' }}>
                  {lane.segments.map((seg, j) => {
                    const left = coord.timeToPixel(seg.start)
                    const width = Math.max(2, (seg.end - seg.start) * coord.pixelsPerSec)
                    const conf = seg.confidence
                    const bgColor = conf >= 0.9 ? `${lane.color}CC` : conf >= 0.7 ? `${lane.color}88` : `${lane.color}55`
                    return (
                      <Tooltip key={j} title={`${seg.text.slice(0, 80)}\n${seg.start.toFixed(1)}s-${seg.end.toFixed(1)}s | conf=${conf.toFixed(2)}`}>
                        <Box sx={{
                          position: 'absolute', left, top: 10, height: LANE_HEIGHT - 20, width,
                          bgcolor: bgColor, borderRadius: 0.5,
                          borderLeft: `2px solid ${lane.color}`, cursor: 'pointer',
                          '&:hover': { filter: 'brightness(1.2)', zIndex: 3 },
                        }} onClick={() => handleSegmentClick(seg.eventId || `${lane.speaker}_seg_${j}`, seg.start)} />
                      </Tooltip>
                    )
                  })}
                </Box>
              </Box>
            ))}
            {speakerLanes.length === 0 && (
              <Box sx={{ p: 4, textAlign: 'center' }}>
                <Typography variant="body2" color="text.secondary">未加载说话人数据</Typography>
              </Box>
            )}
          </Box>
        </Box>

        {/* Right: Speaker Inspector */}
        <Box sx={{
          width: 280, minWidth: 280, borderLeft: '1px solid #d0d5e0',
          overflow: 'hidden auto', bgcolor: '#e8ecf4', p: 1.5,
        }}>
          {selectedLane ? (
            <>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                <Box sx={{ width: 12, height: 12, borderRadius: '50%', bgcolor: selectedLane.color, flexShrink: 0 }} />
                <Typography variant="subtitle2" sx={{ fontSize: '0.8rem' }}>{selectedLane.display_name}</Typography>
              </Box>

              {/* Compact stats card */}
              <Box sx={{
                display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0.5, mb: 1.5,
                bgcolor: '#f1f5f9', borderRadius: 1, p: 1,
              }}>
                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.55rem' }}>片段</Typography>
                  <Typography variant="body2" sx={{ fontSize: '0.75rem', fontWeight: 600 }}>{selectedLane.segment_count}</Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.55rem' }}>总时长</Typography>
                  <Typography variant="body2" sx={{ fontSize: '0.75rem', fontWeight: 600 }}>{selectedLane.total_duration.toFixed(1)}s</Typography>
                </Box>
                {selectedQuality && (
                  <>
                    <Box>
                      <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.55rem' }}>置信度</Typography>
                      <Typography variant="body2" sx={{
                        fontSize: '0.75rem', fontWeight: 600,
                        color: selectedQuality.avgConfidence >= 0.9 ? '#10b981' : selectedQuality.avgConfidence >= 0.7 ? '#f59e0b' : '#ef4444',
                      }}>
                        {(selectedQuality.avgConfidence * 100).toFixed(0)}%
                      </Typography>
                    </Box>
                    <Box>
                      <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.55rem' }}>连续性</Typography>
                      <Typography variant="body2" sx={{
                        fontSize: '0.75rem', fontWeight: 600,
                        color: selectedQuality.continuityScore >= 0.8 ? '#10b981' : '#f59e0b',
                      }}>
                        {(selectedQuality.continuityScore * 100).toFixed(0)}%
                      </Typography>
                    </Box>
                  </>
                )}
                {selectedQuality && selectedQuality.conflictRate > 0 && (
                  <Box sx={{ gridColumn: '1 / -1' }}>
                    <Chip icon={<WarningIcon sx={{ fontSize: 10 }} />}
                      label={`冲突率: ${(selectedQuality.conflictRate * 100).toFixed(0)}%`}
                      size="small" color="warning" sx={{ fontSize: '0.6rem', height: 20 }} />
                  </Box>
                )}
              </Box>

              {/* Voice binding */}
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>声线绑定</Typography>
              <FormControl size="small" fullWidth sx={{ mb: 1 }}>
                <Select value={selectedLane.voice_id || ''}
                  onChange={(e) => bindVoice(selectedLane.speaker, e.target.value)}
                  displayEmpty sx={{ fontSize: '0.7rem' }}>
                  <MenuItem value="" sx={{ fontSize: '0.7rem' }}><em>未绑定</em></MenuItem>
                  {voicePresets.map(v => (
                    <MenuItem key={v.id} value={v.id} sx={{ fontSize: '0.7rem' }}>{v.name} ({v.engine})</MenuItem>
                  ))}
                </Select>
              </FormControl>
              {selectedLane.voice_id && (
                <Button size="small" variant="outlined"
                  startIcon={auditionLoading === selectedLane.voice_id ? <CircularProgress size={12} /> : <PlayArrowIcon />}
                  onClick={() => handleAudition(selectedLane.voice_id)}
                  disabled={auditionLoading !== null}
                  fullWidth sx={{ fontSize: '0.7rem', mb: 1 }}>试听声线</Button>
              )}

              <Divider sx={{ my: 1 }} />

              {/* Actions */}
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                <Button size="small" variant="outlined" startIcon={<EditIcon />}
                  onClick={() => { setEditingName(selectedLane.speaker); setEditValue(selectedLane.display_name) }}
                  fullWidth sx={{ fontSize: '0.7rem', justifyContent: 'flex-start' }}>重命名</Button>
                <Button size="small" variant="outlined" startIcon={<LockIcon />}
                  onClick={() => handleLockSpeaker(selectedLane.speaker)}
                  fullWidth sx={{ fontSize: '0.7rem', justifyContent: 'flex-start' }}>锁定说话人</Button>
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
                      p: 0.5, mb: 0.5, borderRadius: 0.5, bgcolor: 'rgba(245,158,11,0.1)',
                      cursor: 'pointer', '&:hover': { bgcolor: 'rgba(245,158,11,0.2)' },
                    }} onClick={() => handleSegmentClick(s.eventId || `${selectedLane.speaker}_low_${j}`, s.start)}>
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
              <Typography variant="body2" color="text.secondary">选择一个说话人以查看详情</Typography>
              <Typography variant="caption" color="text.disabled">可进行声线绑定、重命名、试听等操作</Typography>
            </Box>
          )}
        </Box>
      </Box>
      <audio ref={audioRef} style={{ display: 'none' }} />
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
    </Box>
  )
}
