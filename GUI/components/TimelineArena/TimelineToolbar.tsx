import { useRef, useCallback, useState, useEffect } from 'react'
import {
  Box, Typography, Slider, IconButton, ToggleButton, Tooltip, Divider,
} from '@mui/material'
import SkipPreviousIcon from '@mui/icons-material/SkipPreviousRounded'
import PlayArrowIcon from '@mui/icons-material/PlayArrowRounded'
import PauseIcon from '@mui/icons-material/PauseRounded'
import SkipNextIcon from '@mui/icons-material/SkipNextRounded'
import LoopIcon from '@mui/icons-material/LoopRounded'
import CenterFocusStrongIcon from '@mui/icons-material/CenterFocusStrongRounded'
import FitScreenIcon from '@mui/icons-material/FitScreenRounded'
import FilterListIcon from '@mui/icons-material/FilterListRounded'
import VisibilityIcon from '@mui/icons-material/VisibilityRounded'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHighRounded'
import LayersClearIcon from '@mui/icons-material/LayersClearRounded'
import PsychologyIcon from '@mui/icons-material/PsychologyRounded'
import SpeakerIcon from '@mui/icons-material/RecordVoiceOverRounded'
import TableViewIcon from '@mui/icons-material/TableViewRounded'
import TimelineViewIcon from '@mui/icons-material/TimelineRounded'
import PeopleIcon from '@mui/icons-material/PeopleRounded'
import { useAppStore } from '../../store/useAppStore'
import type { TimelineCoordAPI } from '../../hooks/useTimelineCoordinates'

interface Props {
  isPlaying: boolean
  onPlayPause: () => void
  onJumpPrev: () => void
  onJumpNext: () => void
  loopEnabled: boolean
  onToggleLoop: () => void
  onZoomToFit: () => void
  onScrollToPlayhead: () => void
  filterBarOpen: boolean
  onToggleFilter: () => void
  onRetrigger: () => void
  onRequestAiAssist: () => void
  coord: TimelineCoordAPI
}

const btnSx = {
  color: '#aaa', fontSize: '0.85rem', '&:hover': { color: '#fff', bgcolor: 'rgba(255,255,255,0.08)' },
}

const activeSx = (on: boolean) => ({
  color: on ? '#90CAF9' : '#aaa',
  bgcolor: on ? 'rgba(144,202,249,0.12)' : 'transparent',
  '&:hover': { color: '#fff', bgcolor: 'rgba(255,255,255,0.08)' },
})

const BASE_PPS = 24 // 1x zoom = 24 pixels per second

