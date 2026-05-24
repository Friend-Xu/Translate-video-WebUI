import { Box, Chip } from '@mui/material'
import FiberManualRecord from '@mui/icons-material/FiberManualRecord'
import { useAppStore } from '../store/useAppStore'
import { MODE_META, ALL_MODES } from '../types/modes'

export default function ModeSwitcher() {
  const mode = useAppStore(s => s.mode)
  const setMode = useAppStore(s => s.setMode)

  return (
    <Box
      role="radiogroup"
      aria-label="工作模式切换"
      sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, p: 1 }}
    >
      {ALL_MODES.map(m => {
        const meta = MODE_META[m]
        const active = mode === m
        return (
          <Chip
            key={m}
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            icon={<FiberManualRecord sx={{ fontSize: 10, fill: meta.hexColor }} />}
            label={meta.label}
            onClick={() => setMode(m)}
            variant={active ? 'filled' : 'outlined'}
            sx={{
              justifyContent: 'flex-start',
              fontWeight: active ? 700 : 400,
              fontSize: '0.8rem',
              py: 2.5,
              px: 1.5,
              cursor: 'pointer',
              transition: 'transform 0.15s, background-color 0.15s',
              '&:active': { transform: 'scale(0.96)' },
              bgcolor: active ? `${meta.hexColor}22` : 'transparent',
              borderColor: active ? meta.hexColor : 'divider',
              color: active ? meta.hexColor : 'text.secondary',
              '&:hover': {
                bgcolor: active ? `${meta.hexColor}33` : 'action.hover',
              },
            }}
          />
        )
      })}
    </Box>
  )
}
