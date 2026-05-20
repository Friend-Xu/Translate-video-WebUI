import React, { useState, useEffect } from 'react'
import {
  Box, Typography, Card, CardContent, Select, MenuItem, TextField, Divider, Alert,
  FormControlLabel, Checkbox, Switch, Slider, Stack, Button, Chip, CircularProgress,
  Dialog, DialogTitle, DialogContent, DialogActions,
} from '@mui/material'
import Grid from '@mui/material/Grid'
import { SectionHeader } from '../SectionHeader'
import { ApiConfigDialog } from '../ApiConfigDialog'
import { CustomPromptDialog } from '../CustomPromptDialog'
import type { PipelineConfig, SystemInfo } from '../../types'

const EDGE_VOICE_OPTIONS: { value: string; label: string }[] = [
  { value: 'zh-CN-XiaoxiaoNeural', label: 'zh-CN-XiaoxiaoNeural (简体中文)' },
  { value: 'zh-CN-YunxiNeural', label: 'zh-CN-YunxiNeural (简体中文)' },
  { value: 'zh-CN-XiaoyiNeural', label: 'zh-CN-XiaoyiNeural (简体中文)' },
  { value: 'zh-TW-HsiaoChenNeural', label: 'zh-TW-HsiaoChenNeural (繁體中文)' },
  { value: 'ja-JP-NanamiNeural', label: 'ja-JP-NanamiNeural (日本語)' },
  { value: 'en-US-AriaNeural', label: 'en-US-AriaNeural (English)' },
  { value: 'ko-KR-SunHiNeural', label: 'ko-KR-SunHiNeural (한국어)' },
  { value: 'fr-FR-DeniseNeural', label: 'fr-FR-DeniseNeural (Français)' },
  { value: 'de-DE-KatjaNeural', label: 'de-DE-KatjaNeural (Deutsch)' },
  { value: 'es-ES-ElviraNeural', label: 'es-ES-ElviraNeural (Español)' },
  { value: 'pt-BR-FranciscaNeural', label: 'pt-BR-FranciscaNeural (Português)' },
  { value: 'ru-RU-SvetlanaNeural', label: 'ru-RU-SvetlanaNeural (Русский)' },
]

// 目标语言 → 默认 EdgeTTS voice
const TARGET_LANG_TO_VOICE: Record<string, string> = {
  'zh-CN': 'zh-CN-XiaoxiaoNeural',
  'zh-TW': 'zh-TW-HsiaoChenNeural',
  ja: 'ja-JP-NanamiNeural',
  en: 'en-US-AriaNeural',
  ko: 'ko-KR-SunHiNeural',
  fr: 'fr-FR-DeniseNeural',
  de: 'de-DE-KatjaNeural',
  es: 'es-ES-ElviraNeural',
  pt: 'pt-BR-FranciscaNeural',
  ru: 'ru-RU-SvetlanaNeural',
}
import { PROVIDER_PRESETS } from '../../types'
import CosyVoiceTTSPanel from './CosyVoiceTTSPanel'
import IndexTTSPanel from './IndexTTSPanel'

interface StepConfigProps {
  config: PipelineConfig
  onConfigChange: <K extends keyof PipelineConfig>(key: K, value: PipelineConfig[K]) => void
  chatttsWorkers?: number
}

/** VRAM 需求估算 (MB per worker) */
const VRAM_PER_WORKER: Record<string, number> = {
  small: 1500,
  medium: 3000,
  large: 6000,
}

