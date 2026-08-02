import { useState, useEffect } from 'react'
import { Box, Tabs, Tab, Typography, IconButton, Tooltip, Collapse, Button } from '@mui/material'
import ExpandLessIcon from '@mui/icons-material/ExpandLessRounded'
import ExpandMoreIcon from '@mui/icons-material/ExpandMoreRounded'
import ContentCopyIcon from '@mui/icons-material/ContentCopyRounded'
import CheckCircleIcon from '@mui/icons-material/CheckCircleRounded'
import PendingIcon from '@mui/icons-material/PendingRounded'
import { useAppStore } from '../../store/useAppStore'
import { LAYOUT_PRESETS } from '../../types/modes'
import type { EventViewModel } from '../../types'
import type { BatchStatus } from '../../types'

type DockView = 'aiTrace' | 'patchDiff' | 'taskOutput' | 'debug'

interface Props {
  events?: EventViewModel[]
  passTrace?: string[]
  batchStatus?: BatchStatus | null
}

const TAB_LABELS: Record<DockView, string> = {
  aiTrace: 'AI 追踪',
  patchDiff: '补丁列表',
  taskOutput: '任务状态',
  debug: '调试',
}

const PASS_NAMES: Record<string, string> = {
  'ASR': '语音识别',
  'Alignment': '时间对齐',
  'Fusion': '多源融合',
  'SpeakerDiarization': '说话人分离',
  'Translation': '翻译',
  'TTS': '语音合成',
}

