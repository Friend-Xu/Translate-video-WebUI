import { useState, useCallback, useRef, useEffect } from 'react'
import {
  Box, Typography, Button, TextField, Card, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, Chip, IconButton,
  Tooltip, ToggleButtonGroup, ToggleButton, Alert, CircularProgress,
  Select, MenuItem, FormControl,
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
import { FilePickerDialog } from '../FilePickerDialog'
import { SectionHeader } from '../SectionHeader'
import type { SubtitleEntry, ReviewSession } from '../../types'

const SRT_EXTS = ['.srt', '.vtt']

interface SubtitleReviewProps {
  videoPath: string
  onSuccess: (msg: string) => void
}

export function SubtitleReview({ videoPath, onSuccess }: SubtitleReviewProps) {
  const [session, setSession] = useState<ReviewSession | null>(null)
  const [filterMode, setFilterMode] = useState<'all' | 'pending' | 'flagged'>('all')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editText, setEditText] = useState('')

  // File picker state
  const [filePickerOpen, setFilePickerOpen] = useState(false)
  const [filePickerMode, setFilePickerMode] = useState<'source' | 'translated' | 'log'>('source')
  const [filePickerInitialPath, setFilePickerInitialPath] = useState('')
  const [sourceSrt, setSourceSrt] = useState('')
  const [translatedSrt, setTranslatedSrt] = useState('')
  const [translateLog, setTranslateLog] = useState('')

  // Derive default directory from video path
  const defaultDir = (() => {
    if (!videoPath) return ''
    const d = videoPath.replace(/\\/g, '/')
    return d.substring(0, d.lastIndexOf('/'))
  })()

  // Video state
  const videoRef = useRef<HTMLVideoElement>(null)
  const [currentEntryIndex, setCurrentEntryIndex] = useState<number | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [playbackRate, setPlaybackRate] = useState(1)
  const [loopCurrent, setLoopCurrent] = useState(false)

  // ── Load ──────────────────────────────────────────

  const handleOpenFilePicker = useCallback((mode: 'source' | 'translated' | 'log') => {
    setFilePickerMode(mode)
    if (mode === 'log' && translatedSrt) {
      // Default translate-log to same dir as translated SRT
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
      // Also try to find translated SRT in same directory
      const d = path.replace(/\\/g, '/')
      const dir = d.substring(0, d.lastIndexOf('/'))
      setFilePickerInitialPath(dir)
      // If no translated SRT set, leave empty for user to select
    } else if (filePickerMode === 'translated') {
      setTranslatedSrt(path)
      // Auto-detect translate-log.json in same directory
      const d = path.replace(/\\/g, '/')
      const dir = d.substring(0, d.lastIndexOf('/'))
      // Check common log paths
      const candidates = [
        dir + '/translate-log.json',
        path.replace(/-auto\.srt$/i, '-translate-log.json'),
        path.replace(/\.srt$/i, '-translate-log.json'),
      ]
      for (const c of candidates) {
        if (c !== path && !translateLog) {
          // Mark for auto-detection - will be verified by backend on load
          setTranslateLog(c)
          break
        }
      }
    } else {
      setTranslateLog(path)
    }
    setFilePickerOpen(false)
  }, [filePickerMode, translateLog])

  const handleLoad = useCallback(async () => {
    if (!sourceSrt || !translatedSrt) return
    setLoading(true)
    setError('')
    setSession(null)
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
      if (!res.ok) {
        const d = await res.json()
        throw new Error(d.detail || '加载失败')
      }
      const data = await res.json()
      setSession({
        videoPath: data.videoPath,
        sourceSrtPath: data.sourceSrtPath,
        translatedSrtPath: data.translatedSrtPath,
        entries: data.entries,
        filterMode: 'all',
      })
      setCurrentEntryIndex(null)
      onSuccess(`已加载 ${data.stats.total} 条字幕 (${data.stats.lowSimilarity} 条低质)`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [sourceSrt, translatedSrt, translateLog, onSuccess])

  // ── Save ──────────────────────────────────────────

  const handleSave = useCallback(async () => {
    if (!session || !session.translatedSrtPath) return
    setSaving(true)
    try {
      const res = await fetch('/api/subtitle/review/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          translated_srt: session.translatedSrtPath,
          entries: session.entries,
        }),
      })
      if (!res.ok) {
        const d = await res.json()
        throw new Error(d.detail || '保存失败')
      }
      const data = await res.json()
      onSuccess(`已保存 ${data.updated} 条修改 → ${data.output_path}`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }, [session, onSuccess])

  // ── Edit ──────────────────────────────────────────

  const handleStartEdit = useCallback((entry: SubtitleEntry) => {
    setEditingIndex(entry.index)
    setEditText(entry.translatedText)
  }, [])

  const handleCommitEdit = useCallback(() => {
    if (editingIndex === null || !session) return
    setSession(prev => {
      if (!prev) return prev
      return {
        ...prev,
        entries: prev.entries.map(e =>
          e.index === editingIndex
            ? { ...e, translatedText: editText, reviewStatus: 'modified' as const }
            : e
        ),
      }
    })
    setEditingIndex(null)
  }, [editingIndex, editText, session])

  const handleCancelEdit = useCallback(() => {
    setEditingIndex(null)
  }, [])

  const handleToggleStatus = useCallback((entry: SubtitleEntry) => {
    if (!session) return
    setSession(prev => {
      if (!prev) return prev
      return {
        ...prev,
        entries: prev.entries.map(e =>
          e.index === entry.index
            ? { ...e, reviewStatus: e.reviewStatus === 'approved' ? 'pending' as const : 'approved' as const }
            : e
        ),
      }
    })
  }, [session])

  const handleApproveAll = useCallback(() => {
    if (!session) return
    setSession(prev => {
      if (!prev) return prev
      return {
        ...prev,
        entries: prev.entries.map(e => ({ ...e, reviewStatus: 'approved' as const })),
      }
    })
  }, [session])

  // ── Video ─────────────────────────────────────────

  const seekToEntry = useCallback((entry: SubtitleEntry) => {
    const video = videoRef.current
    if (!video) return
    video.currentTime = entry.startMs / 1000
    setCurrentEntryIndex(entry.index)
    video.play().catch(() => {})
  }, [])

  const handleVideoTimeUpdate = useCallback(() => {
    const video = videoRef.current
    if (!video || !session) return
    const t = video.currentTime * 1000
    const current = session.entries.find(e => t >= e.startMs && t <= e.endMs)
    if (current && current.index !== currentEntryIndex) {
      setCurrentEntryIndex(current.index)
    }
  }, [session, currentEntryIndex])

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
    if (!session || currentEntryIndex === null) return
    const idx = session.entries.findIndex(e => e.index === currentEntryIndex)
    const next = session.entries[idx + offset]
    if (next) seekToEntry(next)
  }, [session, currentEntryIndex, seekToEntry])

  // Loop current segment
  useEffect(() => {
    const video = videoRef.current
    if (!video || !loopCurrent) return
    const onEnded = () => {
      if (loopCurrent && currentEntryIndex !== null && session) {
        const entry = session.entries.find(e => e.index === currentEntryIndex)
        if (entry) {
          video.currentTime = entry.startMs / 1000
          video.play().catch(() => {})
        }
      }
    }
    video.addEventListener('ended', onEnded)
    return () => video.removeEventListener('ended', onEnded)
  }, [loopCurrent, currentEntryIndex, session])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        if (e.key === 'Escape') handleCancelEdit()
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault()
          handleCommitEdit()
        }
        return
      }
      if (e.key === ' ') { e.preventDefault(); togglePlay() }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [togglePlay, handleCommitEdit, handleCancelEdit])

  // ── Filtered entries ──────────────────────────────

  const filteredEntries = session?.entries.filter(e => {
    if (filterMode === 'pending') return e.reviewStatus === 'pending'
    if (filterMode === 'flagged') return e.issues.length > 0
    return true
  }) ?? []

  // ── Stats ─────────────────────────────────────────

  const approvedCount = session?.entries.filter(e => e.reviewStatus === 'approved').length ?? 0
  const modifiedCount = session?.entries.filter(e => e.reviewStatus === 'modified').length ?? 0
  const flaggedCount = session?.entries.filter(e => e.issues.length > 0).length ?? 0
  const totalCount = session?.entries.length ?? 0

  // ── Status chip ───────────────────────────────────

  const statusChip = (entry: SubtitleEntry) => {
    if (entry.issues.some(i => i.severity === 'error')) {
      return (
        <Tooltip title={entry.issues.map(i => i.message).join('\n')}>
          <ErrorIcon color="error" fontSize="small" />
        </Tooltip>
      )
    }
    if (entry.issues.length > 0) {
      return (
        <Tooltip title={entry.issues.map(i => i.message).join('\n')}>
          <WarningAmberIcon sx={{ color: 'warning.main' }} fontSize="small" />
        </Tooltip>
      )
    }
    switch (entry.reviewStatus) {
      case 'approved':
        return <CheckCircleIcon color="success" fontSize="small" />
      case 'modified':
        return <EditIcon color="info" fontSize="small" />
      default:
        return <Chip label="待审" size="small" variant="outlined" sx={{ height: 22, fontSize: '0.7rem' }} />
    }
  }

  // ── File label helper ─────────────────────────────

  const fileLabel = (path: string) => {
    if (!path) return ''
    const i = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'))
    return i >= 0 ? path.slice(i + 1) : path
  }

  // ── Render ────────────────────────────────────────

  return (
    <>
      <SectionHeader title="字幕校准" />

      {/* Load panel */}
      {!session && (
        <Card sx={{ p: 3 }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
            <Typography variant="subtitle2">加载字幕文件</Typography>

            {/* Source SRT */}
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

            {/* Translated SRT */}
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

            {/* Translate log (optional) */}
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
      {session && (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {/* Toolbar */}
          <Card sx={{ p: 1.5, display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
            <Chip label={`共 ${totalCount} 条`} size="small" />
            <Chip label={`已批准 ${approvedCount}`} size="small" color="success" variant="outlined" />
            <Chip label={`已修改 ${modifiedCount}`} size="small" color="info" variant="outlined" />
            {flaggedCount > 0 && (
              <Chip label={`标记 ${flaggedCount}`} size="small" color="warning" variant="outlined" />
            )}
            <Box sx={{ flexGrow: 1 }} />
            <ToggleButtonGroup size="small" value={filterMode} exclusive
              onChange={(_, v) => v && setFilterMode(v)}>
              <ToggleButton value="all">全部</ToggleButton>
              <ToggleButton value="pending">待审</ToggleButton>
              <ToggleButton value="flagged">标记</ToggleButton>
            </ToggleButtonGroup>
            <Button size="small" variant="outlined" onClick={handleApproveAll}>全部批准</Button>
            <Button size="small" variant="contained" startIcon={saving ? <CircularProgress size={16} /> : <SaveIcon />}
              onClick={handleSave} disabled={saving}>
              {saving ? '保存中...' : '保存'}
            </Button>
            <Button size="small" variant="outlined" color="secondary"
              onClick={() => { setSession(null); setCurrentEntryIndex(null) }}>
              关闭
            </Button>
          </Card>

          {/* Main content: table + video */}
          <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
            {/* Subtitle table */}
            <TableContainer component={Card} sx={{ flex: 3, minWidth: 500, maxHeight: 'calc(100vh - 300px)' }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ width: 50 }}>#</TableCell>
                    <TableCell sx={{ width: 110 }}>开始</TableCell>
                    <TableCell sx={{ width: 110 }}>结束</TableCell>
                    <TableCell>原文</TableCell>
                    <TableCell>译文</TableCell>
                    <TableCell sx={{ width: 50 }} align="center">状态</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {filteredEntries.map(entry => {
                    const isCurrent = entry.index === currentEntryIndex
                    const isEditing = entry.index === editingIndex
                    const hasIssues = entry.issues.length > 0
                    return (
                      <TableRow key={entry.index}
                        hover
                        selected={isCurrent}
                        onClick={() => seekToEntry(entry)}
                        sx={{
                          cursor: 'pointer',
                          bgcolor: hasIssues ? 'warning.light' : undefined,
                          '&.Mui-selected': { bgcolor: 'primary.light' },
                        }}>
                        <TableCell>{entry.index}</TableCell>
                        <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{entry.start}</TableCell>
                        <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{entry.end}</TableCell>
                        <TableCell sx={{ whiteSpace: 'pre-wrap', maxWidth: 280, fontSize: '0.85rem' }}>
                          {entry.sourceText}
                        </TableCell>
                        <TableCell
                          sx={{ maxWidth: 280 }}
                          onClick={e => { e.stopPropagation(); handleStartEdit(entry) }}>
                          {isEditing ? (
                            <TextField size="small" fullWidth multiline autoFocus
                              value={editText}
                              onChange={e => setEditText(e.target.value)}
                              onKeyDown={e => {
                                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleCommitEdit() }
                                if (e.key === 'Escape') handleCancelEdit()
                              }}
                              onBlur={handleCommitEdit}
                              sx={{ '& .MuiInputBase-root': { fontSize: '0.85rem' } }} />
                          ) : (
                            <Typography variant="body2" sx={{
                              whiteSpace: 'pre-wrap', fontSize: '0.85rem',
                              color: entry.reviewStatus === 'modified' ? 'info.main' : 'text.primary',
                              cursor: 'text', '&:hover': { bgcolor: 'action.hover' },
                              p: 0.5, borderRadius: 1, minHeight: 24,
                            }}>
                              {entry.translatedText || (
                                <Typography component="span" color="text.secondary" fontStyle="italic">(空)</Typography>
                              )}
                            </Typography>
                          )}
                        </TableCell>
                        <TableCell align="center" onClick={e => { e.stopPropagation(); handleToggleStatus(entry) }}>
                          {statusChip(entry)}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </TableContainer>

            {/* Video preview */}
            <Box sx={{ flex: 2, minWidth: 280, display: 'flex', flexDirection: 'column', gap: 1 }}>
              <Card sx={{ bgcolor: '#111', borderRadius: 2, minHeight: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
                {session.videoPath ? (
                  <video ref={videoRef}
                    src={`/api/files/stream?path=${encodeURIComponent(session.videoPath)}`}
                    style={{ width: '100%', maxHeight: 350 }}
                    onTimeUpdate={handleVideoTimeUpdate}
                    onPlay={handleVideoPlay} onPause={handleVideoPause}
                    controls={false} />
                ) : (
                  <Box sx={{ textAlign: 'center', p: 4 }}>
                    <Typography variant="body2" color="text.secondary">
                      未找到关联视频文件
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      请确保视频与字幕在同一目录
                    </Typography>
                  </Box>
                )}
              </Card>

              {/* Playback controls */}
              <Card sx={{ p: 1, display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                <IconButton size="small" onClick={() => seekRelative(-2)}>
                  <SkipPreviousIcon />
                </IconButton>
                <IconButton size="small" onClick={togglePlay} color="primary">
                  {isPlaying ? <PauseIcon /> : <PlayArrowIcon />}
                </IconButton>
                <IconButton size="small" onClick={() => seekRelative(2)}>
                  <SkipNextIcon />
                </IconButton>
                <Tooltip title="循环当前段">
                  <IconButton size="small" color={loopCurrent ? 'primary' : 'default'}
                    onClick={() => setLoopCurrent(v => !v)}>
                    <LoopIcon />
                  </IconButton>
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
                <Button size="small" variant="outlined" onClick={() => goToEntry(-1)}
                  disabled={currentEntryIndex === null}>上一条</Button>
                <Button size="small" variant="outlined" onClick={() => goToEntry(1)}
                  disabled={currentEntryIndex === null}>下一条</Button>
              </Card>

              {/* Current entry info */}
              {currentEntryIndex !== null && session && (() => {
                const entry = session.entries.find(e => e.index === currentEntryIndex)
                if (!entry) return null
                return (
                  <Card sx={{ p: 1.5 }}>
                    <Typography variant="caption" color="text.secondary">当前: #{entry.index} | {entry.start} → {entry.end}</Typography>
                    <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', mt: 0.5 }}>{entry.sourceText}</Typography>
                    <Typography variant="body2" color="primary" sx={{ whiteSpace: 'pre-wrap', mt: 0.5 }}>
                      {entry.translatedText || '(空)'}
                    </Typography>
                    {entry.issues.length > 0 && (
                      <Box sx={{ mt: 0.5 }}>
                        {entry.issues.map((issue, i) => (
                          <Chip key={i} label={issue.message} size="small"
                            color={issue.severity === 'error' ? 'error' : 'warning'}
                            sx={{ mr: 0.5, mb: 0.5 }} />
                        ))}
                      </Box>
                    )}
                  </Card>
                )
              })()}
            </Box>
          </Box>
        </Box>
      )}

      {/* File picker */}
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
