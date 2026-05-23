import React, { useState, useCallback } from 'react'
import {
  Box, Typography, Card, IconButton, Tooltip, Alert, Chip,
  Button, Select, MenuItem, FormControl, Dialog, DialogTitle,
  DialogContent, DialogActions, TextField, Checkbox,
} from '@mui/material'
import MergeIcon from '@mui/icons-material/CallMergeRounded'
import SplitIcon from '@mui/icons-material/CallSplitRounded'
import EditIcon from '@mui/icons-material/EditOutlined'
import { SectionHeader } from '../SectionHeader'
import type { SpeakerTurn, SpeakerVerification, SpeakerMergeRequest, SpeakerSplitRequest, SpeakerRenameRequest } from '../../types'

const SPEAKER_COLORS = [
  '#4CAF50', '#2196F3', '#FF9800', '#E91E63',
  '#9C27B0', '#00BCD4', '#FFEB3B', '#795548',
]

interface Props {
  workspace: string
  speakers: string[]
  timeline: SpeakerTurn[]
  verification: SpeakerVerification | null
  speakerNames: Record<string, string>
  onTimelineChange?: (timeline: SpeakerTurn[]) => void
  onSaveCorrections?: (timeline: SpeakerTurn[], corrections: unknown[]) => void
}

export default function SpeakerReviewPanel({
  workspace, speakers, timeline, verification, speakerNames,
  onTimelineChange, onSaveCorrections,
}: Props) {
  const [selectedSpeaker, setSelectedSpeaker] = useState<string | null>(null)
  const [corrections, setCorrections] = useState<unknown[]>([])
  const [dirty, setDirty] = useState(false)
  const [mergeMode, setMergeMode] = useState(false)
  const [mergeSelected, setMergeSelected] = useState<Set<string>>(new Set())
  const [renameTarget, setRenameTarget] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [splitConfirm, setSplitConfirm] = useState<{ speaker: string; index: number } | null>(null)
  const [mergeConfirm, setMergeConfirm] = useState<{ source: string; target: string } | null>(null)
  const [saving, setSaving] = useState(false)

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

  const getDisplayName = (spk: string) => speakerNames[spk] || spk

  const apiCall = async (url: string, body: object) => {
    const res = await fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || res.statusText)
    }
    return res.json()
  }

  const handleMergeAdjacent = useCallback(() => {
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
    setCorrections([...corrections, { action: 'merge-adjacent', timestamp: Date.now() }])
    setDirty(true)
  }, [timeline, corrections, onTimelineChange])

  const toggleMergeMode = () => {
    setMergeMode(!mergeMode)
    setMergeSelected(new Set())
  }

  const toggleMergeSelect = (spk: string) => {
    const next = new Set(mergeSelected)
    if (next.has(spk)) next.delete(spk); else next.add(spk)
    setMergeSelected(next)
  }

  const handleIdentityMerge = () => {
    const sel = Array.from(mergeSelected)
    if (sel.length < 2) return
    setMergeConfirm({ source: sel[1], target: sel[0] })
  }

  const doIdentityMerge = async () => {
    if (!mergeConfirm) return
    try {
      await apiCall('/api/speaker/diarization/merge', {
        workspace, source: mergeConfirm.source, target: mergeConfirm.target,
      } as SpeakerMergeRequest)
      const updated = timeline.map(t =>
        t.speaker === mergeConfirm.source ? { ...t, speaker: mergeConfirm.target } : t
      )
      onTimelineChange?.(updated)
      setCorrections([...corrections, { action: 'merge-identity', ...mergeConfirm, timestamp: Date.now() }])
      setDirty(true)
      setMergeMode(false)
      setMergeSelected(new Set())
      setMergeConfirm(null)
    } catch (e: any) {
      alert(`合并失败: ${e.message}`)
    }
  }

  const handleSplitClick = (speaker: string, turnIndex: number) => {
    const globalIndex = timeline.findIndex(
      t => t.speaker === speaker && t === bySpeaker[speaker]?.find((_, i) => i === turnIndex)
    )
    if (globalIndex >= 0) setSplitConfirm({ speaker, index: globalIndex })
  }

  const doSplit = async () => {
    if (!splitConfirm) return
    try {
      const result = await apiCall('/api/speaker/diarization/split', {
        workspace, speaker: splitConfirm.speaker, split_index: splitConfirm.index,
      } as SpeakerSplitRequest)
      setDirty(true)
      setSplitConfirm(null)
      alert(`已切分为新 speaker: ${result.new_speaker}`)
    } catch (e: any) {
      alert(`切分失败: ${e.message}`)
    }
  }

  const startRename = (spk: string) => {
    setRenameTarget(spk)
    setRenameValue(speakerNames[spk] || '')
  }

  const doRename = async () => {
    if (!renameTarget) return
    try {
      await apiCall('/api/speaker/diarization/rename', {
        workspace, speaker: renameTarget, display_name: renameValue,
      } as SpeakerRenameRequest)
      setDirty(true)
      setRenameTarget(null)
    } catch (e: any) {
      alert(`重命名失败: ${e.message}`)
    }
  }

  const handleSave = useCallback(async () => {
    setSaving(true)
    try {
      await apiCall('/api/speaker/diarization/save', { workspace, timeline, corrections })
      onSaveCorrections?.(timeline, corrections)
      setDirty(false)
    } catch (e: any) {
      alert(`保存失败: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }, [workspace, timeline, corrections, onSaveCorrections])

  const handleRegenerateSrt = async () => {
    try {
      const result = await apiCall('/api/speaker/diarization/regenerate-srt', { workspace })
      alert(`SRT 已重生成: ${result.entries} 条字幕`)
    } catch (e: any) {
      alert(`重生成失败: ${e.message}`)
    }
  }

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

      <Box sx={{ display: 'flex', gap: 1, mb: 2, alignItems: 'center', flexWrap: 'wrap' }}>
        <FormControl size="small" sx={{ minWidth: 120 }}>
          <Select
            value={selectedSpeaker || ''}
            onChange={e => setSelectedSpeaker(e.target.value || null)}
            displayEmpty
          >
            <MenuItem value="">全部说话人</MenuItem>
            {speakers.map(spk => (
              <MenuItem key={spk} value={spk}>
                <Chip size="small" sx={{ bgcolor: getColor(spk), color: '#fff', mr: 1 }}
                  label={getDisplayName(spk)} />
                ({bySpeaker[spk]?.length || 0} 段)
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <Tooltip title="合并相邻同说话人段">
          <IconButton onClick={handleMergeAdjacent} size="small"><MergeIcon /></IconButton>
        </Tooltip>
        <Tooltip title={mergeMode ? '退出合并模式' : '合并说话人身份'}>
          <Button size="small" variant={mergeMode ? 'contained' : 'outlined'}
            color={mergeMode ? 'warning' : 'primary'}
            onClick={toggleMergeMode}>
            {mergeMode ? '退出合并' : '合并说话人'}
          </Button>
        </Tooltip>
        <Tooltip title="从 timeline 重生成 SRT 字幕">
          <Button size="small" variant="outlined" onClick={handleRegenerateSrt}>
            重生成SRT
          </Button>
        </Tooltip>
        <Button size="small" variant="contained" disabled={!dirty || saving}
          onClick={handleSave} sx={{ ml: 'auto' }}>
          {saving ? '保存中...' : '保存修正'}
        </Button>
      </Box>

      {mergeMode && (
        <Alert severity="warning" sx={{ mb: 2 }}
          action={
            <Button size="small" color="warning" variant="contained"
              disabled={mergeSelected.size < 2}
              onClick={handleIdentityMerge}>
              合并为同一人 ({mergeSelected.size})
            </Button>
          }>
          勾选两个或以上说话人，然后点击"合并为同一人"将后面的合并到第一个
        </Alert>
      )}

      <Box sx={{
        position: 'relative', minHeight: speakers.length * 36 + 20,
        bgcolor: '#f5f5f5', borderRadius: 1, overflow: 'auto', mb: 2,
      }}>
        {speakers.map(spk => (
          <Box key={spk} sx={{ display: 'flex', alignItems: 'center', height: 32, mb: '2px' }}>
            <Box sx={{ width: 110, minWidth: 110, px: 1, display: 'flex',
              alignItems: 'center', justifyContent: 'flex-end', gap: 0.5 }}>
              {mergeMode && speakers.length > 1 && (
                <Checkbox size="small" sx={{ p: 0 }}
                  checked={mergeSelected.has(spk)}
                  onChange={() => toggleMergeSelect(spk)} />
              )}
              {renameTarget === spk ? (
                <TextField size="small" variant="standard" value={renameValue}
                  onChange={e => setRenameValue(e.target.value)}
                  onBlur={doRename}
                  onKeyDown={e => { if (e.key === 'Enter') doRename() }}
                  autoFocus
                  sx={{ width: 80, '& input': { fontSize: '0.75rem' } }} />
              ) : (
                <Typography sx={{ fontSize: '0.75rem', fontWeight: 'bold', color: getColor(spk) }}>
                  {getDisplayName(spk)}
                </Typography>
              )}
              <IconButton size="small" sx={{ p: 0 }} onClick={() => startRename(spk)}>
                <EditIcon sx={{ fontSize: 14 }} />
              </IconButton>
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
                      display: 'flex', alignItems: 'center', px: 0.5,
                      overflow: 'hidden', whiteSpace: 'nowrap',
                      fontSize: '0.65rem', color: '#fff',
                      cursor: 'pointer', '&:hover': { opacity: 0.85 },
                    }}
                    onClick={() => handleSplitClick(spk, i)}
                    title={`${getDisplayName(spk)} ${turn.start.toFixed(1)}s-${turn.end.toFixed(1)}s (点击切分)`}
                  >
                    {turn.start.toFixed(1)}-{turn.end.toFixed(1)}
                  </Box>
                )
              })}
            </Box>
          </Box>
        ))}
      </Box>

      <Box sx={{ maxHeight: 300, overflow: 'auto' }}>
        {timeline.filter(t => !selectedSpeaker || t.speaker === selectedSpeaker).map((turn, i) => (
          <Box key={i} sx={{
            display: 'flex', alignItems: 'center', gap: 1, py: 0.5,
            borderBottom: '1px solid #eee', fontSize: '0.85rem',
          }}>
            <Chip size="small" label={getDisplayName(turn.speaker)}
              sx={{ bgcolor: getColor(turn.speaker), color: '#fff', minWidth: 80 }} />
            <Typography variant="caption" sx={{ minWidth: 80, color: 'text.secondary' }}>
              {turn.start.toFixed(1)}s - {turn.end.toFixed(1)}s
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              ({(turn.end - turn.start).toFixed(1)}s)
            </Typography>
            <Tooltip title="从此处切分为新说话人">
              <IconButton size="small" onClick={() => handleSplitClick(turn.speaker, i)}>
                <SplitIcon sx={{ fontSize: 16 }} />
              </IconButton>
            </Tooltip>
          </Box>
        ))}
      </Box>

      <Dialog open={!!splitConfirm} onClose={() => setSplitConfirm(null)}>
        <DialogTitle>确认切分说话人</DialogTitle>
        <DialogContent>
          <Typography>
            将从 turn {splitConfirm?.index} 开始将 "{getDisplayName(splitConfirm?.speaker || '')}"
            的后半段切分为新的 speaker ID。此操作不可撤销。
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSplitConfirm(null)}>取消</Button>
          <Button variant="contained" color="primary" onClick={doSplit}>确认切分</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!mergeConfirm} onClose={() => setMergeConfirm(null)}>
        <DialogTitle>确认合并说话人</DialogTitle>
        <DialogContent>
          <Typography>
            将 "{getDisplayName(mergeConfirm?.source || '')}" 合并到 "{getDisplayName(mergeConfirm?.target || '')}"。
            合并后所有 source 的 turns 将归属于 target。此操作不可撤销。
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setMergeConfirm(null)}>取消</Button>
          <Button variant="contained" color="primary" onClick={doIdentityMerge}>确认合并</Button>
        </DialogActions>
      </Dialog>
    </Card>
  )
}
