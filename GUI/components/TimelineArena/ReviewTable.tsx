import { useState, useCallback, useMemo, useRef, useEffect } from 'react'
import React from 'react'
import {
  Box, Typography, TextField, InputAdornment, IconButton, Tooltip,
  Chip, ToggleButtonGroup, ToggleButton, Button, Card, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, Checkbox,
} from '@mui/material'
import SearchIcon from '@mui/icons-material/SearchRounded'
import UndoIcon from '@mui/icons-material/UndoRounded'
import RedoIcon from '@mui/icons-material/RedoRounded'
import SaveIcon from '@mui/icons-material/SaveRounded'
import { useAppStore } from '../../store/useAppStore'
import type { EventViewModel } from '../../types'
import type { SubtitleEntry } from '../../types/modes'

const MAX_UNDO_STEPS = 50

// ── Helpers ──

function getCPS(entry: SubtitleEntry): number {
  const dur = (entry.endMs - entry.startMs) / 1000
  const chars = entry.translatedText.replace(/\n/g, '').length
  return dur > 0 ? chars / dur : 0
}

function formatMs(ms: number): string {
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  const sec = s % 60
  return `${m}:${String(sec).padStart(2, '0')}`
}

// ── Undoable state hook ──

interface UndoFrame { entries: SubtitleEntry[]; description: string }

function useUndoableState(initial: SubtitleEntry[]) {
  const [past, setPast] = useState<UndoFrame[]>([])
  const [present, setPresent] = useState<SubtitleEntry[]>(initial)
  const [future, setFuture] = useState<UndoFrame[]>([])
  const presentRef = useRef<SubtitleEntry[]>(present)
  presentRef.current = present

  const push = useCallback((entries: SubtitleEntry[], desc: string) => {
    setPast(p => {
      const next = [...p, { entries: presentRef.current, description: desc }]
      return next.length > MAX_UNDO_STEPS ? next.slice(-MAX_UNDO_STEPS) : next
    })
    setPresent(entries)
    setFuture([])
  }, [])

  const undo = useCallback(() => {
    setPast(p => {
      if (p.length === 0) return p
      setFuture(f => [...f, { entries: presentRef.current, description: 'redo' }])
      setPresent(p[p.length - 1].entries)
      return p.slice(0, -1)
    })
  }, [])

  const redo = useCallback(() => {
    setFuture(f => {
      if (f.length === 0) return f
      setPast(p => [...p, { entries: presentRef.current, description: 'undo' }])
      setPresent(f[f.length - 1].entries)
      return f.slice(0, -1)
    })
  }, [])

  const reset = useCallback((entries: SubtitleEntry[]) => {
    setPast([])
    setPresent(entries)
    setFuture([])
  }, [])

  return { entries: present, push, undo, redo, reset, canUndo: past.length > 0, canRedo: future.length > 0 }
}

// ── Props ──

interface Props {
  events: EventViewModel[]
  onSeek?: (time: number) => void
}

// ── Memo row ──

