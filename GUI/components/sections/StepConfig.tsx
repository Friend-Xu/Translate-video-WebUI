import { useState, useEffect } from 'react'
import {
  Box, Typography, Card, CardContent, Select, MenuItem,
  FormControlLabel, Checkbox, TextField, Slider, Stack,
} from '@mui/material'
import Grid from '@mui/material/Grid'
import { SectionHeader } from '../SectionHeader'
import type { PipelineConfig, SystemInfo } from '../../types'

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
                  <Box sx={{ ml: 4, mt: 1, opacity: config.enableAlignment ? 1 : 0.5, pointerEvents: config.enableAlignment ? 'auto' : 'none' }}>
                    <Typography variant="body2" fontWeight={500}>对齐语言</Typography>
                    <Select size="small" fullWidth value={config.alignmentLanguage} onChange={e => onConfigChange('alignmentLanguage', e.target.value)} sx={{ bgcolor: 'background.paper', mt: 0.5 }}>
                      <MenuItem value="ja">日语 (ja)</MenuItem>
                      <MenuItem value="en">英语 (en)</MenuItem>
                      <MenuItem value="zh">中文 (zh)</MenuItem>
                      <MenuItem value="fr">法语 (fr)</MenuItem>
                      <MenuItem value="de">德语 (de)</MenuItem>
                      <MenuItem value="ko">韩语 (ko)</MenuItem>
                    </Select>
                    <Typography variant="caption">指定语言后启用 wav2vec2 精修词级时间戳（~20ms 精度）</Typography>
                  </Box>
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
                  <Typography variant="body2" fontWeight={500}>DeepSeek API 设置</Typography>
                  <TextField
                    size="small"
                    fullWidth
                    type="password"
                    placeholder="sk-xxxxxxxxxxxxxxxxxxxxxxxx"
                    value={config.apiKey}
                    onChange={e => onConfigChange('apiKey', e.target.value)}
                    sx={{ bgcolor: 'background.paper', mt: 0.5 }}
                  />
                  <Typography variant="caption">输入 DeepSeek API Key</Typography>
                </Box>

                <Grid container spacing={2}>
                  <Grid size={{ xs: 6 }}>
                    <Typography variant="body2" fontWeight={500}>API 类型</Typography>
                    <TextField size="small" fullWidth value={config.apiType} onChange={e => onConfigChange('apiType', e.target.value)} sx={{ bgcolor: 'background.paper', mt: 0.5 }} />
                  </Grid>
                  <Grid size={{ xs: 6 }}>
                    <Typography variant="body2" fontWeight={500}>最大 Token 数</Typography>
                    <TextField size="small" fullWidth type="number" value={config.maxTokens} onChange={e => onConfigChange('maxTokens', Number(e.target.value))} sx={{ bgcolor: 'background.paper', mt: 0.5 }} />
                  </Grid>
                </Grid>

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
                    <Typography variant="body2" fontWeight={500}>语速设置</Typography>
                    <Typography variant="body2" fontWeight={600} color="primary">{config.speechRate}%</Typography>
                  </Box>
                  <Typography variant="caption" display="block" mb={1}>语速 (30%~50%)</Typography>
                  <Slider value={config.speechRate} min={30} max={50} onChange={(_, v) => onConfigChange('speechRate', v as number)} />
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
    </>
  )
}
