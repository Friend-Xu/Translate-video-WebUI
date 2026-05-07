import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react'
import {
  Box, Typography, Button, TextField, Card, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, Chip, IconButton,
  Tooltip, ToggleButtonGroup, ToggleButton, Alert, CircularProgress,
  Select, MenuItem, FormControl, Checkbox, LinearProgress, InputAdornment,
} from '@mui/material'
import FolderOpenIcon from '@mui/icons-material/FolderOpenRounded'
import SaveIcon from '@mui/icons-material/SaveRounded'
import PlayArrowIcon from '@mui/icons-material/PlayArrowRounded'
import PauseIcon from '@mui/icons-material/PauseRounded'
import SkipNextIcon from '@mui/icons-material/SkipNextRounded'
import SkipPreviousIcon from '@mui/icons-material/SkipPreviousRounded'
import CheckCircleIcon from '@mui/icons-material/CheckCircleRounded'
import WarningAmberIcon from '@mui/icons-material/WarningAmberRounded'
import ErrorIcon from '@mui/icons-material/ErrorRounded'
import LoopIcon from '@mui/icons-material/LoopRounded'
import EditIcon from '@mui/icons-material/EditRounded'
import UndoIcon from '@mui/icons-material/UndoRounded'
import RedoIcon from '@mui/icons-material/RedoRounded'
import SearchIcon from '@mui/icons-material/SearchRounded'
import CloudDoneIcon from '@mui/icons-material/CloudDoneRounded'
import { FilePickerDialog } from '../FilePickerDialog'
import { SectionHeader } from '../SectionHeader'
import type { SubtitleEntry } from '../../types'

const SRT_EXTS = ['.srt', '.vtt']
const AUTO_SAVE_INTERVAL = 30000
const PRE_ROLL_MS = 500
const MAX_UNDO_STEPS = 50
const CPS_LIMITS: Record<string, number> = { zh: 12, ja: 12, ko: 12 }

// ── Helpers ──

function getCPS(entry: SubtitleEntry): number {
  const dur = (entry.endMs - entry.startMs) / 1000
  const chars = entry.translatedText.replace(/\n/g, '').length
  return dur > 0 ? chars / dur : 0
}

function getCPSLimit(lang: string): number {
  return CPS_LIMITS[lang] ?? 20
}

function getDuration(entry: SubtitleEntry): number {
  return (entry.endMs - entry.startMs) / 1000
}

// ── Undoable state ──

interface UndoFrame {
  entries: SubtitleEntry[]
  description: string
}

