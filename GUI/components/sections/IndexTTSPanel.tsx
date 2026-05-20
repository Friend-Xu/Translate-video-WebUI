import { useState } from "react"
import { Box, Typography, FormControlLabel, Switch, TextField, Stack, Select, MenuItem, Button } from "@mui/material"
import PlayArrowIcon from "@mui/icons-material/PlayArrowRounded"
import type { PipelineConfig } from "../../types"

interface Props {
  config: PipelineConfig
  onConfigChange: <K extends keyof PipelineConfig>(key: K, value: PipelineConfig[K]) => void
}

const PRESET_VOICES = [
  { value: "models/IndexTTS/speakers/voice_01.wav", label: "预设男声 A (沉稳)" },
  { value: "models/IndexTTS/speakers/voice_02.wav", label: "预设女声 B (清晰)" },
  { value: "models/IndexTTS/speakers/voice_03.wav", label: "预设男声 C (年轻)" },
]

export default function IndexTTSPanel({ config, onConfigChange }: Props) {
  const [previewAudio, setPreviewAudio] = useState<string>("")
  const [isCustom, setIsCustom] = useState(false)

  const handlePreview = async (path: string) => {
    if (!path) return
    try {
      const r = await fetch(`/api/tts/indextts-preset-audio?path=${encodeURIComponent(path)}`)
      const data = await r.json()
      if (data.audio_base64) {
        new Audio(`data:audio/wav;base64,${data.audio_base64}`).play()
        setPreviewAudio(data.audio_base64)
      }
    } catch {
      // silently ignore preview errors
    }
  }
  return (
    <Box sx={{ p: 2, bgcolor: 'grey.50', borderRadius: 2, border: '1px solid', borderColor: 'divider' }}>
      <Typography variant="subtitle2" fontWeight={600} gutterBottom>
        IndexTTS 配置
      </Typography>

      <Stack spacing={2.5} mt={1.5}>
        <Box>
          <FormControlLabel
            control={
              <Switch
                checked={config.indexttsFp16}
                onChange={(e) => onConfigChange('indexttsFp16', e.target.checked)}
              />
            }
            label="FP16 推理"
          />
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: -0.5 }}>
            启用半精度推理 (~7.8GB 显存)。8GB 显卡必须开启
          </Typography>
        </Box>

        <Box>
          <FormControlLabel
            control={
              <Switch
                checked={config.indexttsEnableClone}
                onChange={(e) => onConfigChange('indexttsEnableClone', e.target.checked)}
              />
            }
            label="克隆原视频音色"
          />
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: -0.5 }}>
            开启: 自动提取原视频人声作为参考音色。关闭: 使用下方预设音色
          </Typography>
        </Box>

        {config.indexttsEnableClone ? (
          <Box>
            <Typography variant="body2" fontWeight={500} gutterBottom>
              参考音频 (零样本音色克隆)
            </Typography>
            <TextField
              size="small"
              fullWidth
              value={config.indexttsSpeakerAudio}
              onChange={(e) => onConfigChange('indexttsSpeakerAudio', e.target.value)}
              placeholder="留空 = 自动从原视频人声提取"
            />
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
              提供 3-10 秒参考音频。留空时自动从 Demucs 人声生成 Color_audio.WAV
            </Typography>
          </Box>
        ) : (
          <Box>
            <Typography variant="body2" fontWeight={500} gutterBottom>
              预设音色
            </Typography>
            <Select
              size="small"
              fullWidth
              value={isCustom ? '__custom__' : (config.indexttsSpeakerAudio || PRESET_VOICES[0].value)}
              onChange={(e) => {
                const v = e.target.value
                if (v === '__custom__') {
                  setIsCustom(true)
                  onConfigChange('indexttsSpeakerAudio', '')
                } else {
                  setIsCustom(false)
                  onConfigChange('indexttsSpeakerAudio', v)
                }
              }}
              sx={{ bgcolor: 'background.paper' }}
            >
              {PRESET_VOICES.map((v) => (
                <MenuItem key={v.value} value={v.value}>{v.label}</MenuItem>
              ))}
              <MenuItem value="__custom__">自定义...</MenuItem>
            </Select>
            {isCustom && (
              <TextField
                size="small"
                fullWidth
                sx={{ mt: 1 }}
                value={config.indexttsSpeakerAudio}
                onChange={(e) => onConfigChange('indexttsSpeakerAudio', e.target.value)}
                placeholder="输入自定义音色 WAV 文件路径"
              />
            )}
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1 }}>
              <Button
                size="small"
                startIcon={<PlayArrowIcon />}
                onClick={() => handlePreview(config.indexttsSpeakerAudio || PRESET_VOICES[0].value)}
              >
                试听
              </Button>
              {previewAudio && (
                <Typography variant="caption" color="success.main">
                  正在播放...
                </Typography>
              )}
            </Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
              此音色将替代原视频说话人的声音
            </Typography>
          </Box>
        )}

        <Box>
          <Typography variant="body2" fontWeight={500} gutterBottom>
            模型目录 (高级)
          </Typography>
          <TextField
            size="small"
            fullWidth
            value={config.indexttsCheckpointsDir}
            onChange={(e) => onConfigChange('indexttsCheckpointsDir', e.target.value)}
            placeholder="留空 = models/IndexTTS/index-tts-batch/checkpoints/"
          />
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
            模型权重所在目录。留空使用默认路径
          </Typography>
        </Box>

        <Box sx={{ p: 1.5, bgcolor: 'info.light', borderRadius: 1 }}>
          <Typography variant="caption" color="info.dark">
            Worker: 1 (单引擎串行) &nbsp;|&nbsp;
            采样率: 22050 → 44100 Hz &nbsp;|&nbsp;
            时长控制: 原生精确匹配，无需 RubberBand
          </Typography>
        </Box>
      </Stack>
    </Box>
  )
}