const SubtitleRowMemo = React.memo(function SubtitleRow({
  entry, isCurrent, isSelected, isEditing, editText,
  onSeek, onToggleSelect, onStartEdit, onEditTextChange, onCommitEdit, onCancelEdit, onToggleStatus,
}: {
  entry: SubtitleEntry; isCurrent: boolean; isSelected: boolean; isEditing: boolean; editText: string
  onSeek: (e: SubtitleEntry) => void; onToggleSelect: (idx: number) => void
  onStartEdit: (e: SubtitleEntry) => void; onEditTextChange: (t: string) => void
  onCommitEdit: () => void; onCancelEdit: () => void; onToggleStatus: (e: SubtitleEntry) => void
}) {
  const hasIssues = entry.issues.length > 0
  const cps = getCPS(entry)
  const limit = 12
  const cpsColor = cps > limit ? 'error.main' : cps > limit * 0.85 ? 'warning.main' : 'success.main'

  return (
    <TableRow hover selected={isCurrent}
      sx={{
        cursor: 'default',
        bgcolor: hasIssues ? 'rgba(237,108,2,0.06)' : undefined,
      }}>
      <TableCell padding="checkbox" onClick={e => e.stopPropagation()}>
        <Checkbox size="small" checked={isSelected} onChange={() => onToggleSelect(entry.index)} />
      </TableCell>
      <TableCell onClick={() => onSeek(entry)}
        sx={{ fontWeight: 600, fontFamily: 'monospace', fontSize: '0.75rem', cursor: 'pointer' }}>
        {entry.index}
      </TableCell>
      <TableCell onClick={() => onSeek(entry)} sx={{ fontSize: '0.75rem', whiteSpace: 'nowrap', cursor: 'pointer' }}>
        {formatMs(entry.startMs)}
      </TableCell>
      <TableCell onClick={() => onSeek(entry)} sx={{ cursor: 'pointer' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <Box sx={{ width: 4, height: 4, borderRadius: '50%', bgcolor: cpsColor, flexShrink: 0 }} />
          <Typography variant="caption" sx={{ color: cpsColor, fontWeight: 500 }}>{cps.toFixed(1)}</Typography>
        </Box>
      </TableCell>
      <TableCell onClick={() => onSeek(entry)}
        sx={{ cursor: 'pointer', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        <Typography variant="caption">{entry.sourceText}</Typography>
      </TableCell>
      <TableCell onDoubleClick={() => onStartEdit(entry)}
        sx={{ cursor: 'pointer', maxWidth: 250 }}>
        {isEditing ? (
          <input
            value={editText}
            onChange={e => onEditTextChange(e.target.value)}
            onBlur={onCommitEdit}
            onKeyDown={e => { if (e.key === 'Enter') onCommitEdit(); if (e.key === 'Escape') onCancelEdit() }}
            autoFocus
            style={{ width: '100%', fontSize: '0.75rem', padding: 2, border: '1px solid #6366F1', borderRadius: 4 }}
          />
        ) : (
          <Typography variant="caption">{entry.translatedText}</Typography>
        )}
      </TableCell>
      <TableCell align="center" sx={{ minWidth: 28 }}>
        <Chip
          size="small"
          label={entry.reviewStatus === 'approved' ? '✓' : entry.reviewStatus === 'modified' ? '✎' : entry.reviewStatus === 'flagged' ? '⚠' : ''}
          color={entry.reviewStatus === 'approved' ? 'success' : entry.reviewStatus === 'flagged' ? 'warning' : 'default'}
          variant="outlined"
          onClick={() => onToggleStatus(entry)}
          sx={{ height: 20, fontSize: '0.6rem', cursor: 'pointer' }}
        />
      </TableCell>
    </TableRow>
  )
})

// ── Component ──

export default function ReviewTable({ events, onSeek }: Props) {
  const reviewEntries = useAppStore(s => s.reviewEntries)
  const searchQuery = useAppStore(s => s.reviewSearchQuery)
  const filterMode = useAppStore(s => s.reviewFilterMode)

  const { entries: localEntries, push, undo, redo, reset, canUndo, canRedo } = useUndoableState(reviewEntries)

  const [selectedIndices, setSelectedIndices] = useState<Set<number>>(new Set())
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editText, setEditText] = useState('')
  const [currentEntryIndex, setCurrentEntryIndex] = useState<number | null>(null)
  const [toastVisible, setToastVisible] = useState(false)

  // Sync to store
  const syncToStore = useCallback((entries: SubtitleEntry[]) => {
    useAppStore.getState().setReviewEntries(entries)
  }, [])

  // Filter
  const filtered = useMemo(() => {
    let list = localEntries
    const q = searchQuery.toLowerCase().trim()
    if (q) list = list.filter(e =>
      e.translatedText.toLowerCase().includes(q) || e.sourceText.toLowerCase().includes(q)
    )
    switch (filterMode) {
      case 'pending': list = list.filter(e => e.reviewStatus === 'pending'); break
      case 'flagged': list = list.filter(e => e.issues.length > 0); break
    }
    return list
  }, [localEntries, searchQuery, filterMode])

  const approvedCount = localEntries.filter(e => e.reviewStatus === 'approved').length
  const modifiedCount = localEntries.filter(e => e.reviewStatus === 'modified').length
  const flaggedCount = localEntries.filter(e => e.issues.length > 0).length

  // Mutate entry
  const mutateEntry = useCallback((index: number, update: Partial<SubtitleEntry>, desc: string) => {
    push(
      localEntries.map(e => e.index === index ? { ...e, ...update } : e),
      desc,
    )
  }, [push, localEntries])

  const handleToggleStatus = useCallback((entry: SubtitleEntry) => {
    const newStatus = entry.reviewStatus === 'approved' ? 'pending' : 'approved'
    mutateEntry(entry.index, { reviewStatus: newStatus }, newStatus === 'approved' ? '批准' : '取消批准')
  }, [mutateEntry])

  const handleStartEdit = useCallback((entry: SubtitleEntry) => {
    setEditingIndex(entry.index)
    setEditText(entry.translatedText)
  }, [])

  const handleCommitEdit = useCallback(() => {
    if (editingIndex === null) return
    const old = localEntries.find(e => e.index === editingIndex)
    if (old && old.translatedText !== editText) {
      mutateEntry(editingIndex, { translatedText: editText, reviewStatus: 'modified' }, '编辑译文')
    }
    setEditingIndex(null)
  }, [editingIndex, editText, mutateEntry, localEntries])

  const handleCancelEdit = useCallback(() => setEditingIndex(null), [])

  const handleSeek = useCallback((entry: SubtitleEntry) => {
    setCurrentEntryIndex(entry.index)
    onSeek?.(entry.startMs / 1000)
  }, [onSeek])

  const toggleSelect = useCallback((index: number) => {
    setSelectedIndices(p => { const n = new Set(p); n.has(index) ? n.delete(index) : n.add(index); return n })
  }, [])

  const handleSave = useCallback(async () => {
    syncToStore(localEntries)
    setToastVisible(true)
    setTimeout(() => setToastVisible(false), 2000)
  }, [localEntries, syncToStore])

  // Keyboard shortcuts
  const kbp = { handleCommitEdit, handleCancelEdit, undo, redo, handleSave }
  const kbRef = useRef(kbp)
  kbRef.current = kbp

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const r = kbRef.current
      const inField = e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement
      if (inField) {
        if (e.key === 'Escape') r.handleCancelEdit()
        return
      }
      if (e.ctrlKey && e.key === 'z') { e.preventDefault(); r.undo() }
      if (e.ctrlKey && e.key === 'y') { e.preventDefault(); r.redo() }
      if (e.ctrlKey && e.key === 's') { e.preventDefault(); r.handleSave() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Init from events if empty
  useEffect(() => {
    if (localEntries.length === 0 && events.length > 0) {
      const entries: SubtitleEntry[] = events.map((evt, i) => ({
        index: i + 1,
        start: formatMs(Math.round(evt.start * 1000)),
        end: formatMs(Math.round(evt.end * 1000)),
        startMs: Math.round(evt.start * 1000),
        endMs: Math.round(evt.end * 1000),
        sourceText: evt.text || '',
        translatedText: evt.translation || '',
        reviewStatus: 'pending' as const,
        issues: [],
        speakerId: evt.speaker || undefined,
      }))
      reset(entries)
      syncToStore(entries)
    }
  }, [events.length])

  return (
    <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Toolbar */}
      <Card sx={{ p: 1, display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', borderRadius: 0 }}>
        <Chip label={`${localEntries.length} 条`} size="small" />
        <Chip label={`${approvedCount} ✓`} size="small" color="success" variant="outlined" />
        <Chip label={`${modifiedCount} ✎`} size="small" color="info" variant="outlined" />
        {flaggedCount > 0 && <Chip label={`${flaggedCount} ⚠`} size="small" color="warning" variant="outlined" />}

        <TextField
          size="small" placeholder="搜索…"
          value={searchQuery}
          onChange={e => useAppStore.getState().setReviewSearchQuery(e.target.value)}
          sx={{ width: 180 }}
          InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }}
        />

        <Box sx={{ flexGrow: 1 }} />

        <Tooltip title="撤销 (Ctrl+Z)"><span>
          <IconButton size="small" onClick={undo} disabled={!canUndo}><UndoIcon fontSize="small" /></IconButton>
        </span></Tooltip>
        <Tooltip title="重做 (Ctrl+Y)"><span>
          <IconButton size="small" onClick={redo} disabled={!canRedo}><RedoIcon fontSize="small" /></IconButton>
        </span></Tooltip>

        <ToggleButtonGroup size="small" value={filterMode} exclusive
          onChange={(_, v) => v && useAppStore.getState().setReviewFilterMode(v)}>
          <ToggleButton value="all" sx={{ px: 1 }}>
            全部<Box component="span" sx={{ ml: 0.5, opacity: 0.4, fontSize: '0.65rem' }}>{localEntries.length}</Box>
          </ToggleButton>
          <ToggleButton value="flagged" sx={{ px: 1 }}>
            标记<Box component="span" sx={{ ml: 0.5, opacity: 0.4, fontSize: '0.65rem' }}>{flaggedCount}</Box>
          </ToggleButton>
        </ToggleButtonGroup>

        <Button size="small" variant="contained" onClick={handleSave}
          startIcon={<SaveIcon fontSize="small" />}>保存</Button>
      </Card>

      {/* Toast */}
      {toastVisible && (
        <Box sx={{ px: 2, py: 0.5, bgcolor: 'primary.main', color: 'white', fontSize: '0.75rem' }}>已保存</Box>
      )}

      {/* Table */}
      <TableContainer sx={{ flexGrow: 1, overflow: 'auto' }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell padding="checkbox" sx={{ width: 38 }}></TableCell>
              <TableCell sx={{ width: 44 }}>#</TableCell>
              <TableCell sx={{ width: 80 }}>时间</TableCell>
              <TableCell sx={{ width: 50 }}>CPS</TableCell>
              <TableCell>原文</TableCell>
              <TableCell>译文</TableCell>
              <TableCell sx={{ width: 46 }} align="center">状态</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {filtered.map(entry => (
              <SubtitleRowMemo key={entry.index}
                entry={entry}
                isCurrent={entry.index === currentEntryIndex}
                isEditing={entry.index === editingIndex}
                isSelected={selectedIndices.has(entry.index)}
                editText={editText}
                onSeek={handleSeek}
                onToggleSelect={toggleSelect}
                onStartEdit={handleStartEdit}
                onEditTextChange={setEditText}
                onCommitEdit={handleCommitEdit}
                onCancelEdit={handleCancelEdit}
                onToggleStatus={handleToggleStatus}
              />
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  )
}
