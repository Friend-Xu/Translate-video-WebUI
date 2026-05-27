import { useState, useEffect, useMemo, useCallback } from 'react'
import {
  Box, Typography, Button, Divider, FormControl, InputLabel, Select, MenuItem,
  Accordion, AccordionSummary, AccordionDetails, TextField, Slider, Chip,
  ToggleButtonGroup, ToggleButton, IconButton, Tooltip, Switch, FormControlLabel,
  Dialog, DialogTitle, DialogContent, DialogActions, LinearProgress,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMoreRounded'
import FileDownloadIcon from '@mui/icons-material/FileDownloadRounded'
import SaveIcon from '@mui/icons-material/SaveRounded'
import ContentCopyIcon from '@mui/icons-material/ContentCopyRounded'
import DeleteIcon from '@mui/icons-material/DeleteRounded'
import OpenInNewIcon from '@mui/icons-material/OpenInNewRounded'
import FolderOpenIcon from '@mui/icons-material/FolderOpenRounded'
import CheckCircleIcon from '@mui/icons-material/CheckCircleRounded'
import WarningIcon from '@mui/icons-material/WarningRounded'
import ErrorIcon from '@mui/icons-material/ErrorRounded'
import InfoIcon from '@mui/icons-material/InfoRounded'
import SettingsIcon from '@mui/icons-material/SettingsRounded'
import TuneIcon from '@mui/icons-material/TuneRounded'
import { useAppStore } from '../../store/useAppStore'
import type {
  EventViewModel, ExportPreset,
  ExportReadinessCheck, ExportReadinessWarning,
} from '../../types'
import {
  DEFAULT_VIDEO_EXPORT, DEFAULT_SUBTITLE_EXPORT, DEFAULT_AUDIO_EXPORT,
  DEFAULT_OUTPUT_NAMING, DEFAULT_QUALITY_EXPORT, BUILTIN_EXPORT_PRESETS,
} from '../../types'

interface Props {
  events: EventViewModel[]
}

// ── Readiness check ──
function computeReadiness(
  events: EventViewModel[],
  draftsCount: number,
  unboundSpeakers: string[],
  failedBatchCount: number,
): ExportReadinessCheck {
  const warnings: ExportReadinessWarning[] = []
  const lowConfidence = events.filter(e => e.confidence < 0.7)
  const lowConfidenceCount = lowConfidence.length

  if (lowConfidenceCount > 0) {
    warnings.push({
      severity: 'warning',
      message: `${lowConfidenceCount} 个事件置信度低于 0.7`,
      action: { label: '在 Timeline 中修复', mode: 'timeline' },
    })
  }
  if (draftsCount > 0) {
    warnings.push({
      severity: 'warning',
      message: `${draftsCount} 个补丁尚未应用`,
      action: { label: '查看补丁', mode: 'patch' },
    })
  }
  if (unboundSpeakers.length > 0) {
    warnings.push({
      severity: 'warning',
      message: `${unboundSpeakers.length} 个声线未绑定: ${unboundSpeakers.slice(0, 3).join(', ')}`,
      action: { label: '绑定声线', mode: 'timeline' },
    })
  }
  if (failedBatchCount > 0) {
    warnings.push({
      severity: 'error',
      message: `${failedBatchCount} 个批处理任务失败，建议先重试`,
      action: { label: '查看队列', mode: 'batch' },
    })
  }

  return {
    totalEvents: events.length,
    lowConfidenceCount,
    unappliedPatches: draftsCount,
    unboundSpeakers: unboundSpeakers.length,
    failedBatchTasks: failedBatchCount,
    warnings,
    isReady: warnings.filter(w => w.severity === 'error').length === 0,
  }
}

// ── Config section accordion wrapper ──
function ConfigSection({
  id, label, modified, expanded, onChange, children,
}: {
  id: string; label: string; modified: boolean; expanded: boolean
  onChange: (id: string) => void; children: React.ReactNode
}) {
  return (
    <Accordion
      expanded={expanded}
      onChange={() => onChange(id)}
      disableGutters
      sx={{
        '&:before': { display: 'none' },
        borderBottom: 1, borderColor: 'divider',
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}
        sx={{ minHeight: 40, '& .MuiAccordionSummary-content': { my: 0.5, alignItems: 'center', gap: 1 } }}>
        <Typography variant="caption" fontWeight={600}>{label}</Typography>
        {modified && <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: 'primary.main' }} />}
      </AccordionSummary>
      <AccordionDetails sx={{ pt: 0, pb: 1.5 }}>
        {children}
      </AccordionDetails>
    </Accordion>
  )
}

// ── Warning icon ──
function SeverityIcon({ severity }: { severity: string }) {
  if (severity === 'error') return <ErrorIcon sx={{ fontSize: 16, color: 'error.main' }} />
  if (severity === 'warning') return <WarningIcon sx={{ fontSize: 16, color: 'warning.main' }} />
  return <InfoIcon sx={{ fontSize: 16, color: 'info.main' }} />
}

