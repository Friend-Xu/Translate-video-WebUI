import { Box, Typography, Divider } from '@mui/material'
import TimelineIcon from '@mui/icons-material/TimelineRounded'
import HomeIcon from '@mui/icons-material/HomeRounded'
import SpeakerIcon from '@mui/icons-material/RecordVoiceOverRounded'
import BuildIcon from '@mui/icons-material/BuildRounded'
import QueueIcon from '@mui/icons-material/QueuePlayNextRounded'
import ExportIcon from '@mui/icons-material/IosShareRounded'
import SettingsIcon from '@mui/icons-material/SettingsRounded'
import SearchIcon from '@mui/icons-material/SearchRounded'
import LogIcon from '@mui/icons-material/ArticleRounded'
import BugReportIcon from '@mui/icons-material/BugReportRounded'
import ModelIcon from '@mui/icons-material/AccountTreeRounded'
import GlossaryIcon from '@mui/icons-material/BookRounded'
import { useAppStore } from '../../store/useAppStore'
import { ALL_MODES, MODE_META } from '../../types/modes'

const CORE_ICONS: Record<string, React.ReactNode> = {
  hub: <HomeIcon />,
  timeline: <TimelineIcon />,
  speaker: <SpeakerIcon />,
  patch: <BuildIcon />,
  batch: <QueueIcon />,
  export: <ExportIcon />,
}

export default function NavRail() {
  const mode = useAppStore(s => s.mode)
  const setMode = useAppStore(s => s.setMode)
  const timelineFocus = useAppStore(s => s.timelineFocus)
  const setTimelineFocus = useAppStore(s => s.setTimelineFocus)
  const selectedEventIds = useAppStore(s => s.selectedEventIds)
  const speakerFocus = useAppStore(s => s.speakerFocus)
  const pendingDrafts = useAppStore(s => s.pendingDrafts)
  const localJobStatus = useAppStore(s => s.localJobStatus)
  const toggleDockCollapsed = useAppStore(s => s.toggleDockCollapsed)
  const debugMode = useAppStore(s => s.debugMode)
  const toggleDebugMode = useAppStore(s => s.toggleDebugMode)

  const hasContext = (m: typeof ALL_MODES[number]) => {
    switch (m) {
      case 'hub': return false
      case 'timeline': return selectedEventIds.length > 0
      case 'patch': return pendingDrafts.size > 0
      case 'batch': return Object.keys(localJobStatus).length > 0
      case 'export': return false
    }
  }

  const openCommandPalette = () => {
    window.dispatchEvent(new KeyboardEvent('keydown', { ctrlKey: true, key: 'k', bubbles: true }))
  }

  return (
    <Box sx={{
      width: 72, minWidth: 72, height: '100%',
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      bgcolor: 'background.paper', borderRight: '1px solid', borderColor: 'divider',
      py: 1, gap: 0.5,
    }}>
      {ALL_MODES.map(m => (
        <Box key={m} onClick={() => setMode(m)} sx={{
          width: 48, height: 48, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', borderRadius: 2,
          cursor: 'pointer', gap: 0.25, position: 'relative',
          bgcolor: mode === m ? 'action.selected' : 'transparent',
          color: mode === m ? MODE_META[m].hexColor : 'text.secondary',
          borderLeft: mode === m ? '3px solid' : '3px solid transparent',
          borderColor: mode === m ? MODE_META[m].hexColor : 'transparent',
          transition: 'all 0.15s ease',
          '&:hover': { bgcolor: 'action.hover' },
        }}>
          <Box sx={{ fontSize: 20, lineHeight: 1 }}>{CORE_ICONS[m]}</Box>
          <Typography sx={{ fontSize: '0.5rem', lineHeight: 1, textAlign: 'center' }}>
            {MODE_META[m].label.split(' ')[0]}
          </Typography>
          {hasContext(m) && (
            <Box sx={{
              width: 6, height: 6, borderRadius: '50%',
              bgcolor: MODE_META[m].hexColor,
              opacity: mode === m ? 1 : 0.5,
              position: 'absolute', bottom: 2,
            }} />
          )}
        </Box>
      ))}

      {/* Speaker — shortcut to timeline + speaker focus */}
      <Box onClick={() => setTimelineFocus('speaker')} sx={{
        width: 48, height: 48, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', borderRadius: 2,
        cursor: 'pointer', gap: 0.25, position: 'relative',
        bgcolor: timelineFocus === 'speaker' ? 'action.selected' : 'transparent',
        color: timelineFocus === 'speaker' ? MODE_META.speaker.hexColor : 'text.secondary',
        borderLeft: timelineFocus === 'speaker' ? '3px solid' : '3px solid transparent',
        borderColor: timelineFocus === 'speaker' ? MODE_META.speaker.hexColor : 'transparent',
        transition: 'all 0.15s ease',
        '&:hover': { bgcolor: 'action.hover' },
      }}>
        <Box sx={{ fontSize: 20, lineHeight: 1 }}><SpeakerIcon /></Box>
        <Typography sx={{ fontSize: '0.5rem', lineHeight: 1, textAlign: 'center' }}>
          {MODE_META.speaker.label.split(' ')[0]}
        </Typography>
        {speakerFocus !== null && (
          <Box sx={{
            width: 6, height: 6, borderRadius: '50%',
            bgcolor: MODE_META.speaker.hexColor,
            opacity: timelineFocus === 'speaker' ? 1 : 0.5,
            position: 'absolute', bottom: 2,
          }} />
        )}
      </Box>

      <Divider sx={{ width: 40, my: 0.5 }} />

      {/* Resource items */}
      {[
        { icon: <ModelIcon sx={{ fontSize: 18 }} />, label: '模型' },
        { icon: <GlossaryIcon sx={{ fontSize: 18 }} />, label: '术语' },
      ].map(item => (
        <Box key={item.label} sx={{
          width: 40, height: 40, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', borderRadius: 1.5,
          cursor: 'pointer', color: 'text.disabled',
          '&:hover': { color: 'text.secondary', bgcolor: 'action.hover' },
        }}>
          {item.icon}
          <Typography sx={{ fontSize: '0.45rem' }}>{item.label}</Typography>
        </Box>
      ))}

      <Box sx={{ flexGrow: 1 }} />

      {/* Utility items */}
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0.5, pb: 1 }}>
        {[
          {
            icon: <SearchIcon sx={{ fontSize: 18 }} />, label: 'Search',
            action: openCommandPalette, active: false,
          },
          {
            icon: <SettingsIcon sx={{ fontSize: 18 }} />, label: 'Settings',
            action: toggleDockCollapsed, active: false,
          },
          {
            icon: <LogIcon sx={{ fontSize: 18 }} />, label: 'Logs',
            action: toggleDockCollapsed, active: false,
          },
          {
            icon: <BugReportIcon sx={{ fontSize: 18 }} />, label: 'Debug',
            action: toggleDebugMode, active: debugMode,
          },
        ].map(item => (
          <Box key={item.label} onClick={item.action} sx={{
            width: 40, height: 40, display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', borderRadius: 1.5,
            cursor: 'pointer',
            color: item.active ? 'warning.main' : 'text.disabled',
            '&:hover': { color: item.active ? 'warning.main' : 'text.secondary', bgcolor: 'action.hover' },
          }}>
            {item.icon}
            <Typography sx={{ fontSize: '0.45rem' }}>{item.label}</Typography>
          </Box>
        ))}
      </Box>
    </Box>
  )
}
