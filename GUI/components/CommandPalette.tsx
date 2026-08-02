import { useState, useEffect, useCallback, useMemo } from 'react'
import { Box, TextField, List, ListItem, ListItemButton, ListItemText, Typography, Chip, Paper } from '@mui/material'
import SearchIcon from '@mui/icons-material/SearchRounded'
import { useAppStore } from '../store/useAppStore'
import { MODE_META, ALL_MODES } from '../types/modes'

interface Command {
  id: string
  label: string
  shortcut: string
  category: string
  action: () => void
  /** 快捷键提示条目 — 展示型，不可执行 */
  hint?: boolean
}

export default function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [selectedIdx, setSelectedIdx] = useState(0)

  const mode = useAppStore(s => s.mode)
  const setMode = useAppStore(s => s.setMode)
  const selectEvent = useAppStore(s => s.selectEvent)
  const applyAllDrafts = useAppStore(s => s.applyAllDrafts)
  const discardAllDrafts = useAppStore(s => s.discardAllDrafts)
  const undoLastPatch = useAppStore(s => s.undoLastPatch)

  const commands = useMemo<Command[]>(() => [
    ...ALL_MODES.map(m => ({
      id: `mode-${m}`,
      label: `切换到 ${MODE_META[m].label} 模式`,
      shortcut: '',
      category: '模式切换',
      action: () => setMode(m),
    })),
    ...Object.entries(MODE_META[mode].defaultShortcuts).map(([key, desc]) => ({
      id: `ks-${key}`,
      label: desc,
      shortcut: key,
      category: `${MODE_META[mode].label} 模式`,
      action: () => {},
      hint: true,
    })),
    { id: 'apply-all', label: '应用全部草案', shortcut: 'Ctrl+Enter', category: '补丁', action: applyAllDrafts },
    { id: 'discard-all', label: '放弃全部草案', shortcut: '', category: '补丁', action: discardAllDrafts },
    { id: 'undo-patch', label: '回滚上一个补丁', shortcut: 'Ctrl+Shift+Z', category: '补丁', action: () => { undoLastPatch() } },
    { id: 'deselect', label: '取消选中事件', shortcut: 'Escape', category: '时间轴', action: () => selectEvent(null) },
  ], [mode, setMode, applyAllDrafts, discardAllDrafts, undoLastPatch, selectEvent])

  const filtered = useMemo(() => {
    if (!query.trim()) return commands
    const q = query.toLowerCase()
    return commands.filter(c =>
      c.label.toLowerCase().includes(q) || c.category.toLowerCase().includes(q)
    )
  }, [commands, query])

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setOpen(prev => !prev)
        setQuery('')
        setSelectedIdx(0)
      }
      if (e.key === 'Escape' && open) setOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  const handleSelect = useCallback((cmd: Command) => {
    cmd.action()
    setOpen(false)
    setQuery('')
  }, [])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setSelectedIdx(i => Math.min(i + 1, filtered.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSelectedIdx(i => Math.max(i - 1, 0)) }
    else if (e.key === 'Enter' && filtered[selectedIdx] && !filtered[selectedIdx].hint) { e.preventDefault(); handleSelect(filtered[selectedIdx]) }
    else if (e.key === 'Escape') setOpen(false)
  }, [filtered, selectedIdx, handleSelect])

  if (!open) return null

  return (
    <Box sx={{
      position: 'fixed', inset: 0, zIndex: 9999,
      display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
      pt: '15vh', bgcolor: 'rgba(0,0,0,0.5)',
    }} onClick={() => setOpen(false)}>
      <Paper sx={{
        width: 520, maxHeight: '60vh',
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
      }} onClick={e => e.stopPropagation()}>
        <Box sx={{ p: 1.5, borderBottom: 1, borderColor: 'divider' }}>
          <TextField autoFocus fullWidth size="small" placeholder="搜索命令..."
            value={query} onChange={e => { setQuery(e.target.value); setSelectedIdx(0) }}
            onKeyDown={handleKeyDown}
            InputProps={{ startAdornment: <SearchIcon sx={{ mr: 1, color: 'text.secondary', fontSize: 20 }} /> }}
            sx={{ '& .MuiInputBase-root': { fontSize: '0.85rem' } }} />
        </Box>
        <List dense sx={{ flexGrow: 1, overflow: 'auto', py: 0 }}>
          {filtered.length === 0 ? (
            <Box sx={{ p: 3, textAlign: 'center' }}>
              <Typography variant="body2" color="text.secondary">无匹配命令</Typography>
            </Box>
          ) : filtered.map((cmd, idx) => cmd.hint ? (
            <ListItem key={cmd.id} dense sx={{ py: 0.5, opacity: 0.75 }}>
              <ListItemText primary={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Typography variant="body2" sx={{ fontSize: '0.8rem', color: 'text.secondary' }}>{cmd.label}</Typography>
                  <Chip label={cmd.category} size="small" sx={{ fontSize: '0.6rem', height: 18 }} />
                </Box>
              } />
              {cmd.shortcut && <Chip label={cmd.shortcut} size="small" variant="outlined"
                sx={{ fontSize: '0.6rem', height: 20, fontFamily: 'monospace' }} />}
            </ListItem>
          ) : (
            <ListItemButton key={cmd.id} selected={idx === selectedIdx}
              onClick={() => handleSelect(cmd)} sx={{ py: 1 }}>
              <ListItemText primary={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Typography variant="body2" sx={{ fontSize: '0.8rem' }}>{cmd.label}</Typography>
                  <Chip label={cmd.category} size="small" sx={{ fontSize: '0.6rem', height: 18 }} />
                </Box>
              } />
              {cmd.shortcut && <Chip label={cmd.shortcut} size="small" variant="outlined"
                sx={{ fontSize: '0.6rem', height: 20, fontFamily: 'monospace' }} />}
            </ListItemButton>
          ))}
        </List>
        <Box sx={{ p: 1, borderTop: 1, borderColor: 'divider', display: 'flex', gap: 2 }}>
          <Typography variant="caption" color="text.secondary">↑↓ 导航</Typography>
          <Typography variant="caption" color="text.secondary">Enter 执行</Typography>
          <Typography variant="caption" color="text.secondary">Esc 关闭</Typography>
        </Box>
      </Paper>
    </Box>
  )
}
