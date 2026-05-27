import { Box, IconButton, ToggleButton, Tooltip, Divider, Menu, MenuItem, Checkbox, ListItemText } from '@mui/material'
import { useState } from 'react'
import PlayArrowIcon from '@mui/icons-material/PlayArrowRounded'
import PauseIcon from '@mui/icons-material/PauseRounded'
import SkipPreviousIcon from '@mui/icons-material/SkipPreviousRounded'
import SkipNextIcon from '@mui/icons-material/SkipNextRounded'
import LoopIcon from '@mui/icons-material/LoopRounded'
import ZoomInIcon from '@mui/icons-material/ZoomInRounded'
import ZoomOutIcon from '@mui/icons-material/ZoomOutRounded'
import FitScreenIcon from '@mui/icons-material/FitScreenRounded'
import CenterFocusStrongIcon from '@mui/icons-material/CenterFocusStrongRounded'
import FilterListIcon from '@mui/icons-material/FilterListRounded'
import VisibilityIcon from '@mui/icons-material/VisibilityRounded'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHighRounded'
import LayersClearIcon from '@mui/icons-material/LayersClearRounded'
import PsychologyIcon from '@mui/icons-material/PsychologyRounded'
import SpeakerIcon from '@mui/icons-material/RecordVoiceOverRounded'
import { useAppStore } from '../../store/useAppStore'

interface Props {
  isPlaying: boolean
  onPlayPause: () => void
  onJumpPrev: () => void
  onJumpNext: () => void
  loopEnabled: boolean
  onToggleLoop: () => void
  onZoomIn: () => void
  onZoomOut: () => void
  onZoomToFit: () => void
  onScrollToPlayhead: () => void
  filterBarOpen: boolean
  onToggleFilter: () => void
  onRetrigger: () => void
  onRequestAiAssist: () => void
}

