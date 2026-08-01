import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Box, Typography, Card, CardContent, CardActionArea,
  Select, MenuItem, FormControl, InputLabel, Slider, Switch,
  TextField, Button, FormControlLabel, CircularProgress,
  Dialog, DialogTitle, DialogContent, DialogActions,
  Grid,
} from '@mui/material'
import SaveIcon from '@mui/icons-material/SaveRounded'
import TuneIcon from '@mui/icons-material/TuneRounded'
import TranslateIcon from '@mui/icons-material/TranslateRounded'
import RecordVoiceOverIcon from '@mui/icons-material/RecordVoiceOverRounded'
import SubtitlesIcon from '@mui/icons-material/SubtitlesRounded'
import FileDownloadIcon from '@mui/icons-material/FileDownloadRounded'
import PlayArrowIcon from '@mui/icons-material/PlayArrowRounded'
import EditNoteIcon from '@mui/icons-material/EditNoteRounded'
import { useAppStore } from '../../store/useAppStore'
import { CustomPromptDialog } from '../CustomPromptDialog'

/* ── 简单设置卡片 ── */
function SettingCard({ icon, title, subtitle, children }: {
  icon: React.ReactNode; title: string; subtitle?: string; children: React.ReactNode
}) {
  return (
    <Card sx={{ height: '100%' }}>
      <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
          <Box sx={{ color: 'primary.main' }}>{icon}</Box>
          <Box>
            <Typography variant="subtitle2" fontWeight={600} fontSize="0.85rem">{title}</Typography>
            {subtitle && <Typography variant="caption" color="text.secondary">{subtitle}</Typography>}
          </Box>
        </Box>
        {children}
      </CardContent>
    </Card>
  )
}

/* ── 弹窗设置卡片 ── */
function DialogCard({ icon, title, subtitle, children, onSave }: {
  icon: React.ReactNode; title: string; subtitle?: string; children: React.ReactNode
  onSave?: () => void
}) {
  const [open, setOpen] = useState(false)
  const handleSave = () => { onSave?.(); setOpen(false) }
  return (
    <>
      <Card>
        <CardActionArea onClick={() => setOpen(true)}>
          <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Box sx={{ color: 'primary.main' }}>{icon}</Box>
              <Box sx={{ flexGrow: 1 }}>
                <Typography variant="subtitle2" fontWeight={600} fontSize="0.85rem">{title}</Typography>
                {subtitle && <Typography variant="caption" color="text.secondary">{subtitle}</Typography>}
              </Box>
              <TuneIcon sx={{ fontSize: 18, color: 'text.disabled' }} />
            </Box>
          </CardContent>
        </CardActionArea>
      </Card>
      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{title}</DialogTitle>
        <DialogContent>{children}</DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>关闭</Button>
          <Button variant="contained" onClick={handleSave}>保存</Button>
        </DialogActions>
      </Dialog>
    </>
  )
}

