import { useState, useCallback, useRef } from 'react'
import { Box } from '@mui/material'
import RegionPlaceholder from './RegionPlaceholder'

interface Props {
  pulseBar?: React.ReactNode
  railContent?: React.ReactNode
  arenaContent?: React.ReactNode
  inspectorContent?: React.ReactNode
  dockContent?: React.ReactNode
}

const PULSE_HEIGHT = 56
const RAIL_WIDTH = 72
const INSPECTOR_DEFAULT = 360
const INSPECTOR_MIN = 240
const DOCK_DEFAULT = 200
const DOCK_MIN = 100

export default function AppShell({
  pulseBar, railContent, arenaContent, inspectorContent, dockContent,
}: Props) {
  const [railOpen, setRailOpen] = useState(true)
  const [inspectorW, setInspectorW] = useState(INSPECTOR_DEFAULT)
  const [dockH, setDockH] = useState(DOCK_DEFAULT)

  const dragRef = useRef<{
    type: 'inspector' | 'dock'
    startX: number
    startY: number
    startVal: number
  } | null>(null)

  const onMouseDownInspector = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragRef.current = { type: 'inspector', startX: e.clientX, startY: 0, startVal: inspectorW }

    const onMove = (ev: MouseEvent) => {
      const delta = dragRef.current!.startX - ev.clientX
      setInspectorW(Math.max(INSPECTOR_MIN, dragRef.current!.startVal + delta))
    }
    const onUp = () => {
      dragRef.current = null
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [inspectorW])

  const onMouseDownDock = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragRef.current = { type: 'dock', startX: 0, startY: e.clientY, startVal: dockH }

    const onMove = (ev: MouseEvent) => {
      const delta = dragRef.current!.startY - ev.clientY
      const maxH = Math.floor(window.innerHeight * 0.5)
      setDockH(Math.min(maxH, Math.max(DOCK_MIN, dragRef.current!.startVal + delta)))
    }
    const onUp = () => {
      dragRef.current = null
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [dockH])

  const railWidth = railOpen ? RAIL_WIDTH : 0

  // 动态网格: inspector/dock 只在有内容时占列/行, 否则 arena 撑满 — 避免空占位把内容挤向左侧
  const hasInspector = inspectorContent !== undefined && inspectorContent !== null
  const hasDock = dockContent !== undefined && dockContent !== null

  const gridAreas = hasInspector && hasDock
    ? '"pulse pulse pulse" "rail arena inspector" "dock dock dock"'
    : hasInspector
      ? '"pulse pulse pulse" "rail arena inspector"'
      : hasDock
        ? '"pulse pulse" "rail arena" "dock dock"'
        : '"pulse pulse" "rail arena"'

  return (
    <Box
      sx={{ height: '100vh', display: 'grid', overflow: 'hidden' }}
      style={{
        gridTemplateAreas: gridAreas,
        gridTemplateRows: hasDock ? `${PULSE_HEIGHT}px 1fr ${dockH}px` : `${PULSE_HEIGHT}px 1fr`,
        gridTemplateColumns: hasInspector ? `${railWidth}px 1fr ${inspectorW}px` : `${railWidth}px 1fr`,
      }}
    >
      {/* Pulse Bar */}
      <Box gridArea="pulse" role="banner" sx={{
        borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper',
        color: 'text.primary', display: 'flex', alignItems: 'center',
      }}>
        {pulseBar || <RegionPlaceholder name="PulseBar" role="banner" />}
      </Box>

      {/* Rail */}
      <Box gridArea="rail" role="navigation" sx={{
        borderRight: railOpen ? 1 : 0, borderColor: 'divider',
        overflow: railOpen ? 'hidden auto' : 'hidden',
        transition: 'width 0.2s',
      }}>
        {railContent || <RegionPlaceholder name="Rail" role="navigation" />}
      </Box>

      {/* Rail toggle */}
      <Box
        component="button"
        onClick={() => setRailOpen(o => !o)}
        aria-label={railOpen ? '折叠侧边栏' : '展开侧边栏'}
        sx={{
          position: 'absolute', top: PULSE_HEIGHT + 8,
          left: railOpen ? railWidth - 12 : 4,
          width: 20, height: 40, zIndex: 10, cursor: 'pointer',
          border: '1px solid', borderColor: 'divider', borderRadius: 1,
          bgcolor: 'background.paper', fontSize: '0.65rem', p: 0,
          transition: 'left 0.2s',
          '&:hover': { bgcolor: 'grey.200' },
        }}
      >
        {railOpen ? '◀' : '▶'}
      </Box>

      {/* Arena */}
      <Box gridArea="arena" role="main" sx={{ overflow: 'hidden', position: 'relative', display: 'flex', flexDirection: 'column' }}>
        {arenaContent || <RegionPlaceholder name="Timeline Arena" role="main" />}
      </Box>

      {/* Inspector — 无内容时不渲染, arena 撑满 */}
      {hasInspector && (
        <Box gridArea="inspector" sx={{ position: 'relative' }}>
          <Box
            onMouseDown={onMouseDownInspector}
            sx={{
              position: 'absolute', left: 0, top: 0, bottom: 0, width: 5,
              cursor: 'col-resize', zIndex: 10,
              '&:hover': { bgcolor: 'primary.light', opacity: 0.5 },
            }}
          />
          <Box role="complementary" sx={{ height: '100%', overflow: 'hidden auto', pl: 0.5 }}>
            {inspectorContent}
          </Box>
        </Box>
      )}

      {/* Dock — 无内容时不渲染 */}
      {hasDock && (
        <Box gridArea="dock" role="contentinfo" sx={{ position: 'relative', borderTop: 1, borderColor: 'divider' }}>
          <Box
            onMouseDown={onMouseDownDock}
            sx={{
              position: 'absolute', left: 0, right: 0, top: -3, height: 6,
              cursor: 'row-resize', zIndex: 10,
              '&:hover': { bgcolor: 'primary.light', opacity: 0.5 },
            }}
          />
          <Box sx={{ height: '100%', overflow: 'hidden' }}>
            {dockContent}
          </Box>
        </Box>
      )}
    </Box>
  )
}
