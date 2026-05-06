import { useState, useEffect, useCallback } from 'react'
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, List, ListItemButton, ListItemIcon, ListItemText, Checkbox,
  Typography, Box, Breadcrumbs,
} from '@mui/material'
import FolderIcon from '@mui/icons-material/FolderRounded'
import InsertDriveFileIcon from '@mui/icons-material/InsertDriveFileRounded'
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpwardRounded'

const VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.avi']

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
  multiple?: boolean
  onSelectMultiple?: (paths: string[], replace?: boolean) => void
  acceptExtensions?: string[]
  title?: string
}

export function FilePickerDialog({ open, onSelect, onClose, initialPath, multiple, onSelectMultiple, acceptExtensions, title }: FilePickerDialogProps) {
  const exts = acceptExtensions || VIDEO_EXTENSIONS
  const [currentPath, setCurrentPath] = useState('')
  const [entries, setEntries] = useState<FileEntry[]>([])
  const [parentPath, setParentPath] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [recursiveVideos, setRecursiveVideos] = useState<FileEntry[]>([])
  const [showingRecursive, setShowingRecursive] = useState(false)

  const browse = useCallback(async (path: string) => {
    setLoading(true)
    try {
      const res = await fetch(`/api/files/browse?path=${encodeURIComponent(path)}`)
      if (!res.ok) throw new Error('浏览失败')
      const data: BrowseResult = await res.json()
      setCurrentPath(data.current)
      setEntries(data.entries.filter(e => e.is_dir || exts.some(ext => e.name.toLowerCase().endsWith(ext))))
      setParentPath(data.parent)
    } catch {
      setEntries([])
    } finally {
      setLoading(false)
    }
  }, [exts])

  const searchRecursive = useCallback(async (path: string) => {
    setLoading(true)
    try {
      const res = await fetch(`/api/files/search-videos?path=${encodeURIComponent(path)}`)
      if (!res.ok) throw new Error('搜索失败')
      const data = await res.json()
      setRecursiveVideos(data.videos || [])
      setShowingRecursive(true)
    } catch {
      setRecursiveVideos([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) {
      setSelected(new Set())
      setRecursiveVideos([])
      setShowingRecursive(false)
      browse(initialPath || '')
    }
  }, [open, browse, initialPath])

  const handleClick = (entry: FileEntry) => {
    if (entry.is_dir) {
      browse(entry.path)
    } else if (multiple) {
      setSelected(prev => {
        const next = new Set(prev)
        if (next.has(entry.path)) next.delete(entry.path)
        else next.add(entry.path)
        return next
      })
    } else {
      onSelect(entry.path)
    }
  }

  const handleSelectDirectory = () => {
    const videoFiles = entries
      .filter(e => !e.is_dir && exts.some(ext => e.name.toLowerCase().endsWith(ext)))
      .map(e => e.path)
    if (videoFiles.length > 0 && onSelectMultiple) {
      onSelectMultiple(videoFiles)
    }
  }

  const handleConfirmMultiple = () => {
    if (onSelectMultiple && selected.size > 0) {
      onSelectMultiple(Array.from(selected))
    }
  }

  const handleSelectAll = () => {
    const videoEntries = entries.filter(e => !e.is_dir && exts.some(ext => e.name.toLowerCase().endsWith(ext)))
    setSelected(new Set(videoEntries.map(e => e.path)))
  }

  const handleDeselectAll = () => {
    setSelected(new Set())
  }

  const goUp = () => {
    if (parentPath) browse(parentPath)
  }

  const pathParts = currentPath ? currentPath.replace(/\\/g, '/').split('/').filter(Boolean) : []
  const videoCount = entries.filter(e => !e.is_dir && exts.some(ext => e.name.toLowerCase().endsWith(ext))).length

  return (
    <Dialog open={open} onClose={onClose} maxWidth={multiple ? 'md' : 'sm'} fullWidth>
      <DialogTitle>{title || (multiple ? '选择视频文件（多选）' : '选择视频文件')}</DialogTitle>
      <DialogContent>
        <Box sx={{ mb: 1, display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
          <Button size="small" startIcon={<ArrowUpwardIcon />} onClick={goUp} disabled={!parentPath}>
            上级目录
          </Button>
          <Breadcrumbs sx={{ fontSize: '0.8rem', overflow: 'hidden', flex: 1 }}>
            {pathParts.map((part, i) => (
              <Typography key={i} variant="caption" noWrap>{part}</Typography>
            ))}
          </Breadcrumbs>
          {multiple && (
            <Box sx={{ display: 'flex', gap: 0.5 }}>
              <Button size="small" variant="outlined" onClick={handleSelectDirectory} title="导入当前目录下所有视频">
                选择此目录 ({videoCount})
              </Button>
              <Button size="small" variant="outlined" color="secondary" onClick={() => searchRecursive(currentPath)} title="递归搜索子文件夹中所有视频">
                搜索子文件夹
              </Button>
              <Button size="small" variant="text" onClick={handleSelectAll}>全选</Button>
              <Button size="small" variant="text" onClick={handleDeselectAll}>取消全选</Button>
            </Box>
          )}
        </Box>
        {!showingRecursive && (
        <List dense sx={{ maxHeight: 400, overflow: 'auto', bgcolor: 'background.paper', borderRadius: 1, border: '1px solid', borderColor: 'divider' }}>
          {loading ? (
            <Typography sx={{ p: 2, color: 'text.secondary' }}>加载中...</Typography>
          ) : entries.length === 0 ? (
            <Typography sx={{ p: 2, color: 'text.secondary' }}>此目录无可用文件</Typography>
          ) : (
            entries.map(entry => {
              const isVideo = !entry.is_dir && exts.some(ext => entry.name.toLowerCase().endsWith(ext))
              const isChecked = selected.has(entry.path)
              return (
                <ListItemButton key={entry.path} onClick={() => handleClick(entry)} dense>
                  {multiple && isVideo && (
                    <Checkbox checked={isChecked} size="small" sx={{ p: 0.5, mr: 1 }} onClick={e => e.stopPropagation()} />
                  )}
                  <ListItemIcon sx={{ minWidth: 32 }}>
                    {entry.is_dir ? <FolderIcon color="primary" /> : <InsertDriveFileIcon color="action" />}
                  </ListItemIcon>
                  <ListItemText primary={entry.name} primaryTypographyProps={{ noWrap: true, fontSize: '0.875rem' }} />
                </ListItemButton>
              )
            })
          )}
        </List>
        )}

        {showingRecursive && (
          <Box sx={{ mt: 2 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <Button size="small" onClick={() => { setShowingRecursive(false); setRecursiveVideos([]) }}>
                返回目录浏览
              </Button>
              <Typography variant="body2" color="text.secondary">
                在子文件夹中找到 {recursiveVideos.length} 个视频
              </Typography>
            </Box>
            <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
              <Button size="small" variant="contained" onClick={() => {
                if (onSelectMultiple) onSelectMultiple(recursiveVideos.map(e => e.path), true)
              }}>
                导入全部搜索结果（{recursiveVideos.length}）
              </Button>
              <Button size="small" variant="text" onClick={() => setSelected(new Set(recursiveVideos.map(e => e.path)))}>
                全选
              </Button>
              <Button size="small" variant="text" onClick={() => setSelected(new Set())}>
                取消全选
              </Button>
            </Box>
            {recursiveVideos.length > 0 ? (
              <List dense sx={{ maxHeight: 300, overflow: 'auto', bgcolor: 'background.paper', borderRadius: 1, border: '1px solid', borderColor: 'divider' }}>
                {recursiveVideos.map(entry => {
                  const isChecked = selected.has(entry.path)
                  return (
                    <ListItemButton key={entry.path} onClick={() => {
                      setSelected(prev => {
                        const next = new Set(prev)
                        if (next.has(entry.path)) next.delete(entry.path)
                        else next.add(entry.path)
                        return next
                      })
                    }} dense>
                      <Checkbox checked={isChecked} size="small" sx={{ p: 0.5, mr: 1 }} onClick={e => e.stopPropagation()} />
                      <ListItemIcon sx={{ minWidth: 32 }}>
                        <InsertDriveFileIcon color="action" />
                      </ListItemIcon>
                      <ListItemText primary={entry.name} secondary={entry.path}
                        primaryTypographyProps={{ noWrap: true, fontSize: '0.875rem' }}
                        secondaryTypographyProps={{ noWrap: true, fontSize: '0.75rem' }} />
                    </ListItemButton>
                  )
                })}
              </List>
            ) : (
              <Typography variant="body2" color="text.secondary">未找到视频文件</Typography>
            )}
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>取消</Button>
        {multiple && selected.size > 0 && (
          <Button variant="contained" onClick={handleConfirmMultiple}>
            确认选择（{selected.size} 个文件）
          </Button>
        )}
      </DialogActions>
    </Dialog>
  )
}