/* ── SettingsView ── */
export default function SettingsView() {
  const workspace = useAppStore(s => s.workspace)
  const setMode = useAppStore(s => s.setMode)
  const [config, setConfig] = useState<Record<string, any>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [auditionLoading, setAuditionLoading] = useState(false)

  const PREVIEW_DEFAULTS: Record<string, string> = {
    chattts: '这是一个ChatTTS语音合成测试案例。',
    edge: '你好，这是Edge TTS语音试听。',
    cosyvoice: '你好，这是CosyVoice语音试听。',
    indextts: '你好，这是IndexTTS语音试听。',
  }
  const engine = config.tts_engine || 'chattts'
  const [previewText, setPreviewText] = useState(PREVIEW_DEFAULTS[engine])
  const [speakers, setSpeakers] = useState<any[]>([])
  const [edgeVoices, setEdgeVoices] = useState<any[]>([])
  const [fonts, setFonts] = useState<any[]>([])
  const [previewImg, setPreviewImg] = useState<string | null>(null)
  const [promptOpen, setPromptOpen] = useState(false)
  // P5-A: 质量策略选项来自 core 注册表 (GET /api/config quality_strategies)
  const [qualityStrategies, setQualityStrategies] = useState<string[]>([])

  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(data => {
        defaultsRef.current = data.defaults || {}
        setQualityStrategies(data.quality_strategies || [])
        setConfig(data.config || data)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
    fetch('/api/tts/speakers')
      .then(r => r.json())
      .then(data => setSpeakers(data || []))
      .catch(() => {})
    fetch('/api/tts/edge-voices')
      .then(r => r.json())
      .then(data => setEdgeVoices(data || []))
      .catch(() => {})
    fetch('/api/fonts')
      .then(r => r.json())
      .then(data => setFonts(data.fonts || []))
      .catch(() => {})
  }, [])

  // 切换引擎时自动切默认试听文本
  useEffect(() => {
    setPreviewText(PREVIEW_DEFAULTS[engine] || '试听文本。')
  }, [engine])

  // P1 差异层: 只持久化用户改过的键; 值=默认 → 发 null (恢复默认, 删除差异)
  const dirtyRef = useRef<Set<string>>(new Set())
  const defaultsRef = useRef<Record<string, any>>({})

  const set = (key: string, value: any) => {
    dirtyRef.current.add(key)
    setConfig((prev: Record<string, any>) => ({ ...prev, [key]: value }))
  }

  const buildPatch = useCallback((): Record<string, any> | null => {
    const dirty = [...dirtyRef.current]
    if (dirty.length === 0) return null
    const patch: Record<string, any> = {}
    for (const k of dirty) {
      if (config[k] === undefined) continue
      patch[k] = config[k] === defaultsRef.current[k] ? null : config[k]
    }
    dirtyRef.current = new Set()
    return Object.keys(patch).length > 0 ? patch : null
  }, [config])

  const save = useCallback(async () => {
    setSaving(true)
    try {
      const patch = buildPatch()
      if (patch) {
        await fetch('/api/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ config: patch, workspace }),
        })
      }
    } catch {}
    setSaving(false)
  }, [buildPatch, workspace])

  const handleResetAll = useCallback(async () => {
    // P4: 恢复默认 = 清空差异层 (POST null 删除全部键, 后端回落到系统默认)
    const reset: Record<string, any> = {}
    for (const k of Object.keys(config)) reset[k] = null
    dirtyRef.current = new Set()
    setConfig(defaultsRef.current || {})
    if (Object.keys(reset).length === 0) return
    try {
      await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config: reset }),
      })
    } catch {}
  }, [config])

  // 自动保存：任何字段变化 800ms 后差异提交（跳过首次加载）
  const initialLoad = useRef(true)
  useEffect(() => {
    if (initialLoad.current) { initialLoad.current = false; return }
    const timer = setTimeout(() => {
      const patch = buildPatch()
      if (!patch) return
      fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config: patch, workspace }),
      }).catch(() => {})
    }, 800)
    return () => clearTimeout(timer)
  }, [config, workspace, buildPatch])

  const handleAudition = async () => {
    setAuditionLoading(true)
    try {
      const seed = config.chattts_speaker_seed ?? 2
      const ptFile = config.chattts_speaker_pt || ''
      const speakerPt = ptFile ? `models/chattts_speakers/${ptFile}` : ''
      const res = await fetch('/api/tts/preview-chattts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          seed,
          text: previewText,
          speaker_pt: speakerPt,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        console.error('ChatTTS preview failed:', err)
        return
      }
      const data = await res.json()
      if (data.audio_base64) {
        const binary = atob(data.audio_base64)
        const bytes = new Uint8Array(binary.length)
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
        const blob = new Blob([bytes], { type: 'audio/wav' })
        const audio = new Audio(URL.createObjectURL(blob))
        audio.play().catch(e => console.error('Audio play failed:', e))
      }
    } catch (e) { console.error('ChatTTS audition error:', e) }
    finally { setAuditionLoading(false) }
  }

  const handleEdgeAudition = async () => {
    setAuditionLoading(true)
    try {
      const voice = config.edge_voice || 'zh-CN-XiaoxiaoNeural'
      const res = await fetch('/api/tts/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ engine: 'edge', voice_id: voice, text: previewText }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        console.error('Edge TTS preview failed:', err)
        return
      }
      const data = await res.json()
      if (data.audio_base64) {
        const binary = atob(data.audio_base64)
        const bytes = new Uint8Array(binary.length)
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
        const blob = new Blob([bytes], { type: 'audio/wav' })
        const audio = new Audio(URL.createObjectURL(blob))
        audio.play().catch(e => console.error('Audio play failed:', e))
      }
    } catch (e) { console.error('Edge TTS audition error:', e) }
    finally { setAuditionLoading(false) }
  }

  // 字幕参数变化时自动刷新预览
  useEffect(() => {
    const fetchPreview = async () => {
      const hexToRgba = (hex: string) => {
        const h = hex.replace('#', '')
        const r = parseInt(h.slice(0, 2), 16)
        const g = parseInt(h.slice(2, 4), 16)
        const b = parseInt(h.slice(4, 6), 16)
        return `rgba(${r},${g},${b},128)`
      }
      const params = new URLSearchParams({
        font: config.caption_font || 'Minecraft_font/5_Minecraft_AE_zh_en.ttf',
        font_size: String(config.caption_font_size ?? 0),
        font_color: config.caption_font_color || 'white',
        stroke_color: config.caption_stroke_color || 'black',
        stroke_width: String(config.caption_stroke_width ?? 2),
        bg_color: hexToRgba(config.caption_bg_color || '#000000'),
        alignment: config.caption_alignment || 'center',
        position: config.caption_position || 'bottom',
        max_lines: String(config.caption_max_lines ?? 2),
        font_size_factor: String(config.caption_font_size_factor ?? 0.030),
        caption_width_ratio: String(config.caption_width_ratio ?? 0.85),
        font_size_mode: (config.caption_font_size ?? 0) > 0 ? 'fixed' : 'adaptive',
        text_zh: 'Minecraft我的世界 村民交易',
        text_en: 'Minecraft Villager Trade x64',
        engine: 'pil',
      })
      try {
        const res = await fetch(`/api/subtitle/preview?${params}`)
        if (res.ok) {
          const blob = await res.blob()
          if (previewImg) URL.revokeObjectURL(previewImg)
          setPreviewImg(URL.createObjectURL(blob))
        }
      } catch {}
    }
    fetchPreview()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    config.caption_font, config.caption_font_size, config.caption_font_color,
    config.caption_stroke_color, config.caption_stroke_width, config.caption_bg_color,
    config.caption_alignment, config.caption_position, config.caption_max_lines,
    config.caption_font_size_factor, config.caption_width_ratio,
  ])

  if (loading) return <Box sx={{ p: 4, textAlign: 'center' }}><CircularProgress size={24} /></Box>

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', bgcolor: '#f8fafc' }}>
      {/* Header */}
      <Box sx={{
        px: 3, py: 2, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        borderBottom: '1px solid', borderColor: 'divider', bgcolor: 'background.paper',
      }}>
        <Box>
          <Typography variant="h6" fontWeight={600}>项目设置</Typography>
          <Typography variant="caption" color="text.secondary">配置翻译、TTS、字幕样式和导出参数</Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button variant="outlined" size="small" onClick={() => setMode('hub')}>返回</Button>
          <Button variant="outlined" size="small" color="warning"
            onClick={handleResetAll} disabled={saving}>恢复默认</Button>
          <Button variant="contained" size="small"
            startIcon={saving ? <CircularProgress size={14} /> : <SaveIcon />}
            onClick={save} disabled={saving}>保存</Button>
        </Box>
      </Box>

      {/* Card Grid */}
      <Box sx={{ flex: 1, overflow: 'auto', p: 3 }}>
        <Grid container spacing={2}>
          {/* 1. 音频预处理 */}
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <SettingCard icon={<RecordVoiceOverIcon />} title="音频预处理" subtitle="Demucs 人声分离">
              <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
                <InputLabel>Demucs 模型</InputLabel>
                <Select value={config.demucs_model || 'htdemucs'}
                  onChange={e => set('demucs_model', e.target.value)} label="Demucs 模型">
                  <MenuItem value="htdemucs">htdemucs (标准)</MenuItem>
                  <MenuItem value="htdemucs_ft">htdemucs_ft (微调)</MenuItem>
                </Select>
              </FormControl>
              <FormControlLabel control={<Switch size="small" checked={config.skip_demucs || false}
                onChange={e => set('skip_demucs', e.target.checked)} />} label="跳过人声分离" />
            </SettingCard>
          </Grid>

          {/* 2. 语言设置 */}
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <SettingCard icon={<TranslateIcon />} title="语言设置" subtitle="源语言 / 目标语言">
              <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
                <InputLabel>源语言</InputLabel>
                <Select value={config.source_lang || 'auto'}
                  onChange={e => set('source_lang', e.target.value)} label="源语言">
                  <MenuItem value="auto">自动检测</MenuItem>
                  <MenuItem value="en">English</MenuItem>
                  <MenuItem value="zh">中文</MenuItem>
                  <MenuItem value="ja">日本語</MenuItem>
                  <MenuItem value="ko">한국어</MenuItem>
                </Select>
              </FormControl>
              <FormControl fullWidth size="small">
                <InputLabel>目标语言</InputLabel>
                <Select value={config.target_lang || 'zh'}
                  onChange={e => set('target_lang', e.target.value)} label="目标语言">
                  <MenuItem value="zh">中文</MenuItem>
                  <MenuItem value="en">English</MenuItem>
                  <MenuItem value="ja">日本語</MenuItem>
                  <MenuItem value="ko">한국어</MenuItem>
                </Select>
              </FormControl>
            </SettingCard>
          </Grid>

          {/* 3. 说话人分离 */}
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <SettingCard icon={<RecordVoiceOverIcon />} title="说话人分离" subtitle="Pyannote 配置">
              <TextField fullWidth size="small" label="最大说话人数 (0=自动)" type="number"
                value={config.max_speakers ?? 0}
                onChange={e => set('max_speakers', parseInt(e.target.value) || 0)} sx={{ mb: 1.5 }} />
              <Typography variant="caption" color="text.secondary">聚类阈值: {config.clustering_threshold ?? 0.65}</Typography>
              <Slider size="small" value={config.clustering_threshold ?? 0.65} min={0.3} max={0.95} step={0.05}
                onChange={(_, v) => set('clustering_threshold', v)} sx={{ mb: 0.5 }} />
            </SettingCard>
          </Grid>

          {/* 4. 翻译引擎 (弹窗) */}
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <DialogCard icon={<TranslateIcon />} title="翻译引擎" subtitle="API / 模型 / 质量门控" onSave={save}>
              <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
                <InputLabel>API 类型</InputLabel>
                <Select value={config.api_type || 'deepseek'}
                  onChange={e => set('api_type', e.target.value)} label="API 类型">
                  <MenuItem value="deepseek">DeepSeek</MenuItem>
                  <MenuItem value="openai">OpenAI</MenuItem>
                  <MenuItem value="anthropic">Anthropic</MenuItem>
                </Select>
              </FormControl>
              <TextField fullWidth size="small" label="API Key" type="password"
                value={config.api_key || ''} onChange={e => set('api_key', e.target.value)} sx={{ mb: 1.5 }} />
              <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
                <InputLabel>模型</InputLabel>
                <Select value={config.model || (config.api_type === 'deepseek' ? 'deepseek-v4-flash' : config.api_type === 'openai' ? 'gpt-4o' : 'claude-sonnet-4-20250514')}
                  onChange={e => set('model', e.target.value)} label="模型">
                  {(config.api_type || 'deepseek') === 'deepseek' ? [
                    <MenuItem key="v4-pro" value="deepseek-v4-pro">deepseek-v4-pro (旗舰)</MenuItem>,
                    <MenuItem key="v4-flash" value="deepseek-v4-flash">deepseek-v4-flash (高速)</MenuItem>,
                  ] : (config.api_type || 'deepseek') === 'openai' ? [
                    <MenuItem key="gpt-4o" value="gpt-4o">gpt-4o</MenuItem>,
                    <MenuItem key="gpt-4o-mini" value="gpt-4o-mini">gpt-4o-mini</MenuItem>,
                  ] : [
                    <MenuItem key="sonnet" value="claude-sonnet-4-20250514">claude-sonnet-4</MenuItem>,
                    <MenuItem key="opus" value="claude-opus-4-20250514">claude-opus-4</MenuItem>,
                  ]}
                </Select>
              </FormControl>
              <TextField fullWidth size="small" label="API Base URL"
                value={config.api_base_url || 'https://api.deepseek.com'}
                onChange={e => set('api_base_url', e.target.value)} sx={{ mb: 1.5 }} />
              <Typography variant="caption" color="text.secondary">并发: {config.translate_concurrency ?? 3}</Typography>
              <Slider size="small" value={config.translate_concurrency ?? 3} min={1} max={10} step={1}
                onChange={(_, v) => set('translate_concurrency', v)} sx={{ mb: 1 }} />
              <Typography variant="caption" color="text.secondary">温度: {config.temperature ?? 0.1}</Typography>
              <Slider size="small" value={config.temperature ?? 0.1} min={0} max={1} step={0.05}
                onChange={(_, v) => set('temperature', v)} sx={{ mb: 1 }} />
              <Typography variant="caption" color="text.secondary">Max Tokens: {config.max_tokens ?? 4000}</Typography>
              <Slider size="small" value={config.max_tokens ?? 4000} min={500} max={16000} step={500}
                onChange={(_, v) => set('max_tokens', v)} sx={{ mb: 1 }} />
              <Typography variant="caption" color="text.secondary">Top P: {config.top_p ?? 0.9}</Typography>
              <Slider size="small" value={config.top_p ?? 0.9} min={0} max={1} step={0.05}
                onChange={(_, v) => set('top_p', v)} sx={{ mb: 1 }} />

              {/* ── 质量门控 (P5-A: 选项来自 core 策略注册表, 单一事实源) ── */}
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                质量门控由翻译策略驱动（始终启用）
              </Typography>
              <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
                <InputLabel>质量策略</InputLabel>
                <Select value={config.verification_mode || 'logic_gate'}
                  onChange={e => set('verification_mode', e.target.value)} label="质量策略">
                  {(qualityStrategies.length > 0 ? qualityStrategies : ['logic_gate', 'xcomet']).map(s => (
                    <MenuItem key={s} value={s}>
                      {s === 'logic_gate' ? '三门逻辑 (MiniLM 语义 + PPL 自然度)'
                        : s === 'xcomet' ? 'XCOMET 模型评分'
                        : s}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>

              {(config.verification_mode || 'logic_gate') === 'logic_gate' && <>
                <Typography variant="caption" color="text.secondary">
                  Gate A 语义底线: {config.semantic_threshold ?? 0.70}
                </Typography>
                <Slider size="small" value={config.semantic_threshold ?? 0.70}
                  min={0.50} max={0.95} step={0.05}
                  onChange={(_, v) => set('semantic_threshold', v)} sx={{ mb: 1 }} />
                <Typography variant="caption" color="text.secondary">
                  Gate C 退化容忍: {config.sim_drop_limit ?? 0.05}
                </Typography>
                <Slider size="small" value={config.sim_drop_limit ?? 0.05}
                  min={0} max={0.20} step={0.01}
                  onChange={(_, v) => set('sim_drop_limit', v)} sx={{ mb: 1 }} />
              </>}

              {/* ── 提示词 ── */}
              <Button variant="outlined" size="small" fullWidth
                startIcon={<EditNoteIcon />}
                onClick={() => setPromptOpen(true)} sx={{ mb: 1.5 }}>
                {config.custom_prompt_enabled ? '自定义 Prompt (已启用)' : '自定义 Prompt'}
              </Button>

              {/* ── 术语表 ── */}
              <FormControlLabel control={<Switch size="small"
                checked={config.enable_glossary !== false}
                onChange={e => set('enable_glossary', e.target.checked)} />}
                label="术语替换" />

              {/* ── 容错 ── */}
              <Typography variant="caption" color="text.secondary">
                重试: {config.max_retries ?? 2} 次
              </Typography>
              <Slider size="small" value={config.max_retries ?? 2}
                min={0} max={5} step={1}
                onChange={(_, v) => set('max_retries', v)} sx={{ mb: 1 }} />
              <FormControlLabel control={<Switch size="small"
                checked={config.fallback_to_single !== false}
                onChange={e => set('fallback_to_single', e.target.checked)} />}
                label="降级单条翻译" />
            </DialogCard>
          </Grid>

          {/* 5. TTS 引擎 (弹窗) */}
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <DialogCard icon={<RecordVoiceOverIcon />} title="TTS 引擎" subtitle="引擎 / 音色 / 参数" onSave={save}>
              <FormControl fullWidth size="small" sx={{ mb: 2 }}>
                <InputLabel>TTS 引擎</InputLabel>
                <Select value={config.tts_engine || 'chattts'}
                  onChange={e => set('tts_engine', e.target.value)} label="TTS 引擎">
                  <MenuItem value="chattts">ChatTTS</MenuItem>
                  <MenuItem value="cosyvoice">CosyVoice</MenuItem>
                  <MenuItem value="edge">Edge-TTS</MenuItem>
                  <MenuItem value="indextts">IndexTTS</MenuItem>
                </Select>
              </FormControl>

              {/* ── ChatTTS 专属设置 ── */}
              {(config.tts_engine || 'chattts') === 'chattts' && <>
                <TextField fullWidth size="small" label="音色种子 (Speaker Seed)" type="number"
                  value={config.chattts_speaker_seed ?? 2}
                  onChange={e => set('chattts_speaker_seed', parseInt(e.target.value) || 2)}
                  sx={{ mb: 1.5 }}
                  slotProps={{ htmlInput: { min: 1, max: 9999 } }} />

                <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
                  <InputLabel>预设音色</InputLabel>
                  <Select value={config.chattts_speaker_pt || ''}
                    onChange={e => set('chattts_speaker_pt', e.target.value)}
                    label="预设音色">
                    <MenuItem value="">随机 (使用种子)</MenuItem>
                    {speakers.map((s: any) => (
                      <MenuItem key={s.id} value={s.pt_file}>
                        {s.name} {s.gender === '男' ? '♂' : '♀'} — {s.features}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>

                <TextField fullWidth size="small" label="试听文本" multiline maxRows={2}
                  value={previewText}
                  onChange={e => setPreviewText(e.target.value)}
                  sx={{ mb: 1.5 }} />

                <Button variant="outlined" size="small" fullWidth
                  startIcon={auditionLoading ? <CircularProgress size={14} /> : <PlayArrowIcon />}
                  onClick={handleAudition} disabled={auditionLoading}
                  sx={{ mb: 2 }}>
                  {auditionLoading ? '合成中…' : '试听音色'}
                </Button>

                <Typography variant="caption" color="text.secondary">
                  温度: {config.chattts_temperature ?? 0.3}
                </Typography>
                <Slider size="small" value={config.chattts_temperature ?? 0.3}
                  min={0.01} max={2.0} step={0.01}
                  onChange={(_, v) => set('chattts_temperature', v)} sx={{ mb: 1 }} />

                <Typography variant="caption" color="text.secondary">
                  Top-K: {config.chattts_top_k ?? 20}
                </Typography>
                <Slider size="small" value={config.chattts_top_k ?? 20}
                  min={1} max={100} step={1}
                  onChange={(_, v) => set('chattts_top_k', v)} sx={{ mb: 1 }} />

                <Typography variant="caption" color="text.secondary">
                  Top-P: {config.chattts_top_p ?? 0.7}
                </Typography>
                <Slider size="small" value={config.chattts_top_p ?? 0.7}
                  min={0.5} max={1.0} step={0.01}
                  onChange={(_, v) => set('chattts_top_p', v)} sx={{ mb: 1 }} />

                <TextField fullWidth size="small" label="Worker 实例数 (0=自动)" type="number"
                  value={config.chattts_workers ?? 0}
                  onChange={e => set('chattts_workers', parseInt(e.target.value) || 0)}
                  sx={{ mb: 1.5 }}
                  slotProps={{ htmlInput: { min: 0, max: 8 } }} />

                <FormControlLabel control={<Switch size="small"
                  checked={config.chattts_emotion_injection !== false}
                  onChange={e => set('chattts_emotion_injection', e.target.checked)} />}
                  label="情感注入" />
              </>}

              {/* ── Edge TTS 专属设置 ── */}
              {(config.tts_engine || 'chattts') === 'edge' && <>
                <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
                  <InputLabel>语音角色</InputLabel>
                  <Select value={config.edge_voice || 'zh-CN-XiaoxiaoNeural'}
                    onChange={e => set('edge_voice', e.target.value)}
                    label="语音角色">
                    {edgeVoices.map((v: any) => (
                      <MenuItem key={v.name} value={v.name}>
                        {v.display} ({v.gender})
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>

                <TextField fullWidth size="small" label="试听文本" multiline maxRows={2}
                  value={previewText}
                  onChange={e => setPreviewText(e.target.value)}
                  sx={{ mb: 1.5 }} />

                <Button variant="outlined" size="small" fullWidth
                  startIcon={auditionLoading ? <CircularProgress size={14} /> : <PlayArrowIcon />}
                  onClick={handleEdgeAudition} disabled={auditionLoading}
                  sx={{ mb: 2 }}>
                  {auditionLoading ? '合成中…' : '试听语音'}
                </Button>

                <Typography variant="caption" color="text.secondary">
                  基准语速: {config.base_speed ?? 40}
                </Typography>
                <Slider size="small" value={config.base_speed ?? 40} min={10} max={100} step={5}
                  onChange={(_, v) => set('base_speed', v)} sx={{ mb: 1 }} />

                <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
                  <InputLabel>语速偏移 (Rate)</InputLabel>
                  <Select value={config.edge_rate || '+0%'}
                    onChange={e => set('edge_rate', e.target.value)}
                    label="语速偏移 (Rate)">
                    {['-50%','-30%','-10%','+0%','+10%','+30%','+50%','+70%','+100%'].map(r =>
                      <MenuItem key={r} value={r}>{r}</MenuItem>
                    )}
                  </Select>
                </FormControl>

                <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
                  <InputLabel>音高 (Pitch)</InputLabel>
                  <Select value={config.edge_pitch || '+0Hz'}
                    onChange={e => set('edge_pitch', e.target.value)}
                    label="音高 (Pitch)">
                    {['-10Hz','-5Hz','+0Hz','+5Hz','+10Hz','+15Hz','+20Hz'].map(p =>
                      <MenuItem key={p} value={p}>{p}</MenuItem>
                    )}
                  </Select>
                </FormControl>

                <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
                  <InputLabel>音量 (Volume)</InputLabel>
                  <Select value={config.edge_volume || '+0%'}
                    onChange={e => set('edge_volume', e.target.value)}
                    label="音量 (Volume)">
                    {['-20%','-10%','+0%','+10%','+20%','+30%'].map(v =>
                      <MenuItem key={v} value={v}>{v}</MenuItem>
                    )}
                  </Select>
                </FormControl>
              </>}

              <Box sx={{ mt: (config.tts_engine || 'chattts') === 'chattts' ? 2 : 0 }}>
                <Typography variant="caption" color="text.secondary">
                  语速: {config.speed_factor ?? 1.0}
                </Typography>
                <Slider size="small" value={config.speed_factor ?? 1.0} min={0.5} max={2.0} step={0.05}
                  onChange={(_, v) => set('speed_factor', v)} sx={{ mb: 1 }} />
                <Typography variant="caption" color="text.secondary">
                  并发线程: {config.tts_concurrency ?? 2}
                </Typography>
                <Slider size="small" value={config.tts_concurrency ?? 2} min={1} max={8} step={1}
                  onChange={(_, v) => set('tts_concurrency', v)} sx={{ mb: 1 }} />
                <FormControlLabel control={<Switch size="small" checked={config.loudness_norm !== false}
                  onChange={e => set('loudness_norm', e.target.checked)} />} label="音量归一化" />
                {config.loudness_norm !== false && <>
                  <Typography variant="caption" color="text.secondary">
                    目标响度: {config.loudness_target_lufs ?? -16} LUFS
                  </Typography>
                  <Slider size="small" value={config.loudness_target_lufs ?? -16} min={-24} max={-12} step={1}
                    onChange={(_, v) => set('loudness_target_lufs', v)} sx={{ mb: 1 }} />
                </>}
                <Typography variant="caption" color="text.secondary">
                  视频变速范围: {config.video_speed_min ?? 0.6}x – {config.video_speed_max ?? 2.0}x
                </Typography>
                <Slider size="small" value={[config.video_speed_min ?? 0.6, config.video_speed_max ?? 2.0]}
                  min={0.3} max={3.0} step={0.05}
                  onChange={(_, v) => { const [a, b] = v as number[]; set('video_speed_min', a); set('video_speed_max', b) }}
                  sx={{ mb: 1 }} />
              </Box>
            </DialogCard>
          </Grid>

          {/* 6. 字幕样式 (弹窗) */}
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <DialogCard icon={<SubtitlesIcon />} title="字幕样式" subtitle="字体 / 颜色 / 布局" onSave={save}>
              {fonts.length > 0 ? (
                <FormControl fullWidth size="small" sx={{ mb: 2 }}>
                  <InputLabel>字体</InputLabel>
                  <Select value={config.caption_font || 'Minecraft_font/5_Minecraft_AE_zh_en.ttf'}
                    onChange={e => set('caption_font', e.target.value)} label="字体">
                    {fonts.map((f: any) => (
                      <MenuItem key={f.relative} value={f.relative}>{f.name}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              ) : (
                <TextField fullWidth size="small" label="字体"
                  value={config.caption_font || 'Minecraft_font/5_Minecraft_AE_zh_en.ttf'}
                  onChange={e => set('caption_font', e.target.value)} sx={{ mb: 2 }} />
              )}
              <Typography variant="caption" color="text.secondary">
                字号: {config.caption_font_size === 0 || !config.caption_font_size ? '自动' : `${config.caption_font_size}px`}
              </Typography>
              <Slider size="small" value={config.caption_font_size ?? 0} min={0} max={72} step={1}
                onChange={(_, v) => set('caption_font_size', v)} sx={{ mb: 1 }} />

              <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
                <TextField size="small" label="文字色" type="color"
                  value={config.caption_font_color || '#FFFFFF'}
                  onChange={e => set('caption_font_color', e.target.value)} sx={{ flex: 1 }} />
                <TextField size="small" label="描边色" type="color"
                  value={config.caption_stroke_color || '#000000'}
                  onChange={e => set('caption_stroke_color', e.target.value)} sx={{ flex: 1 }} />
                <TextField size="small" label="背景色" type="color"
                  value={config.caption_bg_color || '#000000'}
                  onChange={e => set('caption_bg_color', e.target.value)} sx={{ flex: 1 }} />
              </Box>

              <Typography variant="caption" color="text.secondary">描边: {config.caption_stroke_width ?? 2}px</Typography>
              <Slider size="small" value={config.caption_stroke_width ?? 2} min={0} max={8} step={0.5}
                onChange={(_, v) => set('caption_stroke_width', v)} sx={{ mb: 1 }} />

              <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
                <InputLabel>对齐</InputLabel>
                <Select value={config.caption_alignment || 'center'}
                  onChange={e => set('caption_alignment', e.target.value)} label="对齐">
                  <MenuItem value="left">左对齐</MenuItem>
                  <MenuItem value="center">居中</MenuItem>
                  <MenuItem value="right">右对齐</MenuItem>
                </Select>
              </FormControl>

              <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
                <InputLabel>位置</InputLabel>
                <Select value={config.caption_position || 'bottom'}
                  onChange={e => set('caption_position', e.target.value)} label="位置">
                  <MenuItem value="bottom">底部</MenuItem>
                  <MenuItem value="top">顶部</MenuItem>
                </Select>
              </FormControl>

              <Typography variant="caption" color="text.secondary">最大行数: {config.caption_max_lines ?? 2}</Typography>
              <Slider size="small" value={config.caption_max_lines ?? 2} min={1} max={4} step={1}
                onChange={(_, v) => set('caption_max_lines', v)} sx={{ mb: 1 }} />

              <Typography variant="caption" color="text.secondary">
                字号比率: {config.caption_font_size_factor ?? 0.030}
              </Typography>
              <Slider size="small" value={config.caption_font_size_factor ?? 0.030}
                min={0.010} max={0.060} step={0.005}
                onChange={(_, v) => set('caption_font_size_factor', v)} sx={{ mb: 1 }} />

              <Typography variant="caption" color="text.secondary">
                宽度比: {config.caption_width_ratio ?? 0.85}
              </Typography>
              <Slider size="small" value={config.caption_width_ratio ?? 0.85}
                min={0.50} max={0.95} step={0.05}
                onChange={(_, v) => set('caption_width_ratio', v)} sx={{ mb: 1 }} />

              <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
                <InputLabel>字号模式</InputLabel>
                <Select
                  value={(config.caption_font_size ?? 0) > 0 ? 'fixed' : 'adaptive'}
                  onChange={e => {
                    // P4 单源: font_size_mode 派生自 caption_font_size, 不再独立存键
                    if (e.target.value === 'fixed' && !(config.caption_font_size > 0)) {
                      set('caption_font_size', 36)
                    } else if (e.target.value === 'adaptive') {
                      set('caption_font_size', 0)
                    }
                  }}
                  label="字号模式">
                  <MenuItem value="adaptive">自适应 (按视频宽度)</MenuItem>
                  <MenuItem value="fixed">固定字号</MenuItem>
                </Select>
              </FormControl>
              {((config.caption_font_size ?? 0) > 0) && (
                <TextField fullWidth size="small" label="最大字号 (px, 0=不限)" type="number"
                  value={config.max_font_size ?? 0}
                  onChange={e => set('max_font_size', parseInt(e.target.value) || 0)}
                  sx={{ mb: 1.5 }} slotProps={{ htmlInput: { min: 0, max: 200 } }} />
              )}
              <FormControlLabel control={<Switch size="small"
                checked={config.enable_subtitle_optimization !== false}
                onChange={e => set('enable_subtitle_optimization', e.target.checked)} />}
                label="长文本自动拆分" />

              <FormControl fullWidth size="small">
                <InputLabel>双语</InputLabel>
                <Select value={config.bilingual_mode || 'target_only'}
                  onChange={e => set('bilingual_mode', e.target.value)} label="双语">
                  <MenuItem value="target_only">仅译文</MenuItem>
                  <MenuItem value="source_target">原文 + 译文</MenuItem>
                  <MenuItem value="target_source">译文 + 原文</MenuItem>
                </Select>
              </FormControl>

              {previewImg && (
                <Box component="img" src={previewImg}
                  sx={{ width: '100%', mt: 1.5, borderRadius: 1, border: '1px solid', borderColor: 'divider' }} />
              )}
            </DialogCard>
          </Grid>

          {/* 7. 导出 (弹窗) */}
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <DialogCard icon={<FileDownloadIcon />} title="导出" subtitle="格式 / 编码 / 分辨率" onSave={save}>
              <FormControl fullWidth size="small" sx={{ mb: 2 }}>
                <InputLabel>输出格式</InputLabel>
                <Select value={config.output_format || 'mp4'}
                  onChange={e => set('output_format', e.target.value)} label="输出格式">
                  <MenuItem value="mp4">MP4</MenuItem>
                  <MenuItem value="mkv">MKV</MenuItem>
                  <MenuItem value="mov">MOV</MenuItem>
                </Select>
              </FormControl>
              <FormControl fullWidth size="small" sx={{ mb: 2 }}>
                <InputLabel>视频编码</InputLabel>
                <Select value={config.video_codec || 'libx264'}
                  onChange={e => set('video_codec', e.target.value)} label="视频编码">
                  <MenuItem value="libx264">H.264</MenuItem>
                  <MenuItem value="libx265">H.265</MenuItem>
                  <MenuItem value="h264_nvenc">NVENC H.264</MenuItem>
                </Select>
              </FormControl>
              <FormControl fullWidth size="small" sx={{ mb: 2 }}>
                <InputLabel>分辨率</InputLabel>
                <Select value={config.output_resolution || 'original'}
                  onChange={e => set('output_resolution', e.target.value)} label="分辨率">
                  <MenuItem value="original">原始</MenuItem>
                  <MenuItem value="1080p">1080p</MenuItem>
                  <MenuItem value="720p">720p</MenuItem>
                </Select>
              </FormControl>
              <Typography variant="caption" color="text.secondary">码率: {config.video_bitrate ?? 8} Mbps</Typography>
              <Slider size="small" value={config.video_bitrate ?? 8} min={1} max={50} step={1}
                onChange={(_, v) => set('video_bitrate', v)} sx={{ mb: 1 }} />
              <FormControlLabel control={<Switch size="small" checked={config.preserve_original_audio || false}
                onChange={e => set('preserve_original_audio', e.target.checked)} />} label="保留原声轨" />
              <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
                <InputLabel>音频编码</InputLabel>
                <Select value={config.audio_codec || 'aac'}
                  onChange={e => set('audio_codec', e.target.value)} label="音频编码">
                  <MenuItem value="aac">AAC</MenuItem>
                  <MenuItem value="pcm_s16le">PCM (WAV)</MenuItem>
                  <MenuItem value="mp3">MP3</MenuItem>
                </Select>
              </FormControl>
              <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
                <InputLabel>音频码率</InputLabel>
                <Select value={config.audio_bitrate || '192k'}
                  onChange={e => set('audio_bitrate', e.target.value)} label="音频码率">
                  <MenuItem value="128k">128k</MenuItem>
                  <MenuItem value="192k">192k</MenuItem>
                  <MenuItem value="256k">256k</MenuItem>
                  <MenuItem value="320k">320k</MenuItem>
                </Select>
              </FormControl>
              <Typography variant="caption" color="text.secondary">BGM 音量: {config.bgm_volume ?? 1.0}</Typography>
              <Slider size="small" value={config.bgm_volume ?? 1.0} min={0} max={1} step={0.05}
                onChange={(_, v) => set('bgm_volume', v)} sx={{ mb: 1 }} />
            </DialogCard>
          </Grid>
        </Grid>
      </Box>

      <CustomPromptDialog
        open={promptOpen}
        onClose={() => setPromptOpen(false)}
        config={config as any}
        onConfigChange={(k: string, v: any) => set(k as string, v)}
        jointVerification={config.joint_verification ?? false}
      />
    </Box>
  )
}
