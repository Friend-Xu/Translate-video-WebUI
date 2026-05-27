import { useState, useCallback } from 'react'
import { Box, Button, TextField, List, ListItemButton, ListItemText, Typography, Popover, Chip, Divider } from '@mui/material'
import FolderOpenIcon from '@mui/icons-material/FolderOpenRounded'
import RefreshIcon from '@mui/icons-material/RefreshRounded'
import { useAppStore } from '../store/useAppStore'
import type { WorkspaceSummary } from '../types'

const RECENT_KEY = 'workspace_recent'

function loadRecent(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function saveRecent(paths: string[]) {
  localStorage.setItem(RECENT_KEY, JSON.stringify(paths.slice(0, 5)))
}

export default function WorkspaceSelector() {
  const loadWorkspace = useAppStore(s => s.loadWorkspace)
  const clearWorkspace = useAppStore(s => s.clearWorkspace)
  const loading = useAppStore(s => s.loading)
  const error = useAppStore(s => s.error)
  const currentWorkspace = useAppStore(s => s.workspace)
  const dataSource = useAppStore(s => s.dataSource)

  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)
  const [workspacePath, setWorkspacePath] = useState(currentWorkspace || '')
  const [recent, setRecent] = useState<string[]>(loadRecent)
  const [discovered, setDiscovered] = useState<WorkspaceSummary[]>([])

  const open = Boolean(anchorEl)

  const handleOpen = useCallback((e: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(e.currentTarget)
    fetch('/api/files/browse?path=source_file')
      .then(r => r.json())
      .then(data => {
        const dirs = (data.dirs || [])
          .filter((d: string) => d.endsWith('_project'))
          .map((d: string) => ({
            path: `source_file/${d}`,
            name: d.replace('_project', ''),
            updatedAt: '',
            runtimeState: 'uninitialized',
            pipelineStatus: '',
            videoPath: '',
          }))
        setDiscovered(dirs)
      })
      .catch(() => {})
  }, [])

  const handleClose = () => setAnchorEl(null)

  const handleLoad = useCallback(async (path: string) => {
    const absPath = path.includes(':') ? path : `D:/Workspace/Translate_video/${path}`
    handleClose()
    await loadWorkspace(absPath)
    const next = [absPath, ...recent.filter(r => r !== absPath)]
    setRecent(next)
    saveRecent(next)
  }, [loadWorkspace, recent])

  const handleClear = useCallback(() => {
    clearWorkspace()
    setWorkspacePath('')
  }, [clearWorkspace])

  return (
    <>
      <Button
        size="small"
        variant={dataSource === 'workspace' ? 'contained' : 'outlined'}
        color="primary"
        startIcon={<FolderOpenIcon fontSize="small" />}
        onClick={handleOpen}
        sx={{ fontSize: '0.7rem', textTransform: 'none', mr: 1 }}
      >
        {dataSource === 'workspace'
          ? (currentWorkspace.split('/').pop() || 'Project')
          : 'Open Project'}
      </Button>

      <Popover
        open={open}
        anchorEl={anchorEl}
        onClose={handleClose}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'left' }}
        slotProps={{ paper: { sx: { width: 420, p: 2, bgcolor: 'background.paper', border: '1px solid', borderColor: 'divider', boxShadow: 24 } } }}
      >
        <Typography variant="subtitle2" sx={{ mb: 1, color: 'text.primary' }}>
          Open Workspace
        </Typography>

        <Box sx={{ display: 'flex', gap: 1, mb: 1.5 }}>
          <TextField
            size="small"
            fullWidth
            placeholder="D:/Workspace/Translate_video/source_file/test_project"
            value={workspacePath}
            onChange={e => setWorkspacePath(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleLoad(workspacePath) }}
            sx={{ '& .MuiInputBase-input': { fontSize: '0.75rem' } }}
          />
          <Button
            size="small"
            variant="contained"
            onClick={() => handleLoad(workspacePath)}
            disabled={loading || !workspacePath}
            sx={{ fontSize: '0.7rem', textTransform: 'none', whiteSpace: 'nowrap' }}
          >
            {loading ? 'Loading...' : 'Load'}
          </Button>
        </Box>

        {error && (
          <Typography variant="caption" color="error.main" sx={{ display: 'block', mb: 1 }}>
            {error}
          </Typography>
        )}

        {dataSource === 'workspace' && (
          <Box sx={{ mb: 1 }}>
            <Chip
              label={`Active: ${currentWorkspace.split('/').pop()}`}
              size="small" color="primary" variant="outlined"
              onDelete={handleClear}
              sx={{ fontSize: '0.65rem' }}
            />
          </Box>
        )}

        {discovered.length > 0 && (
          <>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5, fontWeight: 500 }}>
              Discovered Projects
            </Typography>
            <List dense disablePadding sx={{ mb: 1, maxHeight: 180, overflow: 'auto' }}>
              {discovered.map(d => (
                <ListItemButton key={d.path} onClick={() => handleLoad(d.path)} sx={{ borderRadius: 1, py: 0.25, mb: 0.5, bgcolor: 'background.default', border: '1px solid', borderColor: 'divider', '&:hover': { bgcolor: 'action.hover' } }}>
                  <ListItemText
                    primary={d.name}
                    secondary={d.path}
                    primaryTypographyProps={{ fontSize: '0.75rem' }}
                    secondaryTypographyProps={{ fontSize: '0.6rem' }}
                  />
                </ListItemButton>
              ))}
            </List>
          </>
        )}

        {recent.length > 0 && (
          <>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5, fontWeight: 500 }}>
              Recent
            </Typography>
            <List dense disablePadding sx={{ maxHeight: 140, overflow: 'auto' }}>
              {recent.map(path => (
                <ListItemButton key={path} onClick={() => handleLoad(path)} sx={{ borderRadius: 1, py: 0.25, mb: 0.5, bgcolor: 'background.default', border: '1px solid', borderColor: 'divider', '&:hover': { bgcolor: 'action.hover' } }}>
                  <ListItemText
                    primary={path.split('/').pop()}
                    secondary={path}
                    primaryTypographyProps={{ fontSize: '0.75rem' }}
                    secondaryTypographyProps={{ fontSize: '0.6rem' }}
                  />
                </ListItemButton>
              ))}
            </List>
          </>
        )}

        <Divider sx={{ mt: 0.5, mb: 0.5 }} />
        <Button
          size="small" variant="text" color="inherit"
          startIcon={<RefreshIcon fontSize="small" />}
          onClick={handleOpen}
          sx={{ fontSize: '0.65rem', textTransform: 'none', mt: 0.5 }}
        >
          Refresh
        </Button>
      </Popover>
    </>
  )
}
