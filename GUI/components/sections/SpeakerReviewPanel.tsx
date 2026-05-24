import { useState, useCallback, useMemo, useRef, useEffect } from 'react'
import {
  Box, Typography, Card, IconButton, Tooltip, Alert, Chip,
  Button, Slider, Dialog, DialogTitle, DialogContent, DialogActions,
  Badge, Drawer, List, ListItem, ListItemText,
} from '@mui/material'
import PauseIcon from '@mui/icons-material/PauseRounded'
import UndoIcon from '@mui/icons-material/UndoRounded'
import SplitIcon from '@mui/icons-material/CallSplitRounded'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesomeRounded'
import ZoomInIcon from '@mui/icons-material/ZoomInRounded'
import ZoomOutIcon from '@mui/icons-material/ZoomOutRounded'
import RefreshIcon from '@mui/icons-material/RefreshRounded'
import { SectionHeader } from '../SectionHeader'
import type { TimelinePatchData, PatchGenerateResponse } from '../../types'

const LANE_HEIGHT = 52
const LABEL_WIDTH = 110

interface SegmentData {
  id: string; start: number; end: number; text: string
  translation: string; overlap: boolean
}

interface SpeakerLane {
  speaker: string; display_name: string; voice_id: string
  color: string; segments: SegmentData[]; segment_count: number; total_duration: number
}

interface Props {
  workspace: string
  speakers: string[]
  timeline: any[]
  verification: any | null
  speakerNames: Record<string, string>
  onTimelineChange?: (tl: any[]) => void
  onSaveCorrections?: (tl: any[], c: unknown[]) => void
}

export default function SpeakerReviewPanel({
  workspace, speakerNames,
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

  const playRef = useRef<number | null>(null)

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
      setError('')
      setLoading(false)
    }).catch(e => { setError(e.message); setLoading(false) })
  }, [workspace])

  useEffect(() => { loadData() }, [loadData])

  // ── Zoom ──
  const pixelsPerSec = useMemo(() => {
    const w = Math.max(800, window.innerWidth - 200)
    return w / zoomSeconds
  }, [zoomSeconds])

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

  // ── Audio ──
  const play = (seg: SegmentData) => {
    stop()
    setPlayTime(seg.start)
    setPlaying(true)
    const t0 = Date.now() - seg.start * 1000
    playRef.current = window.setInterval(() => {
      const t = (Date.now() - t0) / 1000
      if (t > seg.end) { stop(); return }
      setPlayTime(t)
    }, 50)
  }
  const stop = () => {
    setPlaying(false)
    if (playRef.current) { clearInterval(playRef.current); playRef.current = null }
  }
  useEffect(() => () => stop(), [])

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
    const mid = splitConfirm.start + (splitConfirm.end - splitConfirm.start) / 2
    await applyPatch({
      patch_id: `sp_${Date.now()}`, opcode: 'SPLIT',
      targets: [splitConfirm.id], payload: { split_point: mid },
      reason: ['user_split'], score: 1, confidence: 1,
      parent_version: '', idempotency_key: '', author: 'user',
      timestamp: new Date().toISOString(),
    })
    setSplitConfirm(null)
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
      <Box sx={{ overflowX: 'auto', overflowY: 'hidden', border: '1px solid #e0e0e0', borderRadius: 1 }}>
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
              {/* Label */}
              <Box sx={{
                width: LABEL_WIDTH, minWidth: LABEL_WIDTH,
                display: 'flex', alignItems: 'center', gap: 0.5,
                px: 1, borderRight: '1px solid #e0e0e0', bgcolor: '#fafafa',
              }}>
                <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: lane.color, flexShrink: 0 }} />
                <Typography sx={{ fontSize: '0.72rem', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {speakerNames[lane.speaker] || lane.display_name}
                </Typography>
                <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>
                  {lane.segment_count}
                </Typography>
              </Box>

              {/* Segments */}
              <Box sx={{ flexGrow: 1, position: 'relative', height: LANE_HEIGHT }}>
                {playing && (
                  <Box sx={{ position: 'absolute', left: px(playTime), top: 0, bottom: 0,
                    width: 2, bgcolor: 'red', zIndex: 10, pointerEvents: 'none' }} />
                )}
                {lane.segments.map(seg => {
                  const left = px(seg.start)
                  const width = Math.max(px(seg.end) - left, 3)
                  const sel = selectedSeg === seg.id || multiSelect.has(seg.id)
                  return (
                    <Box key={seg.id} sx={{
                      position: 'absolute', left, top: 6, width, height: LANE_HEIGHT - 12,
                      bgcolor: sel ? lane.color : `${lane.color}88`,
                      borderRadius: 0.75, display: 'flex', alignItems: 'center',
                      px: 0.75, overflow: 'hidden', cursor: 'pointer',
                      border: sel ? '2px solid #333' : '1px solid transparent',
                      '&:hover': { filter: 'brightness(1.2)', zIndex: 3 },
                      opacity: seg.overlap ? 0.7 : 1,
                    }}
                      onClick={() => {
                        if (multiSelect.size > 0) {
                          const n = new Set(multiSelect)
                          n.has(seg.id) ? n.delete(seg.id) : n.add(seg.id)
                          setMultiSelect(n)
                        } else {
                          setSelectedSeg(s => s === seg.id ? null : seg.id)
                          play(seg)
                        }
                      }}
                      onDoubleClick={() => setSplitConfirm(seg)}
                      title={`${seg.text}\n${seg.translation || ''}\n${seg.start.toFixed(1)}s-${seg.end.toFixed(1)}s`}
                    >
                      {width > 30 && (
                        <Typography sx={{ fontSize: '0.6rem', color: '#fff', whiteSpace: 'nowrap',
                          overflow: 'hidden', textOverflow: 'ellipsis',
                          textShadow: '0 1px 2px rgba(0,0,0,0.4)' }}>
                          {width > 80 && seg.translation ? seg.translation : seg.text}
                        </Typography>
                      )}
                    </Box>
                  )
                })}
              </Box>
            </Box>
          ))}
        </Box>
      </Box>

      {/* ── Detail bar ── */}
      {selectedSeg && (() => {
        const seg = lanes.flatMap(l => l.segments).find(s => s.id === selectedSeg)
        if (!seg) return null
        const lane = lanes.find(l => l.segments.some(s => s.id === seg!.id))
        return (
          <Box sx={{ mt: 1, p: 1, bgcolor: '#f9f9f9', borderRadius: 1, display: 'flex',
            alignItems: 'center', gap: 1, flexWrap: 'wrap', fontSize: '0.8rem' }}>
            <Chip size="small" label={lane?.display_name} sx={{ bgcolor: lane?.color, color: '#fff' }} />
            <b>{seg.text}</b>
            {seg.translation && <Typography variant="body2" color="text.secondary">{seg.translation}</Typography>}
            <Typography variant="caption" color="text.secondary">
              {seg.start.toFixed(1)}s - {seg.end.toFixed(1)}s ({(seg.end - seg.start).toFixed(1)}s)
            </Typography>
            <IconButton size="small" onClick={() => setSplitConfirm(seg)}><SplitIcon fontSize="small" /></IconButton>
          </Box>
        )
      })()}

      {/* ── Dialogs ── */}
      <Dialog open={!!splitConfirm} onClose={() => setSplitConfirm(null)}>
        <DialogTitle>确认切分</DialogTitle>
        <DialogContent>
          <Typography>将 "{splitConfirm?.text}" 在中点切分为两段。</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSplitConfirm(null)}>取消</Button>
          <Button variant="contained" onClick={doSplit}>确认</Button>
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
    </Card>
  )
}