export default function TimelineToolbar({
  isPlaying,
  onPlayPause,
  onJumpPrev,
  onJumpNext,
  loopEnabled,
  onToggleLoop,
  onZoomIn,
  onZoomOut,
  onZoomToFit,
  onScrollToPlayhead,
  filterBarOpen,
  onToggleFilter,
  onRetrigger,
  onRequestAiAssist,
}: Props) {
  const snapEnabled = useAppStore(s => s.snapEnabled)
  const setSnapEnabled = useAppStore(s => s.setSnapEnabled)
  const tracks = useAppStore(s => s.tracks)
  const toggleTrackVisibility = useAppStore(s => s.toggleTrackVisibility)
  const applyAllDrafts = useAppStore(s => s.applyAllDrafts)
  const timelineFocus = useAppStore(s => s.timelineFocus)
  const setTimelineFocus = useAppStore(s => s.setTimelineFocus)
  const [visAnchorEl, setVisAnchorEl] = useState<HTMLElement | null>(null)

  const btnSx = { p: 0.5, color: 'text.secondary', '&:hover': { color: 'text.primary' } }
  const activeSx = (active: boolean) => ({
    p: 0.5,
    color: active ? 'primary.main' : 'text.secondary',
    bgcolor: active ? 'action.selected' : 'transparent',
    '&:hover': { color: 'text.primary', bgcolor: 'action.hover' },
  })

  return (
    <Box sx={{
      height: 48, minHeight: 48,
      display: 'flex', alignItems: 'center', gap: 0.5, px: 1,
      borderBottom: 1, borderColor: 'divider',
      bgcolor: 'background.paper',
    }}>
      {/* Left: Transport */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
        <Tooltip title="上一个事件 (Ctrl+←)">
          <IconButton size="small" onClick={onJumpPrev} sx={btnSx}>
            <SkipPreviousIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title={isPlaying ? '暂停 (Space)' : '播放 (Space)'}>
          <IconButton size="small" onClick={onPlayPause} sx={{ ...btnSx, color: 'primary.main' }}>
            {isPlaying ? <PauseIcon fontSize="small" /> : <PlayArrowIcon fontSize="small" />}
          </IconButton>
        </Tooltip>
        <Tooltip title="下一个事件 (Ctrl+→)">
          <IconButton size="small" onClick={onJumpNext} sx={btnSx}>
            <SkipNextIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title={loopEnabled ? '关闭循环 (L)' : '循环播放 (L)'}>
          <ToggleButton size="small" value="loop" selected={loopEnabled}
            onChange={onToggleLoop} sx={activeSx(loopEnabled)}>
            <LoopIcon fontSize="small" />
          </ToggleButton>
        </Tooltip>
      </Box>

      <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />

      {/* Center: Zoom & View */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
        <Tooltip title="缩小 (Ctrl+滚轮)">
          <IconButton size="small" onClick={onZoomOut} sx={btnSx}>
            <ZoomOutIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title="放大 (Ctrl+滚轮)">
          <IconButton size="small" onClick={onZoomIn} sx={btnSx}>
            <ZoomInIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title="适应窗口 (\)">
          <IconButton size="small" onClick={onZoomToFit} sx={btnSx}>
            <FitScreenIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title="定位到播放头">
          <IconButton size="small" onClick={onScrollToPlayhead} sx={btnSx}>
            <CenterFocusStrongIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>

      <Box sx={{ flexGrow: 1 }} />

      <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />

      {/* Right: Tools */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
        <Tooltip title={snapEnabled ? '关闭吸附 (Shift+S)' : '开启吸附 (Shift+S)'}>
          <ToggleButton size="small" value="snap" selected={snapEnabled}
            onChange={() => setSnapEnabled(!snapEnabled)} sx={activeSx(snapEnabled)}>
            <CenterFocusStrongIcon fontSize="small" sx={{ transform: 'rotate(45deg)' }} />
          </ToggleButton>
        </Tooltip>
        <Tooltip title="筛选事件 (Ctrl+F)">
          <ToggleButton size="small" value="filter" selected={filterBarOpen}
            onChange={onToggleFilter} sx={activeSx(filterBarOpen)}>
            <FilterListIcon fontSize="small" />
          </ToggleButton>
        </Tooltip>
        <Tooltip title="轨道可见性">
          <IconButton size="small" sx={btnSx} onClick={(e) => setVisAnchorEl(e.currentTarget)}>
            <VisibilityIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />
        <Tooltip title={timelineFocus === 'speaker' ? '退出说话人聚焦' : '说话人聚焦模式'}>
          <ToggleButton size="small" value="speaker" selected={timelineFocus === 'speaker'}
            onChange={() => setTimelineFocus(timelineFocus === 'speaker' ? 'default' : 'speaker')}
            sx={activeSx(timelineFocus === 'speaker')}>
            <SpeakerIcon fontSize="small" />
          </ToggleButton>
        </Tooltip>
        <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />
        <Tooltip title="局部重算选中事件">
          <IconButton size="small" sx={btnSx} onClick={onRetrigger}>
            <AutoFixHighIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title="应用全部草案">
          <IconButton size="small" sx={btnSx} onClick={() => applyAllDrafts()}>
            <LayersClearIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title="AI 辅助建议">
          <IconButton size="small" sx={btnSx} onClick={onRequestAiAssist}>
            <PsychologyIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>

      {/* Visibility menu */}
      <Menu
        anchorEl={visAnchorEl}
        open={Boolean(visAnchorEl)}
        onClose={() => setVisAnchorEl(null)}
      >
        {tracks.map(track => (
          <MenuItem key={track.id} dense onClick={() => toggleTrackVisibility(track.id)}>
            <Checkbox size="small" checked={track.visible} />
            <ListItemText primary={track.label} primaryTypographyProps={{ variant: 'body2', fontSize: '0.75rem' }} />
          </MenuItem>
        ))}
      </Menu>
    </Box>
  )
}
