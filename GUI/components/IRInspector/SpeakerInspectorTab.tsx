import { useMemo, useState, useCallback } from 'react'
import {
  Box, Typography, Button, Chip, Divider, FormControl, Select,
  MenuItem, CircularProgress,
} from '@mui/material'
import EditIcon from '@mui/icons-material/EditRounded'
import PlayArrowIcon from '@mui/icons-material/PlayArrowRounded'
import LockIcon from '@mui/icons-material/LockRounded'
import WarningIcon from '@mui/icons-material/WarningRounded'
import PersonIcon from '@mui/icons-material/PersonRounded'
import { useAppStore } from '../../store/useAppStore'
import type { EventViewModel } from '../../types'
import type { SpeakerQuality } from '../../types/modes'

interface Props {
  event: EventViewModel
}

export default function SpeakerInspectorTab({ event }: Props) {
  const speakerLanes = useAppStore(s => s.speakerLanes)
  const selectedSpeakerId = useAppStore(s => s.selectedSpeakerId)
  const voicePresets = useAppStore(s => s.voicePresets)
  const bindVoice = useAppStore(s => s.bindVoice)
  const addDraft = useAppStore(s => s.addDraft)
  const timelineFocus = useAppStore(s => s.timelineFocus)
  const setTimelineFocus = useAppStore(s => s.setTimelineFocus)
  const navigateToEvent = useAppStore(s => s.navigateToEvent)

  const [auditionLoading, setAuditionLoading] = useState<string | null>(null)
  const [editingName, setEditingName] = useState(false)
  const [editValue, setEditValue] = useState('')

  const speakerId = selectedSpeakerId || event.speaker || ''
  const selectedLane = speakerLanes.find(l => l.speaker === speakerId) || null

  const quality = useMemo(() => {
    if (!selectedLane) return null
    const segs = selectedLane.segments
    if (segs.length === 0) return null
    const avgConf = segs.reduce((s, seg) => s + seg.confidence, 0) / segs.length
    let overlapTime = 0
    const totalTime = segs[segs.length - 1].end - segs[0].start
    for (const other of speakerLanes) {
      if (other.speaker === selectedLane.speaker) continue
      for (const s of segs) {
        for (const o of other.segments) {
          const overlapStart = Math.max(s.start, o.start)
          const overlapEnd = Math.min(s.end, o.end)
          if (overlapEnd > overlapStart) overlapTime += overlapEnd - overlapStart
        }
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
    return {
      speakerId: selectedLane.speaker,
      avgConfidence: avgConf,
      conflictRate,
      switchFrequency: span > 0 ? segs.length / (span / 60) : 0,
      continuityScore,
    } as SpeakerQuality
  }, [selectedLane, speakerLanes])

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
          new Audio(url).play()
        }
      }
    } finally {
      setAuditionLoading(null)
    }
  }, [voicePresets])

  const handleRename = useCallback(() => {
    if (!editValue.trim() || !speakerId) return
    addDraft({
      eventId: speakerId,
      opcode: 'RENAME_SPEAKER',
      payload: { newName: editValue.trim() },
      before: {},
      after: { displayName: editValue.trim() },
      timestamp: Date.now(),
    })
    setEditingName(false)
  }, [editValue, speakerId, addDraft])

  const handleLockSpeaker = useCallback(() => {
    if (!speakerId) return
    addDraft({
      eventId: speakerId,
      opcode: 'LOCK_SPEAKER',
      payload: { speaker: speakerId },
      before: {}, after: {},
      timestamp: Date.now(),
    })
  }, [speakerId, addDraft])

  // Per-event speaker info when no lane data available
  if (!selectedLane && timelineFocus !== 'speaker') {
    return (
      <Box>
        <Typography variant="subtitle2" gutterBottom>说话人信息</Typography>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          <Box>
            <Typography variant="caption" color="text.secondary">说话人 ID</Typography>
            <Typography variant="body2">{event.speaker || '(未知)'}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">显示名称</Typography>
            <Typography variant="body2">{event.displayName || '(未命名)'}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">ASR 置信度</Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Typography variant="body2">{event.confidence.toFixed(2)}</Typography>
              <Chip
                label={event.confidence < 0.7 ? '低' : event.confidence < 0.85 ? '中' : '高'}
                size="small"
                color={event.confidence < 0.7 ? 'error' : event.confidence < 0.85 ? 'warning' : 'success'}
                sx={{ fontSize: '0.6rem', height: 18 }}
              />
            </Box>
          </Box>
        </Box>
        <Divider sx={{ my: 1.5 }} />
        <Button size="small" variant="outlined" startIcon={<PersonIcon />}
          onClick={() => setTimelineFocus('speaker')}>
          进入说话人聚焦模式
        </Button>
      </Box>
    )
  }

  return (
    <Box>
      <Typography variant="subtitle2" sx={{ fontSize: '0.8rem', mb: 1 }}>
        {selectedLane?.display_name || event.displayName || speakerId}
      </Typography>

      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 1.5 }}>
        <Chip label={speakerId} size="small" variant="outlined" sx={{ fontSize: '0.6rem', height: 20 }} />
        <Chip label={`${selectedLane?.segment_count || 0} 段`} size="small" sx={{ fontSize: '0.6rem', height: 20 }} />
        <Chip label={`${(selectedLane?.total_duration || 0).toFixed(1)}s`} size="small" variant="outlined" sx={{ fontSize: '0.6rem', height: 20 }} />
      </Box>

      {quality && (
        <Box sx={{ mb: 1.5 }}>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
            质量评分
          </Typography>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography variant="caption" sx={{ fontSize: '0.6rem', width: 50 }}>置信度</Typography>
              <Box sx={{ flexGrow: 1, height: 4, borderRadius: 1, bgcolor: 'grey.800' }}>
                <Box sx={{ height: '100%', borderRadius: 1, width: `${quality.avgConfidence * 100}%`,
                  bgcolor: quality.avgConfidence >= 0.9 ? '#4CAF50' : quality.avgConfidence >= 0.7 ? '#FF9800' : '#F44336' }} />
              </Box>
              <Typography variant="caption" sx={{ fontSize: '0.6rem' }}>{(quality.avgConfidence * 100).toFixed(0)}%</Typography>
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography variant="caption" sx={{ fontSize: '0.6rem', width: 50 }}>连续性</Typography>
              <Box sx={{ flexGrow: 1, height: 4, borderRadius: 1, bgcolor: 'grey.800' }}>
                <Box sx={{ height: '100%', borderRadius: 1, width: `${quality.continuityScore * 100}%`,
                  bgcolor: quality.continuityScore >= 0.8 ? '#4CAF50' : '#FF9800' }} />
              </Box>
              <Typography variant="caption" sx={{ fontSize: '0.6rem' }}>{(quality.continuityScore * 100).toFixed(0)}%</Typography>
            </Box>
            {quality.conflictRate > 0 && (
              <Chip icon={<WarningIcon sx={{ fontSize: 10 }} />}
                label={`冲突率: ${(quality.conflictRate * 100).toFixed(0)}%`}
                size="small" color="warning" sx={{ fontSize: '0.6rem', height: 20 }} />
            )}
          </Box>
        </Box>
      )}

      <Divider sx={{ my: 1 }} />

      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
        声线绑定
      </Typography>
      <FormControl size="small" fullWidth sx={{ mb: 1 }}>
        <Select
          value={selectedLane?.voice_id || ''}
          onChange={(e) => bindVoice(speakerId, e.target.value)}
          displayEmpty
          sx={{ fontSize: '0.7rem' }}
        >
          <MenuItem value="" sx={{ fontSize: '0.7rem' }}><em>未绑定</em></MenuItem>
          {voicePresets.map(v => (
            <MenuItem key={v.id} value={v.id} sx={{ fontSize: '0.7rem' }}>
              {v.name} ({v.engine})
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      {selectedLane?.voice_id && (
        <Button
          size="small" variant="outlined"
          startIcon={auditionLoading === selectedLane.voice_id ? <CircularProgress size={12} /> : <PlayArrowIcon />}
          onClick={() => handleAudition(selectedLane.voice_id!)}
          disabled={auditionLoading !== null}
          fullWidth sx={{ fontSize: '0.7rem', mb: 1 }}
        >
          试听声线
        </Button>
      )}

      <Divider sx={{ my: 1 }} />

      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
        {editingName ? (
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            <input
              value={editValue}
              onChange={e => setEditValue(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleRename(); if (e.key === 'Escape') setEditingName(false) }}
              autoFocus
              style={{ flexGrow: 1, background: 'transparent', border: '1px solid #666', color: '#fff', fontSize: '0.7rem', padding: '2px 4px', borderRadius: 2 }}
            />
            <Button size="small" variant="contained" onClick={handleRename} sx={{ fontSize: '0.65rem' }}>确定</Button>
          </Box>
        ) : (
          <Button size="small" variant="outlined" startIcon={<EditIcon />}
            onClick={() => { setEditingName(true); setEditValue(selectedLane?.display_name || '') }}
            fullWidth sx={{ fontSize: '0.7rem', justifyContent: 'flex-start' }}>
            重命名
          </Button>
        )}
        <Button size="small" variant="outlined" startIcon={<LockIcon />}
          onClick={handleLockSpeaker}
          fullWidth sx={{ fontSize: '0.7rem', justifyContent: 'flex-start' }}>
          锁定说话人
        </Button>
      </Box>

      {selectedLane && selectedLane.segments.filter(s => s.confidence < 0.7).length > 0 && (
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
              onClick={() => navigateToEvent(s.eventId || `${speakerId}_low_${j}`, s.start, 'timeline')}>
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
    </Box>
  )
}