function ChatTTSPanel({ config, onConfigChange, chatttsWorkers }: StepConfigProps) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [modelReady, setModelReady] = useState(false)
  const [modelCheckDone, setModelCheckDone] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [downloadPct, setDownloadPct] = useState(0)
  const [downloadGb, setDownloadGb] = useState(0)
  const [downloadTotalGb, setDownloadTotalGb] = useState(2.37)
  const [speakers, setSpeakers] = useState<{ id: string; name: string; pt_file: string }[]>([])

  // 加载预设音色列表
  const fetchSpeakers = async () => {
    try {
      const res = await fetch('/api/tts/speakers')
      if (res.ok) setSpeakers(await res.json())
    } catch { /* API 不可用 */ }
  }
  useEffect(() => { fetchSpeakers() }, [])

  // 当前选中的音色 ID（预设 id 或 "custom"）
  const selectedSpeakerId = config.chatttsSpeakerPt
    ? (speakers.find(s => config.chatttsSpeakerPt.endsWith(s.pt_file))?.id || 'custom')
    : 'custom'

  // 检查模型状态
  const checkModel = async () => {
    try {
      const res = await fetch('/api/models')
      if (res.ok) {
        const data = await res.json()
        const chattts = (data.models || []).find((m: any) => m.id === 'chattts')
        if (chattts) {
          setModelReady(chattts.exists)
        }
      }
    } catch { /* API 不可用，按模型未下载处理 */ }
    setModelCheckDone(true)
  }

  useEffect(() => { checkModel() }, [])

  // PT 预设音色：启动时从服务端缓存静默加载试听，无需 GPU
  useEffect(() => {
    if (modelCheckDone && modelReady && !config.chatttsPreviewAudio && config.chatttsSpeakerPt) {
      doPreviewSpeaker(config.chatttsSpeakerPt)
    }
  }, [modelCheckDone, modelReady])

  const doPreviewSpeaker = async (ptPath: string) => {
    setLoading(true)
    setError('')
    onConfigChange('chatttsPreviewAudio', '')
    try {
      const res = await fetch('/api/tts/preview-chattts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          speaker_pt: ptPath,
          model_source: config.chatttsModelSource,
          model_path: config.chatttsModelPath,
        }),
      })
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || `服务器错误 (${res.status})`)
      }
      const data = await res.json()
      onConfigChange('chatttsPreviewAudio', data.audio_base64)
      onConfigChange('chatttsPreviewSeed', data.seed)
      if (data.spk_emb) onConfigChange('chatttsSpkEmb', data.spk_emb)
    } catch (e: any) {
      console.error('ChatTTS preview failed:', e)
      setError(e?.message || '预览失败')
    } finally {
      setLoading(false)
    }
  }

  const doGacha = async () => {
    setLoading(true)
    setError('')
    onConfigChange('chatttsPreviewAudio', '')
    try {
      const res = await fetch('/api/tts/preview-chattts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          seed: config.chatttsSpeakerSeed,
          model_source: config.chatttsModelSource,
          model_path: config.chatttsModelPath,
          spk_emb: config.chatttsSpkEmb || '',
        }),
      })
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || `服务器错误 (${res.status})`)
      }
      const data = await res.json()
      onConfigChange('chatttsPreviewAudio', data.audio_base64)
      onConfigChange('chatttsPreviewSeed', data.seed)
      onConfigChange('chatttsSpeakerSeed', data.seed)
      if (data.spk_emb) {
        onConfigChange('chatttsSpkEmb', data.spk_emb)
      }
    } catch (e: any) {
      console.error('ChatTTS preview failed:', e)
      setError(e?.message || '预览失败')
    } finally {
      setLoading(false)
    }
  }

  const startDownload = () => {
    setDownloading(true)
    setDownloadPct(0)
    setError('')
    const es = new EventSource('/api/models/download/chattts')
    es.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.status === 'downloading') {
          setDownloadPct(msg.progress)
          setDownloadGb(msg.downloaded_gb)
          setDownloadTotalGb(msg.total_gb)
        } else if (msg.status === 'completed') {
          setDownloading(false)
          setModelReady(true)
          es.close()
        } else if (msg.status === 'error') {
          setError(msg.message || '下载失败')
          setDownloading(false)
          es.close()
        }
      } catch { /* ignore parse errors */ }
    }
    es.onerror = () => {
      if (downloading) {
        setError('下载连接中断，请重试')
        setDownloading(false)
      }
      es.close()
    }
  }

  return (
    <>
      <Box>
        <Typography variant="body2" fontWeight={500}>音色预览</Typography>
        {!modelCheckDone ? (
          <Typography variant="caption" color="text.secondary">检测模型状态...</Typography>
        ) : !modelReady ? (
          <Box sx={{ mt: 0.5 }}>
            {downloading ? (
              <Stack spacing={1}>
                <Box display="flex" alignItems="center" gap={1}>
                  <CircularProgress size={16} />
                  <Typography variant="body2">
                    下载中 {downloadPct}% ({downloadGb.toFixed(1)}/{downloadTotalGb.toFixed(1)} GB)
                  </Typography>
                </Box>
                <Box sx={{ width: '100%', bgcolor: 'divider', borderRadius: 1, height: 6 }}>
                  <Box sx={{ width: `${downloadPct}%`, bgcolor: 'primary.main', borderRadius: 1, height: 6, transition: 'width 0.3s' }} />
                </Box>
              </Stack>
            ) : (
              <Stack spacing={1}>
                <Alert severity="warning" sx={{ mt: 1 }}>
                  模型未下载（{downloadTotalGb} GB）。下载后即可抽卡试听音色。
                </Alert>
                <Button variant="contained" size="small" onClick={startDownload}>
                  下载 ChatTTS 模型 (2.37 GB)
                </Button>
              </Stack>
            )}
          </Box>
        ) : (
          <>
            <Select
              size="small"
              fullWidth
              value={selectedSpeakerId}
              onChange={e => {
                const v = e.target.value
                if (v === 'custom') {
                  onConfigChange('chatttsSpeakerPt', '')
                  onConfigChange('chatttsPreviewAudio', '')
                  onConfigChange('chatttsPreviewSeed', null)
                  onConfigChange('chatttsSpkEmb', '')
                } else {
                  const speaker = speakers.find(s => s.id === v)
                  const ptPath = speaker ? `models/chattts_speakers/${speaker.pt_file}` : ''
                  onConfigChange('chatttsSpeakerPt', ptPath)
                  onConfigChange('chatttsSpeakerSeed', null)
                  onConfigChange('chatttsPreviewAudio', '')
                  onConfigChange('chatttsPreviewSeed', null)
                  onConfigChange('chatttsSpkEmb', '')
                  // 预告音色
                  if (ptPath) doPreviewSpeaker(ptPath)
                }
                setError('')
              }}
              sx={{ bgcolor: 'background.paper', mt: 0.5 }}
            >
              {speakers.map(s => (
                <MenuItem key={s.id} value={s.id}>{s.name}</MenuItem>
              ))}
              <MenuItem value="custom">自定义 (抽卡/随机)</MenuItem>
            </Select>
            {selectedSpeakerId === 'custom' && (
              <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                <TextField
                  size="small"
                  type="number"
                  value={config.chatttsSpeakerSeed ?? ''}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                    const v = e.target.value
                    onConfigChange('chatttsSpeakerSeed', v === '' ? null : Number(v))
                    onConfigChange('chatttsPreviewAudio', '')
                    onConfigChange('chatttsPreviewSeed', null)
                    onConfigChange('chatttsSpkEmb', '')
                    setError('')
                  }}
                  placeholder="种子(留空随机)"
                  inputProps={{ min: 0, max: 99999, style: { width: 80 } }}
                  sx={{ bgcolor: 'background.paper', width: 120 }}
                />
                <Button
                  variant="outlined"
                  size="small"
                  onClick={doGacha}
                  disabled={loading}
                  sx={{ flexShrink: 0 }}
                >
                  {loading ? <CircularProgress size={16} sx={{ mr: 0.5 }} /> : null}
                  抽卡试听
                </Button>
                <Button
                  variant="text"
                  size="small"
                  color="error"
                  onClick={() => {
                    onConfigChange('chatttsSpeakerSeed', null)
                    onConfigChange('chatttsPreviewAudio', '')
                    onConfigChange('chatttsPreviewSeed', null)
                    onConfigChange('chatttsSpkEmb', '')
                    setError('')
                  }}
                  sx={{ flexShrink: 0 }}
                >
                  随机
                </Button>
              </Stack>
            )}
          </>
        )}
      </Box>
      {error && (
        <Alert severity="error" onClose={() => setError('')} sx={{ mt: 1 }}>
          {error}
        </Alert>
      )}
      {config.chatttsPreviewAudio && (
        <Box>
          <Typography variant="body2" fontWeight={500}>
            试听样本 {config.chatttsSpeakerPt
              ? `(${speakers.find(s => config.chatttsSpeakerPt.endsWith(s.pt_file))?.name || '预设音色'})`
              : config.chatttsPreviewSeed != null ? `(种子: ${config.chatttsPreviewSeed})` : ''}
          </Typography>
          {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
          <audio
            controls
            src={`data:audio/wav;base64,${config.chatttsPreviewAudio}`}
            style={{ width: '100%', marginTop: 4 }}
          />
        </Box>
      )}
      <Box>
        <Typography variant="body2" fontWeight={500}>模型来源 (chattts_model_source)</Typography>
        <Select
          size="small"
          fullWidth
          value={config.chatttsModelSource}
          onChange={e => onConfigChange('chatttsModelSource', e.target.value as 'local' | 'custom')}
          sx={{ bgcolor: 'background.paper', mt: 0.5 }}
        >
          <MenuItem value="local">local (models/ChatTTS/)</MenuItem>
          <MenuItem value="custom">custom (自定义路径)</MenuItem>
        </Select>
        <Typography variant="caption">模型统一存储在 models/ 目录下</Typography>
      </Box>
      {config.chatttsModelSource === 'custom' && (
        <Box>
          <Typography variant="body2" fontWeight={500}>自定义模型路径 (chattts_model_path)</Typography>
          <TextField
            size="small"
            fullWidth
            value={config.chatttsModelPath}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => onConfigChange('chatttsModelPath', e.target.value)}
            placeholder="D:/models/ChatTTS"
            sx={{ bgcolor: 'background.paper', mt: 0.5 }}
          />
          <Typography variant="caption">本地模型文件夹的绝对路径</Typography>
        </Box>
      )}
      <Box sx={{ pt: 1, borderTop: '1px solid', borderColor: 'divider' }}>
        <Box display="flex" justifyContent="space-between">
          <Typography variant="body2" fontWeight={500}>ChatTTS 并行数</Typography>
          <Typography variant="body2" fontWeight={600} color="primary">{config.chatttsWorkers || chatttsWorkers || 1}</Typography>
        </Box>
        <Typography variant="caption" display="block" mb={1}>
          模型副本数 (0=自动, 上限 {chatttsWorkers || 1} 由 VRAM 决定, 每个 ~2.37 GB)
        </Typography>
        <Slider
          value={config.chatttsWorkers}
          min={0}
          max={chatttsWorkers || 1}
          step={1}
          marks={[
            { value: 0, label: '自动' },
            { value: 1, label: '1' },
            ...(chatttsWorkers && chatttsWorkers >= 2 ? [{ value: chatttsWorkers, label: String(chatttsWorkers) }] : []),
          ]}
          onChange={(_, v) => onConfigChange('chatttsWorkers', v as number)}
        />
      </Box>

      {/* LUFS 响度归一化 */}
      <FormControlLabel
        control={
          <Switch
            checked={config.loudnessNormEnabled}
            onChange={(e) => onConfigChange('loudnessNormEnabled', e.target.checked)}
          />
        }
        label="LUFS 响度归一化"
      />
      {config.loudnessNormEnabled && (
        <Box>
          <FormControlLabel
            control={
              <Checkbox
                checked={config.loudnessTargetAuto}
                onChange={(e) => onConfigChange('loudnessTargetAuto', e.target.checked)}
              />
            }
            label="自动匹配原视频响度"
          />
          <Box display="flex" justifyContent="space-between">
            <Typography variant="body2" fontWeight={500}>目标响度 (LUFS)</Typography>
            <Typography variant="body2" fontWeight={600} color="primary">
              {config.loudnessTargetAuto ? '自动' : config.loudnessTargetLufs.toFixed(0)}
            </Typography>
          </Box>
          <Typography variant="caption" display="block" mb={1}>
            {config.loudnessTargetAuto
              ? '从原视频人声自动测量目标响度，配音与原片听感一致'
              : '-23 = 广播, -16 = 播客, -14 = YouTube. 逐段对齐，保留抑扬顿挫'}
          </Typography>
          <Slider
            value={config.loudnessTargetLufs}
            min={-23}
            max={-14}
            step={1}
            disabled={config.loudnessTargetAuto}
            marks={[
              { value: -23, label: '-23' },
              { value: -16, label: '-16' },
              { value: -14, label: '-14' },
            ]}
            onChange={(_, v) => onConfigChange('loudnessTargetLufs', v as number)}
          />
        </Box>
      )}
    </>
  )
}

