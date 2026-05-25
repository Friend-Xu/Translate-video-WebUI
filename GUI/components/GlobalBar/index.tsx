import { Box, Typography, IconButton, TextField, Breadcrumbs, Tooltip } from '@mui/material'
import SettingsIcon from '@mui/icons-material/SettingsRounded'
import SearchIcon from '@mui/icons-material/SearchRounded'
import MemoryIcon from '@mui/icons-material/MemoryRounded'
import TaskIcon from '@mui/icons-material/AssignmentRounded'
import { useAppStore } from '../../store/useAppStore'
import { MODE_META } from '../../types/modes'

interface Props {
  projectName?: string
  workspace?: string
  cpuUsage?: number
  memUsage?: number
  gpuUsage?: number | null
}

export default function GlobalBar({ projectName, workspace, cpuUsage, memUsage, gpuUsage }: Props) {
  const mode = useAppStore(s => s.mode)
  const selectedEventId = useAppStore(s => s.selectedEventId)
  const crossModeContext = useAppStore(s => s.crossModeContext)
  const setMode = useAppStore(s => s.setMode)

  const openCommandPalette = () => {
    window.dispatchEvent(new KeyboardEvent('keydown', { ctrlKey: true, key: 'k', bubbles: true }))
  }

  const isFreshCrossMode = crossModeContext && Date.now() - crossModeContext.timestamp < 5000

  return (
    <Box sx={{
      display: 'flex', alignItems: 'center', gap: 1.5, px: 2,
      height: '100%', width: '100%', bgcolor: 'background.paper',
      borderBottom: '1px solid', borderColor: 'divider',
    }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
        <Box sx={{ width: 28, height: 28, borderRadius: 1.5, bgcolor: 'primary.main', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Typography sx={{ fontSize: '0.8rem', fontWeight: 700, color: 'common.white' }}>T</Typography>
        </Box>
        <Box>
          <Breadcrumbs separator="›" sx={{ fontSize: '0.65rem', '& .MuiBreadcrumbs-ol': { flexWrap: 'nowrap' } }}>
            <Typography variant="caption" sx={{ fontSize: '0.65rem', fontWeight: 600 }}>
              {projectName || 'Unnamed Project'}
            </Typography>
            {isFreshCrossMode && crossModeContext && (
              <Typography variant="caption" sx={{ fontSize: '0.6rem', color: 'text.secondary' }}>
                {MODE_META[crossModeContext.sourceMode]?.labelEn || crossModeContext.sourceMode}
              </Typography>
            )}
            <Typography variant="caption" sx={{ fontSize: '0.6rem', color: MODE_META[mode].hexColor }}>
              {MODE_META[mode].labelEn}
            </Typography>
            {selectedEventId && (
              <Typography variant="caption" sx={{ fontSize: '0.6rem', color: 'text.secondary' }}>
                {selectedEventId}
              </Typography>
            )}
          </Breadcrumbs>
          {workspace && (
            <Typography variant="caption" noWrap sx={{ color: 'text.secondary', maxWidth: 180, fontSize: '0.6rem', display: 'block' }}>
              {workspace}
            </Typography>
          )}
        </Box>
      </Box>
      <Box sx={{ flexGrow: 1 }} />
      <TextField size="small" placeholder="Search events, speakers, patches..."
        onFocus={openCommandPalette}
        InputProps={{ startAdornment: <SearchIcon sx={{ fontSize: 16, mr: 0.5, color: 'text.disabled' }} /> }}
        sx={{ width: 320, '& .MuiInputBase-root': { height: 32, fontSize: '0.75rem' } }} />
      <Box sx={{ flexGrow: 1 }} />
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
        <Tooltip title={
          <Box>
            {cpuUsage != null && <Typography variant="caption" display="block">CPU: {cpuUsage.toFixed(0)}%</Typography>}
            {memUsage != null && <Typography variant="caption" display="block">内存: {memUsage.toFixed(0)}%</Typography>}
            {gpuUsage != null && <Typography variant="caption" display="block">GPU: {gpuUsage.toFixed(0)}%</Typography>}
            {cpuUsage == null && <Typography variant="caption">系统状态不可用</Typography>}
          </Box>
        } arrow>
          <IconButton size="small" title="GPU Status"><MemoryIcon sx={{ fontSize: 18 }} /></IconButton>
        </Tooltip>
        <IconButton size="small" title="Task Queue" onClick={() => setMode('batch')}>
          <TaskIcon sx={{ fontSize: 18 }} />
        </IconButton>
        <IconButton size="small" title="Settings" onClick={openCommandPalette}>
          <SettingsIcon sx={{ fontSize: 18 }} />
        </IconButton>
      </Box>
    </Box>
  )
}
