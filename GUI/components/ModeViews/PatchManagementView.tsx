import { useMemo, useState, useCallback, useEffect } from 'react'
import {
  Box, Typography, Chip, IconButton, Tooltip, Button, Divider,
  ToggleButtonGroup, ToggleButton, Dialog, DialogTitle, DialogContent, DialogActions,
} from '@mui/material'
import MergeIcon from '@mui/icons-material/MergeRounded'
import OpenInNewIcon from '@mui/icons-material/OpenInNewRounded'
import LockIcon from '@mui/icons-material/LockRounded'
import LockOpenIcon from '@mui/icons-material/LockOpenRounded'
import CheckIcon from '@mui/icons-material/CheckRounded'
import CloseIcon from '@mui/icons-material/CloseRounded'
import UndoIcon from '@mui/icons-material/UndoRounded'
import AccountTreeIcon from '@mui/icons-material/AccountTreeRounded'
import WarningIcon from '@mui/icons-material/WarningRounded'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHighRounded'
import { useAppStore } from '../../store/useAppStore'
import type { EventViewModel } from '../../types'
import type { PatchViewItem, PatchStatus, PatchRiskLevel } from '../../types/modes'

const OPCODE_LABELS: Record<string, string> = {
  SET_TRANSLATION: '翻译修改',
  RETAG_SPEAKER: '说话人重映射',
  RENAME_SPEAKER: '说话人重命名',
  MERGE_SPEAKERS: '合并说话人',
  SPLIT_EVENT: '拆分事件',
  MERGE_PREV: '合并上文',
  MERGE_NEXT: '合并下文',
  MOVE_EVENT: '时间偏移',
  TRIM_START: '裁剪开头',
  TRIM_END: '裁剪结尾',
  LOCK_EVENT: '锁定事件',
  RETRIGGER: '局部重算',
  AI_SUGGEST: 'AI 建议',
  APPLY_AI_SUGGESTION: '应用AI建议',
}

const RISK_COLORS: Record<PatchRiskLevel, string> = { low: '#4CAF50', medium: '#FF9800', high: '#F44336' }
const STATUS_COLORS: Record<PatchStatus, 'default' | 'primary' | 'success' | 'warning' | 'error'> = {
  draft: 'default', pending_review: 'warning', ready: 'primary', applied: 'success',
  rolled_back: 'default', failed: 'error', conflict: 'error',
}

interface Props {
  events: EventViewModel[]
}

function computeRiskLevel(item: PatchViewItem): PatchRiskLevel {
  let score = 0
  if (item.affectedEventCount > 3) score++
  if (['MOVE_EVENT', 'TRIM_START', 'TRIM_END', 'SPLIT_EVENT'].includes(item.opcode)) score++
  if (item.conflicts.length > 0) score += 2
  if (item.type === 'ai_suggestion') score++
  return score >= 3 ? 'high' : score >= 1 ? 'medium' : 'low'
}

function detectConflicts(item: PatchViewItem, all: PatchViewItem[]): string[] {
  const targetSet = new Set(item.targets)
  return all.filter(p => p.id !== item.id && p.targets.some(t => targetSet.has(t))).map(p => p.id)
}

