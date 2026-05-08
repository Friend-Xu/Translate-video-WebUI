import { useState, useEffect, useCallback } from 'react'
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, TextField, Select, MenuItem, Slider, Typography,
  Box, Accordion, AccordionSummary, AccordionDetails,
  InputAdornment, IconButton,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMoreRounded'
import VisibilityIcon from '@mui/icons-material/VisibilityRounded'
import VisibilityOffIcon from '@mui/icons-material/VisibilityOffRounded'
import type { PipelineConfig } from '../types'
import { PROVIDER_PRESETS } from '../types'

interface ApiConfigDialogProps {
  open: boolean
  onClose: () => void
  config: PipelineConfig
  onConfigChange: <K extends keyof PipelineConfig>(key: K, value: PipelineConfig[K]) => void
}

interface ProviderFormState {
  apiKey: string
  baseUrl: string
  model: string
}

const CUSTOM_MODEL_VALUE = '__custom__'

function defaultModel(provider: string): string {
  const preset = PROVIDER_PRESETS[provider]
  return preset?.models[0] ?? ''
}

function isCustomModel(provider: string, model: string): boolean {
  const preset = PROVIDER_PRESETS[provider]
  if (!preset || preset.models.length === 0) return true
  return !preset.models.includes(model)
}

export function ApiConfigDialog({ open, onClose, config, onConfigChange }: ApiConfigDialogProps) {
  const [provider, setProvider] = useState(config.apiProvider)
  const [apiKey, setApiKey] = useState(config.apiKey)
  const [baseUrl, setBaseUrl] = useState(config.apiBaseUrl)
  const [model, setModel] = useState(config.apiModel || defaultModel(config.apiProvider))
  const [modelSelect, setModelSelect] = useState(
    isCustomModel(config.apiProvider, config.apiModel) ? CUSTOM_MODEL_VALUE : (config.apiModel || defaultModel(config.apiProvider))
  )
  const [temperature, setTemperature] = useState(config.apiTemperature)
  const [maxTokens, setMaxTokens] = useState(config.maxTokens)
  const [topP, setTopP] = useState(config.apiTopP)
  const [showKey, setShowKey] = useState(false)

  // Per-provider state: preserves settings for each provider during the dialog session
  const [_savedStates, setSavedStates] = useState<Map<string, ProviderFormState>>(new Map())

  // Initialize on open
  useEffect(() => {
    if (open) {
      const p = config.apiProvider
      setProvider(p)
      setApiKey(config.apiKey)
      setBaseUrl(config.apiBaseUrl)
      setModel(config.apiModel || defaultModel(p))
      setModelSelect(isCustomModel(p, config.apiModel) ? CUSTOM_MODEL_VALUE : (config.apiModel || defaultModel(p)))
      setTemperature(config.apiTemperature)
      setMaxTokens(config.maxTokens)
      setTopP(config.apiTopP)
      setShowKey(false)
      // Seed saved states with current config for the active provider
      setSavedStates(new Map([[p, {
        apiKey: config.apiKey,
        baseUrl: config.apiBaseUrl,
        model: config.apiModel || defaultModel(p),
      }]]))
    }
  }, [open, config.apiProvider, config.apiKey, config.apiBaseUrl, config.apiModel, config.apiTemperature, config.maxTokens, config.apiTopP])

  const handleProviderChange = useCallback((newProvider: string) => {
    // Save current provider state before switching
    setSavedStates(prev => {
      const next = new Map(prev)
      next.set(provider, { apiKey, baseUrl, model })
      return next
    })

    // Switch
    const p = newProvider as PipelineConfig['apiProvider']
    setProvider(p)

    // Restore target provider state, or use preset defaults
    setSavedStates(prev => {
      const saved = prev.get(p)
      if (saved) {
        setApiKey(saved.apiKey)
        setBaseUrl(saved.baseUrl)
        setModel(saved.model)
        setModelSelect(isCustomModel(p, saved.model) ? CUSTOM_MODEL_VALUE : (saved.model || defaultModel(p)))
      } else {
        const preset = PROVIDER_PRESETS[p]
        setApiKey('')
        setBaseUrl(preset?.baseUrl ?? '')
        const m = defaultModel(p)
        setModel(m)
        setModelSelect(m || CUSTOM_MODEL_VALUE)
      }
      return prev
    })
  }, [provider, apiKey, baseUrl, model])

  const handleModelSelect = useCallback((value: string) => {
    setModelSelect(value)
    if (value === CUSTOM_MODEL_VALUE) {
      setModel('')
    } else {
      setModel(value)
    }
  }, [])

  const handleSave = useCallback(() => {
    const finalModel = modelSelect === CUSTOM_MODEL_VALUE ? model : modelSelect
    const changes: Partial<PipelineConfig> = {
      apiProvider: provider,
      apiKey,
      apiBaseUrl: baseUrl,
      apiModel: finalModel,
      apiTemperature: temperature,
      maxTokens,
      apiTopP: topP,
    }
    for (const [key, value] of Object.entries(changes)) {
      if ((config as any)[key] !== value) {
        (onConfigChange as any)(key, value)
      }
    }
    onClose()
  }, [provider, apiKey, baseUrl, model, modelSelect, temperature, maxTokens, topP, config, onConfigChange, onClose])

  const preset = PROVIDER_PRESETS[provider]
  const modelOptions = preset?.models ?? []

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>API 配置</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5, mt: 0.5 }}>
          <Box>
            <Typography variant="body2" fontWeight={500} mb={0.5}>提供商</Typography>
            <Select
              size="small"
              fullWidth
              value={provider}
              onChange={e => handleProviderChange(e.target.value)}
              sx={{ bgcolor: 'background.paper' }}
            >
              {Object.entries(PROVIDER_PRESETS).map(([key, p]) => (
                <MenuItem key={key} value={key}>{p.name}</MenuItem>
              ))}
            </Select>
          </Box>

          <Box>
            <Typography variant="body2" fontWeight={500} mb={0.5}>API Key</Typography>
            <TextField
              size="small"
              fullWidth
              type={showKey ? 'text' : 'password'}
              placeholder="请输入你的 API Key"
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              sx={{ bgcolor: 'background.paper' }}
              InputProps={{
                endAdornment: (
                  <InputAdornment position="end">
                    <IconButton size="small" onClick={() => setShowKey(v => !v)} edge="end">
                      {showKey ? <VisibilityOffIcon fontSize="small" /> : <VisibilityIcon fontSize="small" />}
                    </IconButton>
                  </InputAdornment>
                ),
              }}
            />
          </Box>

          <Box>
            <Typography variant="body2" fontWeight={500} mb={0.5}>Base URL</Typography>
            <TextField
              size="small"
              fullWidth
              value={baseUrl}
              onChange={e => setBaseUrl(e.target.value)}
              sx={{ bgcolor: 'background.paper' }}
              placeholder="https://api.example.com"
            />
            <Typography variant="caption" color="text.secondary">
              OpenAI 兼容的 API 端点地址，切换提供商会自动填充
            </Typography>
          </Box>

          <Box>
            <Typography variant="body2" fontWeight={500} mb={0.5}>Model</Typography>
            {modelOptions.length > 0 ? (
              <Select
                size="small"
                fullWidth
                value={modelSelect}
                onChange={e => handleModelSelect(e.target.value)}
                sx={{ bgcolor: 'background.paper' }}
              >
                {modelOptions.map(m => (
                  <MenuItem key={m} value={m}>{m}</MenuItem>
                ))}
                <MenuItem value={CUSTOM_MODEL_VALUE}>自定义…</MenuItem>
              </Select>
            ) : (
              <TextField
                size="small"
                fullWidth
                value={model}
                onChange={e => { setModel(e.target.value); setModelSelect(CUSTOM_MODEL_VALUE) }}
                sx={{ bgcolor: 'background.paper' }}
                placeholder="输入模型名称"
              />
            )}
            {modelSelect === CUSTOM_MODEL_VALUE && modelOptions.length > 0 && (
              <TextField
                size="small"
                fullWidth
                value={model}
                onChange={e => setModel(e.target.value)}
                sx={{ bgcolor: 'background.paper', mt: 1 }}
                placeholder="输入模型名称"
              />
            )}
          </Box>

          <Accordion defaultExpanded={false} sx={{ '&:before': { display: 'none' } }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="body2" fontWeight={500}>高级参数</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
                <Box>
                  <Box display="flex" justifyContent="space-between">
                    <Typography variant="body2">Temperature</Typography>
                    <Typography variant="body2" fontWeight={600} color="primary">{temperature.toFixed(2)}</Typography>
                  </Box>
                  <Slider
                    value={temperature}
                    min={0}
                    max={2}
                    step={0.05}
                    marks={[{ value: 0, label: '0' }, { value: 1, label: '1' }, { value: 2, label: '2' }]}
                    onChange={(_, v) => setTemperature(v as number)}
                  />
                  <Typography variant="caption" color="text.secondary">
                    控制输出随机性，越低越确定（推荐翻译任务设为 0-0.3）
                  </Typography>
                </Box>

                <Box>
                  <Typography variant="body2" mb={0.5}>Max Tokens</Typography>
                  <TextField
                    size="small"
                    fullWidth
                    type="number"
                    value={maxTokens}
                    onChange={e => setMaxTokens(Number(e.target.value))}
                    sx={{ bgcolor: 'background.paper' }}
                    inputProps={{ min: 100, max: 128000, step: 100 }}
                  />
                  <Typography variant="caption" color="text.secondary">
                    单次请求的最大输出 Token 数
                  </Typography>
                </Box>

                <Box>
                  <Box display="flex" justifyContent="space-between">
                    <Typography variant="body2">Top P</Typography>
                    <Typography variant="body2" fontWeight={600} color="primary">{topP.toFixed(2)}</Typography>
                  </Box>
                  <Slider
                    value={topP}
                    min={0}
                    max={1}
                    step={0.05}
                    marks={[{ value: 0, label: '0' }, { value: 0.5, label: '0.5' }, { value: 1, label: '1' }]}
                    onChange={(_, v) => setTopP(v as number)}
                  />
                  <Typography variant="caption" color="text.secondary">
                    核采样参数，控制词汇选择范围
                  </Typography>
                </Box>
              </Box>
            </AccordionDetails>
          </Accordion>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>取消</Button>
        <Button variant="contained" onClick={handleSave}>保存配置</Button>
      </DialogActions>
    </Dialog>
  )
}
