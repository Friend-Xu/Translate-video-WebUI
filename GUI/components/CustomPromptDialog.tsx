import { useState, useRef, useEffect } from 'react'
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, TextField, Box, Typography, Chip, Paper, Divider,
  FormControlLabel, Switch,
} from '@mui/material'
import type { PipelineConfig } from '../types'

const VARIABLES = [
  { key: '{source_lang}', label: '源语言', desc: 'ja / en / zh' },
  { key: '{target_lang}', label: '目标语言', desc: '简体中文 / English' },
  { key: '{fmt}', label: '输出格式', desc: 'numbered_list / json' },
]

const TONE_PRESETS = [
  { label: '默认', prompt: '' },
  { label: '口语化', prompt: '请用轻松口语化的风格翻译，避免书面语。' },
  { label: '正式', prompt: '请使用正式、专业的语言风格翻译。' },
  { label: '游戏', prompt: '请使用游戏玩家熟悉的术语和表达方式翻译，保留游戏氛围。' },
  { label: '技术', prompt: '请精确翻译技术术语，保持技术文档的准确性和一致性。' },
]

interface Props {
  open: boolean
  onClose: () => void
  config: PipelineConfig
  onConfigChange: <K extends keyof PipelineConfig>(key: K, value: PipelineConfig[K]) => void
}

export function CustomPromptDialog({ open, onClose, config, onConfigChange }: Props) {
  const [localEnabled, setLocalEnabled] = useState(config.customPromptEnabled)
  const [localPrompt, setLocalPrompt] = useState(config.customSystemPrompt)
  const textFieldRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (open) {
      setLocalEnabled(config.customPromptEnabled)
      setLocalPrompt(config.customSystemPrompt)
    }
  }, [open])

  const handleSave = () => {
    onConfigChange('customPromptEnabled', localEnabled)
    onConfigChange('customSystemPrompt', localPrompt)
    onClose()
  }

  const handleReset = () => {
    setLocalPrompt('')
  }

  const handleClose = () => {
    setLocalEnabled(config.customPromptEnabled)
    setLocalPrompt(config.customSystemPrompt)
    onClose()
  }

  const insertVariable = (key: string) => {
    const el = textFieldRef.current
    if (!el) return
    const start = el.selectionStart ?? localPrompt.length
    const end = el.selectionEnd ?? localPrompt.length
    const newText = localPrompt.slice(0, start) + key + localPrompt.slice(end)
    setLocalPrompt(newText)
    setTimeout(() => {
      el.focus()
      el.setSelectionRange(start + key.length, start + key.length)
    }, 0)
  }

  const applyPreset = (prompt: string) => {
    setLocalPrompt(prompt)
  }

  const systemSuffix =
    '\n\n【以下为系统强制格式要求，必须严格遵守】\n' +
    '输出格式必须严格为 <index> 译文（如 <1> 大家好）\n' +
    '编号数量和顺序必须与输入完全一致\n' +
    '每条独立成行，不要合并\n' +
    '不要添加任何额外说明或标注'

  const preview = localEnabled && localPrompt
    ? localPrompt + systemSuffix
    : localEnabled
      ? systemSuffix.trim()
      : '使用系统默认提示词'

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ pb: 0 }}>自定义 System Prompt</DialogTitle>

      <DialogContent sx={{ pt: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
          <FormControlLabel
            control={<Switch checked={localEnabled} onChange={e => setLocalEnabled(e.target.checked)} />}
            label={<Typography variant="body2" fontWeight={500}>启用自定义提示词</Typography>}
          />
          <Button size="small" color="warning" variant="outlined" onClick={handleReset}>
            恢复默认
          </Button>
        </Box>

        {!localEnabled && (
          <Paper variant="outlined" sx={{ p: 2, mb: 2, bgcolor: 'grey.50' }}>
            <Typography variant="body2" color="text.secondary">
              当前使用系统默认提示词。开启后可自定义翻译风格指令，格式要求由系统自动追加。
            </Typography>
          </Paper>
        )}

        {localEnabled && (
          <>
            <Box sx={{ mb: 2 }}>
              <Typography variant="caption" color="text.secondary" gutterBottom display="block">
                风格预设
              </Typography>
              <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                {TONE_PRESETS.map(p => (
                  <Chip
                    key={p.label}
                    label={p.label}
                    size="small"
                    variant={localPrompt === p.prompt && p.prompt ? 'filled' : 'outlined'}
                    color={localPrompt === p.prompt && p.prompt ? 'primary' : 'default'}
                    onClick={() => applyPreset(p.prompt)}
                    sx={{ cursor: 'pointer' }}
                  />
                ))}
              </Box>
            </Box>

            <Box sx={{ mb: 2 }}>
              <Typography variant="caption" color="text.secondary" gutterBottom display="block">
                可用变量（点击插入到光标位置）
              </Typography>
              <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                {VARIABLES.map(v => (
                  <Chip
                    key={v.key}
                    label={`${v.key} — ${v.label}`}
                    size="small"
                    variant="outlined"
                    onClick={() => insertVariable(v.key)}
                    sx={{ cursor: 'pointer', fontFamily: 'monospace' }}
                  />
                ))}
              </Box>
            </Box>

            <TextField
              label="自定义翻译指令（风格 / 语气 / 角色）"
              multiline
              minRows={5}
              maxRows={10}
              fullWidth
              size="small"
              value={localPrompt}
              onChange={e => setLocalPrompt(e.target.value)}
              placeholder={'你是专业{source_lang}字幕翻译。请用口语化风格翻译成{target_lang}。'}
              inputRef={textFieldRef}
              helperText="上方变量点击即可插入。格式规则由系统自动追加。"
            />

            <Divider sx={{ my: 2 }} />

            <Box>
              <Typography variant="caption" color="text.secondary" fontWeight={600} gutterBottom display="block">
                实际发送的完整 Prompt 预览
              </Typography>
              <Paper variant="outlined" sx={{ p: 2, bgcolor: 'grey.50', maxHeight: 200, overflow: 'auto' }}>
                <Typography variant="caption" sx={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: '0.75rem' }}>
                  {preview}
                </Typography>
              </Paper>
            </Box>
          </>
        )}
      </DialogContent>

      <DialogActions>
        <Button onClick={handleClose}>取消</Button>
        <Button variant="contained" onClick={handleSave}>保存</Button>
      </DialogActions>
    </Dialog>
  )
}
