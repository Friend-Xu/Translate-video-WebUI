import { useState, useRef, useEffect } from 'react'
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, TextField, Box, Typography, Chip, Paper, Divider,
  FormControlLabel, Switch, Tabs, Tab,
} from '@mui/material'
import type { PipelineConfig } from '../types'

const LANG_LABELS: Record<string, string> = {
  auto: '自动检测', ja: '日文', en: 'English', zh: '中文',
  'zh-CN': '简体中文', 'zh-TW': '繁體中文', ko: '한국어',
  fr: 'Français', de: 'Deutsch', es: 'Español', pt: 'Português',
  ru: 'Русский', ar: 'العربية', th: 'ไทย', vi: 'Tiếng Việt',
  id: 'Indonesia', it: 'Italiano',
}

const VARIABLES = [
  { key: '{source_lang}', label: '源语言' },
  { key: '{target_lang}', label: '目标语言' },
  { key: '{fmt}', label: '输出格式' },
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

const PROMPT_LEVELS = [
  { key: 'system' as const, label: '批量翻译', desc: '首发翻译，所有字幕的第一版翻译', trigger: '每条字幕的首次翻译', icon: '📦' },
  { key: 'semantic_retry' as const, label: '语义重翻', desc: 'MiniLM 相似度 < 0.70 时触发', trigger: '语义相似度低于阈值', icon: '🔍' },
  { key: 'naturalness_retry' as const, label: '自然度重翻', desc: 'PPL 自然度比率 > 3.0 时触发', trigger: '翻译腔（直译/不自然）', icon: '💬' },
] as const

export function CustomPromptDialog({ open, onClose, config, onConfigChange }: Props) {
  const [localEnabled, setLocalEnabled] = useState(config.customPromptEnabled)
  const [tabIndex, setTabIndex] = useState(0)
  const textFieldRef = useRef<HTMLTextAreaElement>(null)

  const configKeyMap: Record<string, keyof PipelineConfig> = {
    'system': 'customSystemPrompt',
    'semantic_retry': 'customSemanticRetryPrompt',
    'naturalness_retry': 'customNaturalnessRetryPrompt',
  }
  const level = PROMPT_LEVELS[tabIndex]
  const configKey = configKeyMap[level.key]
  const localPrompt = config[configKey] as string

  useEffect(() => {
    if (open) {
      setLocalEnabled(config.customPromptEnabled)
      setTabIndex(0)
    }
  }, [open])

  const resolveLabel = (key: string, label: string) => {
    if (key === '{source_lang}') return `{source_lang} → ${LANG_LABELS[config.lang] || config.lang || '自动'}`
    if (key === '{target_lang}') return `{target_lang} → ${LANG_LABELS[config.targetLang] || config.targetLang}`
    return `${key} — ${label}`
  }

  const handleSave = () => {
    onConfigChange('customPromptEnabled', localEnabled)
    onClose()
  }

  const handleClose = () => {
    setLocalEnabled(config.customPromptEnabled)
    onClose()
  }

  const updatePrompt = (text: string) => {
    onConfigChange(configKey, text)
  }

  const insertVariable = (key: string) => {
    const el = textFieldRef.current
    if (!el) return
    const start = el.selectionStart ?? localPrompt.length
    const end = el.selectionEnd ?? localPrompt.length
    const newText = localPrompt.slice(0, start) + key + localPrompt.slice(end)
    updatePrompt(newText)
    setTimeout(() => {
      el.focus()
      el.setSelectionRange(start + key.length, start + key.length)
    }, 0)
  }

  const applyPreset = (prompt: string) => {
    updatePrompt(prompt)
  }

  const systemSuffix =
    '\n\n【以下为系统强制格式要求，必须严格遵守】\n' +
    '输出格式必须严格为 <index> 译文（如 <1> 大家好）\n' +
    '编号数量和顺序必须与输入完全一致\n' +
    '每条独立成行，不要合并\n' +
    '不要添加任何额外说明或标注'

  const preview = localEnabled && localPrompt
    ? localPrompt + systemSuffix
    : '使用系统默认提示词'

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ pb: 0 }}>自定义 System Prompt（多级翻译）</DialogTitle>

      <DialogContent sx={{ pt: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 1 }}>
          <FormControlLabel
            control={<Switch checked={localEnabled} onChange={e => setLocalEnabled(e.target.checked)} />}
            label={<Typography variant="body2" fontWeight={500}>启用自定义提示词</Typography>}
          />
          <Button size="small" color="warning" variant="outlined"
            onClick={() => updatePrompt('')}>
            恢复当前级别默认
          </Button>
        </Box>

        {!localEnabled && (
          <Paper variant="outlined" sx={{ p: 2, mb: 2, bgcolor: 'grey.50' }}>
            <Typography variant="body2" color="text.secondary">
              当前使用系统默认提示词。开启后可自定义三级翻译提示词，格式要求由系统自动追加。
            </Typography>
          </Paper>
        )}

        {localEnabled && (
          <>
            <Tabs value={tabIndex} onChange={(_, v) => setTabIndex(v)} sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }}>
              {PROMPT_LEVELS.map((l, i) => (
                <Tab key={l.key} label={
                  <Box sx={{ textAlign: 'left' }}>
                    <Typography variant="body2">{l.label}</Typography>
                    <Typography variant="caption" color={tabIndex === i ? 'primary' : 'text.disabled'} fontSize="0.65rem">
                      {l.trigger}
                    </Typography>
                  </Box>
                } />
              ))}
            </Tabs>

            <Paper variant="outlined" sx={{ p: 1.5, mb: 2, bgcolor: 'action.hover' }}>
              <Typography variant="body2" color="text.secondary">
                <strong>{level.label}</strong>: {level.desc}
              </Typography>
            </Paper>

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
                    label={resolveLabel(v.key, v.label)}
                    size="small"
                    variant="outlined"
                    onClick={() => insertVariable(v.key)}
                    sx={{ cursor: 'pointer', fontFamily: 'monospace' }}
                  />
                ))}
              </Box>
            </Box>

            <TextField
              label={`${level.label} Prompt`}
              multiline
              minRows={5}
              maxRows={10}
              fullWidth
              size="small"
              value={localPrompt}
              onChange={e => updatePrompt(e.target.value)}
              placeholder={`你是专业翻译。请将字幕翻译成${LANG_LABELS[config.targetLang] || config.targetLang}。`}
              inputRef={textFieldRef}
              helperText="上方变量点击即可插入。格式规则由系统自动追加。留空使用系统默认。"
            />

            <Divider sx={{ my: 2 }} />

            <Box>
              <Typography variant="caption" color="text.secondary" fontWeight={600} gutterBottom display="block">
                {level.label} — 实际发送的完整 Prompt 预览
              </Typography>
              <Paper variant="outlined" sx={{ p: 2, bgcolor: 'grey.50', maxHeight: 150, overflow: 'auto' }}>
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
