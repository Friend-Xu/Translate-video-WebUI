import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Box, Typography, Button, TextField, IconButton,
  Switch, List, ListItem, ListItemText,
  Divider, CircularProgress, Dialog, DialogTitle, DialogContent, DialogActions,
} from '@mui/material'
import AddIcon from '@mui/icons-material/AddRounded'
import DeleteIcon from '@mui/icons-material/DeleteRounded'
import SearchIcon from '@mui/icons-material/SearchRounded'
import { useAppStore } from '../store/useAppStore'

interface DictInfo { name: string; description: string; termCount: number }
interface TermItem { key: string; value: string }

const PAGE_SIZE = 200

export default function GlossaryManager() {
  const setMode = useAppStore(s => s.setMode)
  const scrollRef = useRef<HTMLDivElement>(null)

  const [dicts, setDicts] = useState<DictInfo[]>([])
  const [selectedDict, setSelectedDict] = useState<string>('')
  const [items, setItems] = useState<TermItem[]>([])
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState('')
  const [searchDebounced, setSearchDebounced] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [pendingChanges, setPendingChanges] = useState<Record<string, string | null>>({})

  const [newTermKey, setNewTermKey] = useState('')
  const [newTermVal, setNewTermVal] = useState('')
  const [activeDicts, setActiveDicts] = useState<string[]>([])
  const [newDictOpen, setNewDictOpen] = useState(false)
  const [newDictName, setNewDictName] = useState('')
  const [newDictDesc, setNewDictDesc] = useState('')
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)

  // 搜索防抖 300ms
  const searchTimer = useRef<any>(null)
  useEffect(() => {
    clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => setSearchDebounced(search), 300)
    return () => clearTimeout(searchTimer.current)
  }, [search])

  const loadDicts = useCallback(async () => {
    try {
      const res = await fetch('/api/glossary/dicts')
      if (res.ok) setDicts((await res.json()).dicts || [])
    } catch {}
  }, [])

  const loadActive = useCallback(async () => {
    try {
      const res = await fetch('/api/config')
      if (res.ok) {
        const cfg = (await res.json()).config || {}
        const files = (cfg.glossary_files || 'minecraft.json').split(',').map((s: string) => s.trim()).filter(Boolean)
        setActiveDicts(files)
      }
    } catch {}
  }, [])

  useEffect(() => { loadDicts(); loadActive() }, [loadDicts, loadActive])

  // 加载术语页 — 分页请求，不加载全量
  const loadPage = useCallback(async (name: string, q: string, offset: number, append: boolean) => {
    const isFirst = !append
    if (isFirst) setLoading(true); else setLoadingMore(true)
    try {
      const params = new URLSearchParams({ q, offset: String(offset), limit: String(PAGE_SIZE) })
      const res = await fetch(`/api/glossary/dict/${name}/terms?${params}`)
      if (res.ok) {
        const data = await res.json()
        setTotal(data.total)
        setItems(prev => append ? [...prev, ...data.items] : data.items)
      }
    } catch {} finally {
      setLoading(false)
      setLoadingMore(false)
    }
  }, [])

  // 切换术语表 → 重置并加载第一页
  useEffect(() => {
    if (!selectedDict) return
    setItems([]); setTotal(0); setSearch(''); setSearchDebounced('')
    setPendingChanges({}); setDirty(false)
    loadPage(selectedDict, '', 0, false)
  }, [selectedDict, loadPage])

  // 搜索变化 → 重新加载第一页
  useEffect(() => {
    if (!selectedDict) return
    loadPage(selectedDict, searchDebounced, 0, false)
  }, [searchDebounced]) // eslint-disable-line

  // 滚动到底部时自动加载更多
  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 200
        && items.length < total && !loadingMore) {
      loadPage(selectedDict, searchDebounced, items.length, true)
    }
  }

  const toggleActive = (file: string) => {
    setActiveDicts(prev => {
      const next = prev.includes(file) ? prev.filter(f => f !== file) : [...prev, file]
      fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config: { glossary_files: next.join(',') } }),
      }).catch(() => {})
      return next
    })
  }

  // 保存 = 把 pendingChanges 批量 POST 到后端
  const handleSave = async () => {
    const changes = { ...pendingChanges }
    if (Object.keys(changes).length === 0) return
    // 获取当前全量 terms（用空搜索 + 大 limit 加载全量来保存，或逐个 apply）
    // 最简方案: POST 全量到 /api/glossary/dict/{name} 需要先获取原始 terms
    const res = await fetch(`/api/glossary/dict/${selectedDict}`)
    if (!res.ok) return
    const full = await res.json()
    const terms = { ...full.terms }
    for (const [k, v] of Object.entries(changes)) {
      if (v === null) delete terms[k]
      else terms[k] = v
    }
    await fetch(`/api/glossary/dict/${selectedDict}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description: full.description, terms }),
    })
    setPendingChanges({})
    setDirty(false)
    loadDicts()
  }

  const addTerm = () => {
    if (!newTermKey.trim() || !newTermVal.trim()) return
    setPendingChanges(prev => ({ ...prev, [newTermKey.trim()]: newTermVal.trim() }))
    // 乐观更新: 插到列表顶部
    setItems(prev => [{ key: newTermKey.trim(), value: newTermVal.trim() }, ...prev])
    setTotal(prev => prev + 1)
    setNewTermKey(''); setNewTermVal(''); setDirty(true)
  }

  const updateTerm = (key: string, value: string) => {
    setPendingChanges(prev => ({ ...prev, [key]: value }))
    setItems(prev => prev.map(it => it.key === key ? { ...it, value } : it))
    setDirty(true)
  }

  const deleteTerm = (key: string) => {
    setPendingChanges(prev => ({ ...prev, [key]: null }))
    setItems(prev => prev.filter(it => it.key !== key))
    setTotal(prev => prev - 1)
    setDirty(true)
  }

  const createDict = async () => {
    if (!newDictName.trim()) return
    await fetch(`/api/glossary/dict/${newDictName.trim()}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description: newDictDesc.trim(), terms: {} }),
    })
    setNewDictOpen(false); setNewDictName(''); setNewDictDesc('')
    await loadDicts()
    setSelectedDict(newDictName.trim())
  }

  const doDeleteDict = async () => {
    if (!deleteConfirm) return
    await fetch(`/api/glossary/dict/${deleteConfirm}`, { method: 'DELETE' })
    if (selectedDict === deleteConfirm) { setSelectedDict(''); setItems([]) }
    setDeleteConfirm(null)
    await loadDicts()
  }

  // ── 普通滚动 + 无限加载（每页 200 条，无需虚拟化）──

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', bgcolor: '#f8fafc' }}>
      {/* Header */}
      <Box sx={{
        px: 3, py: 2, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        borderBottom: '1px solid', borderColor: 'divider', bgcolor: 'background.paper',
      }}>
        <Box>
          <Typography variant="h6" fontWeight={600}>术语表</Typography>
          <Typography variant="caption" color="text.secondary">编辑、新建术语表，勾选启用的表会注入到翻译 Prompt</Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button variant="outlined" size="small" onClick={() => setMode('hub')}>返回</Button>
          <Button variant="contained" size="small" startIcon={<AddIcon />} onClick={() => setNewDictOpen(true)}>
            新建术语表
          </Button>
        </Box>
      </Box>

      {/* Body */}
      <Box sx={{ flex: 1, display: 'flex', overflow: 'hidden', maxWidth: 1360, mx: 'auto', width: '100%' }}>
        {/* Left: dict list */}
        <Box sx={{ width: 220, flexShrink: 0, borderRight: 1, borderColor: 'divider', p: 2, overflow: 'auto' }}>
          <Typography variant="caption" color="text.secondary" fontWeight={600} gutterBottom>
            术语表 ({dicts.length})
          </Typography>
          <List dense>
            {dicts.map(d => (
              <ListItem key={d.name} disablePadding sx={{ mb: 0.5 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', width: '100%' }}>
                  <Switch size="small"
                    checked={activeDicts.includes(`${d.name}.json`)}
                    onChange={() => toggleActive(`${d.name}.json`)} />
                  <ListItemText
                    primary={<Typography variant="body2" fontWeight={selectedDict === d.name ? 600 : 400}>{d.name}</Typography>}
                    secondary={`${d.termCount} 条`}
                    onClick={() => setSelectedDict(d.name)}
                    sx={{ cursor: 'pointer',
                      bgcolor: selectedDict === d.name ? 'action.selected' : undefined,
                      borderRadius: 1, px: 1, py: 0.5, ml: 0.5,
                    }}
                  />
                </Box>
              </ListItem>
            ))}
          </List>
        </Box>

        {/* Right: term editor */}
        <Box sx={{ flex: 1, p: 3, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          {!selectedDict ? (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 8, textAlign: 'center' }}>
              选择左侧术语表开始编辑，或点击"新建术语表"创建
            </Typography>
          ) : loading ? (
            <CircularProgress size={24} sx={{ mt: 8, display: 'block', mx: 'auto' }} />
          ) : (
            <>
              {/* Toolbar */}
              <Box sx={{ display: 'flex', gap: 1, mb: 2, alignItems: 'center', flexShrink: 0 }}>
                <Typography variant="subtitle2" sx={{ flexShrink: 0 }}>{selectedDict}</Typography>
                <Typography variant="caption" color="text.secondary">{total} 条</Typography>
                {dirty && (
                  <Button variant="contained" size="small" onClick={handleSave} sx={{ ml: 'auto' }}>保存</Button>
                )}
                <IconButton size="small" color="error" onClick={() => setDeleteConfirm(selectedDict)}
                  title="删除术语表" sx={{ flexShrink: 0 }}>
                  <DeleteIcon fontSize="small" />
                </IconButton>
              </Box>

              <Box sx={{ display: 'flex', gap: 1, mb: 2, flexShrink: 0 }}>
                <TextField fullWidth size="small" placeholder="搜索词条...（后端检索）"
                  value={search} onChange={e => setSearch(e.target.value)}
                  InputProps={{ startAdornment: <SearchIcon sx={{ mr: 1, color: 'text.disabled', fontSize: 18 }} /> }} />
                <TextField size="small" placeholder="原文" value={newTermKey}
                  onChange={e => setNewTermKey(e.target.value)} sx={{ width: 160, flexShrink: 0 }}
                  onKeyDown={e => e.key === 'Enter' && addTerm()} />
                <TextField size="small" placeholder="译文" value={newTermVal}
                  onChange={e => setNewTermVal(e.target.value)} sx={{ width: 160, flexShrink: 0 }}
                  onKeyDown={e => e.key === 'Enter' && addTerm()} />
                <Button size="small" variant="outlined" startIcon={<AddIcon />}
                  onClick={addTerm} disabled={!newTermKey.trim() || !newTermVal.trim()} sx={{ flexShrink: 0 }}>
                  新增
                </Button>
              </Box>

              <Divider sx={{ mb: 1, flexShrink: 0 }} />

              {/* 词条列表 + 无限加载 */}
              <Box ref={scrollRef} onScroll={handleScroll}
                sx={{ flex: 1, overflow: 'auto' }}
              >
                {items.map(it => (
                  <Box key={it.key} sx={{
                    display: 'flex', alignItems: 'center', py: 0.25,
                    '&:hover': { bgcolor: 'action.hover' }, borderRadius: 1, px: 1,
                  }}>
                      <Typography variant="body2" sx={{ width: '30%', fontFamily: 'monospace', fontSize: '0.8rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {it.key}
                      </Typography>
                      <Typography variant="body2" sx={{ color: 'text.secondary', mx: 1, flexShrink: 0 }}>→</Typography>
                      <TextField variant="standard" size="small" value={it.value}
                        onChange={e => updateTerm(it.key, e.target.value)}
                        sx={{ flex: 1, '& input': { fontSize: '0.8rem' } }} />
                      <IconButton size="small" onClick={() => deleteTerm(it.key)} sx={{ ml: 0.5, flexShrink: 0 }}>
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Box>
                  ))}
                {loadingMore && (
                  <Box sx={{ textAlign: 'center', py: 1 }}>
                    <CircularProgress size={16} />
                  </Box>
                )}
              </Box>
            </>
          )}
        </Box>
      </Box>

      {/* New dict dialog */}
      <Dialog open={newDictOpen} onClose={() => setNewDictOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>新建术语表</DialogTitle>
        <DialogContent>
          <TextField fullWidth size="small" label="名称（不含扩展名）"
            value={newDictName} onChange={e => setNewDictName(e.target.value)}
            sx={{ mb: 2, mt: 1 }} />
          <TextField fullWidth size="small" label="描述"
            value={newDictDesc} onChange={e => setNewDictDesc(e.target.value)} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setNewDictOpen(false)}>取消</Button>
          <Button variant="contained" onClick={createDict} disabled={!newDictName.trim()}>创建</Button>
        </DialogActions>
      </Dialog>

      {/* Delete confirm */}
      <Dialog open={!!deleteConfirm} onClose={() => setDeleteConfirm(null)} maxWidth="xs" fullWidth>
        <DialogTitle>删除术语表</DialogTitle>
        <DialogContent>
          <Typography>确定要删除 <strong>{deleteConfirm}</strong> 吗？此操作不可恢复。</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteConfirm(null)}>取消</Button>
          <Button variant="contained" color="error" onClick={doDeleteDict}>删除</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
