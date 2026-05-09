import { useState, useEffect, useCallback } from 'react'
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, List, ListItemButton, ListItemIcon, ListItemText, Checkbox,
  Typography, Box, Select, MenuItem, ListSubheader,
} from '@mui/material'
import FolderIcon from '@mui/icons-material/FolderRounded'
import InsertDriveFileIcon from '@mui/icons-material/InsertDriveFileRounded'
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpwardRounded'
import HomeIcon from '@mui/icons-material/HomeRounded'
import DnsIcon from '@mui/icons-material/DnsRounded'
import DesktopWindowsIcon from '@mui/icons-material/DesktopWindowsRounded'
import DownloadIcon from '@mui/icons-material/DownloadRounded'
import VideoLibraryIcon from '@mui/icons-material/VideoLibraryRounded'
import DescriptionIcon from '@mui/icons-material/DescriptionRounded'

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

function isVideo(name: string, exts: string[]) {
  return exts.some(ext => name.toLowerCase().endsWith(ext))
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
  const [drives, setDrives] = useState<Array<{ name: string; path: string }>>([])
  const [quickAccess, setQuickAccess] = useState<Array<{ label: string; path: string }>>([])

  const browse = useCallback(async (path: string) => {
    setLoading(true)
    try {
      const res = await fetch(`/api/files/browse?path=${encodeURIComponent(path)}`)
      if (!res.ok) throw new Error('浏览失败')
      const data: BrowseResult = await res.json()
      setCurrentPath(data.current)
      const dirs = data.entries.filter(e => e.is_dir)
      const vids = data.entries.filter(e => !e.is_dir && isVideo(e.name, exts))
      setEntries([...dirs, ...vids])
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
      fetch('/api/files/drives')
        .then(r => r.ok ? r.json() : Promise.reject())
        .then(d => { setDrives(d.drives || []); setQuickAccess(d.quickAccess || []) })
        .catch(() => { setDrives([]); setQuickAccess([]) })
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
    const videoFiles = entries.filter(e => !e.is_dir && isVideo(e.name, exts)).map(e => e.path)
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
    const videoEntries = entries.filter(e => !e.is_dir && isVideo(e.name, exts))
    setSelected(new Set(videoEntries.map(e => e.path)))
  }

  const handleDeselectAll = () => {
    setSelected(new Set())
  }

  const goUp = () => {
    if (parentPath) browse(parentPath)
  }

  const pathParts = currentPath ? currentPath.replace(/\\/g, '/').split('/').filter(Boolean) : []
  const videoCount = entries.filter(e => !e.is_dir && isVideo(e.name, exts)).length

  const getQaIcon = (label: string) => {
    if (label === '桌面') return <DesktopWindowsIcon />
    if (label === '下载') return <DownloadIcon />
    if (label === '视频') return <VideoLibraryIcon />
    if (label === '文档') return <DescriptionIcon />
    return <FolderIcon />
  }

  const driveRoot = currentPath ? currentPath.slice(0, 3) : ''

  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth>
      <DialogTitle>{title || (multiple ? '选择视频文件（多选）' : '选择视频文件')}</DialogTitle>
      <DialogContent sx={{ p: 2 }}>
        <Box sx={{ display: 'flex', gap: 2, minHeight: 420 }}>
          {/* ---- Sidebar ---- */}
          <Box sx={{
            width: 180, flexShrink: 0,
            borderRight: '1px solid', borderColor: 'divider',
            display: 'flex', flexDirection: 'column', gap: 0.5,
            pr: 1,
          }}>
            <Typography variant="caption" color="text.secondary" sx={{ px: 1, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1 }}>
              快速访问
            </Typography>
            {quickAccess.map(qa => (
              <ListItemButton
                key={qa.path}
                dense
                onClick={() => browse(qa.path)}
                sx={{ borderRadius: 1, gap: 1.5, px: 1 }}
              >
                <Box sx={{ color: 'primary.main', display: 'flex' }}>{getQaIcon(qa.label)}</Box>
                <ListItemText primary={qa.label} primaryTypographyProps={{ fontSize: '0.85rem' }} />
              </ListItemButton>
            ))}
            <Box sx={{ borderTop: '1px solid', borderColor: 'divider', my: 0.5 }} />
            <ListItemButton dense onClick={() => browse(initialPath || 'C:\\')} sx={{ borderRadius: 1, gap: 1.5, px: 1 }}>
              <Box sx={{ color: 'primary.main', display: 'flex' }}><HomeIcon /></Box>
              <ListItemText primary="项目根目录" primaryTypographyProps={{ fontSize: '0.85rem' }} />
            </ListItemButton>
            {drives.map(d => (
              <ListItemButton
                key={d.path}
                dense
                onClick={() => browse(d.path)}
                selected={currentPath.startsWith(d.path)}
                sx={{ borderRadius: 1, gap: 1.5, px: 1 }}
              >
                <Box sx={{ color: 'primary.main', display: 'flex' }}><DnsIcon /></Box>
                <ListItemText primary={d.name} primaryTypographyProps={{ fontSize: '0.85rem', noWrap: true }} />
              </ListItemButton>
            ))}
          </Box>

          {/* ---- Main area ---- */}
          <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
            {/* Navigation bar */}
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
              <Select
                size="small"
                value={driveRoot}
                onChange={e => browse(e.target.value)}
                sx={{ minWidth: 160, fontSize: '0.85rem' }}
              >
                {drives.map(d => (
                  <MenuItem key={d.path} value={d.path} dense>{d.name}</MenuItem>
                ))}
                <ListSubheader>项目</ListSubheader>
                <MenuItem value={initialPath || ''} dense>项目根目录</MenuItem>
              </Select>

              <Button size="small" startIcon={<ArrowUpwardIcon />} onClick={goUp} disabled={!parentPath}>
                上级
              </Button>

              {/* Clickable breadcrumbs */}
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.25, flex: 1, overflow: 'hidden', flexWrap: 'wrap' }}>
                {pathParts.map((part, i) => {
                  const fullPath = i === 0
                    ? `${part}/`
                    : currentPath.split(/[/\\]/).slice(0, i + 1).join('\\')
                  return (
                    <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: 0.25 }}>
                      {i > 0 && <Typography color="text.disabled" sx={{ fontSize: '0.75rem', mx: 0.25 }}>/</Typography>}
                      <Typography
                        onClick={() => browse(fullPath)}
                        sx={{
                          fontSize: '0.8rem', cursor: 'pointer',
                          color: i === pathParts.length - 1 ? 'text.primary' : 'primary.main',
                          fontWeight: i === pathParts.length - 1 ? 600 : 400,
                          '&:hover': { textDecoration: 'underline', color: 'primary.light' },
                          maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }}
                        title={fullPath}
                      >
                        {part}
                      </Typography>
                    </Box>
                  )
                })}
              </Box>

              {multiple && (
                <Box sx={{ display: 'flex', gap: 0.5, ml: 'auto' }}>
                  <Button size="small" variant="outlined" onClick={handleSelectDirectory}>
                    此目录 ({videoCount})
                  </Button>
                  <Button size="small" variant="outlined" color="secondary" onClick={() => searchRecursive(currentPath)}>
                    搜索子文件夹
                  </Button>
                  <Button size="small" variant="text" onClick={handleSelectAll}>全选</Button>
                  <Button size="small" variant="text" onClick={handleDeselectAll}>取消全选</Button>
                </Box>
              )}
            </Box>

            {/* File list */}
            {!showingRecursive && (
              <List sx={{
                flex: 1, maxHeight: 450, overflow: 'auto',
                bgcolor: 'background.paper', borderRadius: 1,
                border: '1px solid', borderColor: 'divider',
              }}>
                {loading ? (
                  <Typography sx={{ p: 3, color: 'text.secondary', textAlign: 'center' }}>加载中...</Typography>
                ) : entries.length === 0 ? (
                  <Typography sx={{ p: 3, color: 'text.secondary', textAlign: 'center' }}>此目录无可用文件</Typography>
                ) : (
                  entries.map(entry => {
                    const isVideoFile = !entry.is_dir && isVideo(entry.name, exts)
                    const isChecked = selected.has(entry.path)
                    return (
                      <ListItemButton key={entry.path} onClick={() => handleClick(entry)} sx={{ py: 1 }}>
                        {multiple && isVideoFile && (
                          <Checkbox checked={isChecked} size="small" sx={{ p: 0.5, mr: 1.5 }} onClick={e => e.stopPropagation()} />
                        )}
                        <ListItemIcon sx={{ minWidth: 40 }}>
                          {entry.is_dir ? (
                            <FolderIcon sx={{ color: 'primary.main', fontSize: 32 }} />
                          ) : (
                            <InsertDriveFileIcon sx={{ color: isVideoFile ? 'success.main' : 'text.disabled', fontSize: 32 }} />
                          )}
                        </ListItemIcon>
                        <ListItemText
                          primary={entry.name}
                          primaryTypographyProps={{ noWrap: true, fontSize: '0.95rem' }}
                        />
                      </ListItemButton>
                    )
                  })
                )}
              </List>
            )}

            {/* Recursive search results */}
            {showingRecursive && (
              <Box sx={{ mt: 1 }}>
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
                  <List dense sx={{ maxHeight: 350, overflow: 'auto', bgcolor: 'background.paper', borderRadius: 1, border: '1px solid', borderColor: 'divider' }}>
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
          </Box>
        </Box>
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
