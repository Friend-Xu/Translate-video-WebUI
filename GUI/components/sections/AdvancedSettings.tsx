import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import {
  Box, Typography, Card, CardContent, FormControlLabel, Checkbox,
  TextField, Stack, Chip, Select, MenuItem, Button, Divider,
  CircularProgress, Tooltip, ToggleButton, ToggleButtonGroup,
} from '@mui/material'
import Grid from '@mui/material/Grid'
import RestoreIcon from '@mui/icons-material/RestoreRounded'
import { SectionHeader } from '../SectionHeader'
import type { PipelineConfig, SystemInfo, VideoInfo } from '../../types'

interface SubtitleStylePreset {
  name: string
  description: string
  font: string
  fontSize: number   // 0 = auto
  strokeWidth: number
}

// System font names registered in ImageMagick (guaranteed CJK support)
const FONT_SYSTEM = {
  minecraft: '',  // empty = default project Minecraft font
  yahei:     'Microsoft-YaHei-Bold',
  simhei:    'SimHei',
  kaiti:     'KaiTi',
  fangsong:  'FangSong',
}

const STYLE_PRESETS: SubtitleStylePreset[] = [
  { name: 'Minecraft 像素', description: '像素风默认字体', font: FONT_SYSTEM.minecraft, fontSize: 0, strokeWidth: 2.5 },
  { name: '微软雅黑', description: '微软雅黑粗体，现代简洁', font: FONT_SYSTEM.yahei, fontSize: 0, strokeWidth: 1.5 },
  { name: '黑体加粗', description: 'SimHei黑体+粗描边，最醒目', font: FONT_SYSTEM.simhei, fontSize: 0, strokeWidth: 4 },
  { name: '楷体书法', description: '楷体风格，文艺典雅', font: FONT_SYSTEM.kaiti, fontSize: 0, strokeWidth: 2 },
  { name: '仿宋古典', description: '仿宋体，正式古典', font: FONT_SYSTEM.fangsong, fontSize: 0, strokeWidth: 1.5 },
]

function isAbsPath(p: string): boolean {
  return /^[A-Za-z]:[\\\/]/.test(p) || p.startsWith('//')
}

function resolveFontPath(font: string, fonts: FontInfo[]): string {
  if (!font) return ''
  if (isAbsPath(font)) return font
  // System font name (e.g. "SimHei") — pass through directly
  if (!font.match(/\.(ttf|otf|ttc)$/i) && !font.includes('/') && !font.includes('\\')) {
    return font
  }
  // Project font file — resolve relative path to absolute
  const found = fonts.find(f => f.relative === font || f.name === font.replace(/\.\w+$/, ''))
  return found ? found.path : font
}

const LANG_LABELS: Record<string, string> = { ja: '日语', en: '英语', zh: '中文', ko: '韩语' }

const SUBTITLE_PARAMS: { key: string; label: string; min: number; max: number; step: number }[] = [
  { key: 'max_chars', label: '单段最大字符数', min: 10, max: 100, step: 1 },
  { key: 'min_duration', label: '最少显示时长(秒)', min: 0.3, max: 3.0, step: 0.1 },
  { key: 'max_gap', label: '最大允许间隙(秒)', min: 0.1, max: 3.0, step: 0.1 },
  { key: 'merge_gap', label: '合并触发间隔(秒)', min: 0.1, max: 2.0, step: 0.1 },
  { key: 'merge_chars', label: '合并后最大字符数', min: 20, max: 200, step: 5 },
  { key: 'merge_dur_max', label: '合并后最大时长(秒)', min: 2.0, max: 15.0, step: 0.5 },
  { key: 'split_chars', label: '拆分触发字符数', min: 50, max: 500, step: 10 },
  { key: 'split_dur', label: '拆分触发时长(秒)', min: 3.0, max: 20.0, step: 0.5 },
  { key: 'split_chars_min', label: '拆分后最少字符数', min: 1, max: 20, step: 1 },
]

