import { useState, useMemo, useCallback, useRef } from 'react'
import {
  Box, Typography, Chip, Button, Divider,
  MenuItem, Select, FormControl,
  CircularProgress,
} from '@mui/material'
import PersonIcon from '@mui/icons-material/PersonRounded'
import PlayArrowIcon from '@mui/icons-material/PlayArrowRounded'
import LockIcon from '@mui/icons-material/LockRounded'
import WarningIcon from '@mui/icons-material/WarningRounded'
import { useAppStore } from '../../store/useAppStore'
import type { EventViewModel } from '../../types'
import type { SpeakerQuality } from '../../types/modes'

const LANE_COLORS = ['#FF9800', '#2196F3', '#4CAF50', '#9C27B0', '#E91E63', '#00BCD4']

interface SpeakerSegment {
  id: string; start: number; end: number; text: string; translation: string | object
  confidence: number; eventId: string
}

interface SpeakerLane {
  speaker: string; display_name: string; voice_id: string; color: string
  segments: SpeakerSegment[]; segment_count: number; total_duration: number
}

interface Props {
  events: EventViewModel[]
  speakerLanes: SpeakerLane[]
  onSeek?: (time: number) => void
}

export default function SpeakerInspector({ events, speakerLanes: externalLanes, onSeek }: Props) {
  const selectedSpeakerId = useAppStore(s => s.selectedSpeakerId)
  const storeSpeakerLanes = useAppStore(s => s.speakerLanes)
  const voicePresets = useAppStore(s => s.voicePresets)
  const bindVoice = useAppStore(s => s.bindVoice)
  const setPlayhead = useAppStore(s => s.setPlayhead)

  const [auditionLoading, setAuditionLoading] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const speakerLanes: SpeakerLane[] = useMemo(() => {
    if (externalLanes && externalLanes.length > 0) return externalLanes
    if (storeSpeakerLanes.length > 0) return storeSpeakerLanes as unknown as SpeakerLane[]
    const spkMap: Record<string, SpeakerSegment[]> = {}
    for (const evt of events) {
      const spk = (evt as any).speaker || 'UNKNOWN'
      if (!spkMap[spk]) spkMap[spk] = []
      spkMap[spk].push({ id: evt.id, start: evt.start, end: evt.end, text: evt.text || '', translation: evt.translation || '', confidence: (evt as any).confidence || 0.9, eventId: evt.id })
    }
    return Object.entries(spkMap).map(([spk, segs], i) => ({ speaker: spk, display_name: spk, voice_id: '', color: LANE_COLORS[i % LANE_COLORS.length], segments: segs, segment_count: segs.length, total_duration: segs.reduce((sum, s) => sum + (s.end - s.start), 0) }))
  }, [events, externalLanes, storeSpeakerLanes])

  const selectedLane = speakerLanes.find(l => l.speaker === selectedSpeakerId) || null

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

  const selectedQuality = selectedSpeakerId ? speakerQualities[selectedSpeakerId] : null

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

  const handleLockSpeaker = useCallback((speakerId: string) => {
    const store = useAppStore.getState()
    store.addDraft({
      eventId: speakerId, opcode: 'LOCK_SPEAKER',
      payload: { speaker: speakerId },
      before: {}, after: {}, timestamp: Date.now(),
    })
    store.applyDraft(speakerId)
  }, [])

  const handleSegmentClick = useCallback((_eventId: string, startTime: number) => {
    setPlayhead(startTime)
    onSeek?.(startTime)
  }, [setPlayhead, onSeek])

  return (
    <Box sx={{ borderTop: '1px solid #d0d5e0', bgcolor: '#e8ecf4', overflow: 'hidden auto', flex: '1 1 auto', minHeight: 0 }}>
      <Typography variant="caption" sx={{ fontWeight: 600, px: 1.5, pt: 1, display: 'block', color: 'text.secondary', fontSize: '0.65rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        说话人详情
      </Typography>

      <Box sx={{ p: 1.5, pt: 0.5 }}>
        {selectedLane ? (
          <>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <Box sx={{ width: 12, height: 12, borderRadius: '50%', bgcolor: selectedLane.color, flexShrink: 0 }} />
              <Typography variant="subtitle2" sx={{ fontSize: '0.8rem' }}>{selectedLane.display_name}</Typography>
            </Box>

            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0.5, mb: 1.5, bgcolor: '#f1f5f9', borderRadius: 1, p: 1 }}>
              <Box><Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.55rem' }}>片段</Typography><Typography variant="body2" sx={{ fontSize: '0.75rem', fontWeight: 600 }}>{selectedLane.segment_count}</Typography></Box>
              <Box><Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.55rem' }}>总时长</Typography><Typography variant="body2" sx={{ fontSize: '0.75rem', fontWeight: 600 }}>{selectedLane.total_duration.toFixed(1)}s</Typography></Box>
              {selectedQuality && (<>
                <Box><Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.55rem' }}>置信度</Typography><Typography variant="body2" sx={{ fontSize: '0.75rem', fontWeight: 600, color: selectedQuality.avgConfidence >= 0.9 ? '#10b981' : selectedQuality.avgConfidence >= 0.7 ? '#f59e0b' : '#ef4444' }}>{(selectedQuality.avgConfidence * 100).toFixed(0)}%</Typography></Box>
                <Box><Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.55rem' }}>连续性</Typography><Typography variant="body2" sx={{ fontSize: '0.75rem', fontWeight: 600, color: selectedQuality.continuityScore >= 0.8 ? '#10b981' : '#f59e0b' }}>{(selectedQuality.continuityScore * 100).toFixed(0)}%</Typography></Box>
              </>)}
              {selectedQuality && selectedQuality.conflictRate > 0 && (
                <Box sx={{ gridColumn: '1 / -1' }}><Chip icon={<WarningIcon sx={{ fontSize: 10 }} />} label={`冲突率: ${(selectedQuality.conflictRate * 100).toFixed(0)}%`} size="small" color="warning" sx={{ fontSize: '0.6rem', height: 20 }} /></Box>
              )}
            </Box>

            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>说话人颜色</Typography>
            <Box sx={{ display: 'flex', gap: 0.5, mb: 1.5, flexWrap: 'wrap' }}>
              {LANE_COLORS.map(c => (
                <Box key={c} onClick={() => { const s = useAppStore.getState(); s.addDraft({ eventId: selectedLane.speaker, opcode: 'RENAME_SPEAKER', payload: { color: c }, before: { color: selectedLane.color }, after: { color: c }, timestamp: Date.now() }); s.applyDraft(selectedLane.speaker) }}
                  sx={{ width: 22, height: 22, borderRadius: '50%', bgcolor: c, cursor: 'pointer', border: selectedLane.color === c ? '3px solid #1e293b' : '2px solid transparent', '&:hover': { transform: 'scale(1.15)' }, transition: 'transform 0.1s' }} />
              ))}
              <label style={{ width: 22, height: 22, borderRadius: '50%', cursor: 'pointer', background: 'conic-gradient(red,yellow,lime,cyan,blue,magenta,red)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <input type="color" value={selectedLane.color} onChange={e => { const s = useAppStore.getState(); s.addDraft({ eventId: selectedLane.speaker, opcode: 'RENAME_SPEAKER', payload: { color: e.target.value }, before: { color: selectedLane.color }, after: { color: e.target.value }, timestamp: Date.now() }); s.applyDraft(selectedLane.speaker) }} style={{ width: 0, height: 0, opacity: 0, position: 'absolute' }} />
              </label>
            </Box>

            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>声线绑定</Typography>
            <FormControl size="small" fullWidth sx={{ mb: 1 }}>
              <Select value={selectedLane.voice_id || ''} onChange={(e) => bindVoice(selectedLane.speaker, e.target.value)} displayEmpty sx={{ fontSize: '0.7rem' }}>
                <MenuItem value="" sx={{ fontSize: '0.7rem' }}><em>未绑定</em></MenuItem>
                {voicePresets.map(v => (<MenuItem key={v.id} value={v.id} sx={{ fontSize: '0.7rem' }}>{v.name} ({v.engine})</MenuItem>))}
              </Select>
            </FormControl>
            {selectedLane.voice_id && (
              <Button size="small" variant="outlined" startIcon={auditionLoading === selectedLane.voice_id ? <CircularProgress size={12} /> : <PlayArrowIcon />} onClick={() => handleAudition(selectedLane.voice_id)} disabled={auditionLoading !== null} fullWidth sx={{ fontSize: '0.7rem', mb: 1 }}>试听声线</Button>
            )}

            <Divider sx={{ my: 1 }} />
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
              <Button size="small" variant="outlined" startIcon={<LockIcon />} onClick={() => handleLockSpeaker(selectedLane.speaker)} fullWidth sx={{ fontSize: '0.7rem', justifyContent: 'flex-start' }}>锁定说话人</Button>
            </Box>

            {selectedLane.segments.filter(s => s.confidence < 0.7).length > 0 && (<>
              <Divider sx={{ my: 1 }} />
              <Typography variant="caption" color="warning.main" sx={{ display: 'block', mb: 0.5 }}>低置信度片段 ({selectedLane.segments.filter(s => s.confidence < 0.7).length})</Typography>
              {selectedLane.segments.filter(s => s.confidence < 0.7).slice(0, 5).map((s, j) => (
                <Box key={j} sx={{ p: 0.5, mb: 0.5, borderRadius: 0.5, bgcolor: 'rgba(245,158,11,0.1)', cursor: 'pointer', '&:hover': { bgcolor: 'rgba(245,158,11,0.2)' } }} onClick={() => handleSegmentClick(s.eventId || `${selectedLane.speaker}_low_${j}`, s.start)}>
                  <Typography variant="caption" sx={{ fontSize: '0.6rem', display: 'block' }} noWrap>{s.text.slice(0, 40)}{s.text.length > 40 ? '…' : ''}</Typography>
                  <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.55rem' }}>{s.start.toFixed(1)}s-{s.end.toFixed(1)}s · conf={s.confidence.toFixed(2)}</Typography>
                </Box>
              ))}
            </>)}
          </>
        ) : (
          <Box sx={{ textAlign: 'center', py: 2 }}>
            <PersonIcon sx={{ fontSize: 32, color: 'text.disabled', mb: 1 }} />
            <Typography variant="body2" color="text.secondary">选择一个说话人以查看详情</Typography>
            <Typography variant="caption" color="text.disabled">可进行声线绑定、重命名、试听等操作</Typography>
          </Box>
        )}
      </Box>
      <audio ref={audioRef} style={{ display: 'none' }} />
    </Box>
  )
}
