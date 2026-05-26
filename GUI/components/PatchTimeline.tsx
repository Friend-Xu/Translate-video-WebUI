import { Box, Typography, Chip, IconButton, Tooltip } from '@mui/material'
import UndoIcon from '@mui/icons-material/UndoRounded'
import CheckCircleIcon from '@mui/icons-material/CheckCircleRounded'
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUncheckedRounded'
import { useAppStore } from '../store/useAppStore'
import type { TimelinePatchData } from '../types'
import type { PatchViewItem } from '../types/modes'

interface Props {
  patches: PatchViewItem[]
  appliedPatches: TimelinePatchData[]
  selectedPatchId: string | null
  onSelectPatch: (id: string) => void
}

const OPCODE_LABELS: Record<string, string> = {
  SET_TRANSLATION: '翻译修改', RETAG_SPEAKER: '说话人重映射', RENAME_SPEAKER: '说话人重命名',
  MERGE_SPEAKERS: '合并说话人', SPLIT_EVENT: '拆分事件', MOVE_EVENT: '时间偏移',
}

export default function PatchTimeline({ patches, appliedPatches, selectedPatchId, onSelectPatch }: Props) {
  const undoLastPatch = useAppStore(s => s.undoLastPatch)
  const getLabel = (opcode: string) => OPCODE_LABELS[opcode] || opcode

  return (
    <Box sx={{ p: 1 }}>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
        补丁时间线 ({appliedPatches.length} 条记录)
      </Typography>

      {appliedPatches.length === 0 ? (
        <Typography variant="caption" color="text.disabled">暂无应用记录</Typography>
      ) : (
        <Box sx={{ position: 'relative', ml: 2 }}>
          <Box sx={{ position: 'absolute', left: 7, top: 4, bottom: 4, width: 2, bgcolor: 'divider' }} />

          {[...appliedPatches].reverse().map((p, idx) => {
            const isLast = idx === 0
            const isSelected = selectedPatchId === p.patch_id
            return (
              <Box key={p.patch_id} sx={{ position: 'relative', mb: idx < appliedPatches.length - 1 ? 1.5 : 0 }}>
                <Box sx={{
                  position: 'absolute', left: -13, top: 4,
                  width: 14, height: 14, borderRadius: '50%',
                  bgcolor: isLast ? 'success.main' : 'grey.600',
                  border: '2px solid', borderColor: 'background.paper',
                  zIndex: 2, display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  {isLast ? <CheckCircleIcon sx={{ fontSize: 10, color: '#fff' }} /> :
                    <RadioButtonUncheckedIcon sx={{ fontSize: 10, color: '#fff' }} />}
                </Box>

                <Box sx={{
                  ml: 2, p: 1, borderRadius: 0.75,
                  border: '1px solid', borderColor: isSelected ? 'primary.main' : 'divider',
                  bgcolor: isSelected ? 'action.selected' : 'action.hover',
                  cursor: 'pointer', '&:hover': { bgcolor: 'action.selected' },
                }}
                  onClick={() => onSelectPatch(p.patch_id)}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.25 }}>
                    <Chip label={getLabel(p.opcode)} size="small" color={idx === 0 ? 'success' : 'default'}
                      variant="outlined" sx={{ fontSize: '0.55rem', height: 16 }} />
                    {idx === 0 && (
                      <Tooltip title="回滚此补丁">
                        <IconButton size="small" onClick={(e) => { e.stopPropagation(); undoLastPatch() }}
                          sx={{ p: 0, ml: 'auto' }}>
                          <UndoIcon sx={{ fontSize: 14, color: 'warning.main' }} />
                        </IconButton>
                      </Tooltip>
                    )}
                  </Box>
                  <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.55rem' }}>
                    {p.targets.join(', ')} · {p.author} · {new Date(p.timestamp).toLocaleTimeString()}
                  </Typography>
                  {p.reason.length > 0 && (
                    <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.5rem', display: 'block' }}>
                      {p.reason.join(', ')}
                    </Typography>
                  )}
                </Box>
              </Box>
            )
          })}
        </Box>
      )}

      {patches.filter(p => p.type === 'draft').length > 0 && (
        <Box sx={{ mt: 1.5 }}>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
            待处理草案 ({patches.filter(p => p.type === 'draft').length})
          </Typography>
          {patches.filter(p => p.type === 'draft').map(p => (
            <Chip key={p.id} label={`${getLabel(p.opcode)} → ${p.targets.join(',')}`}
              size="small" variant="outlined" sx={{ mr: 0.5, mb: 0.5, fontSize: '0.55rem' }}
              onClick={() => onSelectPatch(p.id)} />
          ))}
        </Box>
      )}
    </Box>
  )
}
