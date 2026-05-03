import {
  Box, Typography, Card, CardContent, Select, MenuItem,
  FormControlLabel, Checkbox, TextField, Stack,
} from '@mui/material'
import { SectionHeader } from '../SectionHeader'
import type { PipelineConfig } from '../../types'

interface OutputSettingsProps {
  config: PipelineConfig
  onConfigChange: <K extends keyof PipelineConfig>(key: K, value: PipelineConfig[K]) => void
  showTitle?: boolean
}

export function OutputSettings({ config, onConfigChange, showTitle = true }: OutputSettingsProps) {
  return (
    <>
      {showTitle && <SectionHeader title="输出设置 (Final Output)" />}
      <Card sx={{ height: '100%', mt: showTitle ? 2 : 0 }}>
        <CardContent>
          <Stack spacing={2.5}>
            <FormControlLabel
              control={<Checkbox checked={config.enableVideoMerge} onChange={e => onConfigChange('enableVideoMerge', e.target.checked)} />}
              label={<Box><Typography variant="body2" fontWeight={500}>启用视频合并</Typography><Typography variant="caption">合并处理后的视频段</Typography></Box>}
            />
            <Box>
              <Typography variant="body2" fontWeight={500}>输出路径设置</Typography>
              <TextField size="small" fullWidth value={config.outputPath} onChange={e => onConfigChange('outputPath', e.target.value)} sx={{ mt: 0.5 }} />
            </Box>
            <Box>
              <Typography variant="body2" fontWeight={500}>视频编码器选择 (--video_codec)</Typography>
              <Select size="small" fullWidth value={config.videoCodec} onChange={e => onConfigChange('videoCodec', e.target.value as PipelineConfig['videoCodec'])} sx={{ mt: 0.5 }}>
                <MenuItem value="libx264">libx264</MenuItem>
                <MenuItem value="h265">h265</MenuItem>
              </Select>
            </Box>
            <Box>
              <Typography variant="body2" fontWeight={500}>音频编码器选择 (--audio_codec)</Typography>
              <Select size="small" fullWidth value={config.audioCodec} onChange={e => onConfigChange('audioCodec', e.target.value as PipelineConfig['audioCodec'])} sx={{ mt: 0.5 }}>
                <MenuItem value="aac">aac</MenuItem>
              </Select>
            </Box>
          </Stack>
        </CardContent>
      </Card>
    </>
  )
}
