import { Menu, MenuItem, ListItemIcon, ListItemText, Divider } from '@mui/material'
import CallSplitIcon from '@mui/icons-material/CallSplitRounded'
import MergeIcon from '@mui/icons-material/MergeRounded'
import LockIcon from '@mui/icons-material/LockRounded'
import LockOpenIcon from '@mui/icons-material/LockOpenRounded'
import RefreshIcon from '@mui/icons-material/RefreshRounded'
import ContentCopyIcon from '@mui/icons-material/ContentCopyRounded'
import TranslateIcon from '@mui/icons-material/TranslateRounded'
import { useAppStore } from '../../store/useAppStore'
import type { EventViewModel } from '../../types'

interface Props {
  anchorEl: HTMLElement | null
  event: EventViewModel | null
  events: EventViewModel[]
  playheadTime: number
  onClose: () => void
  lockedEventIds: Set<string>
  onToggleLock: (eventId: string) => void
}

export default function EventContextMenu({
  anchorEl, event, events, playheadTime, onClose, lockedEventIds, onToggleLock,
}: Props) {
  const addDraft = useAppStore(s => s.addDraft)
  const open = Boolean(anchorEl) && event !== null

  if (!event) return null

  const eventIdx = events.findIndex(e => e.id === event.id)
  const hasPrev = eventIdx > 0
  const hasNext = eventIdx >= 0 && eventIdx < events.length - 1
  const isLocked = lockedEventIds.has(event.id)
  const canSplit = playheadTime > event.start + 0.1 && playheadTime < event.end - 0.1

  const handleSplit = () => {
    if (!canSplit) return
    addDraft({
      eventId: event.id,
      opcode: 'SPLIT_EVENT',
      payload: { splitTime: playheadTime },
      before: { start: event.start, end: event.end },
      after: {},
      timestamp: Date.now(),
    })
    onClose()
  }

  const handleMergePrev = () => {
    const prev = events[eventIdx - 1]
    if (!prev) return
    addDraft({
      eventId: event.id,
      opcode: 'MERGE_PREV',
      payload: { mergeTarget: prev.id },
      before: { start: event.start, end: event.end },
      after: { start: prev.start, end: event.end },
      timestamp: Date.now(),
    })
    onClose()
  }

  const handleMergeNext = () => {
    const next = events[eventIdx + 1]
    if (!next) return
    addDraft({
      eventId: event.id,
      opcode: 'MERGE_NEXT',
      payload: { mergeTarget: next.id },
      before: { start: event.start, end: event.end },
      after: { start: event.start, end: next.end },
      timestamp: Date.now(),
    })
    onClose()
  }

  const handleToggleLock = () => {
    onToggleLock(event.id)
    onClose()
  }

  const handleRetrigger = () => {
    addDraft({
      eventId: event.id,
      opcode: 'RETRIGGER',
      payload: {},
      before: {},
      after: {},
      timestamp: Date.now(),
    })
    onClose()
  }

  const handleCopyText = () => {
    navigator.clipboard.writeText(event.text).catch(() => {})
    onClose()
  }

  const handleCopyTranslation = () => {
    if (event.translation) {
      navigator.clipboard.writeText(event.translation).catch(() => {})
    }
    onClose()
  }

  return (
    <Menu
      open={open}
      anchorEl={anchorEl}
      onClose={onClose}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
      transformOrigin={{ vertical: 'top', horizontal: 'left' }}
      slotProps={{ paper: { sx: { minWidth: 180, '& .MuiMenuItem-root': { py: 0.5 } } } }}
    >
      <MenuItem onClick={handleSplit} disabled={!canSplit} dense>
        <ListItemIcon><CallSplitIcon fontSize="small" /></ListItemIcon>
        <ListItemText primary="拆分事件" secondary={canSplit ? `在 ${playheadTime.toFixed(1)}s 处` : '播放头需在事件范围内'} />
      </MenuItem>

      <MenuItem onClick={handleMergePrev} disabled={!hasPrev} dense>
        <ListItemIcon><MergeIcon fontSize="small" /></ListItemIcon>
        <ListItemText primary="与上一事件合并" />
      </MenuItem>

      <MenuItem onClick={handleMergeNext} disabled={!hasNext} dense>
        <ListItemIcon><MergeIcon fontSize="small" sx={{ transform: 'scaleX(-1)' }} /></ListItemIcon>
        <ListItemText primary="与下一事件合并" />
      </MenuItem>

      <Divider />

      <MenuItem onClick={handleToggleLock} dense>
        <ListItemIcon>
          {isLocked ? <LockIcon fontSize="small" /> : <LockOpenIcon fontSize="small" />}
        </ListItemIcon>
        <ListItemText primary={isLocked ? '解锁事件' : '锁定事件'} />
      </MenuItem>

      <MenuItem onClick={handleRetrigger} dense>
        <ListItemIcon><RefreshIcon fontSize="small" /></ListItemIcon>
        <ListItemText primary="局部重算" />
      </MenuItem>

      <Divider />

      <MenuItem onClick={handleCopyText} dense>
        <ListItemIcon><ContentCopyIcon fontSize="small" /></ListItemIcon>
        <ListItemText primary="复制原文" />
      </MenuItem>

      <MenuItem onClick={handleCopyTranslation} disabled={!event.translation} dense>
        <ListItemIcon><TranslateIcon fontSize="small" /></ListItemIcon>
        <ListItemText primary="复制译文" />
      </MenuItem>
    </Menu>
  )
}
