import { useState, useEffect } from 'react'
import {
  Box, Typography, Card, CardContent, Select, MenuItem,
  FormControlLabel, Checkbox, Slider, Stack, Button, Chip, TextField,
} from '@mui/material'
import Grid from '@mui/material/Grid'
import { SectionHeader } from '../SectionHeader'
import { ApiConfigDialog } from '../ApiConfigDialog'
import { GlossaryEditor } from './GlossaryEditor'
import type { PipelineConfig, SystemInfo } from '../../types'
import { PROVIDER_PRESETS } from '../../types'

interface StepConfigProps {
  config: PipelineConfig
  onConfigChange: <K extends keyof PipelineConfig>(key: K, value: PipelineConfig[K]) => void
}

/** VRAM 需求估算 (MB per worker) */
const VRAM_PER_WORKER: Record<string, number> = {
  small: 1500,
  medium: 3000,
  large: 6000,
}

export function StepConfig({ config, onConfigChange }: StepConfigProps) {
  const [sysInfo, setSysInfo] = useState<SystemInfo | null>(null)
  const [apiDialogOpen, setApiDialogOpen] = useState(false)
  const [glossaryOpen, setGlossaryOpen] = useState(false)

  useEffect(() => {
    fetch('/api/system/info')
      .then(r => r.json())
      .then(setSysInfo)
      .catch(() => {})
  }, [])

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
                  control={<Checkbox checked={config.enableAudioExtract} onChange={e => onConfigChange('enableAudioExtract', e.target.checked)} />}
                  label={<Typography variant="body2">启用音频提取 (提取音频并修复采样率)</Typography>}
                />
                <FormControlLabel
                  control={<Checkbox checked={config.enableDemucs} onChange={e => onConfigChange('enableDemucs', e.target.checked)} />}
                  label={<Box><Typography variant="body2">启用 Demucs 人声/背景音分离</Typography><Typography variant="caption" display="block">关闭时使用完整音轨作为背景乐，跳过 AI 分离</Typography></Box>}
                />

                <Box sx={{ pt: 1, borderTop: '1px solid', borderColor: 'divider' }}>
                  <FormControlLabel
                    control={<Checkbox checked={config.enableAlignment} onChange={e => onConfigChange('enableAlignment', e.target.checked)} />}
                    label={<Typography variant="body2" fontWeight={500}>启用 wav2vec2 强制对齐</Typography>}
                  />
                  <Typography variant="caption" sx={{ ml: 4, display: 'block', color: 'text.secondary' }}>
                    对齐语言跟随源语言（{config.lang === 'ja' ? '日语' : config.lang === 'en' ? '英语' : config.lang === 'zh' ? '中文' : config.lang === 'auto' ? '自动检测' : config.lang}）
                  </Typography>
                </Box>

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

                <FormControlLabel
                  control={<Checkbox checked={config.enableSemanticValidation} onChange={e => onConfigChange('enableSemanticValidation', e.target.checked)} />}
                  label={<Box><Typography variant="body2">启用语义校验</Typography><Typography variant="caption" display="block">确保翻译一致性</Typography></Box>}
                />
                <FormControlLabel
                  control={<Checkbox checked={config.enableTermReplacement} onChange={e => onConfigChange('enableTermReplacement', e.target.checked)} />}
                  label={<Box><Typography variant="body2">启用术语替换</Typography><Typography variant="caption" display="block">启用术语替换（如Minecraft专有名词）</Typography></Box>}
                />
                <Box sx={{ pt: 1, borderTop: '1px solid', borderColor: 'divider' }}>
                  <Box display="flex" justifyContent="space-between">
                    <Typography variant="body2" fontWeight={500}>并发数</Typography>
                    <Typography variant="body2" fontWeight={600} color="primary">{config.concurrency}</Typography>
                  </Box>
                  <Typography variant="caption" display="block" mb={1}>同时翻译的组数 (1=串行, 2~8=并行)</Typography>
                  <Slider value={config.concurrency} min={1} max={8} step={1} marks={[{ value: 1, label: '1' }, { value: 3, label: '3' }, { value: 5, label: '5' }, { value: 8, label: '8' }]} onChange={(_, v) => onConfigChange('concurrency', v as number)} />
                </Box>
                <Box sx={{ pt: 1, borderTop: '1px solid', borderColor: 'divider' }}>
                  <FormControlLabel
                    control={<Checkbox checked={config.customPromptEnabled} onChange={e => onConfigChange('customPromptEnabled', e.target.checked)} />}
                    label={<Box><Typography variant="body2">启用自定义 System Prompt</Typography><Typography variant="caption" display="block">自定义翻译风格和格式要求</Typography></Box>}
                  />
                </Box>
                {config.customPromptEnabled && (
                  <>
                    <TextField
                      label="System Prompt"
                      multiline minRows={3} maxRows={6}
                      fullWidth size="small"
                      value={config.customSystemPrompt}
                      onChange={e => onConfigChange('customSystemPrompt', e.target.value)}
                      placeholder="你是专业{source_lang}字幕翻译。请将以下{source_lang}逐条翻译成{target_lang}。"
                      helperText="支持变量: {source_lang}, {target_lang}, {fmt}, {retry}"
                    />
                    <TextField
                      label="Batch Prompt 模板"
                      multiline minRows={3} maxRows={6}
                      fullWidth size="small"
                      value={config.customBatchPrompt}
                      onChange={e => onConfigChange('customBatchPrompt', e.target.value)}
                      placeholder="待翻译：{items}翻译："
                      helperText="{items} 将被替换为待翻译字幕列表"
                    />
                  </>
                )}
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
                  <Button variant="outlined" size="small" fullWidth onClick={() => setGlossaryOpen(true)}>
                    Glossary Editor
                  </Button>
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
                    <MenuItem value="coqui">coqui</MenuItem>
                    <MenuItem value="azure">azure</MenuItem>
                  </Select>
                  <Typography variant="caption">选择用于语音合成的TTS引擎</Typography>
                </Box>
                <Box>
                  <Typography variant="body2" fontWeight={500}>选择语音音色 (voice)</Typography>
                  <Select size="small" fullWidth value={config.voice} onChange={e => onConfigChange('voice', e.target.value)} sx={{ bgcolor: 'background.paper', mt: 0.5 }}>
                    <MenuItem value="zh-CN-XiaoxiaoNeural">zh-CN-XiaoxiaoNeural</MenuItem>
                    <MenuItem value="zh-CN-YunxiNeural">zh-CN-YunxiNeural</MenuItem>
                    <MenuItem value="zh-CN-XiaoyiNeural">zh-CN-XiaoyiNeural</MenuItem>
                  </Select>
                  <Typography variant="caption">选择语音音色</Typography>
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
                <Box>
                  <Box display="flex" justifyContent="space-between">
                    <Typography variant="body2" fontWeight={500}>视频最低速度</Typography>
                    <Typography variant="body2" fontWeight={600} color="primary">{config.videoSpeedMin}x</Typography>
                  </Box>
                  <Typography variant="caption" display="block" mb={1}>TTS 音频过长时，视频最多减速到此倍数 (&lt;1.0 = 减速)</Typography>
                  <Slider value={config.videoSpeedMin} min={0.50} max={1.00} step={0.05} marks={[{ value: 0.50, label: '0.50x' }, { value: 0.60, label: '0.60x' }, { value: 0.80, label: '0.80x' }, { value: 1.00, label: '1.00x' }]} onChange={(_, v) => onConfigChange('videoSpeedMin', v as number)} />
                </Box>
                <Box>
                  <Box display="flex" justifyContent="space-between">
                    <Typography variant="body2" fontWeight={500}>视频最高速度</Typography>
                    <Typography variant="body2" fontWeight={600} color="primary">{config.videoSpeedMax}x</Typography>
                  </Box>
                  <Typography variant="caption" display="block" mb={1}>TTS 音频过短时，视频最多加速到此倍数 (&gt;1.0 = 加速，预留，当前策略不使用)</Typography>
                  <Slider value={config.videoSpeedMax} min={1.05} max={2.00} step={0.05} marks={[{ value: 1.05, label: '1.05x' }, { value: 1.25, label: '1.25x' }, { value: 2.00, label: '2.00x' }]} onChange={(_, v) => onConfigChange('videoSpeedMax', v as number)} />
                </Box>
                <Box sx={{ pt: 1, borderTop: '1px solid', borderColor: 'divider' }}>
                  <Box display="flex" justifyContent="space-between">
                    <Typography variant="body2" fontWeight={500}>TTS 线程数</Typography>
                    <Typography variant="body2" fontWeight={600} color="primary">{config.ttsWorkers}</Typography>
                  </Box>
                  <Typography variant="caption" display="block" mb={1}>EdgeTTS 并行合成线程数 (1=串行, 2~16=并行)</Typography>
                  <Slider
                    value={config.ttsWorkers}
                    min={1}
                    max={16}
                    step={1}
                    marks={[{ value: 1, label: '1' }, { value: 4, label: '4' }, { value: 7, label: '7' }, { value: 12, label: '12' }, { value: 16, label: '16' }]}
                    onChange={(_, v) => onConfigChange('ttsWorkers', v as number)}
                  />
                </Box>
                <Box sx={{ pt: 1, borderTop: '1px solid', borderColor: 'divider' }}>
                  <Box display="flex" justifyContent="space-between">
                    <Typography variant="body2" fontWeight={500}>背景音乐音量</Typography>
                    <Typography variant="body2" fontWeight={600} color="primary">{config.bgmVolume.toFixed(2)}x</Typography>
                  </Box>
                  <Typography variant="caption" display="block" mb={1}>
                    BGM 与 TTS 语音混合比例 (0=静音, 1=原始电平, 2=加倍)
                  </Typography>
                  <Slider
                    value={config.bgmVolume}
                    min={0}
                    max={2.0}
                    step={0.05}
                    marks={[
                      { value: 0, label: '静音' },
                      { value: 0.5, label: '0.5x' },
                      { value: 1.0, label: '1.0x' },
                      { value: 1.5, label: '1.5x' },
                      { value: 2.0, label: '2.0x' },
                    ]}
                    onChange={(_, v) => onConfigChange('bgmVolume', v as number)}
                  />
                </Box>
                <FormControlLabel
                  control={<Checkbox checked={config.enableSubtitleOverlay} onChange={e => onConfigChange('enableSubtitleOverlay', e.target.checked)} />}
                  label={<Box><Typography variant="body2">启用字幕叠加</Typography><Typography variant="caption" display="block">选择是否在视频中显示字幕</Typography></Box>}
                />
              </Stack>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
      <ApiConfigDialog
        open={apiDialogOpen}
        onClose={() => setApiDialogOpen(false)}
        config={config}
        onConfigChange={onConfigChange}
      />
      <GlossaryEditor
        open={glossaryOpen}
        onClose={() => setGlossaryOpen(false)}
      />
    </>
  )
}
