import { Box, Typography, List, ListItemButton, ListItemText, Chip, Button, Divider } from '@mui/material'
import UndoIcon from '@mui/icons-material/UndoRounded'
import HistoryIcon from '@mui/icons-material/HistoryRounded'
import type { TimelinePatchData } from '../types'

interface Props {
  patches: TimelinePatchData[]
  onUndo?: (patchId: string) => void
}

export default function PatchHistory({ patches, onUndo }: Props) {
  if (patches.length === 0) {
    return (
      <Box sx={{ p: 3, textAlign: 'center' }}>
        <HistoryIcon sx={{ fontSize: 40, color: 'text.disabled', mb: 1 }} />
        <Typography variant="body2" color="text.secondary">
          暂无应用记录 — 应用 Patch 后此处显示版本历史
        </Typography>
      </Box>
    )
  }

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Box sx={{ p: 1, display: 'flex', alignItems: 'center', gap: 1, borderBottom: 1, borderColor: 'divider' }}>
        <Typography variant="subtitle2" sx={{ fontSize: '0.8rem' }}>Patch 历史</Typography>
        <Chip label={`${patches.length} 条记录`} size="small" sx={{ fontSize: '0.65rem' }} />
      </Box>
      <Divider />
      <List dense sx={{ flexGrow: 1, overflow: 'auto', py: 0 }}>
        {patches.map(p => (
          <ListItemButton key={p.patch_id}>
            <ListItemText
              primary={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <Chip label={p.opcode} size="small" color="primary" variant="outlined"
                    sx={{ fontSize: '0.6rem', height: 18 }} />
                  <Typography variant="body2" sx={{ fontSize: '0.7rem' }}>
                    {p.targets.join(', ')}
                  </Typography>
                </Box>
              }
              secondary={
                <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.62rem' }}>
                  {p.author} · {new Date(p.timestamp).toLocaleString()} · score: {p.score.toFixed(2)}
                </Typography>
              }
              disableTypography
            />
            <Button size="small" variant="text" color="warning"
              startIcon={<UndoIcon sx={{ fontSize: 14 }} />}
              sx={{ fontSize: '0.6rem', minWidth: 'auto' }}
              onClick={() => onUndo?.(p.patch_id)}>
              回滚
            </Button>
          </ListItemButton>
        ))}
      </List>
    </Box>
  )
}