interface FontInfo {
  name: string
  path: string
  relative: string
}

interface AdvancedSettingsProps {
  config: PipelineConfig
  onConfigChange: <K extends keyof PipelineConfig>(key: K, value: PipelineConfig[K]) => void
  showTitle?: boolean
}

export function AdvancedSettings({ config, onConfigChange, showTitle = true }: AdvancedSettingsProps) {
  const [sysInfo, setSysInfo] = useState<SystemInfo | null>(null)
  const [presets, setPresets] = useState<Record<string, Record<string, unknown>>>({})
  const [overrides, setOverrides] = useState<Record<string, Record<string, unknown>>>({})
  const [fonts, setFonts] = useState<FontInfo[]>([])
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [videoInfo, setVideoInfo] = useState<VideoInfo | null>(null)
  const previewTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const langKey = config.lang === 'auto' ? 'default' : config.lang
  const langLabel = LANG_LABELS[langKey] ?? '默认'

  useEffect(() => {
    fetch('/api/system/info')
      .then(r => r.ok ? r.json() : null)
      .then(setSysInfo)
      .catch(() => {})
    fetch('/api/subtitle/presets')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setPresets(d) })
      .catch(() => {})
    fetch('/api/settings')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.subtitle) setOverrides(d.subtitle) })
      .catch(() => {})
    fetch('/api/fonts')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.fonts) setFonts(d.fonts) })
      .catch(() => {})
  }, [])

  // Fetch video dimensions when video path changes
  useEffect(() => {
    if (!config.videoPath) { setVideoInfo(null); return }
    fetch(`/api/video/info?path=${encodeURIComponent(config.videoPath)}`)
      .then(r => r.ok ? r.json() : null)
      .then(setVideoInfo)
      .catch(() => setVideoInfo(null))
  }, [config.videoPath])

  // Auto font size derived from video width (mirrors backend logic)
  const autoFontSize = useMemo(() => {
    if (!videoInfo?.width) return 36  // fallback default
    return Math.round(videoInfo.width * (config.captionFontSizeFactor || 0.030))
  }, [videoInfo?.width])

  // Detect which preset matches current settings
  const activePresetIndex = useMemo(() => {
    const font = config.captionFont || ''
    const fs = config.captionFontSize || 0
    const sw = config.captionStrokeWidth || 0
    return STYLE_PRESETS.findIndex(p => {
      const pFont = resolveFontPath(p.font, fonts)
      return pFont === font && p.fontSize === fs && p.strokeWidth === sw
    })
  }, [config.captionFont, config.captionFontSize, config.captionStrokeWidth, fonts])

  const applyPreset = useCallback((preset: SubtitleStylePreset) => {
    const resolved = resolveFontPath(preset.font, fonts)
    onConfigChange('captionFont', resolved)
    onConfigChange('captionFontSize', preset.fontSize)
    onConfigChange('captionStrokeWidth', preset.strokeWidth)
  }, [fonts, onConfigChange])

  // Debounced preview fetch
  const fetchPreview = useCallback(() => {
    if (previewTimer.current) clearTimeout(previewTimer.current)
    previewTimer.current = setTimeout(() => {
      const fontSize = config.captionFontSize || autoFontSize
      const params = new URLSearchParams({
        font: config.captionFont || '',
        font_size: String(fontSize),
        font_color: config.captionFontColor || 'white',
        stroke_width: String(config.captionStrokeWidth || 2.5),
        stroke_color: config.captionStrokeColor || 'black',
        bg_color: config.captionBgColor || 'rgba(0,0,0,128)',
        text_zh: 'Minecraft我的世界 村民交易',
        text_en: 'Minecraft Villager Trade x64',
        alignment: config.captionAlignment || 'center',
        position: config.captionPosition || 'bottom',
        engine: config.subtitleEngine || 'pil',
        max_lines: String(config.captionMaxLines || 2),
        font_size_factor: String(config.captionFontSizeFactor || 0.030),
        max_font_size: String(config.captionMaxFontSize || 0),
        caption_width_ratio: String(config.captionWidthRatio || 0.85),
        font_size_mode: config.captionFontSizeMode || 'adaptive',
      })
      setPreviewLoading(true)
      setPreviewError(null)
      fetch(`/api/subtitle/preview?${params}`)
        .then(async r => {
          if (!r.ok) {
            let detail = `HTTP ${r.status}`
            try {
              const body = await r.json()
              if (body?.detail) detail = body.detail
            } catch { /* use status text */ }
            throw new Error(detail)
          }
          if (previewUrl) URL.revokeObjectURL(previewUrl)
          setPreviewUrl(URL.createObjectURL(await r.blob()))
        })
        .catch(err => {
          if (previewUrl) URL.revokeObjectURL(previewUrl)
          setPreviewUrl(null)
          setPreviewError(err?.message || '预览不可用')
        })
        .finally(() => setPreviewLoading(false))
    }, 400)
  }, [config.captionFont, config.captionFontSize, config.captionFontColor, config.captionStrokeWidth, config.captionStrokeColor, config.captionBgColor, config.captionAlignment, config.captionPosition, autoFontSize, config.subtitleEngine, config.captionMaxLines, config.captionFontSizeFactor, config.captionMaxFontSize, config.captionWidthRatio])

  useEffect(() => {
    if (fonts.length > 0) fetchPreview()
    return () => { if (previewTimer.current) clearTimeout(previewTimer.current) }
  }, [fonts.length, config.captionFont, config.captionFontSize, config.captionFontColor, config.captionStrokeWidth, config.captionStrokeColor, config.captionBgColor, config.captionAlignment, config.captionPosition, autoFontSize, config.subtitleEngine, config.captionMaxLines, config.captionFontSizeFactor, config.captionMaxFontSize, config.captionWidthRatio])

  const basePreset = presets[langKey] ?? presets['default'] ?? {}
  const currentParams: Record<string, unknown> = { ...basePreset, ...(overrides[langKey] ?? {}) }

  const handleParamChange = useCallback(async (key: string, value: number) => {
    setOverrides(prev => {
      const next = { ...prev, [langKey]: { ...(prev[langKey] ?? {}), [key]: value } }
      fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subtitle: next }),
      }).catch(() => {})
      return next
    })
  }, [langKey])

  const handleReset = useCallback(async () => {
    try {
      const res = await fetch('/api/settings/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language: langKey }),
      })
      if (!res.ok) return
      const data = await res.json()
      setOverrides(prev => { const next = { ...prev }; delete next[langKey]; return next })
      setPresets(prev => ({ ...prev, [langKey]: data.preset }))
    } catch { /* ignore */ }
  }, [langKey])

  return (
    <>
      {showTitle && <SectionHeader title="高级设置与调节" />}

      {/* System info bar */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap', mt: showTitle ? 1 : 0, mb: 2 }}>
        <Chip label={`CPU: ${sysInfo?.cpuCount ?? '-'} 核`} size="small" />
        <Chip label={sysInfo?.hasGpu ? `GPU: ${sysInfo.gpuName}` : 'GPU: 未检测到'} size="small" color={sysInfo?.hasGpu ? 'success' : 'default'} />
        <Chip label={`推荐并发: ${sysInfo?.recommendedConcurrency ?? '-'}`} size="small" color="primary" />
        <Box sx={{ ml: 1, display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <Typography variant="caption" color="text.secondary">并发数</Typography>
          <TextField size="small" type="number" value={config.concurrency}
            inputProps={{ style: { padding: '2px 6px', width: 48 } }}
            onChange={e => onConfigChange('concurrency', Number(e.target.value))} />
          {sysInfo && (
            <Chip label="自动" size="small" variant="outlined" color="primary"
              onClick={() => onConfigChange('concurrency', sysInfo.recommendedConcurrency)}
              sx={{ cursor: 'pointer', fontSize: '0.7rem' }} />
          )}
        </Box>
        <FormControlLabel sx={{ ml: 0.5 }}
          control={<Checkbox size="small" checked={config.enableCheckpoint} onChange={e => onConfigChange('enableCheckpoint', e.target.checked)} />}
          label={<Typography variant="caption">断点续传</Typography>} />
      </Box>

      {/* Main settings: 3-column grid */}
      <Grid container spacing={3}>

        {/* Clone settings */}
        <Grid size={{ xs: 12, md: 4 }}>
        <Card sx={{ height: '100%', bgcolor: 'action.hover' }}>
          <CardContent>
            <Typography variant="subtitle2" gutterBottom>克隆设置</Typography>

            <Box mt={1}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <FormControlLabel
                  control={<Checkbox size="small" checked={config.enableEmotionClone}
                    onChange={e => onConfigChange('enableEmotionClone', e.target.checked)} />}
                  label={<Typography variant="body2" fontWeight={500}>情感分析</Typography>} />
                <Chip label="ChatTTS" size="small" color="primary" variant="outlined" />
              </Box>
              <Box sx={{ ml: 3.5, mt: 0.5, opacity: config.enableEmotionClone ? 1 : 0.5, pointerEvents: config.enableEmotionClone ? 'auto' : 'none' }}>
                <Stack spacing={1}>
                  <Box>
                    <Typography variant="caption" color="text.secondary">默认情感</Typography>
                    <Select size="small" fullWidth value={config.defaultEmotion}
                      onChange={e => onConfigChange('defaultEmotion', e.target.value)}
                      sx={{ mt: 0.25, bgcolor: 'background.paper' }}>
                      <MenuItem value="neutral">neutral（中性）</MenuItem>
                      <MenuItem value="happy">happy（开心）</MenuItem>
                      <MenuItem value="sad">sad（悲伤）</MenuItem>
                      <MenuItem value="angry">angry（愤怒）</MenuItem>
                      <MenuItem value="fearful">fearful（恐惧）</MenuItem>
                      <MenuItem value="disgust">disgust（厌恶）</MenuItem>
                      <MenuItem value="surprised">surprised（惊讶）</MenuItem>
                    </Select>
                  </Box>
                  <Box>
                    <Typography variant="caption" color="text.secondary">参考音频路径</Typography>
                    <TextField size="small" fullWidth placeholder="留空使用参数式情感"
                      value={config.emotionRefAudio}
                      onChange={e => onConfigChange('emotionRefAudio', e.target.value)}
                      sx={{ mt: 0.25, bgcolor: 'background.paper' }} />
                  </Box>
                </Stack>
              </Box>
            </Box>

            <Divider sx={{ my: 1.5 }} />

            <Box>
              {(config.engine === 'indextts' || config.engine === 'cosyvoice') ? (
                <Box sx={{ p: 1.5, bgcolor: 'info.light', borderRadius: 1 }}>
                  <Typography variant="body2" color="info.dark" fontWeight={500}>
                    声音克隆 — 引擎内置
                  </Typography>
                  <Typography variant="caption" color="info.dark">
                    {config.engine} 已内置零样本音色克隆。参考音频请在 TTS 引擎配置中设置，无需在此独立配置 voice cloner。
                  </Typography>
                </Box>
              ) : config.enableVoiceClone ? (
              <>
              <Typography variant="body2" fontWeight={500} gutterBottom>声音克隆</Typography>
              <Box sx={{ ml: 1 }}>
                <Stack spacing={1}>
                  <Box>
                    <Typography variant="caption" color="text.secondary">引擎</Typography>
                    <Select size="small" fullWidth value={config.voiceCloneEngine}
                      onChange={e => onConfigChange('voiceCloneEngine', e.target.value as PipelineConfig['voiceCloneEngine'])}
                      sx={{ mt: 0.25, bgcolor: 'background.paper' }}>
                      <MenuItem value="openvoice">OpenVoice V2</MenuItem>
                      <MenuItem value="cosyvoice">CosyVoice 2.0/3.0</MenuItem>
                    </Select>
                  </Box>
                  <Box>
                    <Typography variant="caption" color="text.secondary">推理设备</Typography>
                    <Select size="small" fullWidth value={config.voiceCloneDevice}
                      onChange={e => onConfigChange('voiceCloneDevice', e.target.value as PipelineConfig['voiceCloneDevice'])}
                      sx={{ mt: 0.25, bgcolor: 'background.paper' }}>
                      <MenuItem value="auto">自动检测</MenuItem>
                      <MenuItem value="cuda:0">GPU (CUDA)</MenuItem>
                      <MenuItem value="cpu">CPU</MenuItem>
                    </Select>
                  </Box>
                  <Box>
                    <Typography variant="caption" color="text.secondary">并发克隆数</Typography>
                    <Select size="small" fullWidth value={config.voiceCloneConcurrency}
                      onChange={e => onConfigChange('voiceCloneConcurrency', Number(e.target.value))}
                      sx={{ mt: 0.25, bgcolor: 'background.paper' }}>
                      {[1, 2, 3, 4].map(n => <MenuItem key={n} value={n}>{n}{n === 1 ? '（串行）' : ''}</MenuItem>)}
                    </Select>
                  </Box>
                  <Box>
                    <Typography variant="caption" color="text.secondary">参考音频路径（留空自动从 Demucs 人声提取）</Typography>
                    <TextField size="small" fullWidth placeholder="留空自动查找 Vocals.wav"
                      value={config.voiceCloneSample}
                      onChange={e => onConfigChange('voiceCloneSample', e.target.value)}
                      sx={{ mt: 0.25, bgcolor: 'background.paper' }} />
                  </Box>
                </Stack>
              </Box>
              </>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  声音克隆 — 请在主面板「启用声音克隆」后配置
                </Typography>
              )}
            </Box>
          </CardContent>
        </Card>
        </Grid>

        {/* Caption style + preview */}
        <Grid size={{ xs: 12, md: 4 }}>
        <Card sx={{ height: '100%', bgcolor: 'action.hover' }}>
          <CardContent>
            <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
              <Typography variant="subtitle2">字幕样式与预览</Typography>
              {videoInfo && (
                <Typography variant="caption" color="text.secondary">
                  {videoInfo.width}×{videoInfo.height}　自动字号: {autoFontSize}px
                </Typography>
              )}
            </Box>

            {/* Preset selector */}
            <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', mb: 1.5 }}>
              {STYLE_PRESETS.map((p, i) => (
                <Tooltip key={p.name} title={p.description} arrow>
                  <Chip
                    label={p.name}
                    size="small"
                    variant={activePresetIndex === i ? 'filled' : 'outlined'}
                    color={activePresetIndex === i ? 'primary' : 'default'}
                    onClick={() => applyPreset(p)}
                    sx={{ cursor: 'pointer' }}
                  />
                </Tooltip>
              ))}
              {activePresetIndex === -1 && (
                <Chip label="自定义" size="small" variant="filled" color="warning" />
              )}
            </Box>

            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 1.5, mb: 1.5 }}>
              <Box>
                <Typography variant="caption" color="text.secondary">字体</Typography>
                <Select size="small" fullWidth value={config.captionFont || ''}
                  displayEmpty
                  onChange={e => onConfigChange('captionFont', e.target.value)}
                  sx={{ mt: 0.25, bgcolor: 'background.paper' }}>
                  <MenuItem value="">默认 (Minecraft)</MenuItem>
                  <MenuItem disabled divider>── 系统字体 (PIL+IM) ──</MenuItem>
                  {Object.entries(FONT_SYSTEM).filter(([,v]) => v).map(([k, v]) => (
                    <MenuItem key={k} value={v}>{k === 'yahei' ? '微软雅黑 Bold' : k === 'simhei' ? '黑体 SimHei' : k === 'kaiti' ? '楷体 KaiTi' : k === 'fangsong' ? '仿宋 FangSong' : v}</MenuItem>
                  ))}
                  <MenuItem disabled divider>── 项目字体 ──</MenuItem>
                  {fonts.map(f => (
                    <MenuItem key={f.path} value={f.path}>{f.name}</MenuItem>
                  ))}
                </Select>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  字号模式
                </Typography>
                <ToggleButtonGroup size="small" fullWidth exclusive
                  value={config.captionFontSizeMode || 'adaptive'}
                  onChange={(_, v) => {
                    if (!v) return
                    onConfigChange('captionFontSizeMode', v)
                    if (v === 'fixed' && !(config.captionFontSize > 0)) {
                      onConfigChange('captionFontSize', autoFontSize)
                    }
                  }}
                  sx={{ mt: 0.25, '& .MuiToggleButton-root': { flex: 1, py: 0.5 } }}>
                  <ToggleButton value="adaptive">自适应</ToggleButton>
                  <ToggleButton value="fixed">固定</ToggleButton>
                </ToggleButtonGroup>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {config.captionFontSizeMode === 'fixed'
                    ? `字号 (固定) px`
                    : `字号 (自适应 → ${autoFontSize}px)`}
                </Typography>
                <TextField size="small" type="number" fullWidth
                  value={config.captionFontSizeMode === 'fixed'
                    ? (config.captionFontSize || autoFontSize)
                    : autoFontSize}
                  disabled={config.captionFontSizeMode !== 'fixed'}
                  onChange={e => onConfigChange('captionFontSize', Number(e.target.value))}
                  inputProps={{ min: 8, max: 200, step: 2 }}
                  sx={{ mt: 0.25, bgcolor: config.captionFontSizeMode === 'fixed'
                    ? 'background.paper'
                    : 'action.disabledBackground' }} />
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">描边宽度 (0=默认)</Typography>
                <TextField size="small" type="number" fullWidth value={config.captionStrokeWidth || 0}
                  inputProps={{ min: 0, max: 10, step: 0.5 }}
                  onChange={e => onConfigChange('captionStrokeWidth', Number(e.target.value))}
                  sx={{ mt: 0.25, bgcolor: 'background.paper' }} />
              </Box>
            </Box>

            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 1.5, mb: 1.5 }}>
              <Box>
                <Typography variant="caption" color="text.secondary">字体颜色</Typography>
                <TextField size="small" type="color" fullWidth value={config.captionFontColor || '#ffffff'}
                  onChange={e => onConfigChange('captionFontColor', e.target.value)}
                  sx={{ mt: 0.25, bgcolor: 'background.paper', '& input': { p: 0.5 } }} />
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">描边颜色</Typography>
                <TextField size="small" type="color" fullWidth value={config.captionStrokeColor || '#000000'}
                  onChange={e => onConfigChange('captionStrokeColor', e.target.value)}
                  sx={{ mt: 0.25, bgcolor: 'background.paper', '& input': { p: 0.5 } }} />
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">对齐方式</Typography>
                <Select size="small" fullWidth value={config.captionAlignment || 'center'}
                  onChange={e => onConfigChange('captionAlignment', e.target.value as 'center' | 'left' | 'right')}
                  sx={{ mt: 0.25, bgcolor: 'background.paper' }}>
                  <MenuItem value="center">居中</MenuItem>
                  <MenuItem value="left">左对齐</MenuItem>
                  <MenuItem value="right">右对齐</MenuItem>
                </Select>
              </Box>
            </Box>

            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 1.5, mb: 1.5 }}>
              <Box>
                <Typography variant="caption" color="text.secondary">背景 RGBA</Typography>
                <TextField size="small" fullWidth placeholder="rgba(0,0,0,128)"
                  value={config.captionBgColor || ''}
                  onChange={e => onConfigChange('captionBgColor', e.target.value)}
                  sx={{ mt: 0.25, bgcolor: 'background.paper' }} />
                <Box sx={{ display: 'flex', gap: 0.5, mt: 0.25 }}>
                  {[{label: '黑底', v: 'rgba(0,0,0,128)'}, {label: '白底', v: 'rgba(255,255,255,100)'}, {label: '透明', v: 'rgba(0,0,0,0)'}].map(p => (
                    <Chip key={p.label} label={p.label} size="small" variant="outlined"
                      onClick={() => onConfigChange('captionBgColor', p.v)}
                      color={config.captionBgColor === p.v ? 'primary' : 'default'}
                      sx={{ cursor: 'pointer' }} />
                  ))}
                </Box>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">位置</Typography>
                <Select size="small" fullWidth value={config.captionPosition || 'bottom'}
                  onChange={e => onConfigChange('captionPosition', e.target.value as 'bottom' | 'top')}
                  sx={{ mt: 0.25, bgcolor: 'background.paper' }}>
                  <MenuItem value="bottom">底部</MenuItem>
                  <MenuItem value="top">顶部</MenuItem>
                </Select>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">渲染引擎</Typography>
                <Select size="small" fullWidth value={config.subtitleEngine || 'pil'}
                  onChange={e => onConfigChange('subtitleEngine', e.target.value as 'pil' | 'imagemagick')}
                  sx={{ mt: 0.25, bgcolor: 'background.paper' }}>
                  <MenuItem value="pil">PIL/Pillow (推荐)</MenuItem>
                  <MenuItem value="imagemagick">ImageMagick (需安装)</MenuItem>
                </Select>
              </Box>
            </Box>

            {/* Subtitle optimization */}
            <Divider sx={{ my: 1.5 }} />
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <Typography variant="subtitle2">字幕渲染优化</Typography>
              <FormControlLabel
                control={<Checkbox size="small" checked={config.enableSubtitleOptimization !== false}
                  onChange={e => onConfigChange('enableSubtitleOptimization', e.target.checked)} />}
                label={<Typography variant="caption">启用优化</Typography>}
                sx={{ ml: 1 }} />
            </Box>
            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 1.5, mb: 1.5 }}>
              <Box>
                <Tooltip title="字幕最大显示行数，超出时缩小字号或拆分" arrow>
                  <Typography variant="caption" color="text.secondary">最大行数</Typography>
                </Tooltip>
                <TextField size="small" type="number" fullWidth value={config.captionMaxLines || 2}
                  inputProps={{ min: 1, max: 5, step: 1 }}
                  onChange={e => onConfigChange('captionMaxLines', Number(e.target.value))}
                  sx={{ mt: 0.25, bgcolor: 'background.paper' }} />
              </Box>
              <Box>
                <Tooltip title="字号相对于视频宽度的缩放比例" arrow>
                  <Typography variant="caption" color="text.secondary">字号因子</Typography>
                </Tooltip>
                <TextField size="small" type="number" fullWidth value={config.captionFontSizeFactor || 0.030}
                  disabled
                  inputProps={{ min: 0.010, max: 0.080, step: 0.005 }}
                  sx={{ mt: 0.25, bgcolor: 'action.disabledBackground' }} />
              </Box>
              <Box>
                <Tooltip title="字幕显示的最大字号（px），0=自动" arrow>
                  <Typography variant="caption" color="text.secondary">最大字号</Typography>
                </Tooltip>
                <TextField size="small" type="number" fullWidth value={config.captionMaxFontSize || 0}
                  disabled
                  inputProps={{ min: 0, max: 200, step: 4 }}
                  sx={{ mt: 0.25, bgcolor: 'action.disabledBackground' }} />
              </Box>
              <Box>
                <Tooltip title="字幕文本框宽度占视频宽度的比例" arrow>
                  <Typography variant="caption" color="text.secondary">宽度比例</Typography>
                </Tooltip>
                <TextField size="small" type="number" fullWidth value={config.captionWidthRatio || 0.85}
                  disabled
                  inputProps={{ min: 0.50, max: 1.0, step: 0.05 }}
                  sx={{ mt: 0.25, bgcolor: 'action.disabledBackground' }} />
              </Box>
            </Box>

            {/* Preview */}
            <Box sx={{ borderRadius: 1, overflow: 'auto', bgcolor: '#1e1e1e', position: 'relative', minHeight: 120 }}>
              {previewLoading && (
                <Box sx={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1 }}>
                  <CircularProgress size={24} />
                </Box>
              )}
              {previewUrl ? (
                <img src={previewUrl} alt="字幕预览"
                  style={{ width: '600px', maxWidth: 'none', display: 'block', opacity: previewLoading ? 0.4 : 1, transition: 'opacity 0.2s' }} />
              ) : (
                <Box sx={{ p: 3, textAlign: 'center' }}>
                  <Typography variant="caption" color="text.secondary">
                    {fonts.length === 0 ? '加载中...' : (previewError || '预览不可用')}
                  </Typography>
                </Box>
              )}
            </Box>
          </CardContent>
        </Card>
        </Grid>

        {/* Segment params */}
        <Grid size={{ xs: 12, md: 4 }}>
        <Card sx={{ height: '100%', bgcolor: 'action.hover' }}>
          <CardContent>
            <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
              <Box>
                <Typography variant="subtitle2">字幕分段参数</Typography>
                <Typography variant="caption" color="text.secondary">
                  语言: {langLabel} ({langKey})
                </Typography>
              </Box>
              <Box display="flex" alignItems="center" gap={1}>
                <Box component="span" sx={{ px: 0.75, py: 0.2, bgcolor: overrides[langKey] && Object.keys(overrides[langKey]!).length > 0 ? 'warning.light' : 'success.light', borderRadius: 1, fontSize: '0.7rem', fontWeight: 500 }}>
                  {overrides[langKey] && Object.keys(overrides[langKey]!).length > 0 ? '已自定义' : '默认'}
                </Box>
                <Button size="small" variant="outlined" color="secondary" startIcon={<RestoreIcon />}
                  onClick={handleReset} sx={{ minWidth: 0, px: 1, fontSize: '0.75rem' }}>
                  恢复默认
                </Button>
              </Box>
            </Box>

            <Divider sx={{ mb: 1 }} />

            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1.5 }}>
              {SUBTITLE_PARAMS.map(p => {
                const val = currentParams[p.key]
                return (
                  <Box key={p.key}>
                    <Typography variant="caption" color="text.secondary">{p.label}</Typography>
                    <TextField size="small" type="number" fullWidth value={val ?? ''}
                      inputProps={{ min: p.min, max: p.max, step: p.step }}
                      onChange={e => handleParamChange(p.key, Number(e.target.value))}
                      sx={{ bgcolor: 'background.paper', mt: 0.25 }} />
                  </Box>
                )
              })}
            </Box>

            {basePreset['sentence_end'] != null && (
              <Box sx={{ mt: 1.5, p: 1, bgcolor: 'background.paper', borderRadius: 1 }}>
                <Typography variant="caption" color="text.secondary">
                  句末标点: {String(basePreset['sentence_end'])}　停顿标点: {String(basePreset['clause_pause'] ?? '')}
                </Typography>
              </Box>
            )}
          </CardContent>
        </Card>
        </Grid>
      </Grid>
    </>
  )
}
