import { useState, useEffect, useCallback } from 'react'
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, List, ListItemButton, ListItemIcon, ListItemText,
  Typography, Box, Breadcrumbs,
} from '@mui/material'
import FolderIcon from '@mui/icons-material/FolderRounded'
import InsertDriveFileIcon from '@mui/icons-material/InsertDriveFileRounded'
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpwardRounded'

interface FileEntry {
  name: string
  path: string
  is_dir: boolean
}

interface BrowseResult {
  current: string
  parent: string | null
  entries: FileEntry[]
}

interface FilePickerDialogProps {
  open: boolean
  onSelect: (path: string) => void
  onClose: () => void
  initialPath?: string
}

export function FilePickerDialog({ open, onSelect, onClose, initialPath }: FilePickerDialogProps) {
  const [currentPath, setCurrentPath] = useState('')
  const [entries, setEntries] = useState<FileEntry[]>([])
  const [parentPath, setParentPath] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const browse = useCallback(async (path: string) => {
    setLoading(true)
    try {
      const res = await fetch(`/api/files/browse?path=${encodeURIComponent(path)}`)
      if (!res.ok) throw new Error('浏览失败')
      const data: BrowseResult = await res.json()
      setCurrentPath(data.current)
      setEntries(data.entries.filter(e => e.is_dir || e.name.endsWith('.mp4') || e.name.endsWith('.mkv') || e.name.endsWith('.avi')))
      setParentPath(data.parent)
    } catch {
      setEntries([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) browse(initialPath || '')
  }, [open, browse, initialPath])

  const handleClick = (entry: FileEntry) => {
    if (entry.is_dir) {
      browse(entry.path)
    } else {
      onSelect(entry.path)
    }
  }

  const goUp = () => {
    if (parentPath) browse(parentPath)
  }

  // Build breadcrumb parts
  const pathParts = currentPath ? currentPath.replace(/\\/g, '/').split('/').filter(Boolean) : []

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>选择视频文件</DialogTitle>
      <DialogContent>
        <Box sx={{ mb: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
          <Button size="small" startIcon={<ArrowUpwardIcon />} onClick={goUp} disabled={!parentPath}>
            上级目录
          </Button>
          <Breadcrumbs sx={{ fontSize: '0.8rem', overflow: 'hidden', flex: 1 }}>
            {pathParts.map((part, i) => (
              <Typography key={i} variant="caption" noWrap>{part}</Typography>
            ))}
          </Breadcrumbs>
        </Box>
        <List dense sx={{ maxHeight: 400, overflow: 'auto', bgcolor: 'background.paper', borderRadius: 1, border: '1px solid', borderColor: 'divider' }}>
          {loading ? (
            <Typography sx={{ p: 2, color: 'text.secondary' }}>加载中...</Typography>
          ) : entries.length === 0 ? (
            <Typography sx={{ p: 2, color: 'text.secondary' }}>此目录无可用文件</Typography>
          ) : (
            entries.map(entry => (
              <ListItemButton key={entry.path} onClick={() => handleClick(entry)} dense>
                <ListItemIcon sx={{ minWidth: 32 }}>
                  {entry.is_dir ? <FolderIcon color="primary" /> : <InsertDriveFileIcon color="action" />}
                </ListItemIcon>
                <ListItemText primary={entry.name} primaryTypographyProps={{ noWrap: true, fontSize: '0.875rem' }} />
              </ListItemButton>
            ))
          )}
        </List>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>取消</Button>
      </DialogActions>
    </Dialog>
  )
}