export default function TimelineToolbar({
  isPlaying, onPlayPause, onJumpPrev, onJumpNext,
  loopEnabled, onToggleLoop, onZoomToFit, onScrollToPlayhead,
  filterBarOpen, onToggleFilter, onRetrigger, onRequestAiAssist,
  coord,
}: Props) {
  const timelineFocus = useAppStore(s => s.timelineFocus)
  const setTimelineFocus = useAppStore(s => s.setTimelineFocus)
  const timelineViewMode = useAppStore(s => s.timelineViewMode)
  const setTimelineViewMode = useAppStore(s => s.setTimelineViewMode)

  // Zoom slider state
  const [zoomValue, setZoomValue] = useState(1)
  const zoomRef = useRef(1)

  const handleZoomChange = useCallback((_: any, value: number | number[]) => {
    const v = Array.isArray(value) ? value[0] : value
    const scale = v
    coord.zoomTo(BASE_PPS * scale)
    setZoomValue(scale)
    zoomRef.current = scale
  }, [coord])

  // Sync slider from external zoom (wheel/scroll)
  useEffect(() => {
    const scale = coord.pixelsPerSec / BASE_PPS
    if (Math.abs(scale - zoomRef.current) > 0.05) {
      zoomRef.current = scale
      setZoomValue(Math.max(0.1, Math.min(10, scale)))
    }
  }, [coord.pixelsPerSec])

  return (
    <Box>
      {/* Main toolbar row */}
      <Box sx={{
        display: 'flex', alignItems: 'center', gap: 0.5, px: 1, py: 0.5,
        height: 40, minHeight: 40, bgcolor: '#1a1a1a',
        borderBottom: '1px solid rgba(255,255,255,0.08)',
      }}>
        {/* Group A: Transport */}
        <Tooltip title="上一个事件 (Ctrl+←)"><span>
          <IconButton size="small" sx={btnSx} onClick={onJumpPrev}><SkipPreviousIcon fontSize="small" /></IconButton>
        </span></Tooltip>
        <Tooltip title="播放/暂停 (Space)">
          <IconButton size="small" sx={btnSx} onClick={onPlayPause}>
            {isPlaying ? <PauseIcon fontSize="small" /> : <PlayArrowIcon fontSize="small" />}
          </IconButton>
        </Tooltip>
        <Tooltip title="下一个事件 (Ctrl+→)"><span>
          <IconButton size="small" sx={btnSx} onClick={onJumpNext}><SkipNextIcon fontSize="small" /></IconButton>
        </span></Tooltip>
        <Tooltip title={loopEnabled ? '关闭循环 (L)' : '开启循环 (L)'}>
          <ToggleButton size="small" value="loop" selected={loopEnabled}
            onChange={onToggleLoop} sx={activeSx(loopEnabled)}>
            <LoopIcon fontSize="small" />
          </ToggleButton>
        </Tooltip>

        <Tooltip title="定位到播放头">
          <IconButton size="small" sx={btnSx} onClick={onScrollToPlayhead}>
            <CenterFocusStrongIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title="适应窗口 (\)">
          <IconButton size="small" sx={btnSx} onClick={onZoomToFit}>
            <FitScreenIcon fontSize="small" />
          </IconButton>
        </Tooltip>

        <Box sx={{ flexGrow: 1 }} />

        {/* Group B: Snap & Filter & View toggle */}
        <Tooltip title="吸附">
          <ToggleButton size="small" value="snap" sx={activeSx(false)}>
            <CenterFocusStrongIcon fontSize="small" sx={{ transform: 'rotate(45deg)' }} />
          </ToggleButton>
        </Tooltip>
        <Tooltip title={filterBarOpen ? '关闭筛选' : '筛选事件 (Ctrl+F)'}>
          <ToggleButton size="small" value="filter" selected={filterBarOpen}
            onChange={onToggleFilter} sx={activeSx(filterBarOpen)}>
            <FilterListIcon fontSize="small" />
          </ToggleButton>
        </Tooltip>
        <Tooltip title="轨道可见性">
          <IconButton size="small" sx={btnSx}><VisibilityIcon fontSize="small" /></IconButton>
        </Tooltip>

        <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />

        {/* Group C: View mode toggle */}
        <Tooltip title={timelineFocus === 'speaker' ? '关闭说话人聚焦' : '说话人聚焦'}>
          <ToggleButton size="small" value="speaker" selected={timelineFocus === 'speaker'}
            onChange={() => setTimelineFocus(timelineFocus === 'speaker' ? 'default' : 'speaker')}
            sx={activeSx(timelineFocus === 'speaker')}>
            <SpeakerIcon fontSize="small" />
          </ToggleButton>
        </Tooltip>
        <Tooltip title={timelineViewMode === 'table' ? '切换到时间轴视图' : '切换到字幕校验表格'}>
          <ToggleButton size="small" value="table" selected={timelineViewMode === 'table'}
            onChange={() => setTimelineViewMode(timelineViewMode === 'table' ? 'timeline' : 'table')}
            sx={activeSx(timelineViewMode === 'table')}>
            {timelineViewMode === 'table' ? <TimelineViewIcon fontSize="small" /> : <TableViewIcon fontSize="small" />}
          </ToggleButton>
        </Tooltip>
        <Tooltip title="说话人时间轴">
          <ToggleButton size="small" value="speaker-timeline" selected={timelineViewMode === 'speaker-timeline'}
            onChange={() => setTimelineViewMode(timelineViewMode === 'speaker-timeline' ? 'timeline' : 'speaker-timeline' as any)}
            sx={activeSx(timelineViewMode === 'speaker-timeline')}>
            <PeopleIcon fontSize="small" />
          </ToggleButton>
        </Tooltip>

        <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />

        {/* Group D: AI tools */}
        <Tooltip title="局部重算选中事件">
          <IconButton size="small" sx={btnSx} onClick={onRetrigger}><AutoFixHighIcon fontSize="small" /></IconButton>
        </Tooltip>
        <Tooltip title="应用全部草案">
          <IconButton size="small" sx={btnSx}><LayersClearIcon fontSize="small" /></IconButton>
        </Tooltip>
        <Tooltip title="AI 辅助建议">
          <IconButton size="small" sx={btnSx} onClick={onRequestAiAssist}><PsychologyIcon fontSize="small" /></IconButton>
        </Tooltip>
      </Box>

      {/* Zoom slider row — 剪映风格 */}
      <Box sx={{
        display: 'flex', alignItems: 'center', px: 2, height: 28,
        bgcolor: '#121212', borderBottom: '1px solid rgba(255,255,255,0.06)',
        gap: 1,
      }}>
        <Typography variant="caption" sx={{ color: 'text.disabled', fontSize: '0.6rem', minWidth: 18 }}>
          −
        </Typography>
        <Slider
          size="small"
          min={0.1}
          max={10}
          step={0.01}
          value={zoomValue}
          onChange={handleZoomChange}
          sx={{
            color: '#90CAF9',
            height: 3,
            '& .MuiSlider-thumb': { width: 12, height: 12 },
            '& .MuiSlider-track': { height: 3 },
            '& .MuiSlider-rail': { height: 3, opacity: 0.3 },
          }}
        />
        <Typography variant="caption" sx={{ color: 'text.disabled', fontSize: '0.6rem', minWidth: 18 }}>
          +
        </Typography>
        <Typography variant="caption" sx={{ color: 'text.disabled', fontSize: '0.6rem', minWidth: 36, textAlign: 'center' }}>
          {zoomValue.toFixed(1)}x
        </Typography>
      </Box>
    </Box>
  )
}