export default function ExportView({ events }: Props) {
  const setMode = useAppStore(s => s.setMode)
  const navigateToEvent = useAppStore(s => s.navigateToEvent)
  const pendingDrafts = useAppStore(s => s.pendingDrafts)
  const speakerLanes = useAppStore(s => s.speakerLanes)
  const exportPresets = useAppStore(s => s.exportPresets)
  const activePresetId = useAppStore(s => s.activePresetId)
  const previewText = useAppStore(s => s.exportPreviewText)
  const savePreset = useAppStore(s => s.savePreset)
  const deletePreset = useAppStore(s => s.deletePreset)
  const duplicatePreset = useAppStore(s => s.duplicatePreset)
  const setActivePreset = useAppStore(s => s.setActivePreset)
  const setExportPresets = useAppStore(s => s.setExportPresets)
  const setExportPreviewText = useAppStore(s => s.setExportPreviewText)

  const [advancedMode, setAdvancedMode] = useState(false)
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['video']))
  const [fonts, setFonts] = useState<{ name: string; path: string; isSystem: boolean }[]>([])
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportResult, setExportResult] = useState<{
    success: boolean; outputDir: string; files: { name: string; sizeMb: number }[]; durationSec: number
  } | null>(null)

  // Initialize presets
  useEffect(() => {
    if (exportPresets.length > 0) return
    const builtins = BUILTIN_EXPORT_PRESETS
    let userPresets: ExportPreset[] = []
    try {
      const raw = localStorage.getItem('export-presets')
      if (raw) userPresets = JSON.parse(raw)
    } catch { /* corrupt */ }
    const all = [...builtins, ...userPresets]
    setExportPresets(all)
    if (!activePresetId && all.length > 0) setActivePreset(all[0].id)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Load fonts
  useEffect(() => {
    fetch('/api/fonts').then(r => r.json()).then(d => setFonts(d.fonts || [])).catch(() => {})
  }, [])

  // Current preset
  const activePreset = useMemo(() =>
    exportPresets.find(p => p.id === activePresetId) || exportPresets[0] || null,
  [exportPresets, activePresetId])

  // Derived config
  const video = activePreset?.video ?? DEFAULT_VIDEO_EXPORT
  const subtitle = activePreset?.subtitle ?? DEFAULT_SUBTITLE_EXPORT
  const audio = activePreset?.audio ?? DEFAULT_AUDIO_EXPORT
  const output = activePreset?.output ?? DEFAULT_OUTPUT_NAMING
  const quality = activePreset?.quality ?? DEFAULT_QUALITY_EXPORT

  // Readiness check
  const unboundSpeakers = useMemo(() =>
    speakerLanes.filter(l => !l.voice_id).map(l => l.display_name || l.speaker),
  [speakerLanes])
  const readiness = useMemo(() =>
    computeReadiness(events, pendingDrafts.size, unboundSpeakers, 0),
  [events, pendingDrafts, unboundSpeakers])

  // Subtitle preview URL
  const previewUrl = useMemo(() => {
    if (!subtitle.font && subtitle.mode === 'none') return null
    const params = new URLSearchParams({
      font: subtitle.font || 'simhei',
      font_size: String(subtitle.fontSize || 36),
      font_color: subtitle.fontColor,
      stroke_color: subtitle.strokeColor,
      stroke_width: String(subtitle.strokeWidth),
      bg_color: subtitle.bgColor,
      text_zh: previewText.zh,
      text_en: subtitle.bilingual ? previewText.en : '',
      alignment: subtitle.alignment,
      position: subtitle.position,
      engine: 'pil',
      max_lines: String(subtitle.maxLines),
      font_size_factor: String(subtitle.fontSizeFactor),
      max_font_size: String(subtitle.maxFontSize),
      caption_width_ratio: String(subtitle.widthRatio),
      font_size_mode: subtitle.fontSizeMode,
    })
    return `/api/subtitle/preview?${params.toString()}`
  }, [subtitle, previewText])

  // Estimated output size
  const totalDuration = events.length > 0 ? events[events.length - 1].end : 0
  const estimatedSizeMb = useMemo(() => {
    const bitrateMbps = parseInt(quality.videoBitrate.replace(/[^0-9.]/g, '')) || 8
    return Math.round(totalDuration * bitrateMbps / 8 * 1.15) // 15% overhead
  }, [totalDuration, quality.videoBitrate])

  // Toggle section
  const toggleSection = useCallback((id: string) => {
    setExpandedSections(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }, [])

  // Update preset field
  const updatePreset = useCallback(<K extends keyof ExportPreset>(
    section: K, field: string, value: unknown,
  ) => {
    if (!activePreset) return
    const updated: ExportPreset = {
      ...activePreset,
      isBuiltin: false,
      [section]: { ...(activePreset[section] as unknown as Record<string, unknown>), [field]: value },
    }
    savePreset(updated)
  }, [activePreset, savePreset])

  // Handle quick-export click
  const handleExport = useCallback(async () => {
    if (!activePreset) return
    setConfirmOpen(true)
    setExportResult(null)
  }, [activePreset])

  // Confirm export
  const handleConfirmExport = useCallback(async () => {
    setExporting(true)
    // Mock export for now — real implementation would call /api/pipeline/run or /api/batch/run
    await new Promise(r => setTimeout(r, 1500))
    setExporting(false)
    setExportResult({
      success: true,
      outputDir: output.baseDir || 'D:/output/',
      files: [
        { name: 'dubbed.mp4', sizeMb: estimatedSizeMb },
        { name: 'subtitles.srt', sizeMb: 0.01 },
        { name: 'export_config.json', sizeMb: 0.001 },
      ],
      durationSec: 1.5,
    })
  }, [output.baseDir, estimatedSizeMb])

  const severityColor = readiness.isReady ? 'success' : readiness.warnings.some(w => w.severity === 'error') ? 'error' : 'warning'

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* ── Header ── */}
      <Box sx={{
        p: 1, borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper',
        display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap',
      }}>
        <Typography variant="subtitle2" sx={{ mr: 0.5 }}>导出</Typography>

        {/* Preset selector */}
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <Select value={activePresetId || ''}
            onChange={e => setActivePreset(e.target.value || null)}
            displayEmpty
            renderValue={val => {
              const p = exportPresets.find(x => x.id === val)
              return p ? p.name : '选择方案...'
            }}>
            {exportPresets.map(p => (
              <MenuItem key={p.id} value={p.id} dense>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
                  <Typography variant="body2" sx={{ flexGrow: 1 }}>{p.name}</Typography>
                  {p.isBuiltin && <Chip label="内置" size="small" variant="outlined" sx={{ fontSize: '0.55rem', height: 16 }} />}
                </Box>
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <Tooltip title="保存当前方案"><IconButton size="small" onClick={() => activePreset && savePreset({ ...activePreset, updatedAt: new Date().toISOString() })}><SaveIcon sx={{ fontSize: 18 }} /></IconButton></Tooltip>
        <Tooltip title="复制方案"><IconButton size="small" onClick={() => activePresetId && duplicatePreset(activePresetId)}><ContentCopyIcon sx={{ fontSize: 18 }} /></IconButton></Tooltip>
        <Tooltip title="删除方案"><IconButton size="small" onClick={() => activePresetId && !activePreset?.isBuiltin && deletePreset(activePresetId)}><DeleteIcon sx={{ fontSize: 18 }} /></IconButton></Tooltip>

        <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />

        {/* Simple/Advanced toggle */}
        <ToggleButtonGroup value={advancedMode ? 'advanced' : 'simple'} size="small"
          exclusive onChange={(_, v) => v && setAdvancedMode(v === 'advanced')}>
          <ToggleButton value="simple" sx={{ px: 1, fontSize: '0.65rem' }}>
            <TuneIcon sx={{ fontSize: 14, mr: 0.5 }} />快速
          </ToggleButton>
          <ToggleButton value="advanced" sx={{ px: 1, fontSize: '0.65rem' }}>
            <SettingsIcon sx={{ fontSize: 14, mr: 0.5 }} />高级
          </ToggleButton>
        </ToggleButtonGroup>

        <Box sx={{ flexGrow: 1 }} />

        <Button variant="contained" size="small" startIcon={<FileDownloadIcon />}
          onClick={handleExport} disabled={events.length === 0}>
          导出视频
        </Button>
      </Box>

      {/* ── Body: 3 columns ── */}
      <Box sx={{ flexGrow: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Left: Config accordions */}
        <Box sx={{
          width: 300, minWidth: 300, borderRight: 1, borderColor: 'divider',
          overflow: 'hidden auto', bgcolor: 'background.paper',
        }}>
          {/* Video section */}
          <ConfigSection id="video" label="视频封装" modified={false}
            expanded={expandedSections.has('video')} onChange={toggleSection}>
            <FormControl fullWidth size="small" sx={{ mb: 1 }}>
              <InputLabel>容器格式</InputLabel>
              <Select value={video.container}
                label="容器格式"
                onChange={e => updatePreset('video', 'container', e.target.value)}>
                <MenuItem value="mp4">MP4</MenuItem>
                <MenuItem value="mkv">MKV (崩溃安全)</MenuItem>
              </Select>
            </FormControl>
            <FormControl fullWidth size="small" sx={{ mb: 1 }}>
              <InputLabel>视频编码</InputLabel>
              <Select value={video.videoCodec}
                label="视频编码"
                onChange={e => updatePreset('video', 'videoCodec', e.target.value)}>
                <MenuItem value="libx264">H.264</MenuItem>
                <MenuItem value="h265">H.265 / HEVC</MenuItem>
              </Select>
            </FormControl>
            <FormControlLabel
              control={<Switch size="small" checked={video.reencode}
                onChange={e => updatePreset('video', 'reencode', e.target.checked)} />}
              label={<Typography variant="caption">重新编码</Typography>}
              sx={{ '& .MuiFormControlLabel-label': { mt: 0 } }}
            />
            {video.reencode && (
              <Box sx={{ mt: 0.5 }}>
                <FormControlLabel
                  control={<Switch size="small" checked={video.preserveResolution}
                    onChange={e => updatePreset('video', 'preserveResolution', e.target.checked)} />}
                  label={<Typography variant="caption">保持原始分辨率</Typography>}
                  sx={{ '& .MuiFormControlLabel-label': { mt: 0 } }}
                />
                {!video.preserveResolution && advancedMode && (
                  <Box sx={{ display: 'flex', gap: 1, mt: 0.5 }}>
                    <TextField size="small" label="宽" type="number"
                      value={video.targetWidth || ''}
                      onChange={e => updatePreset('video', 'targetWidth', parseInt(e.target.value) || undefined)}
                      InputProps={{ sx: { fontSize: '0.7rem' } }} />
                    <TextField size="small" label="高" type="number"
                      value={video.targetHeight || ''}
                      onChange={e => updatePreset('video', 'targetHeight', parseInt(e.target.value) || undefined)}
                      InputProps={{ sx: { fontSize: '0.7rem' } }} />
                  </Box>
                )}
              </Box>
            )}
            <FormControlLabel
              control={<Switch size="small" checked={video.preserveFramerate}
                onChange={e => updatePreset('video', 'preserveFramerate', e.target.checked)} />}
              label={<Typography variant="caption">保持原始帧率</Typography>}
              sx={{ '& .MuiFormControlLabel-label': { mt: 0 } }}
            />
          </ConfigSection>

          {/* Subtitle section */}
          <ConfigSection id="subtitle" label="字幕样式" modified={false}
            expanded={expandedSections.has('subtitle')} onChange={toggleSection}>
            <FormControl fullWidth size="small" sx={{ mb: 1 }}>
              <InputLabel>字幕模式</InputLabel>
              <Select value={subtitle.mode}
                label="字幕模式"
                onChange={e => updatePreset('subtitle', 'mode', e.target.value)}>
                <MenuItem value="burned">烧录 (硬字幕)</MenuItem>
                <MenuItem value="soft">内挂 (软字幕)</MenuItem>
                <MenuItem value="external">外部字幕文件</MenuItem>
                <MenuItem value="none">无字幕</MenuItem>
              </Select>
            </FormControl>
            {subtitle.mode === 'external' && (
              <FormControl fullWidth size="small" sx={{ mb: 1 }}>
                <InputLabel>字幕格式</InputLabel>
                <Select value={subtitle.externalFormat || 'srt'}
                  label="字幕格式"
                  onChange={e => updatePreset('subtitle', 'externalFormat', e.target.value)}>
                  <MenuItem value="srt">SRT</MenuItem>
                  <MenuItem value="ass">ASS</MenuItem>
                  <MenuItem value="vtt">WebVTT</MenuItem>
                </Select>
              </FormControl>
            )}
            {subtitle.mode !== 'none' && (
              <>
                <FormControlLabel
                  control={<Switch size="small" checked={subtitle.bilingual}
                    onChange={e => updatePreset('subtitle', 'bilingual', e.target.checked)} />}
                  label={<Typography variant="caption">双语字幕</Typography>}
                  sx={{ '& .MuiFormControlLabel-label': { mt: 0 } }}
                />
                <FormControl fullWidth size="small" sx={{ mb: 0.5 }}>
                  <InputLabel>字体</InputLabel>
                  <Select value={subtitle.font}
                    label="字体"
                    onChange={e => updatePreset('subtitle', 'font', e.target.value)}>
                    {fonts.map(f => (
                      <MenuItem key={f.path} value={f.name} dense>
                        <Typography variant="caption">{f.name}{f.isSystem ? ' (系统)' : ''}</Typography>
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                {advancedMode && (
                  <>
                    <FormControl fullWidth size="small" sx={{ mb: 0.5 }}>
                      <InputLabel>字号模式</InputLabel>
                      <Select value={subtitle.fontSizeMode}
                        label="字号模式"
                        onChange={e => updatePreset('subtitle', 'fontSizeMode', e.target.value)}>
                        <MenuItem value="adaptive">自适应</MenuItem>
                        <MenuItem value="fixed">固定</MenuItem>
                      </Select>
                    </FormControl>
                    {subtitle.fontSizeMode === 'fixed' && (
                      <TextField fullWidth size="small" label="字号" type="number"
                        value={subtitle.fontSize}
                        onChange={e => updatePreset('subtitle', 'fontSize', parseInt(e.target.value) || 0)}
                        sx={{ mb: 0.5 }} InputProps={{ sx: { fontSize: '0.7rem' } }} />
                    )}
                  </>
                )}
                <Box sx={{ display: 'flex', gap: 0.5, mb: 0.5 }}>
                  <TextField size="small" label="文字颜色" type="color"
                    value={subtitle.fontColor} sx={{ width: 60 }}
                    onChange={e => updatePreset('subtitle', 'fontColor', e.target.value)} />
                  <TextField size="small" label="描边颜色" type="color"
                    value={subtitle.strokeColor} sx={{ width: 60 }}
                    onChange={e => updatePreset('subtitle', 'strokeColor', e.target.value)} />
                  <TextField size="small" label="背景颜色" type="color"
                    value={subtitle.bgColor.replace(/rgba?\([^)]+\)/, '#000000')} sx={{ width: 60 }}
                    onChange={e => updatePreset('subtitle', 'bgColor', e.target.value)} />
                </Box>
                {advancedMode && (
                  <>
                    <Box sx={{ display: 'flex', gap: 0.5, mb: 0.5 }}>
                      <FormControl size="small" sx={{ flex: 1 }}>
                        <InputLabel>对齐</InputLabel>
                        <Select value={subtitle.alignment}
                          label="对齐"
                          onChange={e => updatePreset('subtitle', 'alignment', e.target.value)}>
                          <MenuItem value="center">居中</MenuItem>
                          <MenuItem value="left">左对齐</MenuItem>
                          <MenuItem value="right">右对齐</MenuItem>
                        </Select>
                      </FormControl>
                      <FormControl size="small" sx={{ flex: 1 }}>
                        <InputLabel>位置</InputLabel>
                        <Select value={subtitle.position}
                          label="位置"
                          onChange={e => updatePreset('subtitle', 'position', e.target.value)}>
                          <MenuItem value="bottom">底部</MenuItem>
                          <MenuItem value="top">顶部</MenuItem>
                        </Select>
                      </FormControl>
                    </Box>
                    <Typography variant="caption" color="text.secondary" gutterBottom>
                      描边宽度: {subtitle.strokeWidth}
                    </Typography>
                    <Slider size="small" min={0} max={8} step={0.5}
                      value={subtitle.strokeWidth}
                      onChange={(_, v) => updatePreset('subtitle', 'strokeWidth', v as number)}
                      sx={{ mb: 0.5 }} />
                    <Typography variant="caption" color="text.secondary">
                      最大行数: {subtitle.maxLines}
                    </Typography>
                    <Slider size="small" min={1} max={4} step={1}
                      value={subtitle.maxLines}
                      onChange={(_, v) => updatePreset('subtitle', 'maxLines', v as number)} />
                  </>
                )}
              </>
            )}
          </ConfigSection>

          {/* Audio section */}
          <ConfigSection id="audio" label="音轨策略" modified={false}
            expanded={expandedSections.has('audio')} onChange={toggleSection}>
            <FormControl fullWidth size="small" sx={{ mb: 1 }}>
              <InputLabel>音轨策略</InputLabel>
              <Select value={audio.strategy}
                label="音轨策略"
                onChange={e => updatePreset('audio', 'strategy', e.target.value)}>
                <MenuItem value="dubbed_only">仅配音</MenuItem>
                <MenuItem value="original_only">仅原声</MenuItem>
                <MenuItem value="mixed">混合 (配音+原声)</MenuItem>
                <MenuItem value="multi_track">多轨并存</MenuItem>
              </Select>
            </FormControl>
            {audio.strategy === 'multi_track' && (
              <FormControlLabel
                control={<Switch size="small" checked={audio.separateTracks}
                  onChange={e => updatePreset('audio', 'separateTracks', e.target.checked)} />}
                label={<Typography variant="caption">分离音轨文件</Typography>}
                sx={{ '& .MuiFormControlLabel-label': { mt: 0 } }}
              />
            )}
            <FormControlLabel
              control={<Switch size="small" checked={audio.preserveOriginal}
                onChange={e => updatePreset('audio', 'preserveOriginal', e.target.checked)} />}
              label={<Typography variant="caption">保留原始音轨</Typography>}
              sx={{ '& .MuiFormControlLabel-label': { mt: 0 } }}
            />
            <Typography variant="caption" color="text.secondary" gutterBottom>
              BGM 音量: {audio.bgmVolume.toFixed(1)}
            </Typography>
            <Slider size="small" min={0} max={2} step={0.1}
              value={audio.bgmVolume}
              onChange={(_, v) => updatePreset('audio', 'bgmVolume', v as number)} />
          </ConfigSection>

          {/* Output naming */}
          <ConfigSection id="output" label="输出命名" modified={false}
            expanded={expandedSections.has('output')} onChange={toggleSection}>
            <TextField fullWidth size="small" label="输出目录"
              value={output.baseDir}
              onChange={e => updatePreset('output', 'baseDir', e.target.value)}
              sx={{ mb: 0.5 }} InputProps={{ sx: { fontSize: '0.7rem' } }} />
            <TextField fullWidth size="small" label="命名模式"
              value={output.pattern} helperText="使用 {project} {lang} {date} {version}"
              onChange={e => updatePreset('output', 'pattern', e.target.value)}
              sx={{ mb: 0.5 }} InputProps={{ sx: { fontSize: '0.7rem' } }}
              FormHelperTextProps={{ sx: { fontSize: '0.5rem' } }} />
            <FormControlLabel
              control={<Switch size="small" checked={output.createDateSubdir}
                onChange={e => updatePreset('output', 'createDateSubdir', e.target.checked)} />}
              label={<Typography variant="caption">创建日期子目录</Typography>}
              sx={{ '& .MuiFormControlLabel-label': { mt: 0 } }}
            />
            <FormControlLabel
              control={<Switch size="small" checked={output.includeConfigSnapshot}
                onChange={e => updatePreset('output', 'includeConfigSnapshot', e.target.checked)} />}
              label={<Typography variant="caption">包含配置快照</Typography>}
              sx={{ '& .MuiFormControlLabel-label': { mt: 0 } }}
            />
            <FormControlLabel
              control={<Switch size="small" checked={output.includeExportLog}
                onChange={e => updatePreset('output', 'includeExportLog', e.target.checked)} />}
              label={<Typography variant="caption">包含导出日志</Typography>}
              sx={{ '& .MuiFormControlLabel-label': { mt: 0 } }}
            />
          </ConfigSection>

          {/* Quality section (advanced mode only) */}
          {advancedMode && (
            <ConfigSection id="quality" label="质量与兼容性" modified={false}
              expanded={expandedSections.has('quality')} onChange={toggleSection}>
              <TextField fullWidth size="small" label="视频码率"
                value={quality.videoBitrate}
                onChange={e => updatePreset('quality', 'videoBitrate', e.target.value)}
                sx={{ mb: 0.5 }} InputProps={{ sx: { fontSize: '0.7rem' } }} />
              <TextField fullWidth size="small" label="音频码率"
                value={quality.audioBitrate}
                onChange={e => updatePreset('quality', 'audioBitrate', e.target.value)}
                sx={{ mb: 0.5 }} InputProps={{ sx: { fontSize: '0.7rem' } }} />
              <Typography variant="caption" color="text.secondary">CRF: {quality.crf}</Typography>
              <Slider size="small" min={18} max={28} step={1}
                value={quality.crf}
                onChange={(_, v) => updatePreset('quality', 'crf', v as number)}
                sx={{ mb: 0.5 }} />
              <FormControl fullWidth size="small" sx={{ mb: 0.5 }}>
                <InputLabel>编码速度</InputLabel>
                <Select value={quality.preset}
                  label="编码速度"
                  onChange={e => updatePreset('quality', 'preset', e.target.value)}>
                  <MenuItem value="ultrafast">极速 (文件大)</MenuItem>
                  <MenuItem value="fast">快速</MenuItem>
                  <MenuItem value="medium">均衡</MenuItem>
                  <MenuItem value="slow">慢速 (文件小)</MenuItem>
                </Select>
              </FormControl>
              <FormControl fullWidth size="small">
                <InputLabel>兼容性目标</InputLabel>
                <Select value={quality.compatibility}
                  label="兼容性目标"
                  onChange={e => updatePreset('quality', 'compatibility', e.target.value)}>
                  <MenuItem value="desktop">桌面端</MenuItem>
                  <MenuItem value="mobile">移动端</MenuItem>
                  <MenuItem value="both">通用</MenuItem>
                </Select>
              </FormControl>
            </ConfigSection>
          )}
        </Box>

        {/* Center: Preview */}
        <Box sx={{
          flexGrow: 1, display: 'flex', flexDirection: 'column',
          bgcolor: 'background.default', p: 2, overflow: 'hidden auto',
        }}>
          <Typography variant="subtitle2" gutterBottom>字幕预览</Typography>

          {/* Preview text inputs */}
          <Box sx={{ display: 'flex', gap: 1, mb: 1.5 }}>
            <TextField size="small" label="预览中文" value={previewText.zh}
              onChange={e => setExportPreviewText({ ...previewText, zh: e.target.value })}
              InputProps={{ sx: { fontSize: '0.7rem' } }} sx={{ flex: 1 }} />
            {subtitle.bilingual && (
              <TextField size="small" label="预览英文" value={previewText.en}
                onChange={e => setExportPreviewText({ ...previewText, en: e.target.value })}
                InputProps={{ sx: { fontSize: '0.7rem' } }} sx={{ flex: 1 }} />
            )}
          </Box>

          {/* Preview image */}
          {subtitle.mode !== 'none' && previewUrl ? (
            <Box sx={{
              position: 'relative', bgcolor: '#1a1a1a', borderRadius: 1,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              minHeight: 200, mb: 2, border: '1px solid', borderColor: 'divider',
              overflow: 'hidden',
            }}>
              <img src={previewUrl} alt="字幕预览"
                style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
                onError={e => { (e.target as HTMLImageElement).style.display = 'none' }} />
            </Box>
          ) : (
            <Box sx={{
              bgcolor: 'background.paper', borderRadius: 1, minHeight: 200, mb: 2,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              border: '1px dashed', borderColor: 'divider',
            }}>
              <Typography variant="caption" color="text.disabled">
                {subtitle.mode === 'none' ? '字幕已禁用' : '正在加载预览...'}
              </Typography>
            </Box>
          )}

          {/* Audio track visualization */}
          <Typography variant="subtitle2" gutterBottom>音轨结构</Typography>
          <Box sx={{ bgcolor: 'background.paper', borderRadius: 1, p: 1.5, mb: 2 }}>
            {/* Track visualization bars */}
            {audio.strategy === 'dubbed_only' && (
              <>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                  <Box sx={{ width: '100%', height: 24, borderRadius: 1, bgcolor: 'primary.main', opacity: 0.8,
                    display: 'flex', alignItems: 'center', px: 1 }}>
                    <Typography variant="caption" color="white" fontSize="0.6rem">配音轨 (zh-CN)</Typography>
                  </Box>
                </Box>
              </>
            )}
            {audio.strategy === 'mixed' && (
              <>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                  <Box sx={{ flex: 7, height: 22, borderRadius: 1, bgcolor: 'primary.main', opacity: 0.8,
                    display: 'flex', alignItems: 'center', px: 1 }}>
                    <Typography variant="caption" color="white" fontSize="0.6rem">配音</Typography>
                  </Box>
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                  <Box sx={{ flex: 3, height: 22, borderRadius: 1, bgcolor: 'grey.500', opacity: 0.7,
                    display: 'flex', alignItems: 'center', px: 1 }}>
                    <Typography variant="caption" color="white" fontSize="0.6rem">原声 ({audio.bgmVolume.toFixed(1)}x)</Typography>
                  </Box>
                </Box>
              </>
            )}
            {audio.strategy === 'multi_track' && (
              <>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                  <Box sx={{ flex: 1, height: 22, borderRadius: 1, bgcolor: 'primary.main', opacity: 0.8,
                    display: 'flex', alignItems: 'center', px: 1 }}>
                    <Typography variant="caption" color="white" fontSize="0.6rem">T1: 配音</Typography>
                  </Box>
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                  <Box sx={{ flex: 1, height: 22, borderRadius: 1, bgcolor: 'grey.500', opacity: 0.7,
                    display: 'flex', alignItems: 'center', px: 1 }}>
                    <Typography variant="caption" color="white" fontSize="0.6rem">T2: 原声</Typography>
                  </Box>
                </Box>
              </>
            )}
            {audio.strategy === 'original_only' && (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Box sx={{ width: '100%', height: 24, borderRadius: 1, bgcolor: 'grey.500', opacity: 0.7,
                  display: 'flex', alignItems: 'center', px: 1 }}>
                  <Typography variant="caption" color="white" fontSize="0.6rem">原始音轨</Typography>
                </Box>
              </Box>
            )}
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
              {audio.strategy === 'dubbed_only' && '仅输出配音轨'}
              {audio.strategy === 'original_only' && '仅保留原始音轨'}
              {audio.strategy === 'mixed' && `配音 + 原声混合 (BGM ${audio.bgmVolume.toFixed(1)}x)`}
              {audio.strategy === 'multi_track' && '多轨并存 (播放器可选)'}
              {audio.preserveOriginal && ' · 保留原始音轨'}
              {audio.separateTracks && ' · 分离音轨文件'}
            </Typography>
          </Box>
        </Box>

        {/* Right: Output manifest + Readiness */}
        <Box sx={{
          width: 280, minWidth: 280, borderLeft: 1, borderColor: 'divider',
          overflow: 'hidden auto', bgcolor: 'background.paper', p: 1.5,
        }}>
          {/* Readiness check */}
          <Box sx={{
            p: 1, mb: 1.5, borderRadius: 1,
            bgcolor: readiness.isReady ? 'rgba(76,175,80,0.08)' : 'rgba(255,152,0,0.08)',
            border: '1px solid',
            borderColor: readiness.isReady ? 'success.main' : severityColor + '.main',
          }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5 }}>
              {readiness.isReady
                ? <CheckCircleIcon sx={{ fontSize: 18, color: 'success.main' }} />
                : <WarningIcon sx={{ fontSize: 18, color: severityColor + '.main' }} />
              }
              <Typography variant="caption" fontWeight={600}
                color={readiness.isReady ? 'success.main' : severityColor + '.main'}>
                {readiness.isReady ? '项目已就绪' : `${readiness.warnings.length} 项建议`}
              </Typography>
            </Box>
            {readiness.warnings.map((w, i) => (
              <Box key={i} sx={{ display: 'flex', alignItems: 'flex-start', gap: 0.5, mb: 0.5 }}>
                <SeverityIcon severity={w.severity} />
                <Box sx={{ flexGrow: 1 }}>
                  <Typography variant="caption" fontSize="0.6rem">{w.message}</Typography>
                  {w.action && (
                    <Button size="small" sx={{ fontSize: '0.55rem', minWidth: 0, p: 0, textTransform: 'none' }}
                      onClick={() => { setMode(w.action!.mode); if (w.action!.mode === 'timeline' && events.length > 0) navigateToEvent(events[0].id, events[0].start) }}>
                      前往修复 →
                    </Button>
                  )}
                </Box>
              </Box>
            ))}
          </Box>

          {/* Stats */}
          <Typography variant="caption" color="text.secondary" fontWeight={600}>项目概览</Typography>
          <Box sx={{ display: 'flex', gap: 1, mb: 1.5, mt: 0.5 }}>
            <Box sx={{ bgcolor: 'background.default', p: 1, borderRadius: 1, flex: 1, textAlign: 'center' }}>
              <Typography variant="caption" fontWeight={600}>{readiness.totalEvents}</Typography>
              <Typography variant="caption" color="text.secondary" display="block" fontSize="0.55rem">事件</Typography>
            </Box>
            <Box sx={{ bgcolor: 'background.default', p: 1, borderRadius: 1, flex: 1, textAlign: 'center' }}>
              <Typography variant="caption" fontWeight={600}>{totalDuration.toFixed(1)}s</Typography>
              <Typography variant="caption" color="text.secondary" display="block" fontSize="0.55rem">时长</Typography>
            </Box>
            <Box sx={{ bgcolor: 'background.default', p: 1, borderRadius: 1, flex: 1, textAlign: 'center' }}>
              <Typography variant="caption" fontWeight={600}>{new Set(events.map(e => e.speaker).filter(Boolean)).size || '-'}</Typography>
              <Typography variant="caption" color="text.secondary" display="block" fontSize="0.55rem">声线</Typography>
            </Box>
          </Box>

          {/* Output file tree */}
          <Typography variant="caption" color="text.secondary" fontWeight={600} gutterBottom>
            输出清单
          </Typography>
          <Box sx={{
            bgcolor: 'background.default', p: 1, borderRadius: 1, mb: 1.5,
            fontFamily: 'monospace', fontSize: '0.62rem', color: 'text.secondary',
            lineHeight: 1.6,
          }}>
            <Box sx={{ color: 'warning.light' }}>{output.baseDir || 'output/'}</Box>
            <Box sx={{ ml: 1 }}>dubbed.{video.container}</Box>
            {subtitle.mode === 'external' && (
              <Box sx={{ ml: 1 }}>subtitles.{subtitle.externalFormat || 'srt'}</Box>
            )}
            {subtitle.mode !== 'none' && subtitle.mode !== 'external' && (
              <Box sx={{ ml: 1, color: 'text.disabled' }}>{subtitle.mode === 'burned' ? '(字幕已烧录)' : '(字幕已内挂)'}</Box>
            )}
            {audio.separateTracks && <Box sx={{ ml: 1 }}>audio.wav</Box>}
            {output.includeConfigSnapshot && <Box sx={{ ml: 1 }}>export_config.json</Box>}
            {output.includeExportLog && <Box sx={{ ml: 1 }}>export.log</Box>}
          </Box>

          {/* Size estimate */}
          <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
            <Typography variant="caption" color="text.secondary">预估大小</Typography>
            <Typography variant="caption" fontWeight={600}>~{estimatedSizeMb} MB</Typography>
          </Box>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1.5 }}>
            <Typography variant="caption" color="text.secondary">编码器</Typography>
            <Typography variant="caption">{video.videoCodec} · {video.container.toUpperCase()}</Typography>
          </Box>

          {/* Quick actions */}
          <Button variant="outlined" size="small" fullWidth startIcon={<FolderOpenIcon />}
            sx={{ fontSize: '0.65rem', mb: 0.5 }}>
            打开输出目录
          </Button>
          <Button variant="outlined" size="small" fullWidth startIcon={<OpenInNewIcon />}
            sx={{ fontSize: '0.65rem' }}
            onClick={() => setMode('batch')}>
            加入批处理队列
          </Button>
        </Box>
      </Box>

      {/* ── Export Confirm Dialog ── */}
      <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ fontSize: '0.95rem' }}>
          {exportResult ? (exportResult.success ? '导出完成' : '导出失败') : '确认导出'}
        </DialogTitle>
        <DialogContent>
          {exporting && <LinearProgress sx={{ mb: 2 }} />}
          {exportResult ? (
            exportResult.success ? (
              <Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
                  <CheckCircleIcon sx={{ color: 'success.main' }} />
                  <Typography variant="body2">导出成功 (耗时 {exportResult.durationSec.toFixed(0)}s)</Typography>
                </Box>
                <Typography variant="caption" color="text.secondary" gutterBottom display="block">
                  输出目录: {exportResult.outputDir}
                </Typography>
                {exportResult.files.map(f => (
                  <Box key={f.name} sx={{ display: 'flex', justifyContent: 'space-between', py: 0.25 }}>
                    <Typography variant="caption" fontFamily="monospace">{f.name}</Typography>
                    <Typography variant="caption" color="text.secondary">{f.sizeMb.toFixed(2)} MB</Typography>
                  </Box>
                ))}
              </Box>
            ) : (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <ErrorIcon sx={{ color: 'error.main' }} />
                <Typography variant="body2">导出失败，请检查日志</Typography>
              </Box>
            )
          ) : (
            <Box>
              <Typography variant="body2" sx={{ mb: 1.5 }}>
                方案: <strong>{activePreset?.name}</strong>
                {output.baseDir && <> · 输出: <strong>{output.baseDir}</strong></>}
              </Typography>
              <Box sx={{ bgcolor: 'background.default', p: 1, borderRadius: 1, mb: 1.5 }}>
                <Typography variant="caption" display="block">视频: {video.container.toUpperCase()} {video.videoCodec} {video.reencode ? '重新编码' : '复用流'}</Typography>
                <Typography variant="caption" display="block">字幕: {subtitle.mode === 'burned' ? '烧录硬字幕' : subtitle.mode === 'soft' ? '内挂软字幕' : subtitle.mode === 'external' ? '外部文件' : '无'}{subtitle.bilingual ? ' · 双语' : ''}</Typography>
                <Typography variant="caption" display="block">音轨: {audio.strategy === 'dubbed_only' ? '仅配音' : audio.strategy === 'mixed' ? '混合' : audio.strategy === 'multi_track' ? '多轨' : '仅原声'}</Typography>
                <Typography variant="caption" display="block">预估: ~{estimatedSizeMb} MB</Typography>
              </Box>
              {!readiness.isReady && (
                <Box sx={{ p: 1, borderRadius: 1, bgcolor: 'rgba(255,152,0,0.08)', mb: 1.5 }}>
                  <Typography variant="caption" color="warning.main" fontWeight={600}>
                    存在 {readiness.warnings.length} 个风险项，建议修复后再导出
                  </Typography>
                  {readiness.warnings.map((w, i) => (
                    <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.25 }}>
                      <SeverityIcon severity={w.severity} />
                      <Typography variant="caption" fontSize="0.6rem">{w.message}</Typography>
                    </Box>
                  ))}
                </Box>
              )}
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          {exportResult ? (
            <>
              {exportResult.success && (
                <>
                  <Button size="small" startIcon={<FolderOpenIcon />}
                    onClick={() => setConfirmOpen(false)}>打开目录</Button>
                  <Button size="small" startIcon={<ContentCopyIcon />}
                    onClick={() => { navigator.clipboard.writeText(exportResult.outputDir); setConfirmOpen(false) }}>复制路径</Button>
                </>
              )}
              <Button size="small" onClick={() => setConfirmOpen(false)}>关闭</Button>
            </>
          ) : (
            <>
              <Button size="small" onClick={() => setConfirmOpen(false)}>取消</Button>
              <Button size="small" variant="contained" startIcon={<FileDownloadIcon />}
                onClick={handleConfirmExport} disabled={exporting}>
                {exporting ? '导出中...' : '立即导出'}
              </Button>
            </>
          )}
        </DialogActions>
      </Dialog>
    </Box>
  )
}
