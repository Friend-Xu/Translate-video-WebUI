import {
  Box, Typography, Card, CardContent, Button, Select, MenuItem,
  LinearProgress, Stack, Checkbox, FormControlLabel, Divider,
} from '@mui/material'
import Grid from '@mui/material/Grid'
import FolderOpenIcon from '@mui/icons-material/FolderOpenRounded'
import PlayArrowIcon from '@mui/icons-material/PlayArrowRounded'
import StopIcon from '@mui/icons-material/StopRounded'
import RefreshIcon from '@mui/icons-material/RefreshRounded'
import LanguageIcon from '@mui/icons-material/LanguageRounded'
import MemoryIcon from '@mui/icons-material/MemoryRounded'
import DeveloperBoardIcon from '@mui/icons-material/DeveloperBoardRounded'
import { SectionHeader } from '../SectionHeader'
import { ControlCard } from '../ControlCard'
import type { PipelineConfig, PipelineStatus } from '../../types'

interface PipelinePanelProps {
  config: PipelineConfig
  onConfigChange: <K extends keyof PipelineConfig>(key: K, value: PipelineConfig[K]) => void
  status: PipelineStatus
  onStart: () => void
  onCancel: () => void
  onForceRetry: () => void
  onSelectFile: () => void
}

export function PipelinePanel({
  config, onConfigChange, status,
  onStart, onCancel, onForceRetry, onSelectFile,
}: PipelinePanelProps) {
  return (
    <>
      <SectionHeader title="主界面 (Pipeline 控制面板)" />
      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 3 }}>
          <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column', bgcolor: 'action.hover', border: '2px dashed', borderColor: 'divider' }}>
            <CardContent sx={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', flex: 1, gap: 1.5 }}>
              <Box display="flex" alignItems="center" gap={1}>
                <FolderOpenIcon color="primary" />
                <Typography variant="body1" fontWeight={600} color="text.primary">视频导入</Typography>
              </Box>
              <TextFieldDisplay value={config.videoPath} placeholder="请选择视频文件（.mp4）" />
              <Button variant="contained" size="small" disableElevation sx={{ borderRadius: 2 }} onClick={onSelectFile}>
                选择文件
              </Button>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 3 }}>
          <ControlCard icon={<LanguageIcon color="primary" />} title="源语言" subtitle="自动检测 / 英文 / 中文 / 日文">
            <Select size="small" fullWidth value={config.lang} onChange={e => onConfigChange('lang', e.target.value as PipelineConfig['lang'])} sx={{ mt: 1 }}>
              <MenuItem value="auto">自动检测</MenuItem>
              <MenuItem value="en">英文</MenuItem>
              <MenuItem value="zh">中文</MenuItem>
              <MenuItem value="ja">日文</MenuItem>
            </Select>
          </ControlCard>
        </Grid>

        <Grid size={{ xs: 12, md: 3 }}>
          <ControlCard icon={<MemoryIcon color="primary" />} title="Whisper 模型" subtitle="选择提取模型">
            <Select size="small" fullWidth value={config.model} onChange={e => onConfigChange('model', e.target.value as PipelineConfig['model'])} sx={{ mt: 1 }}>
              <MenuItem value="small">小型 (Small)</MenuItem>
              <MenuItem value="medium">中型 (Medium)</MenuItem>
              <MenuItem value="large">大型 (Large)</MenuItem>
            </Select>
          </ControlCard>
        </Grid>

        <Grid size={{ xs: 12, md: 3 }}>
          <ControlCard icon={<DeveloperBoardIcon color="primary" />} title="计算设备" subtitle="CPU / GPU">
            <Select size="small" fullWidth value={config.device} onChange={e => onConfigChange('device', e.target.value as PipelineConfig['device'])} sx={{ mt: 1 }}>
              <MenuItem value="cpu">CPU</MenuItem>
              <MenuItem value="gpu">GPU</MenuItem>
            </Select>
          </ControlCard>
        </Grid>
      </Grid>

      <Card>
        <CardContent>
          <Typography variant="subtitle2" gutterBottom>步骤控制</Typography>

          {/* All "启用X" — checked means run, unchecked means skip */}
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 2 }}>
            <FormControlLabel
              control={<Checkbox size="small" checked={config.enableDefectCheck} onChange={e => onConfigChange('enableDefectCheck', e.target.checked)} disabled={status.state === 'running'} />}
              label={<Typography variant="body2">启用音频缺陷检测</Typography>}
            />
            <FormControlLabel
              control={<Checkbox size="small" checked={config.enableExtract} onChange={e => onConfigChange('enableExtract', e.target.checked)} disabled={status.state === 'running'} />}
              label={<Typography variant="body2">启用字幕提取</Typography>}
            />
            <FormControlLabel
              control={<Checkbox size="small" checked={config.enableTranslate} onChange={e => onConfigChange('enableTranslate', e.target.checked)} disabled={status.state === 'running'} />}
              label={<Typography variant="body2">启用翻译</Typography>}
            />
            <FormControlLabel
              control={<Checkbox size="small" checked={config.enableTTS} onChange={e => onConfigChange('enableTTS', e.target.checked)} disabled={status.state === 'running'} />}
              label={<Typography variant="body2">启用TTS合成</Typography>}
            />
          </Box>

          <Divider sx={{ mb: 2 }} />

          <Stack direction="row" spacing={2} sx={{ mb: 3 }}>
            {status.state === 'running' ? (
              <Button variant="contained" color="error" startIcon={<StopIcon />} onClick={onCancel}>
                取消处理
              </Button>
            ) : (
              <Button variant="contained" startIcon={<PlayArrowIcon />} onClick={onStart} disabled={!config.videoPath}>
                开始处理
              </Button>
            )}
            <Button variant="outlined" color="error" startIcon={<RefreshIcon />} onClick={onForceRetry}
              disabled={status.state === 'running'}>
              强制重新执行
            </Button>
          </Stack>

          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
            <Typography variant="subtitle2">
              {status.state === 'idle' ? '就绪' : status.currentStep}
            </Typography>
            <Typography variant="body2" fontWeight={600} color="primary">{status.progress}%</Typography>
          </Box>
          <LinearProgress variant="determinate" value={status.progress} />
        </CardContent>
      </Card>
    </>
  )
}

function TextFieldDisplay({ value, placeholder }: { value: string; placeholder: string }) {
  return (
    <Box sx={{ px: 1.5, py: 1, bgcolor: 'background.paper', borderRadius: 1, border: '1px solid', borderColor: 'divider', fontSize: '0.875rem', minHeight: 36, display: 'flex', alignItems: 'center', color: value ? 'text.primary' : 'text.secondary' }}>
      {value || placeholder}
    </Box>
  )
}