export default function EvidenceDock({
  events = [], passTrace, batchStatus,
}: Props) {
  const mode = useAppStore(s => s.mode)
  const preset = LAYOUT_PRESETS[mode]
  const dockCollapsed = useAppStore(s => s.dockCollapsed)
  const toggleDockCollapsed = useAppStore(s => s.toggleDockCollapsed)
  const pendingDrafts = useAppStore(s => s.pendingDrafts)
  const appliedPatches = useAppStore(s => s.appliedPatches)
  const debugMode = useAppStore(s => s.debugMode)

  const [activeView, setActiveView] = useState<DockView>(preset.defaultDockView)

  useEffect(() => {
    setActiveView(preset.defaultDockView)
  }, [mode, preset.defaultDockView])

  const collapsed = dockCollapsed
  const setCollapsed = () => toggleDockCollapsed()

  const displayPassTrace = passTrace && passTrace.length > 0
    ? passTrace
    : events.length > 0 ? events[0]?.passTrace ?? [] : []

  // 调试 tab 仅在 debugMode 时出现 (开发者工具不混入用户界面)
  const visibleTabs = (Object.keys(TAB_LABELS) as DockView[])
    .filter(v => v !== 'debug' || debugMode)
  const visibleView: DockView = visibleTabs.includes(activeView) ? activeView : 'patchDiff'

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Box sx={{
        display: 'flex', alignItems: 'center',
        borderBottom: 1, borderColor: 'divider', px: 0.5,
        height: 32, minHeight: 32,
      }}>
        <Collapse in={!collapsed} orientation="horizontal">
          <Tabs
            value={visibleView}
            onChange={(_, v) => setActiveView(v)}
            sx={{ minHeight: 32, '& .MuiTab-root': { minHeight: 32, py: 0, fontSize: '0.72rem' } }}
          >
            {visibleTabs.map(tab => (
              <Tab key={tab} label={TAB_LABELS[tab]} value={tab} />
            ))}
          </Tabs>
        </Collapse>
        <Box sx={{ flexGrow: 1 }} />
        <Tooltip title={collapsed ? '展开面板' : '折叠面板'}>
          <IconButton size="small" onClick={() => setCollapsed()}
            sx={{ color: 'text.secondary', p: 0.25 }}>
            {collapsed ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
          </IconButton>
        </Tooltip>
      </Box>

      <Collapse in={!collapsed}>
        <Box sx={{ flexGrow: 1, overflow: 'hidden', height: 168 }}>
          {visibleView === 'aiTrace' && (
            <Box sx={{ p: 1.5, height: '100%', overflow: 'auto' }}>
              <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
                Pass 链路 — 翻译与 TTS 推理流程
              </Typography>
              {displayPassTrace.length > 0 ? (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                  {displayPassTrace.map((name: string) => (
                    <Box key={name} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      <CheckCircleIcon sx={{ fontSize: 14, color: 'success.main' }} />
                      <Typography variant="caption">{PASS_NAMES[name] || name}</Typography>
                    </Box>
                  ))}
                </Box>
              ) : (
                <Typography variant="caption" color="text.disabled">无 Pass 链路数据</Typography>
              )}
            </Box>
          )}

          {visibleView === 'patchDiff' && (
            <Box sx={{ p: 1.5, height: '100%', overflow: 'auto' }}>
              <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
                补丁与草案
              </Typography>
              {pendingDrafts.size === 0 && appliedPatches.length === 0 ? (
                <Typography variant="caption" color="text.disabled">暂无补丁或草案</Typography>
              ) : (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                  {Array.from(pendingDrafts.entries()).map(([eventId, draft]) => {
                    const evt = events.find(e => e.id === eventId)
                    return (
                      <Box key={eventId} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                        <PendingIcon sx={{ fontSize: 14, color: 'warning.main' }} />
                        <Typography variant="caption">{draft.opcode} · {evt?.id || eventId}</Typography>
                      </Box>
                    )
                  })}
                  {appliedPatches.slice(-10).map(p => (
                    <Box key={p.patch_id} sx={{ display: 'flex', alignItems: 'center', gap: 0.5, opacity: 0.6 }}>
                      <CheckCircleIcon sx={{ fontSize: 14, color: 'success.main' }} />
                      <Typography variant="caption">{p.opcode} · {p.author}</Typography>
                    </Box>
                  ))}
                </Box>
              )}
            </Box>
          )}

          {visibleView === 'taskOutput' && (
            <Box sx={{ p: 1.5, height: '100%', overflow: 'auto' }}>
              <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
                批处理任务状态
              </Typography>
              {!batchStatus || batchStatus.videos.length === 0 ? (
                <Typography variant="caption" color="text.disabled">暂无批处理任务</Typography>
              ) : (
                <>
                  <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
                    状态: {batchStatus.status} · 视频: {batchStatus.videos.length} 个
                  </Typography>
                  {batchStatus.videos.map((v, i) => (
                    <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.25 }}>
                      <Box sx={{
                        width: 8, height: 8, borderRadius: '50%',
                        bgcolor: v.status === 'completed' ? 'success.main' : v.status === 'failed' ? 'error.main' : v.status === 'running' ? 'primary.main' : 'grey.400',
                      }} />
                      <Typography variant="caption" noWrap sx={{ flexGrow: 1 }}>{v.video_name}</Typography>
                      <Typography variant="caption" color="text.secondary">{v.status}</Typography>
                    </Box>
                  ))}
                </>
              )}
            </Box>
          )}

          {visibleView === 'debug' && (
            <Box sx={{ p: 1.5, height: '100%', overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
              <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5, display: 'block' }}>
                Store State
              </Typography>
              <Box sx={{
                bgcolor: 'grey.900', color: 'grey.300', p: 1, borderRadius: 1,
                fontFamily: 'monospace', fontSize: '0.6rem', flexGrow: 1, overflow: 'auto',
                whiteSpace: 'pre-wrap',
              }}>
                {JSON.stringify({
                  mode: useAppStore.getState().mode,
                  selectedEventId: useAppStore.getState().selectedEventId,
                  crossModeContext: useAppStore.getState().crossModeContext,
                  pendingDrafts: useAppStore.getState().pendingDrafts.size,
                  appliedPatches: useAppStore.getState().appliedPatches.length,
                  dockCollapsed: useAppStore.getState().dockCollapsed,
                  debugMode: useAppStore.getState().debugMode,
                  localJobStatus: useAppStore.getState().localJobStatus,
                }, null, 2)}
              </Box>
              <Button size="small" variant="outlined" startIcon={<ContentCopyIcon />}
                onClick={() => {
                  navigator.clipboard.writeText(JSON.stringify(useAppStore.getState(), null, 2))
                }}
                sx={{ mt: 0.5, fontSize: '0.65rem' }}>
                复制状态
              </Button>
            </Box>
          )}
        </Box>
      </Collapse>
    </Box>
  )
}
