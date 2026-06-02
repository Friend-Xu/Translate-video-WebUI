import { useState, useEffect, useCallback } from 'react'
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
import { useAppStore } from '../../store/useAppStore'

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
function DialogCard({ icon, title, subtitle, children }: {
  icon: React.ReactNode; title: string; subtitle?: string; children: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
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

  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(data => setConfig(data.config || data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const save = useCallback(async () => {
    setSaving(true)
    try {
      await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config, workspace }),
      })
    } catch {}
    setSaving(false)
  }, [config, workspace])

  const set = (key: string, value: any) =>
    setConfig((prev: Record<string, any>) => ({ ...prev, [key]: value }))

  if (loading) return <Box sx={{ p: 4, textAlign: 'center' }}><CircularProgress size={24} /></Box>

  return (
    <Box sx={{ height: '100vh', display: 'flex', flexDirection: 'column', bgcolor: '#f8fafc' }}>
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

          {/* 2. ASR */}
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <SettingCard icon={<RecordVoiceOverIcon />} title="语音识别" subtitle="Whisper 模型配置">
              <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
                <InputLabel>模型</InputLabel>
                <Select value={config.asr_model || 'small'}
                  onChange={e => set('asr_model', e.target.value)} label="模型">
                  <MenuItem value="tiny">tiny</MenuItem>
                  <MenuItem value="base">base</MenuItem>
                  <MenuItem value="small">small</MenuItem>
                  <MenuItem value="medium">medium</MenuItem>
                  <MenuItem value="large-v3">large-v3</MenuItem>
                </Select>
              </FormControl>
              <FormControlLabel control={<Switch size="small"
                checked={config.device === 'cuda'} onChange={e => set('device', e.target.checked ? 'cuda' : 'cpu')} />}
                label="GPU 加速" />
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
            <DialogCard icon={<TranslateIcon />} title="翻译引擎" subtitle="API / 模型 / 质量门禁">
              <FormControl fullWidth size="small" sx={{ mb: 2 }}>
                <InputLabel>API 类型</InputLabel>
                <Select value={config.api_type || 'deepseek'}
                  onChange={e => set('api_type', e.target.value)} label="API 类型">
                  <MenuItem value="deepseek">DeepSeek</MenuItem>
                  <MenuItem value="openai">OpenAI</MenuItem>
                  <MenuItem value="anthropic">Anthropic</MenuItem>
                </Select>
              </FormControl>
              <TextField fullWidth size="small" label="API Key" type="password"
                value={config.api_key || ''} onChange={e => set('api_key', e.target.value)} sx={{ mb: 2 }} />
              <FormControl fullWidth size="small" sx={{ mb: 2 }}>
                <InputLabel>模型</InputLabel>
                <Select value={config.api_model || 'deepseek-chat'}
                  onChange={e => set('api_model', e.target.value)} label="模型">
                  <MenuItem value="deepseek-chat">deepseek-chat</MenuItem>
                  <MenuItem value="deepseek-reasoner">deepseek-reasoner</MenuItem>
                  <MenuItem value="gpt-4o">gpt-4o</MenuItem>
                  <MenuItem value="gpt-4o-mini">gpt-4o-mini</MenuItem>
                  <MenuItem value="claude-3.5-sonnet">claude-3.5-sonnet</MenuItem>
                </Select>
              </FormControl>
              <FormControl fullWidth size="small" sx={{ mb: 2 }}>
                <InputLabel>目标语言</InputLabel>
                <Select value={config.target_lang || 'zh'}
                  onChange={e => set('target_lang', e.target.value)} label="目标语言">
                  <MenuItem value="zh">中文</MenuItem>
                  <MenuItem value="en">English</MenuItem>
                  <MenuItem value="ja">日本語</MenuItem>
                  <MenuItem value="ko">한국어</MenuItem>
                </Select>
              </FormControl>
              <Typography variant="caption" color="text.secondary">并发数: {config.translate_concurrency ?? 3}</Typography>
              <Slider size="small" value={config.translate_concurrency ?? 3} min={1} max={10} step={1}
                onChange={(_, v) => set('translate_concurrency', v)} sx={{ mb: 1 }} />
              <Typography variant="caption" color="text.secondary">温度: {config.temperature ?? 0.1}</Typography>
              <Slider size="small" value={config.temperature ?? 0.1} min={0} max={1} step={0.05}
                onChange={(_, v) => set('temperature', v)} sx={{ mb: 1 }} />
              <FormControlLabel control={<Switch size="small" checked={config.quality_gate !== false}
                onChange={e => set('quality_gate', e.target.checked)} />} label="质量门禁" />
            </DialogCard>
          </Grid>

          {/* 5. TTS 引擎 (弹窗) */}
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <DialogCard icon={<RecordVoiceOverIcon />} title="TTS 引擎" subtitle="引擎 / 语速 / 并发">
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
              <Typography variant="caption" color="text.secondary">语速: {config.speed_factor ?? 1.0}</Typography>
              <Slider size="small" value={config.speed_factor ?? 1.0} min={0.5} max={2.0} step={0.05}
                onChange={(_, v) => set('speed_factor', v)} sx={{ mb: 1 }} />
              <Typography variant="caption" color="text.secondary">并发线程: {config.tts_concurrency ?? 2}</Typography>
              <Slider size="small" value={config.tts_concurrency ?? 2} min={1} max={8} step={1}
                onChange={(_, v) => set('tts_concurrency', v)} sx={{ mb: 1 }} />
              <FormControlLabel control={<Switch size="small" checked={config.loudness_norm !== false}
                onChange={e => set('loudness_norm', e.target.checked)} />} label="音量归一化" />
            </DialogCard>
          </Grid>

          {/* 6. 字幕样式 (弹窗) */}
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <DialogCard icon={<SubtitlesIcon />} title="字幕样式" subtitle="字体 / 颜色 / 位置 / 双语">
              <TextField fullWidth size="small" label="字体"
                value={config.caption_font || 'Microsoft YaHei'}
                onChange={e => set('caption_font', e.target.value)} sx={{ mb: 2 }} />
              <Typography variant="caption" color="text.secondary">字号: {config.caption_font_size ?? 24}</Typography>
              <Slider size="small" value={config.caption_font_size ?? 24} min={12} max={72} step={1}
                onChange={(_, v) => set('caption_font_size', v)} sx={{ mb: 1 }} />
              <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
                <TextField size="small" label="文字颜色" type="color"
                  value={config.caption_color || '#FFFFFF'}
                  onChange={e => set('caption_color', e.target.value)} sx={{ flex: 1 }} />
                <TextField size="small" label="描边颜色" type="color"
                  value={config.caption_stroke_color || '#000000'}
                  onChange={e => set('caption_stroke_color', e.target.value)} sx={{ flex: 1 }} />
              </Box>
              <Typography variant="caption" color="text.secondary">描边宽度: {config.caption_stroke_width ?? 2}px</Typography>
              <Slider size="small" value={config.caption_stroke_width ?? 2} min={0} max={8} step={0.5}
                onChange={(_, v) => set('caption_stroke_width', v)} sx={{ mb: 1 }} />
              <FormControl fullWidth size="small" sx={{ mb: 2 }}>
                <InputLabel>位置</InputLabel>
                <Select value={config.caption_position || 'bottom'}
                  onChange={e => set('caption_position', e.target.value)} label="位置">
                  <MenuItem value="bottom">底部</MenuItem>
                  <MenuItem value="top">顶部</MenuItem>
                  <MenuItem value="center">居中</MenuItem>
                </Select>
              </FormControl>
              <FormControl fullWidth size="small">
                <InputLabel>双语模式</InputLabel>
                <Select value={config.bilingual_mode || 'target_only'}
                  onChange={e => set('bilingual_mode', e.target.value)} label="双语模式">
                  <MenuItem value="target_only">仅译文</MenuItem>
                  <MenuItem value="source_target">原文 + 译文</MenuItem>
                  <MenuItem value="target_source">译文 + 原文</MenuItem>
                </Select>
              </FormControl>
            </DialogCard>
          </Grid>

          {/* 7. 导出 (弹窗) */}
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <DialogCard icon={<FileDownloadIcon />} title="导出" subtitle="格式 / 编码 / 分辨率">
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
            </DialogCard>
          </Grid>
        </Grid>
      </Box>
    </Box>
  )
}