function useUndoableState(initial: SubtitleEntry[]) {
  const [past, setPast] = useState<UndoFrame[]>([])
  const [present, setPresent] = useState<SubtitleEntry[]>(initial)
  const [future, setFuture] = useState<UndoFrame[]>([])
  const presentRef = useRef(present)
  presentRef.current = present

  const push = useCallback((entries: SubtitleEntry[], description: string) => {
    setPast(prev => {
      const next = [...prev, { entries: presentRef.current, description }]
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

interface SubtitleReviewProps {
  videoPath: string
  onSuccess: (msg: string) => void
}

// ── Memoized row (prevents O(n) re-renders on single-entry changes) ──

const SubtitleRowMemo = React.memo(function SubtitleRow({
  entry, isCurrent, isEditing, isSelected, editText,
  onSeek, onToggleSelect, onStartEdit, onEditTextChange, onCommitEdit, onCancelEdit, onToggleStatus,
}: {
  entry: SubtitleEntry
  isCurrent: boolean
  isEditing: boolean
  isSelected: boolean
  editText: string
  onSeek: (e: SubtitleEntry) => void
  onToggleSelect: (idx: number) => void
  onStartEdit: (e: SubtitleEntry) => void
  onEditTextChange: (t: string) => void
  onCommitEdit: () => void
  onCancelEdit: () => void
  onToggleStatus: (e: SubtitleEntry) => void
}) {
  const hasIssues = entry.issues.length > 0
  const dur = getDuration(entry)
  const durWarning = dur < 0.8 || dur > 7.0
  const cps = getCPS(entry)
  const limit = getCPSLimit('zh')
  const ratio = Math.min(cps / limit, 1.5)
  const color = cps > limit ? 'error.main' : cps > limit * 0.85 ? 'warning.main' : 'success.main'

  return (
    <TableRow hover selected={isCurrent}
      sx={{
        cursor: 'default',
        bgcolor: hasIssues ? 'rgba(237,108,2,0.06)' : undefined,
        '&.Mui-selected': { bgcolor: 'primary.light' },
      }}>
      <TableCell padding="checkbox" onClick={e => e.stopPropagation()}>
        <Checkbox size="small" checked={isSelected} onChange={() => onToggleSelect(entry.index)} />
      </TableCell>
      <TableCell onClick={() => onSeek(entry)}
        sx={{ cursor: 'pointer', fontFamily: 'monospace', fontSize: '0.8rem' }}>
        {entry.index}
      </TableCell>
      <TableCell onClick={() => onSeek(entry)} sx={{ cursor: 'pointer', p: 0.5 }}>
        <Box sx={{ display: 'flex', flexDirection: 'column' }}>
          <Typography variant="caption" sx={{
            fontFamily: 'monospace', fontSize: '0.7rem',
            color: durWarning ? 'warning.main' : 'text.secondary',
          }}>
            {entry.start} → {entry.end}
          </Typography>
          <Typography variant="caption" sx={{
            fontSize: '0.65rem',
            color: durWarning ? 'warning.main' : 'text.disabled',
          }}>
            {dur.toFixed(1)}s
          </Typography>
        </Box>
      </TableCell>
      <TableCell sx={{ p: 0.5 }}>
        <Tooltip title={`${cps.toFixed(1)} 字符/秒 (上限 ${limit})`}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <LinearProgress
              variant="determinate"
              value={Math.min(ratio * 100, 100)}
              sx={{
                width: 40, height: 4, borderRadius: 2,
                bgcolor: 'action.hover',
                '& .MuiLinearProgress-bar': { bgcolor: color, borderRadius: 2 },
              }}
            />
            <Typography variant="caption" sx={{ fontSize: '0.65rem', color, minWidth: 28 }}>
              {cps.toFixed(1)}
            </Typography>
          </Box>
        </Tooltip>
      </TableCell>
      <TableCell onClick={() => onSeek(entry)}
        sx={{ cursor: 'pointer', whiteSpace: 'pre-wrap', maxWidth: 250, fontSize: '0.85rem' }}>
        {entry.sourceText}
      </TableCell>
      <TableCell sx={{ maxWidth: 250 }}
        onDoubleClick={e => { e.stopPropagation(); onStartEdit(entry) }}>
        {isEditing ? (
          <TextField size="small" fullWidth multiline autoFocus
            value={editText}
            onChange={e => onEditTextChange(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onCommitEdit() }
              if (e.key === 'Escape') onCancelEdit()
            }}
            onBlur={onCommitEdit}
            sx={{ '& .MuiInputBase-root': { fontSize: '0.85rem' } }} />
        ) : (
          <Typography variant="body2" sx={{
            whiteSpace: 'pre-wrap', fontSize: '0.85rem',
            color: entry.reviewStatus === 'modified' ? 'info.main' : 'text.primary',
            cursor: 'text', '&:hover': { bgcolor: 'action.hover' },
            p: 0.5, borderRadius: 1, minHeight: 24,
          }}
          onClick={e => { e.stopPropagation(); onStartEdit(entry) }}>
            {entry.translatedText || (
              <Typography component="span" color="text.secondary" fontStyle="italic">(空)</Typography>
            )}
          </Typography>
        )}
      </TableCell>
      <TableCell align="center"
        onClick={e => { e.stopPropagation(); onToggleStatus(entry) }}
        sx={{ cursor: 'pointer' }}>
        {entry.issues.some(i => i.severity === 'error') ? (
          <Tooltip title={entry.issues.map(i => i.message).join('\n')}>
            <ErrorIcon color="error" fontSize="small" />
          </Tooltip>
        ) : entry.issues.length > 0 ? (
          <Tooltip title={entry.issues.map(i => i.message).join('\n')}>
            <WarningAmberIcon sx={{ color: 'warning.main' }} fontSize="small" />
          </Tooltip>
        ) : entry.reviewStatus === 'approved' ? (
          <CheckCircleIcon color="success" fontSize="small" />
        ) : entry.reviewStatus === 'modified' ? (
          <EditIcon color="info" fontSize="small" />
        ) : (
          <Chip label="待审" size="small" variant="outlined" sx={{ height: 22, fontSize: '0.7rem' }} />
        )}
      </TableCell>
    </TableRow>
  )
})

// ── Component ──

export function SubtitleReview({ videoPath, onSuccess }: SubtitleReviewProps) {
  // Session meta
  const [sessionMeta, setSessionMeta] = useState<{
    videoPath: string; sourceSrtPath: string; translatedSrtPath: string
  } | null>(null)
  const [filterMode, setFilterMode] = useState<'all' | 'pending' | 'flagged'>('all')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editText, setEditText] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedIndices, setSelectedIndices] = useState<Set<number>>(new Set())
  const [lastSaved, setLastSaved] = useState<Date | null>(null)
  const [autoSaveDirty, setAutoSaveDirty] = useState(false)
  const [toast, setToast] = useState('')

  // File picker
  const [filePickerOpen, setFilePickerOpen] = useState(false)
  const [filePickerMode, setFilePickerMode] = useState<'source' | 'translated' | 'log'>('source')
  const [filePickerInitialPath, setFilePickerInitialPath] = useState('')
  const [sourceSrt, setSourceSrt] = useState('')
  const [translatedSrt, setTranslatedSrt] = useState('')
  const [translateLog, setTranslateLog] = useState('')

  // Undoable entries
  const { entries, push, undo, redo, reset, canUndo, canRedo } = useUndoableState([])
  const entriesRef = useRef(entries)
  entriesRef.current = entries

  // Video
  const videoRef = useRef<HTMLVideoElement>(null)
  const [currentEntryIndex, setCurrentEntryIndex] = useState<number | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [playbackRate, setPlaybackRate] = useState(1)
  const [loopCurrent, setLoopCurrent] = useState(false)
  const [preRollEnabled, setPreRollEnabled] = useState(true)

  // Derived
  const defaultDir = useMemo(() => {
    if (!videoPath) return ''
    const d = videoPath.replace(/\\/g, '/')
    return d.substring(0, d.lastIndexOf('/'))
  }, [videoPath])

  const filteredEntries = useMemo(() => {
    let result = entries
    if (filterMode === 'pending') result = result.filter(e => e.reviewStatus === 'pending')
    else if (filterMode === 'flagged') result = result.filter(e => e.issues.length > 0)
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      result = result.filter(e =>
        e.sourceText.toLowerCase().includes(q) ||
        e.translatedText.toLowerCase().includes(q)
      )
    }
    return result
  }, [entries, filterMode, searchQuery])

  const approvedCount = useMemo(() => entries.filter(e => e.reviewStatus === 'approved').length, [entries])
  const modifiedCount = useMemo(() => entries.filter(e => e.reviewStatus === 'modified').length, [entries])
  const flaggedCount = useMemo(() => entries.filter(e => e.issues.length > 0).length, [entries])
  const totalCount = entries.length

  const showToast = useCallback((msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(''), 2500)
  }, [])

  // ── File picker ──

  const handleOpenFilePicker = useCallback((mode: 'source' | 'translated' | 'log') => {
    setFilePickerMode(mode)
    if (mode === 'log' && translatedSrt) {
      const d = translatedSrt.replace(/\\/g, '/')
      setFilePickerInitialPath(d.substring(0, d.lastIndexOf('/')))
    } else if (defaultDir) {
      setFilePickerInitialPath(defaultDir)
    } else {
      setFilePickerInitialPath('')
    }
    setFilePickerOpen(true)
  }, [defaultDir, translatedSrt])

  const handleFileSelected = useCallback((path: string) => {
    if (filePickerMode === 'source') {
      setSourceSrt(path)
      const d = path.replace(/\\/g, '/')
      setFilePickerInitialPath(d.substring(0, d.lastIndexOf('/')))
    } else if (filePickerMode === 'translated') {
      setTranslatedSrt(path)
      const d = path.replace(/\\/g, '/')
      const dir = d.substring(0, d.lastIndexOf('/'))
      const candidates = [
        dir + '/translate-log.json',
        path.replace(/-auto\.srt$/i, '-translate-log.json'),
        path.replace(/\.srt$/i, '-translate-log.json'),
      ]
      for (const c of candidates) {
        if (c !== path && !translateLog) { setTranslateLog(c); break }
      }
    } else {
      setTranslateLog(path)
    }
    setFilePickerOpen(false)
  }, [filePickerMode, translateLog])

  // ── Load ──

  const handleLoad = useCallback(async () => {
    if (!sourceSrt || !translatedSrt) return
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/subtitle/review/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_srt: sourceSrt,
          translated_srt: translatedSrt,
          translate_log: translateLog || null,
        }),
      })
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || '加载失败') }
      const data = await res.json()
      setSessionMeta({
        videoPath: data.videoPath,
        sourceSrtPath: data.sourceSrtPath,
        translatedSrtPath: data.translatedSrtPath,
      })
      reset(data.entries)
      setCurrentEntryIndex(null)
      setSelectedIndices(new Set())
      setSearchQuery('')
      setLastSaved(null)
      setAutoSaveDirty(false)
      onSuccess(`已加载 ${data.stats.total} 条字幕 (${data.stats.lowSimilarity} 条低质)`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [sourceSrt, translatedSrt, translateLog, onSuccess, reset])

  // ── Save ──

  const doSave = useCallback(async (silent = false) => {
    if (!sessionMeta?.translatedSrtPath) return
    setSaving(true)
    try {
      const res = await fetch('/api/subtitle/review/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          translated_srt: sessionMeta.translatedSrtPath,
          entries: entriesRef.current,
        }),
      })
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || '保存失败') }
      const data = await res.json()
      setLastSaved(new Date())
      setAutoSaveDirty(false)
      if (!silent) onSuccess(`已保存 ${data.updated} 条修改 → ${data.output_path}`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }, [sessionMeta, onSuccess])

  // Auto-save timer
  useEffect(() => {
    if (!autoSaveDirty || !sessionMeta) return
    const timer = setTimeout(() => { doSave(true) }, AUTO_SAVE_INTERVAL)
    return () => clearTimeout(timer)
  }, [autoSaveDirty, sessionMeta, doSave, entries])

  // Mark dirty on entry changes
  const prevEntriesRef = useRef(entries)
  useEffect(() => {
    if (prevEntriesRef.current !== entries && sessionMeta) {
      setAutoSaveDirty(true)
    }
    prevEntriesRef.current = entries
  }, [entries, sessionMeta])

  // ── Entry mutations (with undo) ──

  const mutateEntry = useCallback((index: number, update: Partial<SubtitleEntry>, desc: string) => {
    push(
      entriesRef.current.map(e => e.index === index ? { ...e, ...update } : e),
      desc,
    )
  }, [push])

  const mutateEntries = useCallback((indices: Set<number>, update: Partial<SubtitleEntry>, desc: string) => {
    push(
      entriesRef.current.map(e => indices.has(e.index) ? { ...e, ...update } : e),
      desc,
    )
  }, [push])

  // ── Edit ──

  const handleStartEdit = useCallback((entry: SubtitleEntry) => {
    setEditingIndex(entry.index)
    setEditText(entry.translatedText)
  }, [])

  const handleCommitEdit = useCallback(() => {
    if (editingIndex === null) return
    const old = entriesRef.current.find(e => e.index === editingIndex)
    if (old && old.translatedText !== editText) {
      mutateEntry(editingIndex, { translatedText: editText, reviewStatus: 'modified' }, '编辑译文')
    }
    setEditingIndex(null)
  }, [editingIndex, editText, mutateEntry])

  const handleCancelEdit = useCallback(() => {
    setEditingIndex(null)
  }, [])

  // ── Review status ──

  const handleToggleStatus = useCallback((entry: SubtitleEntry) => {
    const newStatus = entry.reviewStatus === 'approved' ? 'pending' : 'approved'
    mutateEntry(entry.index, { reviewStatus: newStatus }, newStatus === 'approved' ? '批准' : '取消批准')
  }, [mutateEntry])

  const handleApproveAll = useCallback(() => {
    if (entriesRef.current.length === 0) return
    push(
      entriesRef.current.map(e => ({ ...e, reviewStatus: 'approved' as const })),
      '全部批准',
    )
    showToast('已全部批准')
  }, [push, showToast])

  const handleApproveSelected = useCallback(() => {
    if (selectedIndices.size === 0) return
    mutateEntries(selectedIndices, { reviewStatus: 'approved' as const }, `批准 ${selectedIndices.size} 条`)
    setSelectedIndices(new Set())
    showToast(`已批准 ${selectedIndices.size} 条`)
  }, [selectedIndices, mutateEntries, showToast])

  // ── Selection ──

  const toggleSelect = useCallback((index: number) => {
    setSelectedIndices(prev => {
      const next = new Set(prev)
      if (next.has(index)) next.delete(index); else next.add(index)
      return next
    })
  }, [])

  const selectAllFiltered = useCallback(() => {
    const allSelected = filteredEntries.length > 0 && filteredEntries.every(e => selectedIndices.has(e.index))
    if (allSelected) {
      setSelectedIndices(new Set())
    } else {
      setSelectedIndices(new Set(filteredEntries.map(e => e.index)))
    }
  }, [filteredEntries, selectedIndices])

  // ── Video ──

  const seekToEntry = useCallback((entry: SubtitleEntry) => {
    const video = videoRef.current
    if (!video) return
    const offset = preRollEnabled ? PRE_ROLL_MS / 1000 : 0
    video.currentTime = Math.max(0, entry.startMs / 1000 - offset)
    setCurrentEntryIndex(entry.index)
    video.play().catch(() => {})
  }, [preRollEnabled])

  const lastEntryIdxRef = useRef(-1)
  const handleVideoTimeUpdate = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    const t = video.currentTime * 1000
    const list = entriesRef.current

    if (loopCurrent && currentEntryIndex !== null) {
      const entry = list.find(e => e.index === currentEntryIndex)
      if (entry && t > entry.endMs) {
        video.currentTime = entry.startMs / 1000
        video.play().catch(() => {})
        return
      }
    }

    // Index-based tracking (entries are time-sorted) — avoids O(n) scan at 30fps
    let current: SubtitleEntry | undefined
    let idx = lastEntryIdxRef.current
    if (idx >= 0 && idx < list.length) {
      const at = list[idx]
      if (t >= at.startMs && t <= at.endMs) {
        current = at
      } else if (t > at.endMs && idx + 1 < list.length && t <= list[idx + 1].startMs) {
        // Between entries — don't reassign
      } else if (t > at.endMs && idx + 1 < list.length && t >= list[idx + 1].startMs && t <= list[idx + 1].endMs) {
        current = list[idx + 1]; idx++
      } else if (t < at.startMs && idx - 1 >= 0 && t >= list[idx - 1].startMs && t <= list[idx - 1].endMs) {
        current = list[idx - 1]; idx--
      }
    }
    if (!current) {
      // Fall back to linear scan
      for (let i = 0; i < list.length; i++) {
        if (t >= list[i].startMs && t <= list[i].endMs) { current = list[i]; idx = i; break }
      }
    }
    lastEntryIdxRef.current = idx
    if (current && current.index !== currentEntryIndex) {
      setCurrentEntryIndex(current.index)
    }
  }, [currentEntryIndex, loopCurrent])

  const handleVideoPlay = useCallback(() => setIsPlaying(true), [])
  const handleVideoPause = useCallback(() => setIsPlaying(false), [])

  const togglePlay = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    if (video.paused) video.play().catch(() => {})
    else video.pause()
  }, [])

  const seekRelative = useCallback((deltaSec: number) => {
    const video = videoRef.current
    if (!video) return
    video.currentTime = Math.max(0, video.currentTime + deltaSec)
  }, [])

  const goToEntry = useCallback((offset: number) => {
    if (currentEntryIndex === null) return
    const list = entriesRef.current
    const idx = list.findIndex(e => e.index === currentEntryIndex)
    const next = list[idx + offset]
    if (next) seekToEntry(next)
  }, [currentEntryIndex, seekToEntry])

  const playCurrentSegment = useCallback(() => {
    if (currentEntryIndex === null) return
    const entry = entriesRef.current.find(e => e.index === currentEntryIndex)
    if (!entry) return
    const video = videoRef.current
    if (!video) return
    video.currentTime = entry.startMs / 1000
    video.play().catch(() => {})
    const checkEnd = () => {
      if (video.currentTime * 1000 >= entry.endMs) {
        video.pause()
        video.removeEventListener('timeupdate', checkEnd)
      }
    }
    video.addEventListener('timeupdate', checkEnd)
  }, [currentEntryIndex])

  const goToNextFlagged = useCallback(() => {
    const flagged = entriesRef.current.filter(e => e.issues.length > 0)
    if (flagged.length === 0) return
    const currentIdx = flagged.findIndex(e => e.index === currentEntryIndex)
    const next = flagged[(currentIdx + 1) % flagged.length]
    seekToEntry(next)
  }, [currentEntryIndex, seekToEntry])

  const goToPrevFlagged = useCallback(() => {
    const flagged = entriesRef.current.filter(e => e.issues.length > 0)
    if (flagged.length === 0) return
    const currentIdx = flagged.findIndex(e => e.index === currentEntryIndex)
    const prev = flagged[(currentIdx - 1 + flagged.length) % flagged.length]
    seekToEntry(prev)
  }, [currentEntryIndex, seekToEntry])

  // ── Keyboard shortcuts (registered once via ref) ──

  const kbRef = useRef({
    handleCancelEdit, handleCommitEdit, doSave, togglePlay, seekRelative,
    goToEntry, goToPrevFlagged, goToNextFlagged, handleStartEdit,
    playCurrentSegment, undo, redo, selectAllFiltered, showToast,
    currentEntryIndex, editingIndex,
  })
  kbRef.current = {
    handleCancelEdit, handleCommitEdit, doSave, togglePlay, seekRelative,
    goToEntry, goToPrevFlagged, goToNextFlagged, handleStartEdit,
    playCurrentSegment, undo, redo, selectAllFiltered, showToast,
    currentEntryIndex, editingIndex,
  }

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      const r = kbRef.current
      const inTextField = e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement
      if (inTextField) {
        if (e.key === 'Escape') r.handleCancelEdit()
        if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
          e.preventDefault()
          r.handleCommitEdit()
        }
        if ((e.ctrlKey || e.metaKey) && e.key === 's') {
          e.preventDefault()
          r.doSave(false)
        }
        return
      }

      const ctrl = e.ctrlKey || e.metaKey

      if (e.key === ' ') { e.preventDefault(); r.togglePlay(); return }
      if (e.key === 'j' || e.key === 'J') { e.preventDefault(); r.seekRelative(-2); return }
      if (e.key === 'k' || e.key === 'K') { e.preventDefault(); videoRef.current?.pause(); return }
      if (e.key === 'l' || e.key === 'L') { e.preventDefault(); r.seekRelative(2); return }
      if (e.key === 'ArrowUp') { e.preventDefault(); r.goToEntry(-1); return }
      if (e.key === 'ArrowDown') { e.preventDefault(); r.goToEntry(1); return }
      if (e.key === '[') { e.preventDefault(); r.goToPrevFlagged(); return }
      if (e.key === ']') { e.preventDefault(); r.goToNextFlagged(); return }

      if (e.key === 'Enter' && !ctrl) {
        e.preventDefault()
        if (r.currentEntryIndex !== null) {
          const entry = entriesRef.current.find(en => en.index === r.currentEntryIndex)
          if (entry) r.handleStartEdit(entry)
        }
        return
      }

      if (e.key === 'Tab') { e.preventDefault(); r.playCurrentSegment(); return }

      if (ctrl && e.key === 'z') { e.preventDefault(); r.undo(); r.showToast('撤销'); return }
      if (ctrl && (e.key === 'y' || (e.key === 'Z' && e.shiftKey))) { e.preventDefault(); r.redo(); r.showToast('重做'); return }
      if (ctrl && e.key === 's') { e.preventDefault(); r.doSave(false); return }
      if (ctrl && e.key === 'a') { e.preventDefault(); r.selectAllFiltered(); return }
      if (ctrl && e.key === 'f') {
        e.preventDefault()
        document.getElementById('subtitle-search-input')?.focus()
        return
      }

      if (e.key === '1') { e.preventDefault(); setFilterMode('all'); return }
      if (e.key === '2') { e.preventDefault(); setFilterMode('pending'); return }
      if (e.key === '3') { e.preventDefault(); setFilterMode('flagged'); return }

      if (e.key === 'Escape') {
        setSelectedIndices(new Set())
        if (r.editingIndex !== null) r.handleCancelEdit()
      }
    }

    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [])

  // Stable wrapper for handleCommitEdit (depends on editText which changes per-keystroke)
  const handleCommitEditRef = useRef(handleCommitEdit)
  handleCommitEditRef.current = handleCommitEdit
  const commitEditStable = useCallback(() => handleCommitEditRef.current(), [])

  // ── File label ──

  const fileLabel = (path: string) => {
    if (!path) return ''
    const i = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'))
    return i >= 0 ? path.slice(i + 1) : path
  }

  // ── Render ──

  return (
    <>
      <SectionHeader title="字幕校准" />

      {/* Load panel */}
      {!sessionMeta && (
        <Card sx={{ p: 3 }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
            <Typography variant="subtitle2">加载字幕文件</Typography>

            <Box>
              <Typography variant="body2" mb={0.5} fontWeight={500}>
                原文字幕 <Typography component="span" color="error">*</Typography>
              </Typography>
              <Box sx={{ display: 'flex', gap: 1 }}>
                <TextField size="small" fullWidth value={fileLabel(sourceSrt)}
                  placeholder="选择原文字幕文件 (.srt)" InputProps={{ readOnly: true }}
                  onClick={() => handleOpenFilePicker('source')}
                  sx={{ cursor: 'pointer', '& .MuiInputBase-root': { cursor: 'pointer' } }} />
                <Button variant="outlined" startIcon={<FolderOpenIcon />}
                  onClick={() => handleOpenFilePicker('source')} size="small" sx={{ minWidth: 100, flexShrink: 0 }}>
                  选择文件
                </Button>
              </Box>
            </Box>

            <Box>
              <Typography variant="body2" mb={0.5} fontWeight={500}>
                机器翻译字幕 <Typography component="span" color="error">*</Typography>
              </Typography>
              <Box sx={{ display: 'flex', gap: 1 }}>
                <TextField size="small" fullWidth value={fileLabel(translatedSrt)}
                  placeholder="选择机器翻译字幕文件 (*-auto.srt)" InputProps={{ readOnly: true }}
                  onClick={() => handleOpenFilePicker('translated')}
                  sx={{ cursor: 'pointer', '& .MuiInputBase-root': { cursor: 'pointer' } }} />
                <Button variant="outlined" startIcon={<FolderOpenIcon />}
                  onClick={() => handleOpenFilePicker('translated')} size="small" sx={{ minWidth: 100, flexShrink: 0 }}>
                  选择文件
                </Button>
              </Box>
            </Box>

            <Box>
              <Typography variant="body2" mb={0.5} fontWeight={500}>
                翻译日志 <Typography component="span" color="text.secondary">(可选，用于语义质量标记)</Typography>
              </Typography>
              <Box sx={{ display: 'flex', gap: 1 }}>
                <TextField size="small" fullWidth value={fileLabel(translateLog)}
                  placeholder="选择 translate-log.json" InputProps={{ readOnly: true }}
                  onClick={() => handleOpenFilePicker('log')}
                  sx={{ cursor: 'pointer', '& .MuiInputBase-root': { cursor: 'pointer' } }} />
                <Button variant="outlined" startIcon={<FolderOpenIcon />}
                  onClick={() => handleOpenFilePicker('log')} size="small" sx={{ minWidth: 100, flexShrink: 0 }}>
                  选择文件
                </Button>
              </Box>
            </Box>

            {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}

            <Box sx={{ display: 'flex', gap: 2 }}>
              <Button variant="contained" onClick={handleLoad}
                disabled={!sourceSrt || !translatedSrt || loading}
                startIcon={loading ? <CircularProgress size={18} /> : undefined}>
                {loading ? '加载中...' : '加载字幕'}
              </Button>
            </Box>
          </Box>
        </Card>
      )}

      {/* Review panel */}
      {sessionMeta && (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {/* Toolbar */}
          <Card sx={{ p: 1.5, display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap' }}>
            <Chip label={`${totalCount} 条`} size="small" />
            <Chip label={`${approvedCount} ✓`} size="small" color="success" variant="outlined" />
            <Chip label={`${modifiedCount} ✎`} size="small" color="info" variant="outlined" />
            {flaggedCount > 0 && (
              <Chip label={`${flaggedCount} ⚠`} size="small" color="warning" variant="outlined" />
            )}

            <TextField
              id="subtitle-search-input"
              size="small"
              placeholder="搜索… (Ctrl+F)"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              sx={{ width: 180, '& .MuiInputBase-root': { fontSize: '0.8rem' } }}
              InputProps={{
                startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment>,
              }}
            />

            <Box sx={{ flexGrow: 1 }} />

            {selectedIndices.size > 0 && (
              <>
                <Chip label={`${selectedIndices.size} 已选`} size="small" color="primary"
                  onDelete={() => setSelectedIndices(new Set())} />
                <Button size="small" variant="outlined" color="success" onClick={handleApproveSelected}>
                  批准所选
                </Button>
              </>
            )}

            <Tooltip title="撤销 (Ctrl+Z)">
              <span>
                <IconButton size="small" onClick={() => { undo(); showToast('撤销') }} disabled={!canUndo}>
                  <UndoIcon fontSize="small" />
                </IconButton>
              </span>
            </Tooltip>
            <Tooltip title="重做 (Ctrl+Y)">
              <span>
                <IconButton size="small" onClick={() => { redo(); showToast('重做') }} disabled={!canRedo}>
                  <RedoIcon fontSize="small" />
                </IconButton>
              </span>
            </Tooltip>

            {autoSaveDirty && (
              <Tooltip title="有未保存的修改 (30s 自动保存)">
                <Chip icon={<CloudDoneIcon />} label="未保存" size="small" color="warning" variant="outlined" />
              </Tooltip>
            )}
            {lastSaved && !autoSaveDirty && (
              <Tooltip title={`上次保存: ${lastSaved.toLocaleTimeString()}`}>
                <Chip icon={<CloudDoneIcon />} label="已保存" size="small" color="success" variant="outlined" />
              </Tooltip>
            )}

            <ToggleButtonGroup size="small" value={filterMode} exclusive
              onChange={(_, v) => v && setFilterMode(v)}>
              <ToggleButton value="all" sx={{ px: 1.5 }}>
                全部<Box component="span" sx={{ ml: 0.5, opacity: 0.4, fontSize: '0.65rem' }}>1</Box>
              </ToggleButton>
              <ToggleButton value="pending" sx={{ px: 1.5 }}>
                待审<Box component="span" sx={{ ml: 0.5, opacity: 0.4, fontSize: '0.65rem' }}>2</Box>
              </ToggleButton>
              <ToggleButton value="flagged" sx={{ px: 1.5 }}>
                标记<Box component="span" sx={{ ml: 0.5, opacity: 0.4, fontSize: '0.65rem' }}>3</Box>
              </ToggleButton>
            </ToggleButtonGroup>

            <Button size="small" variant="outlined" onClick={handleApproveAll}>全部批准</Button>
            <Button size="small" variant="contained" startIcon={saving ? <CircularProgress size={16} /> : <SaveIcon />}
              onClick={() => doSave(false)} disabled={saving}>
              {saving ? '保存中...' : '保存'}
              <Box component="span" sx={{ ml: 0.5, opacity: 0.4, fontSize: '0.65rem' }}>^S</Box>
            </Button>
            <Button size="small" variant="outlined" color="secondary"
              onClick={() => { setSessionMeta(null); setCurrentEntryIndex(null); setSelectedIndices(new Set()) }}>
              关闭
            </Button>
          </Card>

          {toast && (
            <Alert severity="info" sx={{ py: 0 }} onClose={() => setToast('')}>
              <Typography variant="caption">{toast}</Typography>
            </Alert>
          )}

          {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}

          {/* Main content */}
          <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
            {/* Table */}
            <TableContainer component={Card} sx={{ flex: 3, minWidth: 550, maxHeight: 'calc(100vh - 280px)' }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    <TableCell padding="checkbox" sx={{ width: 38 }}>
                      <Checkbox
                        size="small"
                        checked={filteredEntries.length > 0 && filteredEntries.every(e => selectedIndices.has(e.index))}
                        indeterminate={filteredEntries.some(e => selectedIndices.has(e.index)) &&
                          !filteredEntries.every(e => selectedIndices.has(e.index))}
                        onChange={selectAllFiltered}
                      />
                    </TableCell>
                    <TableCell sx={{ width: 44 }}>#</TableCell>
                    <TableCell sx={{ width: 100 }}>时间</TableCell>
                    <TableCell sx={{ width: 50 }}>CPS</TableCell>
                    <TableCell>原文</TableCell>
                    <TableCell>译文</TableCell>
                    <TableCell sx={{ width: 46 }} align="center">状态</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {filteredEntries.map(entry => (
                    <SubtitleRowMemo key={entry.index}
                      entry={entry}
                      isCurrent={entry.index === currentEntryIndex}
                      isEditing={entry.index === editingIndex}
                      isSelected={selectedIndices.has(entry.index)}
                      editText={editText}
                      onSeek={seekToEntry}
                      onToggleSelect={toggleSelect}
                      onStartEdit={handleStartEdit}
                      onEditTextChange={setEditText}
                      onCommitEdit={commitEditStable}
                      onCancelEdit={handleCancelEdit}
                      onToggleStatus={handleToggleStatus}
                    />
                  ))}
                </TableBody>
              </Table>
            </TableContainer>

            {/* Video panel */}
            <Box sx={{ flex: 2, minWidth: 280, display: 'flex', flexDirection: 'column', gap: 1 }}>
              <Card sx={{ bgcolor: '#111', borderRadius: 2, minHeight: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
                {sessionMeta.videoPath ? (
                  <video ref={videoRef}
                    src={`/api/files/stream?path=${encodeURIComponent(sessionMeta.videoPath)}`}
                    style={{ width: '100%', maxHeight: 350 }}
                    onTimeUpdate={handleVideoTimeUpdate}
                    onPlay={handleVideoPlay} onPause={handleVideoPause}
                    controls={false} />
                ) : (
                  <Box sx={{ textAlign: 'center', p: 4 }}>
                    <Typography variant="body2" color="text.secondary">未找到关联视频文件</Typography>
                    <Typography variant="caption" color="text.secondary">请确保视频与字幕在同一目录</Typography>
                  </Box>
                )}
              </Card>

              {/* Playback controls */}
              <Card sx={{ p: 1, display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                <Tooltip title="快退 2s (J)">
                  <IconButton size="small" onClick={() => seekRelative(-2)}><SkipPreviousIcon /></IconButton>
                </Tooltip>
                <Tooltip title={isPlaying ? '暂停 (Space/K)' : '播放 (Space)'}>
                  <IconButton size="small" onClick={togglePlay} color="primary">
                    {isPlaying ? <PauseIcon /> : <PlayArrowIcon />}
                  </IconButton>
                </Tooltip>
                <Tooltip title="快进 2s (L)">
                  <IconButton size="small" onClick={() => seekRelative(2)}><SkipNextIcon /></IconButton>
                </Tooltip>

                <Tooltip title={loopCurrent ? '取消循环' : '循环当前段'}>
                  <IconButton size="small" color={loopCurrent ? 'primary' : 'default'}
                    onClick={() => setLoopCurrent(v => !v)}><LoopIcon /></IconButton>
                </Tooltip>

                <Tooltip title={preRollEnabled ? '预卷开 (提前0.5s)' : '预卷关'}>
                  <Chip label={preRollEnabled ? '预卷' : '直切'} size="small"
                    color={preRollEnabled ? 'primary' : 'default'}
                    variant={preRollEnabled ? 'filled' : 'outlined'}
                    onClick={() => setPreRollEnabled(v => !v)}
                    sx={{ height: 24, fontSize: '0.7rem', cursor: 'pointer' }} />
                </Tooltip>

                <Box sx={{ flexGrow: 1 }} />

                <Typography variant="caption" color="text.secondary">速度:</Typography>
                <FormControl size="small" sx={{ minWidth: 70 }}>
                  <Select value={playbackRate} onChange={e => {
                    const v = Number(e.target.value)
                    setPlaybackRate(v)
                    if (videoRef.current) videoRef.current.playbackRate = v
                  }}>
                    <MenuItem value={0.5}>0.5x</MenuItem>
                    <MenuItem value={0.75}>0.75x</MenuItem>
                    <MenuItem value={1}>1x</MenuItem>
                    <MenuItem value={1.25}>1.25x</MenuItem>
                    <MenuItem value={1.5}>1.5x</MenuItem>
                  </Select>
                </FormControl>

                <Button size="small" variant="outlined" onClick={() => goToEntry(-1)} disabled={currentEntryIndex === null}>
                  上一条 <Box component="span" sx={{ ml: 0.3, opacity: 0.4, fontSize: '0.6rem' }}>↑</Box>
                </Button>
                <Button size="small" variant="outlined" onClick={() => goToEntry(1)} disabled={currentEntryIndex === null}>
                  下一条 <Box component="span" sx={{ ml: 0.3, opacity: 0.4, fontSize: '0.6rem' }}>↓</Box>
                </Button>
              </Card>

              {/* Current entry info */}
              {currentEntryIndex !== null && (() => {
                const entry = entries.find(e => e.index === currentEntryIndex)
                if (!entry) return null
                const cps = getCPS(entry)
                const limit = getCPSLimit('zh')
                return (
                  <Card sx={{ p: 1.5 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                      <Chip label={`#${entry.index}`} size="small" color="primary" variant="outlined" />
                      <Typography variant="caption" color="text.secondary">
                        {entry.start} → {entry.end} ({getDuration(entry).toFixed(1)}s)
                      </Typography>
                      <Chip label={`CPS ${cps.toFixed(1)}`} size="small"
                        color={cps > limit ? 'error' : cps > limit * 0.85 ? 'warning' : 'default'}
                        variant="outlined" sx={{ height: 20, fontSize: '0.65rem' }} />
                      {entry.similarity != null && (
                        <Chip label={`相似度 ${(entry.similarity * 100).toFixed(0)}%`} size="small"
                          color={entry.similarity < 0.65 ? 'warning' : 'success'}
                          variant="outlined" sx={{ height: 20, fontSize: '0.65rem' }} />
                      )}
                      <Box sx={{ flexGrow: 1 }} />
                      <Button size="small" variant="text" onClick={() => handleStartEdit(entry)}
                        sx={{ minWidth: 0, fontSize: '0.75rem' }}>编辑 (Enter)</Button>
                    </Box>
                    <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', mt: 0.5 }}>{entry.sourceText}</Typography>
                    <Typography variant="body2" color="primary" sx={{ whiteSpace: 'pre-wrap', mt: 0.5 }}>
                      {entry.translatedText || '(空)'}
                    </Typography>
                    {entry.issues.length > 0 && (
                      <Box sx={{ mt: 0.5 }}>
                        {entry.issues.map((issue, i) => (
                          <Chip key={i} label={issue.message} size="small"
                            color={issue.severity === 'error' ? 'error' : 'warning'}
                            sx={{ mr: 0.5, mb: 0.5, fontSize: '0.7rem' }} />
                        ))}
                      </Box>
                    )}
                  </Card>
                )
              })()}

              {/* Shortcuts reference */}
              <Card sx={{ p: 1 }}>
                <Typography variant="caption" color="text.secondary">
                  <strong>快捷键:</strong> Space 播放 | JKL 快退/暂停/快进 | ↑↓ 导航 | Enter 编辑 | Tab 播放当前段 |
                  Ctrl+Z/Y 撤销/重做 | Ctrl+S 保存 | Ctrl+F 搜索 | [ ] 跳转标记 | 1/2/3 筛选 | Esc 取消
                </Typography>
              </Card>
            </Box>
          </Box>
        </Box>
      )}

      <FilePickerDialog
        open={filePickerOpen}
        onSelect={handleFileSelected}
        onClose={() => setFilePickerOpen(false)}
        initialPath={filePickerInitialPath}
        title={
          filePickerMode === 'source' ? '选择原文字幕文件' :
          filePickerMode === 'translated' ? '选择译文字幕文件' :
          '选择翻译日志文件'
        }
        acceptExtensions={filePickerMode === 'log' ? ['.json'] : SRT_EXTS}
      />
    </>
  )
}
