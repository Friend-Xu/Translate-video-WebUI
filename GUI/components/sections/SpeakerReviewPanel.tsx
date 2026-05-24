import { useState, useCallback, useMemo, useRef, useEffect } from 'react'
import {
  Box, Typography, Card, IconButton, Tooltip, Alert, Chip,
  Button, Slider, Dialog, DialogTitle, DialogContent, DialogActions,
  Badge, Drawer, List, ListItem, ListItemText,
  Menu, MenuItem, ListItemIcon, Divider as MuiDivider,
} from '@mui/material'
import PauseIcon from '@mui/icons-material/PauseRounded'
import PlayIcon from '@mui/icons-material/PlayArrowRounded'
import UndoIcon from '@mui/icons-material/UndoRounded'
import SplitIcon from '@mui/icons-material/CallSplitRounded'
import MergeIcon from '@mui/icons-material/MergeRounded'
import EditIcon from '@mui/icons-material/EditRounded'
import VoiceIcon from '@mui/icons-material/RecordVoiceOverRounded'
import InfoIcon from '@mui/icons-material/InfoOutlined'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesomeRounded'
import ZoomInIcon from '@mui/icons-material/ZoomInRounded'
import ZoomOutIcon from '@mui/icons-material/ZoomOutRounded'
import RefreshIcon from '@mui/icons-material/RefreshRounded'
import { SectionHeader } from '../SectionHeader'
import EventBlock from './EventBlock'
import EventInspector from './EventInspector'
import WaveformLayer from './WaveformLayer'
import type {
  TimelinePatchData, PatchGenerateResponse,
  EventViewModel, ContextMenuState, WaveformData,
} from '../../types'

const LANE_HEIGHT = 52
const LABEL_WIDTH = 110

interface SegmentData {
  id: string; start: number; end: number; text: string
  translation: string; overlap: boolean
  words?: { word: string; start: number; end: number }[]
}

interface SpeakerLane {
  speaker: string; display_name: string; voice_id: string
  color: string; segments: SegmentData[]; segment_count: number; total_duration: number
}

interface Props {
  workspace: string
  videoPath: string
  speakers: string[]
  timeline: any[]
  verification: any | null
  speakerNames: Record<string, string>
  onTimelineChange?: (tl: any[]) => void
  onSaveCorrections?: (tl: any[], c: unknown[]) => void
}

