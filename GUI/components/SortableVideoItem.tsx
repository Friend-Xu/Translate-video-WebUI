import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { ListItemButton, ListItemIcon, ListItemText, IconButton, Box, Chip, LinearProgress } from '@mui/material'
import DragIndicatorIcon from '@mui/icons-material/DragIndicatorRounded'
import DeleteIcon from '@mui/icons-material/DeleteOutlineRounded'
import InsertDriveFileIcon from '@mui/icons-material/InsertDriveFileRounded'

interface SortableVideoItemProps {
  id: string
  videoName: string
  progress: number
  statusLabel: string
  statusColor: 'default' | 'primary' | 'success' | 'error' | 'warning'
  statusVariant: 'filled' | 'outlined'
  selected: boolean
  disabled: boolean
  onClick: () => void
  onRemove: () => void
}

export function SortableVideoItem({
  id, videoName, progress, statusLabel, statusColor, statusVariant,
  selected, disabled, onClick, onRemove,
}: SortableVideoItemProps) {
  const {
    attributes, listeners, setNodeRef, transform, transition, isDragging,
  } = useSortable({ id, disabled })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 1000 : 'auto',
  }

  return (
    <ListItemButton ref={setNodeRef} style={style} selected={selected}
      onClick={onClick} dense sx={{ pl: 1 }}>
      {!disabled && (
        <Box {...attributes} {...listeners} sx={{ cursor: 'grab', display: 'flex', mr: 0.5 }}>
          <DragIndicatorIcon sx={{ fontSize: 18, color: 'text.secondary' }} />
        </Box>
      )}
      <ListItemIcon sx={{ minWidth: 28 }}>
        <InsertDriveFileIcon color="action" sx={{ fontSize: 18 }} />
      </ListItemIcon>
      <ListItemText
        primary={videoName}
        primaryTypographyProps={{ noWrap: true, fontSize: '0.875rem' }}
        secondaryTypographyProps={{ variant: 'caption' }}
      />
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 200 }}>
        <Box sx={{ flex: 1, maxWidth: 100 }}>
          <LinearProgress variant="determinate" value={progress} sx={{ height: 4, borderRadius: 2 }} />
        </Box>
        <Chip
          label={statusLabel}
          color={statusColor}
          size="small"
          variant={statusVariant}
        />
      </Box>
      {!disabled && (
        <IconButton size="small" onClick={(e) => { e.stopPropagation(); onRemove() }} sx={{ ml: 1 }}>
          <DeleteIcon sx={{ fontSize: 16 }} />
        </IconButton>
      )}
    </ListItemButton>
  )
}