export function StepConfig({ config, onConfigChange }: StepConfigProps) {
  const [sysInfo, setSysInfo] = useState<SystemInfo | null>(null)
  const [apiDialogOpen, setApiDialogOpen] = useState(false)
  const [glossaryDicts, setGlossaryDicts] = useState<{name: string, description: string, termCount: number}[]>([])
  const [customPromptOpen, setCustomPromptOpen] = useState(false)
  const [generalSettingsOpen, setGeneralSettingsOpen] = useState(false)

  useEffect(() => {
    fetch('/api/system/info')
      .then(r => r.json())
      .then(setSysInfo)
      .catch(() => {})
    fetch('/api/glossary/dicts')
      .then(r => r.json())
      .then(d => setGlossaryDicts(d.dicts || []))
      .catch(() => {})
  }, [])

  // 目标语言变化时自动选取默认 EdgeTTS 语音
  useEffect(() => {
    const defaultVoice = TARGET_LANG_TO_VOICE[config.targetLang]
    if (defaultVoice && config.voice !== defaultVoice) {
      onConfigChange('voice', defaultVoice)
    }
  }, [config.targetLang])

  const gpuVramMb = sysInfo?.gpuVramMb ?? 0
  const perWorker = VRAM_PER_WORKER[config.model] ?? 1500
  const maxNumWorkers = gpuVramMb > 0
    ? Math.max(1, Math.min(8, Math.floor(gpuVramMb / perWorker)))
    : 1
  return (
    <>
      <SectionHeader title="步骤配置面板 (Step-by-Step 设置)" />
      <Grid container spacing={3}>
        {/* Step 1 */}
        <Grid size={{ xs: 12, md: 4 }}>
          <Card sx={{ height: '100%', bgcolor: 'action.hover' }}>
            <CardContent>
              <Typography variant="subtitle2" gutterBottom>步骤 1: 字幕提取配置</Typography>
              <Stack spacing={2} mt={2}>
                <Box>
                  <Typography variant="body2" fontWeight={500}>语言选择 (--lang)</Typography>
                  <Select size="small" fullWidth value={config.lang} onChange={e => onConfigChange('lang', e.target.value as PipelineConfig['lang'])} sx={{ bgcolor: 'background.paper' }}>
                    <MenuItem value="auto">自动检测</MenuItem>
                    <MenuItem value="en">英文</MenuItem>
                    <MenuItem value="zh">中文</MenuItem>
                    <MenuItem value="ja">日文</MenuItem>
                  </Select>
                  <Typography variant="caption">选择字幕提取时使用的语言</Typography>
                </Box>
                <Box>
                  <Typography variant="body2" fontWeight={500}>模型选择 (--model)</Typography>
                  <Select size="small" fullWidth value={config.model} onChange={e => onConfigChange('model', e.target.value as PipelineConfig['model'])} sx={{ bgcolor: 'background.paper' }}>
                    <MenuItem value="small">小型 (Small)</MenuItem>
                    <MenuItem value="medium">中型 (Medium)</MenuItem>
                    <MenuItem value="turbo">Turbo (推荐)</MenuItem>
                    <MenuItem value="large-v3">大型 (Large-v3)</MenuItem>
                  </Select>
                  <Typography variant="caption">选择字幕提取模型</Typography>
                </Box>
                <Box>
                  <Typography variant="body2" fontWeight={500}>计算精度 (--compute-type)</Typography>
                  <Select size="small" fullWidth value={config.computeType} onChange={e => onConfigChange('computeType', e.target.value as PipelineConfig['computeType'])} sx={{ bgcolor: 'background.paper' }}>
                    <MenuItem value="float16">float16 (GPU 推荐)</MenuItem>
                    <MenuItem value="int8_float16">int8_float16</MenuItem>
                    <MenuItem value="int8">int8 (CPU)</MenuItem>
                    <MenuItem value="float32">float32</MenuItem>
                  </Select>
                  <Typography variant="caption">选择计算精度</Typography>
                </Box>
                <FormControlLabel
                  control={<Checkbox checked={config.enableDemucs} onChange={e => onConfigChange('enableDemucs', e.target.checked)} />}
                  label={<Box><Typography variant="body2">启用 Demucs 人声/背景音分离</Typography><Typography variant="caption" display="block">关闭时使用完整音轨作为背景乐，跳过 AI 分离</Typography></Box>}
                />

                <Box sx={{ pt: 1, borderTop: '1px solid', borderColor: 'divider' }}>
                  <Box display="flex" justifyContent="space-between">
                    <Typography variant="body2" fontWeight={500}>whisper 并发数</Typography>
                    <Typography variant="body2" fontWeight={600} color="primary">{config.numWorkers}</Typography>
                  </Box>
                  <Typography variant="caption" display="block" mb={1}>
                    {sysInfo?.hasGpu
                      ? `GPU: ${sysInfo?.gpuName ?? ''} (${(gpuVramMb / 1024).toFixed(1)}GB), 最大 ${maxNumWorkers} workers`
                      : 'CPU 模式，仅支持串行'}
                  </Typography>
                  <Slider
                    value={config.numWorkers}
                    min={1}
                    max={maxNumWorkers}
                    step={1}
                    disabled={maxNumWorkers <= 1}
                    marks={
                      maxNumWorkers <= 4
                        ? Array.from({ length: maxNumWorkers }, (_, i) => ({ value: i + 1, label: String(i + 1) }))
                        : [{ value: 1, label: '1' }, { value: Math.floor(maxNumWorkers / 2), label: String(Math.floor(maxNumWorkers / 2)) }, { value: maxNumWorkers, label: String(maxNumWorkers) }]
                    }
                    onChange={(_, v) => onConfigChange('numWorkers', v as number)}
                  />
                </Box>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        {/* Step 2 */}
        <Grid size={{ xs: 12, md: 4 }}>
          <Card sx={{ height: '100%', bgcolor: 'action.hover' }}>
            <CardContent>
              <Typography variant="subtitle2" gutterBottom>步骤 2: 翻译配置</Typography>
              <Stack spacing={2} mt={2}>
                <Box sx={{ display: 'flex', gap: 2 }}>
                  <Box sx={{ flex: 1 }}>
                    <Typography variant="body2" fontWeight={500}>源语言</Typography>
                    <Select size="small" fullWidth value={config.lang} onChange={e => onConfigChange('lang', e.target.value as PipelineConfig['lang'])} sx={{ bgcolor: 'background.paper' }}>
                      <MenuItem value="auto">自动检测</MenuItem>
                      <MenuItem value="en">英文</MenuItem>
                      <MenuItem value="zh">中文</MenuItem>
                      <MenuItem value="ja">日文</MenuItem>
                    </Select>
                  </Box>
                  <Box sx={{ flex: 1 }}>
                    <Typography variant="body2" fontWeight={500}>目标语言</Typography>
                    <Select size="small" fullWidth value={config.targetLang} onChange={e => onConfigChange('targetLang', e.target.value as PipelineConfig['targetLang'])} sx={{ bgcolor: 'background.paper' }}>
                      <MenuItem value="zh-CN">简体中文</MenuItem>
                      <MenuItem value="en">English</MenuItem>
                      <MenuItem value="ja">日本語</MenuItem>
                      <MenuItem value="ko">한국어</MenuItem>
                      <MenuItem value="auto">自动</MenuItem>
                    </Select>
                  </Box>
                </Box>
                <Box>
                  <Typography variant="body2" fontWeight={500}>API 配置</Typography>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
                    <Button
                      variant="outlined"
                      size="small"
                      onClick={() => setApiDialogOpen(true)}
                    >
                      配置 API
                    </Button>
                    <Chip
                      label={`${PROVIDER_PRESETS[config.apiProvider]?.name ?? config.apiProvider} / ${config.apiModel || (PROVIDER_PRESETS[config.apiProvider]?.models[0] ?? '未设置')}`}
                      size="small"
                      variant="outlined"
                      color={config.apiKey ? 'success' : 'default'}
                    />
                  </Box>
                  <Typography variant="caption" display="block">
                    点击按钮配置 API 提供商、密钥和模型参数
                  </Typography>
                </Box>

                <Box sx={{ pt: 1, borderTop: '1px solid', borderColor: 'divider' }}>
                  <Box display="flex" justifyContent="space-between">
                    <Typography variant="body2" fontWeight={500}>并发数</Typography>
                    <Typography variant="body2" fontWeight={600} color="primary">{config.concurrency}</Typography>
                  </Box>
                  <Typography variant="caption" display="block" mb={1}>同时翻译的组数 (1=串行, 2~8=并行)</Typography>
                  <Slider value={config.concurrency} min={1} max={8} step={1} marks={[{ value: 1, label: '1' }, { value: 3, label: '3' }, { value: 5, label: '5' }, { value: 8, label: '8' }]} onChange={(_, v) => onConfigChange('concurrency', v as number)} />
                </Box>
                <Box sx={{ pt: 1, borderTop: '1px solid', borderColor: 'divider' }}>
                  <Typography variant="body2" fontWeight={500}>System Prompt</Typography>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
                    <Button
                      variant="outlined"
                      size="small"
                      onClick={() => setCustomPromptOpen(true)}
                    >
                      配置 Prompt
                    </Button>
                    <Chip
                      label={config.customPromptEnabled ? '已自定义' : '系统默认'}
                      size="small"
                      variant="outlined"
                      color={config.customPromptEnabled ? 'primary' : 'default'}
                    />
                  </Box>
                  <Typography variant="caption" display="block">
                    点击按钮配置翻译风格、语气和自定义指令
                  </Typography>
                </Box>
                <Box sx={{ pt: 1, borderTop: '1px solid', borderColor: 'divider' }}>
                  <FormControlLabel
                    control={<Checkbox checked={config.splitBrainEnabled} onChange={e => onConfigChange('splitBrainEnabled', e.target.checked)} />}
                    label={<Box><Typography variant="body2">Split-Brain 翻译模式</Typography><Typography variant="caption" display="block">分离创意翻译与行数约束，提高翻译质量（需额外 API 调用）</Typography></Box>}
                  />
                </Box>
                <Box sx={{ pt: 1, borderTop: '1px solid', borderColor: 'divider' }}>
                  <FormControlLabel
                    control={<Checkbox checked={config.multiAgentEnabled} onChange={e => onConfigChange('multiAgentEnabled', e.target.checked)} />}
                    label={<Box><Typography variant="body2">Multi-Agent 翻译流水线</Typography><Typography variant="caption" display="block">Director→Glossary→Translate→Mapper→Review→Polish（需 3-5x API 调用）</Typography></Box>}
                  />
                </Box>
                {config.multiAgentEnabled && (
                  <Box>
                    <Box display="flex" justifyContent="space-between">
                      <Typography variant="body2" fontWeight={500}>MQM 质量阈值</Typography>
                      <Typography variant="body2" fontWeight={600} color="primary">{config.mqmThreshold}</Typography>
                    </Box>
                    <Typography variant="caption" display="block" mb={1}>低于此值自动重试（0.5~0.8）</Typography>
                    <Slider value={config.mqmThreshold} min={0.5} max={0.8} step={0.05}
                      marks={[{ value: 0.5, label: '0.5' }, { value: 0.6, label: '0.6' }, { value: 0.7, label: '0.7' }, { value: 0.8, label: '0.8' }]}
                      onChange={(_, v) => onConfigChange('mqmThreshold', v as number)} />
                  </Box>
                )}
                <Box sx={{ pt: 1, borderTop: '1px solid', borderColor: 'divider' }}>
                  <Box display="flex" justifyContent="space-between" alignItems="center" mb={0.5}>
                    <Typography variant="body2" fontWeight={500}>术语词典</Typography>
                    <Button
                      size="small"
                      variant="outlined"
                      onClick={() => {
                        fetch('/api/glossary/dicts')
                          .then(r => r.json())
                          .then(d => setGlossaryDicts(d.dicts || []))
                          .catch(() => {})
                      }}
                    >
                      扫描加载
                    </Button>
                  </Box>
                  <Typography variant="caption" color="text.secondary" display="block" mb={0.5}>
                    选择本地术语表，按需注入翻译 prompt（仅源文本中实际出现的术语会被传递）
                  </Typography>
                  <Select
                    size="small"
                    fullWidth
                    multiple
                    value={config.activeGlossary}
                    onChange={e => onConfigChange('activeGlossary', e.target.value as string[])}
                    renderValue={(selected) => (
                      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                        {(selected as string[]).map((name: string) => (
                          <Chip key={name} label={name.replace('.json', '')} size="small" variant="outlined" />
                        ))}
                      </Box>
                    )}
                    sx={{ bgcolor: 'background.paper' }}
                  >
                    {glossaryDicts.length === 0 ? (
                      <MenuItem value="" disabled>未找到术语表文件 — 点击"扫描加载"</MenuItem>
                    ) : glossaryDicts.map(d => (
                      <MenuItem key={d.name} value={d.name + '.json'}>
                        <Checkbox checked={config.activeGlossary.includes(d.name + '.json')} size="small" />
                        {d.name} ({d.termCount}条) {d.description ? `— ${d.description}` : ''}
                      </MenuItem>
                    ))}
                  </Select>
                </Box>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        {/* Step 3 */}
        <Grid size={{ xs: 12, md: 4 }}>
          <Card sx={{ height: '100%', bgcolor: 'action.hover' }}>
            <CardContent>
              <Typography variant="subtitle2" gutterBottom>步骤 3: TTS 合成配置</Typography>
              <Stack spacing={2} mt={2}>
                <Box>
                  <Typography variant="body2" fontWeight={500}>选择 TTS 引擎 (--engine)</Typography>
                  <Select size="small" fullWidth value={config.engine} onChange={e => onConfigChange('engine', e.target.value as PipelineConfig['engine'])} sx={{ bgcolor: 'background.paper', mt: 0.5 }}>
                    <MenuItem value="edge">edge</MenuItem>
                    <MenuItem value="chattts">chattts</MenuItem>
                    <MenuItem value="cosyvoice">cosyvoice</MenuItem>
                    <MenuItem value="indextts">indextts</MenuItem>
                  </Select>
                  <Typography variant="caption">选择用于语音合成的TTS引擎</Typography>
                </Box>
                {config.engine === 'chattts' && (
                  <ChatTTSPanel config={config} onConfigChange={onConfigChange} chatttsWorkers={sysInfo?.chatttsWorkers} />
                )}
                {config.engine === 'cosyvoice' && (
                  <CosyVoiceTTSPanel config={config} onConfigChange={onConfigChange} />
                )}
                {config.engine === 'indextts' && (
                  <IndexTTSPanel config={config} onConfigChange={onConfigChange} />
                )}
                {config.engine === 'edge' && (
                  <>
                    <Box>
                      <Typography variant="body2" fontWeight={500}>选择语音音色 (voice)</Typography>
                      <Select size="small" fullWidth value={config.voice} onChange={e => onConfigChange('voice', e.target.value)} sx={{ bgcolor: 'background.paper', mt: 0.5 }}>
                        {EDGE_VOICE_OPTIONS.map(opt => (
                          <MenuItem key={opt.value} value={opt.value}>{opt.label}</MenuItem>
                        ))}
                      </Select>
                      <Typography variant="caption">根据目标语言自动推荐，可手动切换</Typography>
                    </Box>
                    <Box>
                      <Box display="flex" justifyContent="space-between">
                        <Typography variant="body2" fontWeight={500}>基础语速</Typography>
                        <Typography variant="body2" fontWeight={600} color="primary">{config.speechRate}%</Typography>
                      </Box>
                      <Typography variant="caption" display="block" mb={1}>TTS 合成起始语速 (10%~50%)</Typography>
                      <Slider value={config.speechRate} min={10} max={50} onChange={(_, v) => onConfigChange('speechRate', v as number)} />
                    </Box>
                    <Box>
                      <Box display="flex" justifyContent="space-between">
                        <Typography variant="body2" fontWeight={500}>最大语速</Typography>
                        <Typography variant="body2" fontWeight={600} color="primary">{config.maxSpeed}%</Typography>
                      </Box>
                      <Typography variant="caption" display="block" mb={1}>对齐时允许的最高加速 (50%~100%)</Typography>
                      <Slider value={config.maxSpeed} min={50} max={100} step={5} marks={[{ value: 50, label: '50%' }, { value: 70, label: '70%' }, { value: 100, label: '100%' }]} onChange={(_, v) => onConfigChange('maxSpeed', v as number)} />
                    </Box>
                    <Box sx={{ pt: 1, borderTop: '1px solid', borderColor: 'divider' }}>
                      <Box display="flex" justifyContent="space-between">
                        <Typography variant="body2" fontWeight={500}>TTS 线程数</Typography>
                        <Typography variant="body2" fontWeight={600} color="primary">{config.ttsWorkers}</Typography>
                      </Box>
                      <Typography variant="caption" display="block" mb={1}>EdgeTTS 云端并发线程数 (1=串行, 4~7=推荐)</Typography>
                      <Slider
                        value={config.ttsWorkers}
                        min={1}
                        max={16}
                        step={1}
                        marks={[{ value: 1, label: '1' }, { value: 4, label: '4' }, { value: 7, label: '7' }, { value: 12, label: '12' }, { value: 16, label: '16' }]}
                        onChange={(_, v) => onConfigChange('ttsWorkers', v as number)}
                      />
                    </Box>
                  </>
                )}
                <Divider sx={{ my: 1 }} />
                <Button
                  fullWidth
                  variant="outlined"
                  size="small"
                  onClick={() => setGeneralSettingsOpen(true)}
                  sx={{ justifyContent: 'space-between', py: 0.5 }}
                >
                  <Typography variant="body2" fontWeight={500}>通用设置</Typography>
                  <Typography variant="caption" color="text.secondary">
                    调速 {config.videoSpeedMin}x–{config.videoSpeedMax}x · BGM {config.bgmVolume.toFixed(1)}x
                  </Typography>
                </Button>
                <FormControlLabel
                  control={<Checkbox checked={config.enableSubtitleOverlay} onChange={e => onConfigChange('enableSubtitleOverlay', e.target.checked)} />}
                  label={<Box><Typography variant="body2">启用字幕叠加</Typography><Typography variant="caption" display="block">选择是否在视频中显示字幕</Typography></Box>}
                />
              </Stack>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
      <Dialog open={generalSettingsOpen} onClose={() => setGeneralSettingsOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>通用设置</DialogTitle>
        <DialogContent dividers>
          <Box sx={{ mb: 3 }}>
            <Box display="flex" justifyContent="space-between">
              <Typography variant="body2" fontWeight={500}>视频最低速度</Typography>
              <Typography variant="body2" fontWeight={600} color="primary">{config.videoSpeedMin}x</Typography>
            </Box>
            <Typography variant="caption" display="block" mb={1}>TTS 音频过长时，视频最多减速到此倍数</Typography>
            <Slider value={config.videoSpeedMin} min={0.50} max={1.00} step={0.05} marks={[{ value: 0.50, label: '0.50x' }, { value: 0.60, label: '0.60x' }, { value: 0.80, label: '0.80x' }, { value: 1.00, label: '1.00x' }]} onChange={(_, v) => onConfigChange('videoSpeedMin', v as number)} />
          </Box>
          <Box sx={{ mb: 3 }}>
            <Box display="flex" justifyContent="space-between">
              <Typography variant="body2" fontWeight={500}>视频最高速度</Typography>
              <Typography variant="body2" fontWeight={600} color="primary">{config.videoSpeedMax}x</Typography>
            </Box>
            <Typography variant="caption" display="block" mb={1}>TTS 音频过短时，视频最多加速到此倍数</Typography>
            <Slider value={config.videoSpeedMax} min={1.05} max={2.00} step={0.05} marks={[{ value: 1.05, label: '1.05x' }, { value: 1.25, label: '1.25x' }, { value: 2.00, label: '2.00x' }]} onChange={(_, v) => onConfigChange('videoSpeedMax', v as number)} />
          </Box>
          <Box>
            <Box display="flex" justifyContent="space-between">
              <Typography variant="body2" fontWeight={500}>背景音乐音量</Typography>
              <Typography variant="body2" fontWeight={600} color="primary">{config.bgmVolume.toFixed(2)}x</Typography>
            </Box>
            <Typography variant="caption" display="block" mb={1}>BGM 与 TTS 语音混合比例 (0=静音, 1=原始, 2=加倍)</Typography>
            <Slider value={config.bgmVolume} min={0} max={2.0} step={0.05} marks={[{ value: 0, label: '0' }, { value: 1.0, label: '1x' }, { value: 2.0, label: '2x' }]} onChange={(_, v) => onConfigChange('bgmVolume', v as number)} />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setGeneralSettingsOpen(false)}>关闭</Button>
        </DialogActions>
      </Dialog>
      <ApiConfigDialog
        open={apiDialogOpen}
        onClose={() => setApiDialogOpen(false)}
        config={config}
        onConfigChange={onConfigChange}
      />
      <CustomPromptDialog
        open={customPromptOpen}
        onClose={() => setCustomPromptOpen(false)}
        config={config}
        onConfigChange={onConfigChange}
      />
    </>
  )
}