export default function PatchManagementView({ events }: Props) {
  const pendingDrafts = useAppStore(s => s.pendingDrafts)
  const appliedPatches = useAppStore(s => s.appliedPatches)
  const addDraft = useAppStore(s => s.addDraft)
  const applyDraft = useAppStore(s => s.applyDraft)
  const discardDraft = useAppStore(s => s.discardDraft)
  const applyAllDrafts = useAppStore(s => s.applyAllDrafts)
  const discardAllDrafts = useAppStore(s => s.discardAllDrafts)
  const undoLastPatch = useAppStore(s => s.undoLastPatch)
  const fetchPatchLog = useAppStore(s => s.fetchPatchLog)
  const navigateToEvent = useAppStore(s => s.navigateToEvent)

  useEffect(() => { fetchPatchLog() }, [fetchPatchLog])

  const [selectedPatchId, setSelectedPatchId] = useState<string | null>(null)
  const [selectedPatchIds, setSelectedPatchIds] = useState<Set<string>>(new Set())
  const [lockedIds, setLockedIds] = useState<Set<string>>(new Set())
  const [statusFilter, setStatusFilter] = useState<'all' | 'draft' | 'applied' | 'ai_suggestion'>('all')
  const [mergeDialogOpen, setMergeDialogOpen] = useState(false)

  // Unify all patches into PatchViewItem[]
  const allPatchItems = useMemo<PatchViewItem[]>(() => {
    const items: PatchViewItem[] = []

    for (const [eventId, draft] of pendingDrafts) {
      const evt = events.find(e => e.id === eventId)
      items.push({
        id: `draft_${eventId}`,
        type: 'draft',
        opcode: draft.opcode,
        targets: [draft.eventId],
        status: 'draft',
        riskLevel: 'low',
        author: 'user',
        timestamp: draft.timestamp,
        before: draft.before,
        after: draft.after,
        affectedEventCount: evt ? 1 : 0,
        conflicts: [],
        isLocked: lockedIds.has(`draft_${eventId}`),
      })
    }

    for (const p of appliedPatches) {
      const affectedCount = events.filter(e => p.targets.includes(e.id)).length
      items.push({
        id: p.patch_id,
        type: 'applied',
        opcode: p.opcode,
        targets: p.targets,
        status: 'applied',
        riskLevel: 'low',
        author: p.author,
        timestamp: p.timestamp,
        before: {},
        after: p.payload,
        affectedEventCount: affectedCount,
        conflicts: [],
        isLocked: lockedIds.has(p.patch_id),
      })
    }

    // Also add events with AI suggestions as ai_suggestion patches
    for (const evt of events) {
      if (evt.visualState.hasAiSuggestion) {
        items.push({
          id: `ai_${evt.id}`,
          type: 'ai_suggestion',
          opcode: 'AI_SUGGEST',
          targets: [evt.id],
          status: 'pending_review',
          riskLevel: 'medium',
          author: 'AI',
          timestamp: Date.now(),
          before: { translation: evt.translation },
          after: {},
          affectedEventCount: 1,
          conflicts: [],
          isLocked: lockedIds.has(`ai_${evt.id}`),
        })
      }
    }

    // Compute conflicts + risk levels
    for (const item of items) {
      item.conflicts = detectConflicts(item, items)
      item.riskLevel = computeRiskLevel(item)
    }

    return items
  }, [pendingDrafts, appliedPatches, events, lockedIds])

  // Filter
  const filteredItems = useMemo(() => {
    if (statusFilter === 'all') return allPatchItems
    return allPatchItems.filter(p => p.type === statusFilter)
  }, [allPatchItems, statusFilter])

  const selectedItem = filteredItems.find(p => p.id === selectedPatchId) || null

  const handleSelect = useCallback((id: string, e: React.MouseEvent) => {
    if (e.ctrlKey || e.metaKey) {
      setSelectedPatchIds(prev => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next })
    } else {
      setSelectedPatchId(id)
      setSelectedPatchIds(new Set([id]))
    }
  }, [])

  const handleApply = useCallback(async (item: PatchViewItem) => {
    if (item.type === 'draft') {
      const eventId = item.targets[0]
      if (eventId) await applyDraft(eventId)
    } else if (item.type === 'ai_suggestion') {
      const eventId = item.targets[0]
      if (eventId) {
        // 应用 AI 建议: 从 pendingDrafts 拿最新 suggestion (此前写旧译文 + 不提交 = 点了不生效)
        const aiDraft = Array.from(pendingDrafts.values())
          .find(d => d.eventId === eventId && d.opcode === 'AI_SUGGEST')
        const suggestion = (aiDraft?.payload as any)?.suggestion || ''
        addDraft({
          eventId, opcode: 'APPLY_AI_SUGGESTION',
          payload: { translation: suggestion },
          before: item.before || {}, after: { translation: suggestion },
          timestamp: Date.now(),
        })
        await applyDraft(eventId)
      }
    }
  }, [applyDraft, addDraft, pendingDrafts])

  const handleUndo = useCallback(() => undoLastPatch(), [undoLastPatch])
  const handleToggleLock = useCallback((id: string) => {
    setLockedIds(prev => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next })
  }, [])

  const handleMerge = useCallback(async () => {
    const targets = Array.from(selectedPatchIds)
    if (targets.length < 2) return
    const selected = allPatchItems.filter(p => targets.includes(p.id))
    // 合并补丁是坏设计 (生成的 MERGED_PATCH draft 无真实写入内容) —
    // 改为批量应用选中的 draft/AI 建议, 已入库的 applied 跳过
    for (const item of selected) {
      const eventId = item.targets[0]
      if (!eventId) continue
      if (item.type === 'draft') {
        await applyDraft(eventId)
      } else if (item.type === 'ai_suggestion') {
        const aiDraft = Array.from(pendingDrafts.values())
          .find(d => d.eventId === eventId && d.opcode === 'AI_SUGGEST')
        const suggestion = (aiDraft?.payload as any)?.suggestion || ''
        addDraft({
          eventId, opcode: 'APPLY_AI_SUGGESTION',
          payload: { translation: suggestion },
          before: item.before || {}, after: { translation: suggestion },
          timestamp: Date.now(),
        })
        await applyDraft(eventId)
      }
    }
    setMergeDialogOpen(false)
    setSelectedPatchIds(new Set())
  }, [selectedPatchIds, allPatchItems, applyDraft, addDraft, pendingDrafts])

  // Dependency tree for selected item
  const depTree = useMemo(() => {
    if (!selectedItem) return null
    const related = allPatchItems.filter(p =>
      p.id !== selectedItem.id && p.targets.some(t => selectedItem.targets.includes(t))
    )
    const affectedEvents = events.filter(e => selectedItem.targets.includes(e.id))
    return { selected: selectedItem, related, conflicts: selectedItem.conflicts, affectedEvents }
  }, [selectedItem, allPatchItems, events])

  const opcodeLabel = (opcode: string) => OPCODE_LABELS[opcode] || opcode

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <Box sx={{ p: 1.5, borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper', display: 'flex', alignItems: 'center', gap: 2 }}>
        <Box>
          <Typography variant="subtitle2">补丁管理</Typography>
          <Typography variant="caption" color="text.secondary">
            {pendingDrafts.size} 草案 · {appliedPatches.length} 已应用 · {allPatchItems.filter(p => p.type === 'ai_suggestion').length} AI 建议
          </Typography>
        </Box>
        <Box sx={{ flexGrow: 1 }} />
        <ToggleButtonGroup size="small" value={statusFilter} exclusive
          onChange={(_, v) => v && setStatusFilter(v)}>
          <ToggleButton value="all" sx={{ px: 1, py: 0, fontSize: '0.65rem' }}>全部</ToggleButton>
          <ToggleButton value="draft" sx={{ px: 1, py: 0, fontSize: '0.65rem' }}>草案</ToggleButton>
          <ToggleButton value="applied" sx={{ px: 1, py: 0, fontSize: '0.65rem' }}>已应用</ToggleButton>
          <ToggleButton value="ai_suggestion" sx={{ px: 1, py: 0, fontSize: '0.65rem' }}>AI</ToggleButton>
        </ToggleButtonGroup>
        {selectedPatchIds.size >= 2 && (
          <Button size="small" variant="outlined" startIcon={<MergeIcon />}
            onClick={() => setMergeDialogOpen(true)} sx={{ fontSize: '0.7rem' }}>
            合并 ({selectedPatchIds.size})
          </Button>
        )}
        {pendingDrafts.size > 0 && (
          <>
            <Button size="small" variant="contained" color="success" startIcon={<CheckIcon />}
              onClick={() => applyAllDrafts()} sx={{ fontSize: '0.7rem' }}>
              全部应用
            </Button>
            <Button size="small" variant="outlined" color="inherit" startIcon={<CloseIcon />}
              onClick={() => discardAllDrafts()} sx={{ fontSize: '0.7rem' }}>
              全部放弃
            </Button>
          </>
        )}
        {appliedPatches.length > 0 && (
          <Button size="small" variant="outlined" color="warning" startIcon={<UndoIcon />}
            onClick={handleUndo} sx={{ fontSize: '0.7rem' }}>
            回滚最近
          </Button>
        )}
      </Box>

      <Box sx={{ flexGrow: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Left: Patch List */}
        <Box sx={{
          width: 280, minWidth: 280, borderRight: 1, borderColor: 'divider',
          overflow: 'hidden auto', bgcolor: 'rgba(0,0,0,0.2)',
        }}>
          {filteredItems.length === 0 ? (
            <Box sx={{ p: 3, textAlign: 'center' }}>
              <Typography variant="body2" color="text.secondary">暂无补丁</Typography>
              <Typography variant="caption" color="text.disabled">
                在 Timeline Studio 中编辑事件或应用 AI 建议来生成补丁
              </Typography>
            </Box>
          ) : (
            filteredItems.map(item => {
              const isSelected = selectedPatchId === item.id
              const isMulti = selectedPatchIds.has(item.id)
              return (
                <Box
                  key={item.id}
                  onClick={(e) => handleSelect(item.id, e)}
                  sx={{
                    p: 1.25, cursor: 'pointer', mb: 0.5, mx: 0.5, borderRadius: 1.5,
                    border: '1px solid', borderColor: 'divider',
                    bgcolor: isSelected ? 'action.selected' : isMulti ? 'action.hover' : 'background.paper',
                    opacity: item.isLocked ? 0.65 : 1,
                    '&:hover': { bgcolor: 'action.hover', borderColor: 'primary.light' },
                  }}
                >
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5 }}>
                    <Box sx={{ width: 3, height: 3, borderRadius: '50%', bgcolor: RISK_COLORS[item.riskLevel], flexShrink: 0 }} />
                    <Chip label={opcodeLabel(item.opcode)} size="small"
                      color={item.type === 'draft' ? 'default' : item.type === 'ai_suggestion' ? 'warning' : 'success'}
                      variant={item.type === 'applied' ? 'filled' : 'outlined'}
                      sx={{ fontSize: '0.65rem', height: 20 }} />
                    {item.isLocked && <LockIcon sx={{ fontSize: 12, color: 'text.disabled', ml: 'auto' }} />}
                    {item.conflicts.length > 0 && (
                      <Tooltip title={`与 ${item.conflicts.length} 个补丁冲突`}>
                        <WarningIcon sx={{ fontSize: 14, color: 'error.main', ml: 'auto' }} />
                      </Tooltip>
                    )}
                    <Tooltip title="在 Timeline 中定位">
                      <IconButton size="small" sx={{ ml: 'auto', p: 0 }}
                        onClick={(e) => { e.stopPropagation(); const evt = events.find(ev => item.targets.includes(ev.id)); if (evt) navigateToEvent(evt.id, evt.start, 'patch') }}>
                        <OpenInNewIcon sx={{ fontSize: 14 }} />
                      </IconButton>
                    </Tooltip>
                  </Box>
                  <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', ml: 1.5 }}>
                    <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.65rem' }}>
                      {item.targets.join(', ')}
                    </Typography>
                    <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.65rem' }}>
                      · {typeof item.timestamp === 'string' ? new Date(item.timestamp).toLocaleTimeString() : new Date(item.timestamp).toLocaleTimeString()}
                    </Typography>
                    <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.65rem' }}>
                      · {item.author}
                    </Typography>
                  </Box>
                </Box>
              )
            })
          )}
        </Box>

        {/* Center: Dependency Graph */}
        <Box sx={{ flexGrow: 1, overflow: 'hidden auto', p: 1.5, bgcolor: 'background.default' }}>
          {depTree ? (
            <>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                依赖关系与影响范围
              </Typography>

              {/* Main patch node */}
              <Box sx={{
                p: 1, mb: 1, borderRadius: 1, bgcolor: 'action.selected',
                border: '1px solid', borderColor: 'divider',
              }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <AccountTreeIcon sx={{ fontSize: 16, color: 'primary.main' }} />
                  <Typography variant="body2" sx={{ fontSize: '0.72rem', fontWeight: 600 }}>
                    {opcodeLabel(depTree.selected.opcode)}
                  </Typography>
                  <Chip label={depTree.selected.status} size="small" color={STATUS_COLORS[depTree.selected.status]}
                    sx={{ fontSize: '0.55rem', height: 16 }} />
                </Box>
              </Box>

              {/* Affected events children */}
              {depTree.affectedEvents.length > 0 && (
                <Box sx={{ ml: 3, mb: 1 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                    受影响事件 ({depTree.affectedEvents.length}):
                  </Typography>
                  {depTree.affectedEvents.map(evt => (
                    <Box key={evt.id} sx={{
                      p: 0.5, mb: 0.5, borderRadius: 0.5, bgcolor: 'rgba(33,150,243,0.08)',
                      border: '1px solid rgba(33,150,243,0.15)', cursor: 'pointer',
                      '&:hover': { bgcolor: 'rgba(33,150,243,0.15)' },
                    }}
                      onClick={() => navigateToEvent(evt.id, evt.start, 'patch')}>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                        <Box sx={{ width: 6, height: 2, bgcolor: 'primary.main' }} />
                        <Typography variant="caption" sx={{ fontSize: '0.62rem' }}>{evt.id}</Typography>
                        <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.55rem' }}>
                          {evt.start.toFixed(1)}s-{evt.end.toFixed(1)}s
                        </Typography>
                        <Typography variant="caption" color="text.disabled" noWrap sx={{ fontSize: '0.55rem', flexGrow: 1 }}>
                          {evt.text.slice(0, 30)}{evt.text.length > 30 ? '…' : ''}
                        </Typography>
                      </Box>
                    </Box>
                  ))}
                </Box>
              )}

              {/* Conflicts */}
              {depTree.conflicts.length > 0 && (
                <Box sx={{ ml: 3, mb: 1 }}>
                  <Typography variant="caption" color="error.main" sx={{ display: 'block', mb: 0.5 }}>
                    ⚠ 冲突补丁 ({depTree.conflicts.length}):
                  </Typography>
                  {depTree.conflicts.map(cid => {
                    const cp = allPatchItems.find(p => p.id === cid)
                    return cp ? (
                      <Box key={cid} sx={{
                        p: 0.5, mb: 0.5, borderRadius: 0.5, bgcolor: 'rgba(244,67,54,0.08)',
                        border: '1px solid rgba(244,67,54,0.2)',
                        cursor: 'pointer', '&:hover': { bgcolor: 'rgba(244,67,54,0.15)' },
                      }}
                        onClick={() => setSelectedPatchId(cid)}>
                        <Typography variant="caption" sx={{ fontSize: '0.6rem' }}>
                          {opcodeLabel(cp.opcode)} · {cp.targets.join(', ')}
                        </Typography>
                      </Box>
                    ) : null
                  })}
                </Box>
              )}

              {/* Related patches */}
              {depTree.related.length > 0 && (
                <Box sx={{ ml: 3 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                    相关补丁 ({depTree.related.length}):
                  </Typography>
                  {depTree.related.map(rp => (
                    <Box key={rp.id} sx={{
                      p: 0.5, mb: 0.5, borderRadius: 0.5, bgcolor: 'rgba(255,255,255,0.03)',
                      border: '1px dashed rgba(255,255,255,0.1)', cursor: 'pointer',
                    }}
                      onClick={() => setSelectedPatchId(rp.id)}>
                      <Typography variant="caption" sx={{ fontSize: '0.6rem' }}>
                        {opcodeLabel(rp.opcode)} · {rp.author}
                      </Typography>
                    </Box>
                  ))}
                </Box>
              )}
            </>
          ) : (
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
              <Box sx={{ textAlign: 'center' }}>
                <AccountTreeIcon sx={{ fontSize: 40, color: 'text.disabled', mb: 1 }} />
                <Typography variant="body2" color="text.secondary">
                  选择一个补丁以查看依赖关系
                </Typography>
              </Box>
            </Box>
          )}
        </Box>

        {/* Right: Preview Panel */}
        <Box sx={{
          width: 280, minWidth: 280, borderLeft: 1, borderColor: 'divider',
          overflow: 'hidden auto', bgcolor: 'background.paper', p: 1.5,
        }}>
          {selectedItem ? (
            <>
              <Typography variant="subtitle2" sx={{ fontSize: '0.78rem', mb: 1 }}>
                {opcodeLabel(selectedItem.opcode)}
              </Typography>

              <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mb: 1 }}>
                <Chip label={selectedItem.type === 'draft' ? '草案' : selectedItem.type === 'ai_suggestion' ? 'AI 建议' : '已应用'}
                  size="small" color={selectedItem.type === 'applied' ? 'success' : selectedItem.type === 'ai_suggestion' ? 'warning' : 'default'}
                  sx={{ fontSize: '0.6rem', height: 20 }} />
                <Chip label={`风险: ${selectedItem.riskLevel}`} size="small"
                  sx={{ fontSize: '0.6rem', height: 20, bgcolor: RISK_COLORS[selectedItem.riskLevel], color: '#fff' }} />
                <Chip label={`影响 ${selectedItem.affectedEventCount} 事件`} size="small" variant="outlined"
                  sx={{ fontSize: '0.6rem', height: 20 }} />
              </Box>

              {/* Diff preview */}
              {(selectedItem.before && Object.keys(selectedItem.before).length > 0) && (
                <Box sx={{ mb: 1.5 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>变更对比</Typography>
                  {Object.keys(selectedItem.before).map(key => (
                    <Box key={key} sx={{ mb: 0.5 }}>
                      <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.55rem', display: 'block' }}>
                        {key}
                      </Typography>
                      <Box sx={{
                        p: 0.5, borderRadius: 0.5, mb: 0.25,
                        bgcolor: 'rgba(244,67,54,0.1)', border: '1px solid rgba(244,67,54,0.2)',
                      }}>
                        <Typography variant="caption" sx={{ fontSize: '0.55rem', color: 'error.light' }}>
                          - {String(selectedItem.before![key]).slice(0, 60)}
                        </Typography>
                      </Box>
                      <Box sx={{
                        p: 0.5, borderRadius: 0.5,
                        bgcolor: 'rgba(76,175,80,0.1)', border: '1px solid rgba(76,175,80,0.2)',
                      }}>
                        <Typography variant="caption" sx={{ fontSize: '0.55rem', color: 'success.light' }}>
                          + {String((selectedItem.after || {})[key] || '').slice(0, 60)}
                        </Typography>
                      </Box>
                    </Box>
                  ))}
                </Box>
              )}

              <Divider sx={{ my: 1 }} />

              {/* Actions */}
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                {selectedItem.type !== 'applied' && (
                  <Button size="small" variant="contained" color="success" startIcon={<CheckIcon />}
                    onClick={() => handleApply(selectedItem)} fullWidth sx={{ fontSize: '0.7rem', justifyContent: 'flex-start' }}>
                    应用此补丁
                  </Button>
                )}
                {selectedItem.type === 'applied' && (
                  <Button size="small" variant="outlined" color="warning" startIcon={<UndoIcon />}
                    onClick={handleUndo} fullWidth sx={{ fontSize: '0.7rem', justifyContent: 'flex-start' }}>
                    回滚此补丁
                  </Button>
                )}
                {selectedItem.type === 'draft' && (
                  <Button size="small" variant="outlined" color="inherit" startIcon={<CloseIcon />}
                    onClick={() => discardDraft(selectedItem.targets[0])} fullWidth
                    sx={{ fontSize: '0.7rem', justifyContent: 'flex-start' }}>
                    放弃草案
                  </Button>
                )}
                <Button size="small" variant="outlined"
                  startIcon={selectedItem.isLocked ? <LockOpenIcon /> : <LockIcon />}
                  onClick={() => handleToggleLock(selectedItem.id)} fullWidth
                  sx={{ fontSize: '0.7rem', justifyContent: 'flex-start' }}>
                  {selectedItem.isLocked ? '解锁补丁' : '锁定补丁'}
                </Button>
              </Box>
            </>
          ) : (
            <Box sx={{ textAlign: 'center', py: 4 }}>
              <AutoFixHighIcon sx={{ fontSize: 40, color: 'text.disabled', mb: 1 }} />
              <Typography variant="body2" color="text.secondary">
                选择一个补丁以查看详情
              </Typography>
            </Box>
          )}
        </Box>
      </Box>

      {/* Merge dialog */}
      <Dialog open={mergeDialogOpen} onClose={() => setMergeDialogOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontSize: '0.9rem' }}>合并补丁</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary">
            将 {selectedPatchIds.size} 个选中的补丁合并为一个逻辑补丁。
            合并后的补丁将包含所有 targets 和 payload 的并集。
          </Typography>
          <Box sx={{ mt: 1 }}>
            {Array.from(selectedPatchIds).map(id => {
              const item = allPatchItems.find(p => p.id === id)
              return item ? (
                <Chip key={id} label={`${opcodeLabel(item.opcode)} → ${item.targets.join(',')}`}
                  size="small" sx={{ mr: 0.5, mb: 0.5, fontSize: '0.6rem' }} />
              ) : null
            })}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button size="small" onClick={() => setMergeDialogOpen(false)}>取消</Button>
          <Button size="small" variant="contained" color="primary" onClick={handleMerge}>合并</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
