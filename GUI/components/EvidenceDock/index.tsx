import { useState, useEffect } from 'react'
import { Box, Tabs, Tab, Typography } from '@mui/material'
import { useAppStore } from '../../store/useAppStore'
import { LAYOUT_PRESETS } from '../../types/modes'
import { LogPanel } from '../sections/LogPanel'
import type { LogEntry } from '../../types'
import type { ConnectionState } from '../../hooks/useSSE'

type DockView = 'log' | 'execution' | 'patchHistory'

interface Props {
  logs?: LogEntry[]
  connectionState?: ConnectionState
  logFirstIndex?: number
  logTotal?: number
  onLoadOlder?: () => void
}

export default function EvidenceDock({
  logs = [], connectionState = 'closed',
  logFirstIndex = 0, logTotal = 0, onLoadOlder,
}: Props) {
  const mode = useAppStore(s => s.mode)
  const preset = LAYOUT_PRESETS[mode]
  const [activeView, setActiveView] = useState<DockView>(preset.defaultDockView)

  useEffect(() => {
    setActiveView(preset.defaultDockView)
  }, [mode, preset.defaultDockView])

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Tab bar */}
      <Box sx={{ borderBottom: 1, borderColor: 'divider', px: 1 }}>
        <Tabs
          value={activeView}
          onChange={(_, v) => setActiveView(v)}
          sx={{ minHeight: 32, '& .MuiTab-root': { minHeight: 32, py: 0, fontSize: '0.75rem' } }}
        >
          <Tab label="日志" value="log" />
          <Tab label="执行" value="execution" />
          <Tab label="Patch历史" value="patchHistory" />
        </Tabs>
      </Box>

      {/* View content */}
      <Box sx={{ flexGrow: 1, overflow: 'hidden' }}>
        {activeView === 'log' && (
          <LogPanel
            logs={logs}
            showTitle={false}
            connectionState={connectionState}
            logFirstIndex={logFirstIndex}
            logTotal={logTotal}
            onLoadOlder={onLoadOlder}
          />
        )}

        {activeView === 'execution' && (
          <Box sx={{ p: 3, textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              执行视图 — 运行 Pipeline 或应用 Patch 后显示任务详情
            </Typography>
          </Box>
        )}

        {activeView === 'patchHistory' && (
          <Box sx={{ p: 3, textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              Patch 历史 — 应用 Patch 后此处显示版本记录
            </Typography>
          </Box>
        )}
      </Box>
    </Box>
  )
}
