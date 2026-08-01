import { useState, useCallback } from 'react'
import {
  Box, Typography, Chip, Tooltip, Menu, MenuItem,
  ListItemIcon, ListItemText, Dialog, DialogTitle, DialogContent,
  DialogActions, Button, FormControl, Select,
} from '@mui/material'
import LockIcon from '@mui/icons-material/LockRounded'
import EditIcon from '@mui/icons-material/EditRounded'
import MergeIcon from '@mui/icons-material/MergeRounded'
import PlayArrowIcon from '@mui/icons-material/PlayArrowRounded'
import VoiceIcon from '@mui/icons-material/RecordVoiceOverRounded'
import { useAppStore } from '../store/useAppStore'
import type { EventViewModel } from '../types'

interface SpeakerLaneData {
  speaker: string
  displayName: string
  color: string
  locked: boolean
  events: EventViewModel[]
  voice_id?: string
}

interface Props {
  lanes: SpeakerLaneData[]
  timeToPixel: (time: number) => number
  pixelsPerSec: number
  onRenameSpeaker?: (speaker: string) => void
  laneHeight?: number
  expanded?: boolean
}

const DEFAULT_LANE_H = 36
const EXPANDED_LANE_H = 80
const LABEL_WIDTH = 100

export default function SpeakerLane({
  lanes, timeToPixel, pixelsPerSec,
  laneHeight, expanded = false,
}: Props) {
  const selectedSpeakerId = useAppStore(s => s.selectedSpeakerId)
  const setSelectedSpeaker = useAppStore(s => s.setSelectedSpeaker)
  const toggleSpeakerSelection = useAppStore(s => s.toggleSpeakerSelection)
  const voicePresets = useAppStore(s => s.voicePresets)
  const bindVoice = useAppStore(s => s.bindVoice)
  const addDraft = useAppStore(s => s.addDraft)
  const applyDraft = useAppStore(s => s.applyDraft)
  const navigateToEvent = useAppStore(s => s.navigateToEvent)
  const timelineFocus = useAppStore(s => s.timelineFocus)
  const setPlayhead = useAppStore(s => s.setPlayhead)

  const [contextMenu, setContextMenu] = useState<{ mouseX: number; mouseY: number; speaker: string } | null>(null)
  const [mergeDialogOpen, setMergeDialogOpen] = useState(false)
  const [mergeTarget, setMergeTarget] = useState<string>('')
  const [editingName, setEditingName] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')

  const handleContextMenu = useCallback((speaker: string, e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setContextMenu({ mouseX: e.clientX, mouseY: e.clientY, speaker })
  }, [])

  const handleCloseMenu = () => setContextMenu(null)

  const handleSelect = useCallback((speaker: string, e: React.MouseEvent) => {
    if (e.ctrlKey || e.metaKey) {
      toggleSpeakerSelection(speaker)
    } else {
      setSelectedSpeaker(speaker)
    }
  }, [setSelectedSpeaker, toggleSpeakerSelection])

  const handleAudition = useCallback(async (voiceId: string) => {
    const voice = voicePresets.find(v => v.id === voiceId)
    if (!voice) return
    try {
      if (voice.engine === 'chattts') {
        const res = await fetch('/api/tts/preview-chattts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: '你好，这是声线试听。', seed: 2 }),
        })
        if (res.ok) {
          const blob = await res.blob()
          const url = URL.createObjectURL(blob)
          const a = new Audio(url)
          a.play()
        }
      }
    } catch { /* non-critical */ }
  }, [voicePresets])

  const handleRename = useCallback((speakerId: string) => {
    if (!editValue.trim()) return
    addDraft({
      eventId: speakerId,
      opcode: 'RENAME_SPEAKER',
      payload: { newName: editValue.trim() },
      before: {},
      after: { displayName: editValue.trim() },
      timestamp: Date.now(),
    })
    applyDraft(speakerId)
    setEditingName(null)
  }, [editValue, addDraft, applyDraft])

  const handleMerge = useCallback(async () => {
    if (!mergeTarget || !contextMenu) return
    const source = contextMenu.speaker
    addDraft({
      eventId: source,
      opcode: 'MERGE_SPEAKERS',
      payload: { source, target: mergeTarget },
      before: {}, after: {},
      timestamp: Date.now(),
    })
    setMergeDialogOpen(false)
    setMergeTarget('')
    handleCloseMenu()
    applyDraft(source)
  }, [mergeTarget, contextMenu, addDraft, applyDraft])

  const handleLockSpeaker = useCallback((speakerId: string) => {
    addDraft({
      eventId: speakerId,
      opcode: 'LOCK_SPEAKER',
      payload: { speaker: speakerId },
      before: {}, after: {},
      timestamp: Date.now(),
    })
    applyDraft(speakerId)
  }, [addDraft, applyDraft])

  const handleSegmentClick = useCallback((eventId: string, startTime: number, e: React.MouseEvent) => {
    e.stopPropagation()
    setPlayhead(startTime)
    navigateToEvent(eventId, startTime, 'timeline')
  }, [setPlayhead, navigateToEvent])

  const h = expanded ? EXPANDED_LANE_H : (laneHeight || DEFAULT_LANE_H)

  if (lanes.length === 0) {
    return (
      <Box sx={{ p: 2, textAlign: 'center' }}>
        <Typography variant="body2" color="text.secondary">
          未检测到说话人 — 启用说话人分离后显示轨道
        </Typography>
      </Box>
    )
  }

  return (
    <Box>
      {lanes.map(lane => {
        const isSelected = selectedSpeakerId === lane.speaker
        return (
          <Box key={lane.speaker} sx={{
            display: 'flex', height: h,
            borderBottom: '1px solid rgba(255,255,255,0.05)',
            position: 'relative',
            bgcolor: isSelected ? 'rgba(255,255,255,0.04)' : 'transparent',
            cursor: 'pointer',
          }}
            onClick={(e) => handleSelect(lane.speaker, e)}
            onContextMenu={(e) => handleContextMenu(lane.speaker, e)}
          >
            <Box sx={{
              width: LABEL_WIDTH, minWidth: LABEL_WIDTH,
              display: 'flex', alignItems: 'center', gap: 0.5, px: 1,
              bgcolor: 'rgba(0,0,0,0.3)', borderRight: '1px solid rgba(255,255,255,0.1)',
            }}>
              <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: lane.color, flexShrink: 0 }} />
              <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                {timelineFocus === 'speaker' && editingName === lane.speaker ? (
                  <input
                    value={editValue}
                    onChange={e => setEditValue(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') handleRename(lane.speaker); if (e.key === 'Escape') setEditingName(null) }}
                    onBlur={() => handleRename(lane.speaker)}
                    autoFocus
                    style={{ width: '100%', background: 'transparent', border: '1px solid #666', color: '#fff', fontSize: '0.7rem', padding: '1px 4px', borderRadius: 2 }}
                  />
                ) : (
                  <Typography variant="caption" noWrap
                    sx={{
                      fontSize: '0.65rem', color: 'common.white', cursor: 'pointer',
                      '&:hover': { textDecoration: 'underline' },
                    }}
                    onDoubleClick={() => { setEditingName(lane.speaker); setEditValue(lane.displayName) }}>
                    {lane.displayName}
                  </Typography>
                )}
              </Box>
              {lane.locked && <LockIcon sx={{ fontSize: 10, color: 'grey.400', flexShrink: 0 }} />}
              <Chip label={lane.events.length} size="small"
                sx={{ fontSize: '0.55rem', height: 16, ml: 'auto', flexShrink: 0 }} />
            </Box>
            <Box sx={{ flexGrow: 1, position: 'relative', overflow: 'hidden' }}>
              {lane.events.map(evt => {
                const left = timeToPixel(evt.start)
                const w = Math.max(2, (evt.end - evt.start) * pixelsPerSec)
                const conf = evt.confidence ?? 0.9
                const alpha = conf >= 0.9 ? '99' : conf >= 0.7 ? '66' : '44'
                return (
                  <Tooltip key={evt.id} disableInteractive
                    title={`${evt.text.slice(0, 40)}${evt.text.length > 40 ? '…' : ''}\n${evt.start.toFixed(1)}s-${evt.end.toFixed(1)}s | conf=${conf.toFixed(2)}`}>
                    <Box sx={{
                      position: 'absolute', left, top: 4, height: h - 8, width: w,
                      bgcolor: `${lane.color}${alpha}`, borderRadius: 0.5,
                      borderLeft: `2px solid ${lane.color}`,
                      cursor: 'pointer',
                      '&:hover': { filter: 'brightness(1.3)', zIndex: 3 },
                    }}
                      onClick={(e) => handleSegmentClick(evt.id, evt.start, e)}
                    />
                  </Tooltip>
                )
              })}
            </Box>
          </Box>
        )
      })}

      {/* Context menu */}
      <Menu
        open={contextMenu !== null}
        onClose={handleCloseMenu}
        anchorReference="anchorPosition"
        anchorPosition={contextMenu ? { top: contextMenu.mouseY, left: contextMenu.mouseX } : undefined}
      >
        <MenuItem dense onClick={() => {
          if (contextMenu) {
            setEditingName(contextMenu.speaker)
            const lane = lanes.find(l => l.speaker === contextMenu.speaker)
            setEditValue(lane?.displayName || '')
          }
          handleCloseMenu()
        }}>
          <ListItemIcon><EditIcon fontSize="small" /></ListItemIcon>
          <ListItemText primary="重命名" primaryTypographyProps={{ fontSize: '0.75rem' }} />
        </MenuItem>
        {lanes.find(l => l.speaker === contextMenu?.speaker)?.voice_id && (
          <MenuItem dense onClick={() => {
            if (contextMenu) {
              const lane = lanes.find(l => l.speaker === contextMenu.speaker)
              if (lane?.voice_id) handleAudition(lane.voice_id)
            }
            handleCloseMenu()
          }}>
            <ListItemIcon><PlayArrowIcon fontSize="small" /></ListItemIcon>
            <ListItemText primary="试听声线" primaryTypographyProps={{ fontSize: '0.75rem' }} />
          </MenuItem>
        )}
        {timelineFocus === 'speaker' && voicePresets.length > 0 && (
          <MenuItem dense sx={{ flexDirection: 'column', alignItems: 'flex-start', gap: 0.5 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
              <VoiceIcon fontSize="small" />
              <Typography variant="body2" sx={{ fontSize: '0.75rem' }}>绑定声线</Typography>
            </Box>
            <FormControl size="small" sx={{ minWidth: 160, ml: 4 }}>
              <Select
                value={lanes.find(l => l.speaker === contextMenu?.speaker)?.voice_id || ''}
                onChange={(e) => {
                  if (contextMenu) bindVoice(contextMenu.speaker, e.target.value as string)
                  handleCloseMenu()
                }}
                displayEmpty
                sx={{ fontSize: '0.7rem', height: 28 }}
              >
                <MenuItem value="" sx={{ fontSize: '0.7rem' }}><em>未绑定</em></MenuItem>
                {voicePresets.map(v => (
                  <MenuItem key={v.id} value={v.id} sx={{ fontSize: '0.7rem' }}>{v.name}</MenuItem>
                ))}
              </Select>
            </FormControl>
          </MenuItem>
        )}
        <MenuItem dense onClick={() => {
          setMergeDialogOpen(true)
          setMergeTarget('')
          handleCloseMenu()
        }}>
          <ListItemIcon><MergeIcon fontSize="small" /></ListItemIcon>
          <ListItemText primary="合并到其他说话人" primaryTypographyProps={{ fontSize: '0.75rem' }} />
        </MenuItem>
        <MenuItem dense onClick={() => {
          if (contextMenu) handleLockSpeaker(contextMenu.speaker)
        }}>
          <ListItemIcon><LockIcon fontSize="small" /></ListItemIcon>
          <ListItemText primary="锁定说话人" primaryTypographyProps={{ fontSize: '0.75rem' }} />
        </MenuItem>
      </Menu>

      {/* Merge dialog */}
      <Dialog open={mergeDialogOpen} onClose={() => setMergeDialogOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontSize: '0.9rem' }}>合并说话人</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            将 "{lanes.find(l => l.speaker === contextMenu?.speaker)?.displayName || contextMenu?.speaker}" 合并到目标说话人。
          </Typography>
          <FormControl fullWidth size="small">
            <Select value={mergeTarget} onChange={(e) => setMergeTarget(e.target.value)} displayEmpty>
              <MenuItem value="" disabled><em>选择目标说话人</em></MenuItem>
              {lanes.filter(l => l.speaker !== contextMenu?.speaker).map(l => (
                <MenuItem key={l.speaker} value={l.speaker}>{l.displayName}</MenuItem>
              ))}
            </Select>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button size="small" onClick={() => setMergeDialogOpen(false)}>取消</Button>
          <Button size="small" variant="contained" color="warning" onClick={handleMerge} disabled={!mergeTarget}>
            合并
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