export default function SpeakerReviewPanel({
  workspace, videoPath, speakerNames,
}: Props) {
  // ── Data ──
  const [lanes, setLanes] = useState<SpeakerLane[]>([])
  const [aiPatches, setAiPatches] = useState<PatchGenerateResponse | null>(null)
  const [patchLog, setPatchLog] = useState<TimelinePatchData[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // ── View ──
  const [totalDuration, setTotalDuration] = useState(120)
  const [zoomSeconds, setZoomSeconds] = useState(60)
  const [selectedSeg, setSelectedSeg] = useState<string | null>(null)
  const [multiSelect, setMultiSelect] = useState<Set<string>>(new Set())
  const [playing, setPlaying] = useState(false)
  const [playTime, setPlayTime] = useState(0)
  const [aiOpen, setAiOpen] = useState(false)
  const [undoing, setUndoing] = useState(false)
  const [splitConfirm, setSplitConfirm] = useState<SegmentData | null>(null)
  const [mergeConfirm, setMergeConfirm] = useState<SegmentData[] | null>(null)
  const [splitIdx, setSplitIdx] = useState(-1)
  const [splitTime, setSplitTime] = useState<number | null>(null)

  // ── v2 新增 state ──
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null)
  const [inspectorEvent, setInspectorEvent] = useState<EventViewModel | null>(null)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [waveform, setWaveform] = useState<WaveformData | null>(null)
  const [eventViewModels, setEventViewModels] = useState<Record<string, EventViewModel>>({})
  const [passTrace, setPassTrace] = useState<string[]>([])

  const videoRef = useRef<HTMLVideoElement>(null)

  // ── Load ──
  const loadData = useCallback(() => {
    if (!workspace) return
    setLoading(true)
    fetch('/api/speaker/diarization/load', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace }),
    }).then(r => r.json()).then(data => {
      const l = data.speaker_lanes || []
      setLanes(l)
      setAiPatches(data.patches || null)
      setPatchLog(data.patch_log || [])
      if (l.length) {
        const maxEnd = Math.max(...l.flatMap((ln: SpeakerLane) =>
          ln.segments.map((s: SegmentData) => s.end)
        ))
        setTotalDuration(Math.ceil(maxEnd / 10) * 10 || 120)
      }
      setPassTrace(data.pass_trace || [])
      if (data.inspector_data) {
        setEventViewModels(data.inspector_data)
      }
      setError('')
      setLoading(false)
    }).catch(e => { setError(e.message); setLoading(false) })
  }, [workspace])

  useEffect(() => { loadData() }, [loadData])

  // ── Zoom (基于容器真实宽度) ──
  const timelineRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState(800)

  useEffect(() => {
    const el = timelineRef.current
    if (!el) return
    const ro = new ResizeObserver(entries => {
      for (const e of entries) setContainerWidth(e.contentRect.width)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // ── Waveform 加载 ──
  useEffect(() => {
    if (!workspace) return
    fetch(`/api/speaker/diarization/waveform?workspace=${encodeURIComponent(workspace)}`)
      .then(r => r.json()).then(setWaveform).catch(() => setWaveform(null))
  }, [workspace])

  // ── EventViewModel 工厂 ──
  const buildEventView = useCallback((seg: SegmentData, lane: SpeakerLane): EventViewModel => {
    return eventViewModels[seg.id] || {
      id: seg.id, start: seg.start, end: seg.end,
      speaker: lane.speaker, displayName: lane.display_name,
      text: seg.text, translation: seg.translation || '',
      source: 'asr', confidence: 1.0,
      visualState: {
        hasPatches: false, hasAiSuggestion: false,
        isSelected: false, isMultiSelected: false,
      },
      patches: [], passTrace,
    }
  }, [eventViewModels, passTrace])

  const pixelsPerSec = useMemo(() => {
    if (zoomSeconds <= 0 || containerWidth <= 0) return 1
    return containerWidth / zoomSeconds
  }, [zoomSeconds, containerWidth])

  const totalWidth = totalDuration * pixelsPerSec
  const px = useCallback((s: number) => s * pixelsPerSec, [pixelsPerSec])

  // ── API ──
  const api = async (url: string, body: object) => {
    const r = await fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!r.ok) throw new Error((await r.json().catch(() => ({ detail: r.statusText }))).detail)
    return r.json()
  }

  // ── Video playback ──
  const [videoDuration, setVideoDuration] = useState(0)
  const play = useCallback((seg: SegmentData) => {
    const v = videoRef.current
    if (!v) return
    v.currentTime = Math.max(0, seg.start - 0.3)
    v.play().catch(() => {})
    setPlaying(true)
    setPlayTime(seg.start)
  }, [])

  const togglePlay = useCallback(() => {
    const v = videoRef.current
    if (!v) return
    if (v.paused) { v.play().catch(() => {}); setPlaying(true) }
    else { v.pause(); setPlaying(false) }
  }, [])

  const skip = useCallback((sec: number) => {
    const v = videoRef.current
    if (!v) return
    v.currentTime = Math.max(0, Math.min(v.duration || 0, v.currentTime + sec))
    setPlayTime(v.currentTime)
  }, [])

  const stop = useCallback(() => {
    videoRef.current?.pause()
    setPlaying(false)
  }, [])

  const handleVideoTimeUpdate = useCallback(() => {
    const v = videoRef.current
    if (v && !v.paused) setPlayTime(v.currentTime)
  }, [])

  const handleVideoLoaded = useCallback(() => {
    setVideoDuration(videoRef.current?.duration || 0)
  }, [])

  useEffect(() => () => stop(), [])

  // Keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.code === 'Space') { e.preventDefault(); togglePlay() }
      if (e.code === 'ArrowLeft') { e.preventDefault(); skip(-2) }
      if (e.code === 'ArrowRight') { e.preventDefault(); skip(2) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [togglePlay, skip])

  const fmtTime = (s: number) => {
    const m = Math.floor(s / 60), sec = s % 60
    return `${m}:${sec.toFixed(1).padStart(4, '0')}`
  }

  // ── Undo ──
  const undo = async () => {
    setUndoing(true)
    try { await api('/api/timeline/patch/undo', { workspace }); loadData() }
    catch (e: any) { alert(e.message) }
    finally { setUndoing(false) }
  }

  // ── Apply patch ──
  const applyPatch = async (p: TimelinePatchData) => {
    try { await api('/api/timeline/patch/apply', { workspace, patch: p }); loadData() }
    catch (e: any) { alert(e.message) }
  }

  // ── Split ──
  const doSplit = async () => {
    if (!splitConfirm) return
    const point = splitTime ?? (splitConfirm.start + (splitConfirm.end - splitConfirm.start) / 2)
    await applyPatch({
      patch_id: `sp_${Date.now()}`, opcode: 'SPLIT',
      targets: [splitConfirm.id], payload: { split_point: point },
      reason: ['user_split'], score: 1, confidence: 1,
      parent_version: '', idempotency_key: '', author: 'user',
      timestamp: new Date().toISOString(),
    })
    setSplitConfirm(null)
    setSplitTime(null); setSplitIdx(-1)
  }

  // ── Merge ──
  const startMerge = () => {
    if (multiSelect.size >= 2) {
      const allSegs = lanes.flatMap(l => l.segments)
      const selected = allSegs.filter(s => multiSelect.has(s.id))
      setMergeConfirm(selected)
    }
  }
  const doMerge = async () => {
    if (!mergeConfirm || mergeConfirm.length < 2) return
    await applyPatch({
      patch_id: `mg_${Date.now()}`, opcode: 'MERGE',
      targets: mergeConfirm.map(s => s.id),
      payload: {}, reason: ['user_merge'], score: 1, confidence: 1,
      parent_version: '', idempotency_key: '', author: 'user',
      timestamp: new Date().toISOString(),
    })
    setMergeConfirm(null)
    setMultiSelect(new Set())
  }

  const aiCount = (aiPatches?.high?.length || 0) + (aiPatches?.medium?.length || 0)
  const totalSegs = lanes.reduce((s, l) => s + l.segment_count, 0)

  // ── Render ──
  if (loading) return <Card sx={{ p: 3 }}><Typography>加载中...</Typography></Card>
  if (error) return <Card sx={{ p: 3 }}><Alert severity="error">{error}</Alert></Card>
  if (!lanes.length) {
    return (
      <Card sx={{ p: 3 }}>
        <SectionHeader title="说话人审核" />
        <Alert severity="info">
          {workspace
            ? '当前工作目录未检测到 Timeline 数据。请先运行字幕提取。'
            : '请先选择一个视频开始处理。'}
        </Alert>
      </Card>
    )
  }

  return (
    <Card sx={{ p: 2 }}>
      {/* ── Header ── */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
        <SectionHeader title={`说话人审核 (${lanes.length} 人, ${totalSegs} 段)`} />
        <Box sx={{ flexGrow: 1 }} />
        <Tooltip title="刷新数据">
          <IconButton onClick={loadData}><RefreshIcon /></IconButton>
        </Tooltip>
        {aiCount > 0 && (
          <Badge badgeContent={aiCount} color="warning">
            <IconButton onClick={() => setAiOpen(true)} color="warning"><AutoAwesomeIcon /></IconButton>
          </Badge>
        )}
        <Tooltip title="撤销 (Ctrl+Z)">
          <span><IconButton disabled={patchLog.length === 0 || undoing} onClick={undo}><UndoIcon /></IconButton></span>
        </Tooltip>
        <Button size="small" variant="outlined" startIcon={<AutoAwesomeIcon />}
          onClick={() => setAiOpen(true)} disabled={aiCount === 0}>
          AI 建议{aiCount > 0 ? ` (${aiCount})` : ''}
        </Button>
        {multiSelect.size >= 2 && (
          <Button size="small" variant="contained" color="warning" onClick={startMerge}>
            合并选中 ({multiSelect.size})
          </Button>
        )}
      </Box>

      {/* ── Zoom + Playhead ── */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
        <ZoomOutIcon fontSize="small" />
        <Slider size="small" min={10} max={Math.max(totalDuration, 30)} value={zoomSeconds}
          onChange={(_, v) => setZoomSeconds(v as number)} sx={{ width: 200 }} />
        <ZoomInIcon fontSize="small" />
        <Typography variant="caption" color="text.secondary">
          视口 {zoomSeconds}s / 总计 {totalDuration.toFixed(0)}s
        </Typography>
        {playing && (
          <Chip size="small" icon={<PauseIcon />} label={`${playTime.toFixed(1)}s`}
            onDelete={stop} color="primary" />
        )}
      </Box>

      {/* ── Timeline ── */}
      <Box ref={timelineRef} sx={{ overflowX: 'auto', overflowY: 'hidden', border: '1px solid #e0e0e0', borderRadius: 1 }}>
        <Box sx={{ minWidth: totalWidth, position: 'relative' }}>
          {/* Time ruler */}
          <Box sx={{ height: 18, borderBottom: '1px solid #e0e0e0', bgcolor: '#fafafa', position: 'relative' }}>
            {Array.from({ length: Math.ceil(totalDuration / 10) }, (_, i) => (
              <Typography key={i} variant="caption" sx={{
                position: 'absolute', left: px(i * 10), top: 1,
                fontSize: '0.55rem', color: '#aaa',
              }}>{i * 10}s</Typography>
            ))}
          </Box>

          {/* Lanes */}
          {lanes.map(lane => (
            <Box key={lane.speaker} sx={{
              display: 'flex', height: LANE_HEIGHT,
              borderBottom: '1px solid #f0f0f0',
              bgcolor: selectedSeg && lane.segments.some(s => s.id === selectedSeg)
                ? '#f5f5f5' : 'transparent',
            }}>
              {/* Label — 增强: Tooltip 信息卡 */}
              <Tooltip title={
                <Box>
                  <Typography variant="body2"><b>{lane.speaker}</b></Typography>
                  <Typography variant="caption" display="block">
                    显示名: {speakerNames[lane.speaker] || lane.display_name}
                  </Typography>
                  <Typography variant="caption" display="block">
                    voice_id: {lane.voice_id || '未配置'}
                  </Typography>
                  <Typography variant="caption" display="block">
                    segments: {lane.segment_count}
                  </Typography>
                  <Typography variant="caption" display="block">
                    时长: {lane.total_duration.toFixed(1)}s
                  </Typography>
                </Box>
              } arrow placement="right">
                <Box sx={{
                  width: LABEL_WIDTH, minWidth: LABEL_WIDTH,
                  display: 'flex', alignItems: 'center', gap: 0.5,
                  px: 1, borderRight: '1px solid #e0e0e0', bgcolor: '#fafafa',
                  position: 'sticky', left: 0, zIndex: 5,
                }}>
                  <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: lane.color, flexShrink: 0 }} />
                  <Typography sx={{ fontSize: '0.72rem', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {speakerNames[lane.speaker] || lane.display_name}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>
                    {lane.segment_count}
                  </Typography>
                </Box>
              </Tooltip>

              {/* Segments — 增强: 波形层 + EventBlock */}
              <Box sx={{ flexGrow: 1, position: 'relative', height: LANE_HEIGHT }}>
                {playing && (
                  <Box sx={{ position: 'absolute', left: px(playTime), top: 0, bottom: 0,
                    width: 2, bgcolor: 'red', zIndex: 10, pointerEvents: 'none' }} />
                )}
                {waveform && (
                  <WaveformLayer width={totalWidth} height={LANE_HEIGHT}
                    peaks={waveform.peaks} duration={waveform.duration} pixelsPerSec={pixelsPerSec} />
                )}
                {lane.segments.map(seg => {
                  const evm = buildEventView(seg, lane)
                  evm.visualState.isSelected = selectedSeg === seg.id
                  evm.visualState.isMultiSelected = multiSelect.has(seg.id)
                  return (
                    <EventBlock key={seg.id} event={evm} laneColor={lane.color}
                      left={px(seg.start)} width={Math.max(px(seg.end) - px(seg.start), 3)}
                      laneHeight={LANE_HEIGHT}
                      isSelected={evm.visualState.isSelected}
                      isMultiSelected={evm.visualState.isMultiSelected}
                      onClick={() => {
                        if (multiSelect.size > 0) {
                          const n = new Set(multiSelect)
                          n.has(seg.id) ? n.delete(seg.id) : n.add(seg.id)
                          setMultiSelect(n)
                        } else {
                          setSelectedSeg(s => s === seg.id ? null : seg.id)
                          setInspectorEvent(evm); setInspectorOpen(true)
                          play(seg)
                        }
                      }}
                      onDoubleClick={() => setSplitConfirm(seg)}
                      onContextMenu={(e: React.MouseEvent) => {
                        e.preventDefault()
                        setContextMenu({ mouseX: e.clientX - 2, mouseY: e.clientY - 4, event: evm })
                      }}
                    />
                  )
                })}
              </Box>
            </Box>
          ))}
        </Box>
      </Box>

      {/* ── Inspector panel (替换原 detail bar) ── */}
      <EventInspector event={inspectorEvent} open={inspectorOpen}
        onClose={() => setInspectorOpen(false)}
        onSplit={() => {
          const seg = lanes.flatMap(l => l.segments).find(s => s.id === inspectorEvent?.id)
          if (seg) setSplitConfirm(seg)
        }}
        onMergePrev={() => {
          if (!inspectorEvent) return
          const all = lanes.flatMap(l => l.segments.map(s => ({ ...s, laneSpeaker: l.speaker })))
          const idx = all.findIndex(s => s.id === inspectorEvent!.id)
          if (idx > 0 && all[idx - 1].laneSpeaker === inspectorEvent!.speaker) {
            setMergeConfirm([all[idx - 1], all[idx]])
          }
        }}
        onEditTranslation={() => {
          const newTrans = prompt('输入新翻译:', inspectorEvent?.translation || '')
          if (newTrans !== null && inspectorEvent) {
            applyPatch({
              patch_id: `ed_${Date.now()}`, opcode: 'SET_TRANSLATION',
              targets: [inspectorEvent.id],
              payload: { translation: newTrans },
              reason: ['user_edit'], score: 1, confidence: 1,
              parent_version: '', idempotency_key: '', author: 'user',
              timestamp: new Date().toISOString(),
            })
          }
        }}
        onRetagSpeaker={() => {
          const newSpk = prompt('输入说话人 ID:', inspectorEvent?.speaker || '')
          if (newSpk !== null && inspectorEvent) {
            applyPatch({
              patch_id: `rs_${Date.now()}`, opcode: 'RETAG_SPEAKER',
              targets: [inspectorEvent.id],
              payload: { new_speaker: newSpk },
              reason: ['user_retag'], score: 1, confidence: 1,
              parent_version: '', idempotency_key: '', author: 'user',
              timestamp: new Date().toISOString(),
            })
          }
        }}
      />

      {/* ── Context Menu ── */}
      <Menu open={contextMenu !== null}
        onClose={() => setContextMenu(null)}
        anchorReference="anchorPosition"
        anchorPosition={contextMenu ? { top: contextMenu.mouseY, left: contextMenu.mouseX } : undefined}>
        <MenuItem onClick={() => {
          if (contextMenu?.event) {
            const seg = lanes.flatMap(l => l.segments).find(s => s.id === contextMenu!.event!.id)
            if (seg) { setSplitConfirm(seg); setContextMenu(null) }
          }
        }}>
          <ListItemIcon><SplitIcon fontSize="small" /></ListItemIcon> 在此切分 (SPLIT)
        </MenuItem>
        <MenuItem onClick={() => {
          if (contextMenu?.event) {
            const all = lanes.flatMap(l => l.segments.map(s => ({ ...s, laneSpeaker: l.speaker })))
            const idx = all.findIndex(s => s.id === contextMenu!.event!.id)
            if (idx > 0 && all[idx - 1].laneSpeaker === contextMenu!.event!.speaker) {
              setMergeConfirm([all[idx - 1], all[idx]])
            }
            setContextMenu(null)
          }
        }}>
          <ListItemIcon><MergeIcon fontSize="small" /></ListItemIcon> 与上段合并 (MERGE)
        </MenuItem>
        <MuiDivider />
        <MenuItem onClick={() => {
          const newTrans = prompt('输入新翻译:', contextMenu?.event?.translation || '')
          if (newTrans !== null && contextMenu?.event) {
            applyPatch({
              patch_id: `ed_${Date.now()}`, opcode: 'SET_TRANSLATION',
              targets: [contextMenu.event.id],
              payload: { translation: newTrans },
              reason: ['user_edit'], score: 1, confidence: 1,
              parent_version: '', idempotency_key: '', author: 'user',
              timestamp: new Date().toISOString(),
            })
          }
          setContextMenu(null)
        }}>
          <ListItemIcon><EditIcon fontSize="small" /></ListItemIcon> 编辑翻译 (REPLACE)
        </MenuItem>
        <MenuItem onClick={() => {
          const newSpk = prompt('输入说话人 ID:', contextMenu?.event?.speaker || '')
          if (newSpk !== null && contextMenu?.event) {
            applyPatch({
              patch_id: `rs_${Date.now()}`, opcode: 'RETAG_SPEAKER',
              targets: [contextMenu.event.id],
              payload: { new_speaker: newSpk },
              reason: ['user_retag'], score: 1, confidence: 1,
              parent_version: '', idempotency_key: '', author: 'user',
              timestamp: new Date().toISOString(),
            })
          }
          setContextMenu(null)
        }}>
          <ListItemIcon><VoiceIcon fontSize="small" /></ListItemIcon> 重标说话人 (RETAG)
        </MenuItem>
        <MuiDivider />
        <MenuItem onClick={() => {
          setInspectorEvent(contextMenu?.event || null)
          setInspectorOpen(true)
          setContextMenu(null)
        }}>
          <ListItemIcon><InfoIcon fontSize="small" /></ListItemIcon> 查看 Inspector
        </MenuItem>
      </Menu>

      {/* ── Minimap 缩略概览条 ── */}
      {totalDuration > 0 && (
        <Box sx={{ mx: 1, mt: 1, height: 20, bgcolor: '#f0f0f0', borderRadius: 1,
          position: 'relative', overflow: 'hidden' }}>
          {lanes.flatMap(l => l.segments).map(seg => (
            <Box key={seg.id} sx={{
              position: 'absolute', left: `${(seg.start / totalDuration) * 100}%`,
              width: `${Math.max(((seg.end - seg.start) / totalDuration) * 100, 0.5)}%`,
              height: '100%',
              bgcolor: lanes.find(l => l.segments.some(s => s.id === seg.id))?.color || '#ccc',
              opacity: 0.6, cursor: 'pointer',
              '&:hover': { opacity: 1 },
            }} onClick={() => {
              const v = videoRef.current
              if (v) { v.currentTime = seg.start; v.play().catch(() => {}) }
            }} />
          ))}
          <Box sx={{ position: 'absolute',
            left: `${(playTime / totalDuration) * 100}%`,
            width: `${(zoomSeconds / totalDuration) * 100}%`,
            height: '100%', border: '2px solid red', borderRadius: 0.5,
            bgcolor: 'transparent', pointerEvents: 'none' }} />
        </Box>
      )}

      {/* ── Split Dialog (词级选择) ── */}
      <Dialog open={!!splitConfirm} onClose={() => { setSplitConfirm(null); setSplitTime(null); setSplitIdx(-1) }}
        maxWidth="sm" fullWidth>
        <DialogTitle>选择拆分位置</DialogTitle>
        <DialogContent>
          {splitConfirm?.words && splitConfirm.words.length > 0 ? (
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.3, alignItems: 'center', my: 2 }}>
              {splitConfirm.words.map((w, i) => (
                <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: 0 }}>
                  {i > 0 && (
                    <Box sx={{
                      width: 6, height: 22, cursor: 'pointer', mx: 0.2,
                      bgcolor: splitIdx === i - 1 ? '#FF5722' : '#ccc',
                      borderRadius: 0.5,
                      '&:hover': { bgcolor: '#FF5722', transform: 'scaleY(1.6)' },
                      transition: 'all 0.15s',
                    }}
                      onClick={() => { setSplitIdx(i - 1); setSplitTime(w.start) }}
                      title={`在此切分 (${w.start.toFixed(2)}s)`}
                    />
                  )}
                  <Chip label={w.word} size="small"
                    sx={{
                      bgcolor: splitIdx === i - 1 ? '#FF9800' : splitIdx === i ? '#e0e0e0' : '#f5f5f5',
                      color: splitIdx === i - 1 ? '#fff' : 'inherit',
                    }} />
                </Box>
              ))}
              {/* 最后一个词后的分隔符 */}
              {splitConfirm.words.length > 0 && (() => {
                const lastW = splitConfirm.words[splitConfirm.words.length - 1]
                return (
                  <Box sx={{
                    width: 6, height: 22, cursor: 'pointer', mx: 0.2,
                    bgcolor: splitIdx === splitConfirm.words.length - 1 ? '#FF5722' : '#ccc',
                    borderRadius: 0.5,
                    '&:hover': { bgcolor: '#FF5722', transform: 'scaleY(1.6)' },
                    transition: 'all 0.15s',
                  }}
                    onClick={() => { setSplitIdx(splitConfirm.words!.length - 1); setSplitTime(lastW.end) }}
                    title={`在此切分 (${lastW.end.toFixed(2)}s)`}
                  />
                )
              })()}
            </Box>
          ) : (
            <Box sx={{ my: 2 }}>
              <Typography variant="caption" color="text.secondary">
                无词级数据，拖动选择拆分时间:
              </Typography>
              <Slider min={splitConfirm?.start ?? 0} max={splitConfirm?.end ?? 0}
                step={0.05}
                value={splitTime ?? (splitConfirm ? (splitConfirm.start + splitConfirm.end) / 2 : 0)}
                onChange={(_, v) => { setSplitTime(v as number); setSplitIdx(-1) }}
                valueLabelDisplay="auto" valueLabelFormat={v => `${(v as number).toFixed(2)}s`}
                sx={{ mt: 1 }} />
            </Box>
          )}

          {splitTime !== null && (
            <Box sx={{ mt: 1, p: 1, bgcolor: '#FFF3E0', borderRadius: 1 }}>
              <Typography variant="caption" color="text.secondary">
                拆分时间: <b>{splitTime.toFixed(2)}s</b>
              </Typography>
            </Box>
          )}

          {/* 左右预览 */}
          <Box sx={{ display: 'flex', gap: 2, mt: 1.5 }}>
            <Box sx={{ flex: 1, p: 1, bgcolor: '#f5f5f5', borderRadius: 1 }}>
              <Typography variant="caption" color="text.secondary">左段</Typography>
              <Typography variant="body2" sx={{ fontSize: '0.8rem' }}>
                {splitTime !== null && splitConfirm
                  ? (splitConfirm.words
                    ? splitConfirm.words.filter(w => w.end <= splitTime).map(w => w.word).join(' ')
                    : splitConfirm.text.slice(0, Math.floor((splitTime - splitConfirm.start) / (splitConfirm.end - splitConfirm.start) * splitConfirm.text.length))
                    )
                  : splitConfirm?.text}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {splitConfirm?.start.toFixed(1)}s - {splitTime?.toFixed(1) ?? '?'}s
              </Typography>
            </Box>
            <Box sx={{ flex: 1, p: 1, bgcolor: '#f5f5f5', borderRadius: 1 }}>
              <Typography variant="caption" color="text.secondary">右段</Typography>
              <Typography variant="body2" sx={{ fontSize: '0.8rem' }}>
                {splitTime !== null && splitConfirm
                  ? (splitConfirm.words
                    ? splitConfirm.words.filter(w => w.start >= splitTime).map(w => w.word).join(' ')
                    : splitConfirm.text.slice(Math.floor((splitTime - splitConfirm.start) / (splitConfirm.end - splitConfirm.start) * splitConfirm.text.length))
                    )
                  : ''}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {splitTime?.toFixed(1) ?? '?'}s - {splitConfirm?.end.toFixed(1)}s
              </Typography>
            </Box>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setSplitConfirm(null); setSplitTime(null); setSplitIdx(-1) }}>取消</Button>
          <Button variant="contained" onClick={doSplit}>确认拆分</Button>
        </DialogActions>
      </Dialog>
      <Dialog open={!!mergeConfirm} onClose={() => setMergeConfirm(null)}>
        <DialogTitle>确认合并</DialogTitle>
        <DialogContent>
          <Typography>合并以下 {mergeConfirm?.length} 个 segments？</Typography>
          {mergeConfirm?.map(s => (
            <Typography key={s.id} variant="caption" display="block">
              · {s.text} ({s.start.toFixed(1)}s-{s.end.toFixed(1)}s)
            </Typography>
          ))}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setMergeConfirm(null)}>取消</Button>
          <Button variant="contained" onClick={doMerge}>合并</Button>
        </DialogActions>
      </Dialog>

      {/* ── AI Drawer ── */}
      <Drawer anchor="right" open={aiOpen} onClose={() => setAiOpen(false)}>
        <Box sx={{ width: 360, p: 2 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            <AutoAwesomeIcon sx={{ mr: 1, verticalAlign: 'middle' }} color="warning" />
            AI 建议
          </Typography>
          {(aiPatches?.high?.length || aiPatches?.medium?.length) ? (
            <>
              {aiPatches!.high!.map((p, i) => (
                <Card key={`h${i}`} sx={{ p: 1, mb: 1, borderLeft: '4px solid #4CAF50' }}>
                  <Typography variant="body2"><b>{p.opcode}</b> — {p.reason?.join(', ')}</Typography>
                  <Typography variant="caption" color="text.secondary">
                    置信度 {(p.confidence * 100).toFixed(0)}% | {p.targets?.join(', ')}
                  </Typography>
                  <Button size="small" variant="contained" color="success"
                    onClick={() => applyPatch(p)} sx={{ mt: 0.5 }}>应用</Button>
                </Card>
              ))}
              {aiPatches!.medium!.map((p, i) => (
                <Card key={`m${i}`} sx={{ p: 1, mb: 1, borderLeft: '4px solid #FF9800' }}>
                  <Typography variant="body2"><b>{p.opcode}</b> — {p.reason?.join(', ')}</Typography>
                  <Typography variant="caption" color="text.secondary">
                    置信度 {(p.confidence * 100).toFixed(0)}% | {p.targets?.join(', ')}
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 0.5, mt: 0.5 }}>
                    <Button size="small" variant="contained" onClick={() => applyPatch(p)}>应用</Button>
                    <Button size="small" onClick={() => {}}>忽略</Button>
                  </Box>
                </Card>
              ))}
            </>
          ) : <Alert severity="info">暂无可用的 AI 建议。</Alert>}

          {patchLog.length > 0 && (
            <Box sx={{ mt: 3 }}>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>操作历史 ({patchLog.length})</Typography>
              <List dense>
                {[...patchLog].reverse().slice(0, 20).map((p, i) => (
                  <ListItem key={i}>
                    <ListItemText primary={`${p.opcode} → ${p.targets?.join(', ')}`}
                      secondary={`${p.author} · ${new Date(p.timestamp).toLocaleTimeString()}`} />
                  </ListItem>
                ))}
              </List>
            </Box>
          )}
        </Box>
      </Drawer>

      {/* Video player — compact, fixed width */}
      {videoPath && (
        <Box sx={{ mt: 1, display: 'flex', gap: 1, alignItems: 'flex-start' }}>
          {/* Video panel */}
          <Card sx={{ width: 340, minWidth: 340, bgcolor: '#111', borderRadius: 2,
            overflow: 'hidden', position: 'relative' }}>
            <video ref={videoRef} src={`/api/files/stream?path=${encodeURIComponent(videoPath)}`}
              onTimeUpdate={handleVideoTimeUpdate} onEnded={stop}
              onLoadedMetadata={handleVideoLoaded}
              onClick={togglePlay}
              style={{ width: '100%', display: 'block', cursor: 'pointer' }} />
            {/* Custom controls overlay */}
            <Box sx={{
              display: 'flex', alignItems: 'center', gap: 1, px: 1, py: 0.5,
              bgcolor: 'rgba(0,0,0,0.75)', color: '#fff',
            }}>
              <IconButton size="small" onClick={() => skip(-5)} sx={{ color: '#fff' }}>
                <Typography variant="caption">-5s</Typography>
              </IconButton>
              <IconButton size="small" onClick={togglePlay} sx={{ color: '#fff' }}>
                {playing ? <PauseIcon /> : <PlayIcon />}
              </IconButton>
              <IconButton size="small" onClick={() => skip(5)} sx={{ color: '#fff' }}>
                <Typography variant="caption">+5s</Typography>
              </IconButton>
              <Typography variant="caption" sx={{ flexGrow: 1, textAlign: 'center', fontFamily: 'monospace' }}>
                {fmtTime(playTime)} / {fmtTime(videoDuration)}
              </Typography>
            </Box>
          </Card>
          {/* Quick info */}
          <Card sx={{ flex: 1, p: 1.5, minWidth: 180 }}>
            <Typography variant="subtitle2" sx={{ mb: 0.5 }}>键盘快捷键</Typography>
            <Typography variant="caption" display="block">Space — 播放/暂停</Typography>
            <Typography variant="caption" display="block">← → — 快退/进 2s</Typography>
            <Typography variant="caption" display="block">点击时间轴 — 定位播放</Typography>
            <Typography variant="caption" display="block">双击片段 — 切分</Typography>
            <Typography variant="caption" display="block">Ctrl+点击 — 多选合并</Typography>
          </Card>
        </Box>
      )}
    </Card>
  )
}
