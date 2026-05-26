import { Box, Typography, Slider, ToggleButton, ToggleButtonGroup, Chip, IconButton, Tooltip, Collapse } from '@mui/material'
import CloseIcon from '@mui/icons-material/CloseRounded'
import type { EventViewModel } from '../../types'

export interface FilterState {
  minConfidence: number
  maxConfidence: number
  speakers: Set<string>
  patchStatus: 'all' | 'hasPatches' | 'noPatches'
  aiSuggestionOnly: boolean
  minDuration: number
  maxDuration: number
}

export const DEFAULT_FILTER: FilterState = {
  minConfidence: 0,
  maxConfidence: 1,
  speakers: new Set(),
  patchStatus: 'all',
  aiSuggestionOnly: false,
  minDuration: 0,
  maxDuration: 999,
}

interface Props {
  open: boolean
  filter: FilterState
  onChange: (f: FilterState) => void
  onClose: () => void
  events: EventViewModel[]
}

const QUICK_PRESETS = [
  { label: '仅低置信度', apply: (f: FilterState) => ({ ...f, maxConfidence: 0.5, patchStatus: 'all' as const, aiSuggestionOnly: false }) },
  { label: '仅超长字幕', apply: (f: FilterState) => ({ ...f, minDuration: 8, patchStatus: 'all' as const, aiSuggestionOnly: false }) },
  { label: '有补丁', apply: (f: FilterState) => ({ ...f, patchStatus: 'hasPatches' as const, aiSuggestionOnly: false }) },
  { label: 'AI 建议', apply: (f: FilterState) => ({ ...f, aiSuggestionOnly: true, patchStatus: 'all' as const }) },
  { label: '全部显示', apply: (_f: FilterState) => ({ ...DEFAULT_FILTER, speakers: new Set<string>() }) },
]

export default function FilterBar({ open, filter, onChange, onClose, events }: Props) {
  const allSpeakers = Array.from(new Set(events.map(e => e.speaker || 'unknown')))
  const selectedSpeakers = filter.speakers.size === 0 ? allSpeakers : Array.from(filter.speakers)

  const setFilter = (partial: Partial<FilterState>) => onChange({ ...filter, ...partial })

  return (
    <Collapse in={open}>
      <Box sx={{
        px: 1.5, py: 1, borderBottom: 1, borderColor: 'divider',
        bgcolor: 'grey.900', display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap',
      }}>
        <Box sx={{ minWidth: 140 }}>
          <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.6rem' }}>
            置信度: {filter.minConfidence.toFixed(1)}–{filter.maxConfidence.toFixed(1)}
          </Typography>
          <Slider
            size="small"
            min={0} max={1} step={0.05}
            value={[filter.minConfidence, filter.maxConfidence]}
            onChange={(_, v) => {
              const [min, max] = v as number[]
              setFilter({ minConfidence: min, maxConfidence: max })
            }}
            sx={{ py: 0, '& .MuiSlider-thumb': { width: 12, height: 12 } }}
          />
        </Box>

        <Box>
          <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.6rem', display: 'block', mb: 0.25 }}>
            说话人
          </Typography>
          <ToggleButtonGroup
            size="small"
            value={selectedSpeakers}
            onChange={(_, speakers: string[]) => {
              if (speakers.length === 0 || speakers.length === allSpeakers.length) {
                setFilter({ speakers: new Set() })
              } else {
                setFilter({ speakers: new Set(speakers) })
              }
            }}
          >
            {allSpeakers.map(s => (
              <ToggleButton key={s} value={s} sx={{ px: 1, py: 0, fontSize: '0.6rem', textTransform: 'none' }}>
                {events.find(e => (e.speaker || 'unknown') === s)?.displayName || s}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        </Box>

        <Box>
          <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.6rem', display: 'block', mb: 0.25 }}>
            补丁状态
          </Typography>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            {(['all', 'hasPatches', 'noPatches'] as const).map(s => (
              <Chip
                key={s}
                label={s === 'all' ? '全部' : s === 'hasPatches' ? '有补丁' : '无补丁'}
                size="small"
                variant={filter.patchStatus === s ? 'filled' : 'outlined'}
                color={filter.patchStatus === s ? 'primary' : 'default'}
                onClick={() => setFilter({ patchStatus: s })}
                sx={{ fontSize: '0.6rem', height: 22, cursor: 'pointer' }}
              />
            ))}
          </Box>
        </Box>

        <Chip
          label="仅 AI 建议"
          size="small"
          variant={filter.aiSuggestionOnly ? 'filled' : 'outlined'}
          color={filter.aiSuggestionOnly ? 'warning' : 'default'}
          onClick={() => setFilter({ aiSuggestionOnly: !filter.aiSuggestionOnly })}
          sx={{ fontSize: '0.6rem', height: 22, cursor: 'pointer' }}
        />

        <Box sx={{ display: 'flex', gap: 0.5, ml: 'auto', alignItems: 'center' }}>
          <Typography variant="caption" color="text.disabled" sx={{ fontSize: '0.6rem', mr: 0.5 }}>
            快速:
          </Typography>
          {QUICK_PRESETS.map(p => (
            <Chip
              key={p.label}
              label={p.label}
              size="small"
              variant="outlined"
              onClick={() => onChange(p.apply(filter))}
              sx={{ fontSize: '0.6rem', height: 20, cursor: 'pointer' }}
            />
          ))}
          <Tooltip title="关闭筛选">
            <IconButton size="small" onClick={onClose} sx={{ p: 0, ml: 0.5 }}>
              <CloseIcon sx={{ fontSize: 16 }} />
            </IconButton>
          </Tooltip>
        </Box>
      </Box>
    </Collapse>
  )
}

export function applyFilter(events: EventViewModel[], filter: FilterState): { visible: EventViewModel[]; dimmed: Set<string> } {
  const allSpeakers = Array.from(new Set(events.map(e => e.speaker || 'unknown')))
  const activeSpeakers = filter.speakers.size === 0 ? allSpeakers : Array.from(filter.speakers)

  const visible: EventViewModel[] = []
  const dimmed = new Set<string>()

  for (const evt of events) {
    let match = true
    if (evt.confidence < filter.minConfidence || evt.confidence > filter.maxConfidence) match = false
    if (!activeSpeakers.includes(evt.speaker || 'unknown')) match = false
    if (filter.patchStatus === 'hasPatches' && !evt.visualState.hasPatches) match = false
    if (filter.patchStatus === 'noPatches' && evt.visualState.hasPatches) match = false
    if (filter.aiSuggestionOnly && !evt.visualState.hasAiSuggestion) match = false
    const dur = evt.end - evt.start
    if (dur < filter.minDuration || dur > filter.maxDuration) match = false

    if (match) visible.push(evt)
    else dimmed.add(evt.id)
  }

  return { visible, dimmed }
}
