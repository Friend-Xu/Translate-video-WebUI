import { useCallback } from 'react'
import {
  Box, Slider, IconButton, ToggleButton, Tooltip, Divider,
} from '@mui/material'
import CenterFocusStrongIcon from '@mui/icons-material/CenterFocusStrongRounded'
import FitScreenIcon from '@mui/icons-material/FitScreenRounded'
import ZoomInIcon from '@mui/icons-material/ZoomInRounded'
import ZoomOutIcon from '@mui/icons-material/ZoomOutRounded'
import FilterListIcon from '@mui/icons-material/FilterListRounded'
import VisibilityIcon from '@mui/icons-material/VisibilityRounded'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHighRounded'
import LayersClearIcon from '@mui/icons-material/LayersClearRounded'
import PsychologyIcon from '@mui/icons-material/PsychologyRounded'
import TableViewIcon from '@mui/icons-material/TableViewRounded'
import PeopleIcon from '@mui/icons-material/PeopleRounded'
import FileDownloadIcon from '@mui/icons-material/FileDownloadRounded'
import { useAppStore } from '../../store/useAppStore'
import type { TimelineCoordAPI } from '../../hooks/useTimelineCoordinates'

interface Props {
  onZoomToFit: () => void
  onScrollToPlayhead: () => void
  filterBarOpen: boolean
  onToggleFilter: () => void
  onRetrigger: () => void
  onRequestAiAssist: () => void
  coord: TimelineCoordAPI
}

const btnSx = {
  color: '#475569', fontSize: '0.85rem', '&:hover': { color: '#1e293b', bgcolor: 'rgba(99,102,241,0.08)' },
}

const activeSx = (on: boolean) => ({
  color: on ? '#6366f1' : '#475569',
  bgcolor: on ? 'rgba(99,102,241,0.1)' : 'transparent',
  '&:hover': { color: '#4f46e5', bgcolor: 'rgba(99,102,241,0.08)' },
})

const MIN_ZOOM = 0.1
const MAX_ZOOM = 50

export default function TimelineToolbar({
  onZoomToFit, onScrollToPlayhead,
  filterBarOpen, onToggleFilter, onRetrigger, onRequestAiAssist,
  coord,
}: Props) {
  const mode = useAppStore(s => s.mode)
  const setMode = useAppStore(s => s.setMode)

  const zoomLevel = coord.zoomLevel

  // Zoom slider uses log scale for natural feel
  const zoomToSlider = (zl: number) => (Math.log10(zl) - Math.log10(MIN_ZOOM)) / (Math.log10(MAX_ZOOM) - Math.log10(MIN_ZOOM)) * 100
  const sliderToZoom = (sv: number) => Math.pow(10, Math.log10(MIN_ZOOM) + (sv / 100) * (Math.log10(MAX_ZOOM) - Math.log10(MIN_ZOOM)))

  const handleZoomChange = useCallback((_: any, value: number | number[]) => {
    const v = Array.isArray(value) ? value[0] : value
    coord.zoomTo(sliderToZoom(v))
  }, [coord])

  return (
    <Box>
      {/* Main toolbar row */}
      <Box sx={{
        display: 'flex', alignItems: 'center', gap: 0.5, px: 1, py: 0.5,
        height: 40, minHeight: 40, bgcolor: '#e8ecf4',
        borderBottom: '1px solid #d0d5e0',
      }}>
        {/* Navigation + Zoom */}
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
        <Tooltip title="缩小">
          <IconButton size="small" sx={btnSx} onClick={() => coord.zoomOut()}>
            <ZoomOutIcon fontSize="small" />
          </IconButton>
        </Tooltip>

        {/* Zoom slider — log scale for natural feel across 0.1x–50x */}
        <Box sx={{ width: 120, mx: 0.5 }}>
          <Slider
            size="small"
            min={0}
            max={100}
            step={0.1}
            value={zoomToSlider(zoomLevel)}
            onChange={handleZoomChange}
            sx={{
              color: '#6366f1',
              height: 3,
              '& .MuiSlider-thumb': { width: 12, height: 12 },
              '& .MuiSlider-track': { height: 3 },
              '& .MuiSlider-rail': { height: 3, opacity: 0.2 },
            }}
          />
        </Box>

        <Tooltip title="放大">
          <IconButton size="small" sx={btnSx} onClick={() => coord.zoomIn()}>
            <ZoomInIcon fontSize="small" />
          </IconButton>
        </Tooltip>

        <Box sx={{ flexGrow: 1 }} />

        {/* Snap & Filter */}
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

        {/* View mode toggle */}
        <Tooltip title={mode === 'review' ? '切换到时间轴视图' : '字幕校验'}>
          <IconButton size="small" sx={{ ...btnSx, color: mode === 'review' ? '#10B981' : undefined }}
            onClick={() => setMode(mode === 'review' ? 'timeline' : 'review')}><TableViewIcon fontSize="small" /></IconButton>
        </Tooltip>
        <Tooltip title="说话人审核">
          <IconButton size="small" sx={{ ...btnSx, color: mode === 'speaker' ? '#FF9800' : undefined }}
            onClick={() => setMode(mode === 'speaker' ? 'timeline' : 'speaker')}><PeopleIcon fontSize="small" /></IconButton>
        </Tooltip>

        <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />

        {/* AI tools */}
        <Tooltip title="局部重算选中事件">
          <IconButton size="small" sx={btnSx} onClick={onRetrigger}><AutoFixHighIcon fontSize="small" /></IconButton>
        </Tooltip>
        <Tooltip title="应用全部草案">
          <IconButton size="small" sx={btnSx}><LayersClearIcon fontSize="small" /></IconButton>
        </Tooltip>
        <Tooltip title="AI 辅助建议">
          <IconButton size="small" sx={btnSx} onClick={onRequestAiAssist}><PsychologyIcon fontSize="small" /></IconButton>
        </Tooltip>

        <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />
        <Tooltip title="导出配音">
          <IconButton size="small" sx={{ ...btnSx, color: '#00BCD4' }} onClick={() => setMode('export')}><FileDownloadIcon fontSize="small" /></IconButton>
        </Tooltip>
      </Box>
    </Box>
  )
}
