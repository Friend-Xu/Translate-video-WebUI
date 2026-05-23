import React, { useState, useCallback } from 'react'
import {
  Box, Typography, Card, IconButton, Tooltip, Alert, Chip,
  Button, Select, MenuItem, FormControl,
} from '@mui/material'
import MergeIcon from '@mui/icons-material/CallMergeRounded'
import { SectionHeader } from '../SectionHeader'
import type { SpeakerTurn, SpeakerVerification } from '../../types'

const SPEAKER_COLORS = [
  '#4CAF50', '#2196F3', '#FF9800', '#E91E63',
  '#9C27B0', '#00BCD4', '#FFEB3B', '#795548',
]

interface Props {
  workspace: string
  vocalPath: string
  speakers: string[]
  timeline: SpeakerTurn[]
  verification: SpeakerVerification | null
  onTimelineChange?: (timeline: SpeakerTurn[]) => void
  onSaveCorrections?: (timeline: SpeakerTurn[], corrections: unknown[]) => void
}

export default function SpeakerReviewPanel({
  speakers, timeline, verification, onTimelineChange, onSaveCorrections,
}: Props) {
  const [selectedSpeaker, setSelectedSpeaker] = useState<string | null>(null)
  const [corrections, setCorrections] = useState<unknown[]>([])
  const [dirty, setDirty] = useState(false)

  const bySpeaker = React.useMemo(() => {
    const map: Record<string, SpeakerTurn[]> = {}
    for (const t of timeline) {
      if (!map[t.speaker]) map[t.speaker] = []
      map[t.speaker].push(t)
    }
    return map
  }, [timeline])

  const getColor = (spk: string) =>
    SPEAKER_COLORS[speakers.indexOf(spk) % SPEAKER_COLORS.length]

  const handleMerge = useCallback(() => {
    const merged: SpeakerTurn[] = []
    for (const t of timeline) {
      const prev = merged[merged.length - 1]
      if (prev && prev.speaker === t.speaker && t.start - prev.end < 1.0) {
        prev.end = t.end
      } else {
        merged.push({ ...t })
      }
    }
    onTimelineChange?.(merged)
    setCorrections([...corrections, { action: 'merge', timestamp: Date.now() }])
    setDirty(true)
  }, [timeline, corrections, onTimelineChange])

  const handleSave = useCallback(() => {
    onSaveCorrections?.(timeline, corrections)
    setDirty(false)
  }, [timeline, corrections, onSaveCorrections])

  if (!speakers.length) {
    return (
      <Card sx={{ p: 3 }}>
        <SectionHeader title="说话人审核" />
        <Alert severity="info">未启用说话人分离，或未检测到多个说话人。</Alert>
      </Card>
    )
  }

  return (
    <Card sx={{ p: 3 }}>
      <SectionHeader title={`说话人审核 (${speakers.length} 人, ${timeline.length} 段)`} />

      {verification && (
        <Alert severity={verification.passesAll ? 'success' : 'warning'} sx={{ mb: 2 }}>
          验证: {verification.summary.errors} 错误, {verification.summary.warnings} 警告 —{' '}
          {verification.passesAll ? '全部通过' : '存在问题'}
        </Alert>
      )}

      <Box sx={{ display: 'flex', gap: 1, mb: 2, alignItems: 'center' }}>
        <FormControl size="small" sx={{ minWidth: 120 }}>
          <Select
            value={selectedSpeaker || ''}
            onChange={e => setSelectedSpeaker(e.target.value || null)}
            displayEmpty
          >
            <MenuItem value="">全部说话人</MenuItem>
            {speakers.map(spk => (
              <MenuItem key={spk} value={spk}>
                <Chip size="small" sx={{ bgcolor: getColor(spk), color: '#fff', mr: 1 }} label={spk} />
                ({bySpeaker[spk]?.length || 0} 段)
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <Tooltip title="合并相邻同说话人段">
          <IconButton onClick={handleMerge} size="small"><MergeIcon /></IconButton>
        </Tooltip>
        <Button size="small" variant="contained" disabled={!dirty}
          onClick={handleSave} sx={{ ml: 'auto' }}>
          保存修正
        </Button>
      </Box>

      {/* 时间线 */}
      <Box sx={{
        position: 'relative', height: speakers.length * 36 + 20,
        bgcolor: '#f5f5f5', borderRadius: 1, overflow: 'auto',
      }}>
        {speakers.map(spk => (
          <Box key={spk} sx={{ display: 'flex', alignItems: 'center', height: 32, mb: '2px' }}>
            <Box sx={{ width: 100, minWidth: 100, px: 1, textAlign: 'right',
              fontSize: '0.75rem', fontWeight: 'bold', color: getColor(spk) }}>
              {spk}
            </Box>
            <Box sx={{ flexGrow: 1, position: 'relative', height: 24 }}>
              {(selectedSpeaker && selectedSpeaker !== spk ? [] : bySpeaker[spk] || []).map((turn, i) => {
                const maxEnd = Math.max(...timeline.map(t => t.end), 1)
                return (
                  <Box key={`${spk}-${i}`}
                    sx={{
                      position: 'absolute',
                      left: `${(turn.start / maxEnd) * 100}%`,
                      width: `${Math.max(((turn.end - turn.start) / maxEnd) * 100, 0.5)}%`,
                      height: 22, bgcolor: getColor(spk), borderRadius: 0.5,
                      opacity: 0.85, cursor: 'pointer', '&:hover': { opacity: 1 },
                    }}
                    title={`${spk}: ${turn.start.toFixed(1)}s - ${turn.end.toFixed(1)}s`}
                  />
                )
              })}
            </Box>
          </Box>
        ))}
      </Box>

      {/* 段列表 */}
      <Box sx={{ mt: 2, maxHeight: 400, overflow: 'auto' }}>
        {(selectedSpeaker ? bySpeaker[selectedSpeaker] || [] : timeline).map((turn, i) => (
          <Box key={i} sx={{
            display: 'flex', alignItems: 'center', py: 0.5,
            borderBottom: '1px solid #eee', fontSize: '0.8rem',
          }}>
            <Chip size="small" label={turn.speaker}
              sx={{ bgcolor: getColor(turn.speaker), color: '#fff', mr: 1, minWidth: 90 }} />
            <Typography variant="body2" sx={{ minWidth: 80 }}>
              {turn.start.toFixed(1)}s – {turn.end.toFixed(1)}s
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ ml: 1 }}>
              ({(turn.end - turn.start).toFixed(1)}s)
            </Typography>
          </Box>
        ))}
      </Box>
    </Card>
  )
}
