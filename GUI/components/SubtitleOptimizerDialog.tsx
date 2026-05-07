import { useState, useEffect, useCallback } from 'react'
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, TextField, Select, MenuItem, FormControl, InputLabel,
  Typography, Box, Checkbox, FormControlLabel, Chip,
  Accordion, AccordionSummary, AccordionDetails,
  CircularProgress, Alert,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMoreRounded'
import FolderOpenIcon from '@mui/icons-material/FolderOpenRounded'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHighRounded'
import { FilePickerDialog } from './FilePickerDialog'

const SRT_EXTS = ['.srt', '.ass', '.ssa', '.vtt']

const LANGUAGES: { code: string; label: string }[] = [
  { code: 'zh', label: '中文 (zh)' },
  { code: 'ja', label: '日本語 (ja)' },
  { code: 'ko', label: '한국어 (ko)' },
  { code: 'en', label: 'English (en)' },
  { code: 'fr', label: 'Français (fr)' },
  { code: 'de', label: 'Deutsch (de)' },
  { code: 'es', label: 'Español (es)' },
  { code: 'ru', label: 'Русский (ru)' },
  { code: 'pt', label: 'Português (pt)' },
  { code: 'it', label: 'Italiano (it)' },
]

interface Defaults {
  mode: string
  min_duration_cjk: number
  reading_speed_cjk: number
  min_duration_latin: number
  reading_speed_latin: number
  min_duration_arabic: number
  reading_speed_arabic: number
  max_merge_gap: number
  inter_gap: number
  max_duration: number
}

interface OptimizeResult {
  ok: boolean
  output_path: string
  stats: { total: number; adjusted: number; merged: number }
}

interface SubtitleOptimizerDialogProps {
  open: boolean
  onClose: () => void
  onSuccess: (msg: string) => void
}

export function SubtitleOptimizerDialog({ open, onClose, onSuccess }: SubtitleOptimizerDialogProps) {
  const [targetSrt, setTargetSrt] = useState('')
  const [sourceSrt, setSourceSrt] = useState('')
  const [bilingual, setBilingual] = useState(false)
  const [lang, setLang] = useState('zh')
  const [defaults, setDefaults] = useState<Defaults | null>(null)
  const [optimizing, setOptimizing] = useState(false)
  const [result, setResult] = useState<OptimizeResult | null>(null)
  const [error, setError] = useState('')
  const [filePickerOpen, setFilePickerOpen] = useState(false)
  const [filePickerMode, setFilePickerMode] = useState<'target' | 'source'>('target')

  useEffect(() => {
    if (open) {
      setTargetSrt('')
      setSourceSrt('')
      setBilingual(false)
      setLang('zh')
      setResult(null)
      setError('')
      fetch('/api/subtitle/optimize-defaults')
        .then(r => r.json())
        .then(setDefaults)
        .catch(() => {})
    }
  }, [open])

  const handleOpenFilePicker = useCallback((mode: 'target' | 'source') => {
    setFilePickerMode(mode)
    setFilePickerOpen(true)
  }, [])

  const handleFileSelected = useCallback((path: string) => {
    if (filePickerMode === 'target') {
      setTargetSrt(path)
    } else {
      setSourceSrt(path)
    }
    setFilePickerOpen(false)
    setResult(null)
    setError('')
  }, [filePickerMode])

  const handleOptimize = useCallback(async () => {
    if (!targetSrt) return
    setOptimizing(true)
    setError('')
    setResult(null)
    try {
      const res = await fetch('/api/subtitle/optimize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_srt: targetSrt,
          source_srt: bilingual ? sourceSrt : null,
          mode: bilingual ? 'bilingual' : 'target_only',
          lang,
        }),
      })
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || '优化失败')
      }
      const data: OptimizeResult = await res.json()
      setResult(data)
      onSuccess(`优化完成: ${data.stats.total} 条字幕 → ${data.stats.adjusted} 条调整, ${data.stats.merged} 条合并`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setOptimizing(false)
    }
  }, [targetSrt, sourceSrt, bilingual, lang, onSuccess])

  const outputPreview = targetSrt
    ? (() => {
        const i = targetSrt.lastIndexOf('.')
        return i > 0 ? targetSrt.slice(0, i) + '_optimized' + targetSrt.slice(i) : targetSrt + '_optimized.srt'
      })()
    : ''

  const fileLabel = (path: string) => {
    if (!path) return ''
    const i = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'))
    return i >= 0 ? path.slice(i + 1) : path
  }

  const canOptimize = !!targetSrt && (!bilingual || !!sourceSrt) && !optimizing

  return (
    <>
      <Dialog open={open} onClose={optimizing ? undefined : onClose} maxWidth="sm" fullWidth>
        <DialogTitle>优化外挂字幕</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5, mt: 1 }}>

            {/* Target SRT */}
            <Box>
              <Typography variant="body2" mb={0.5} fontWeight={500}>
                目标字幕文件 <Typography component="span" color="error">*</Typography>
              </Typography>
              <Box sx={{ display: 'flex', gap: 1 }}>
                <TextField
                  size="small"
                  fullWidth
                  value={fileLabel(targetSrt)}
                  placeholder="选择需要优化的字幕文件"
                  InputProps={{ readOnly: true }}
                  onClick={() => handleOpenFilePicker('target')}
                  sx={{ cursor: 'pointer', '& .MuiInputBase-root': { cursor: 'pointer' } }}
                />
                <Button
                  variant="outlined"
                  startIcon={<FolderOpenIcon />}
                  onClick={() => handleOpenFilePicker('target')}
                  size="small"
                  sx={{ minWidth: 100, flexShrink: 0 }}
                >
                  选择文件
                </Button>
              </Box>
            </Box>

            {/* Bilingual toggle */}
            <FormControlLabel
              control={
                <Checkbox
                  checked={bilingual}
                  onChange={e => { setBilingual(e.target.checked); setSourceSrt(''); setResult(null) }}
                />
              }
              label="合并双语字幕（原文 + 译文）"
            />

            {/* Source SRT (bilingual only) */}
            {bilingual && (
              <Box>
                <Typography variant="body2" mb={0.5} fontWeight={500}>
                  原文字幕文件 <Typography component="span" color="error">*</Typography>
                </Typography>
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <TextField
                    size="small"
                    fullWidth
                    value={fileLabel(sourceSrt)}
                    placeholder="选择原文字幕文件"
                    InputProps={{ readOnly: true }}
                    onClick={() => handleOpenFilePicker('source')}
                    sx={{ cursor: 'pointer', '& .MuiInputBase-root': { cursor: 'pointer' } }}
                  />
                  <Button
                    variant="outlined"
                    startIcon={<FolderOpenIcon />}
                    onClick={() => handleOpenFilePicker('source')}
                    size="small"
                    sx={{ minWidth: 100, flexShrink: 0 }}
                  >
                    选择文件
                  </Button>
                </Box>
              </Box>
            )}

            {/* Language */}
            <FormControl size="small">
              <InputLabel>语言</InputLabel>
              <Select value={lang} label="语言" onChange={e => setLang(e.target.value)}>
                {LANGUAGES.map(l => (
                  <MenuItem key={l.code} value={l.code}>{l.label}</MenuItem>
                ))}
              </Select>
            </FormControl>

            {/* Output preview */}
            {outputPreview && (
              <Box>
                <Typography variant="caption" color="text.secondary">输出文件</Typography>
                <Typography variant="body2" sx={{ wordBreak: 'break-all' }}>{outputPreview}</Typography>
              </Box>
            )}

            {/* Advanced params (read-only) */}
            {defaults && (
              <Accordion disableGutters sx={{ bgcolor: 'transparent', boxShadow: 'none', '&:before': { display: 'none' } }}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 0, minHeight: 40 }}>
                  <Typography variant="body2" fontWeight={500}>高级参数（只读）</Typography>
                </AccordionSummary>
                <AccordionDetails sx={{ px: 0 }}>
                  <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1 }}>
                    <Box>
                      <Typography variant="caption" color="text.secondary">CJK 最小显示时长</Typography>
                      <Typography variant="body2">{defaults.min_duration_cjk}s</Typography>
                    </Box>
                    <Box>
                      <Typography variant="caption" color="text.secondary">CJK 阅读速度</Typography>
                      <Typography variant="body2">{defaults.reading_speed_cjk} 字/秒</Typography>
                    </Box>
                    <Box>
                      <Typography variant="caption" color="text.secondary">拉丁 最小显示时长</Typography>
                      <Typography variant="body2">{defaults.min_duration_latin}s</Typography>
                    </Box>
                    <Box>
                      <Typography variant="caption" color="text.secondary">拉丁 阅读速度</Typography>
                      <Typography variant="body2">{defaults.reading_speed_latin} 字符/秒</Typography>
                    </Box>
                    <Box>
                      <Typography variant="caption" color="text.secondary">阿拉伯 最小显示时长</Typography>
                      <Typography variant="body2">{defaults.min_duration_arabic}s</Typography>
                    </Box>
                    <Box>
                      <Typography variant="caption" color="text.secondary">阿拉伯 阅读速度</Typography>
                      <Typography variant="body2">{defaults.reading_speed_arabic} 字符/秒</Typography>
                    </Box>
                    <Box>
                      <Typography variant="caption" color="text.secondary">合并间隙阈值</Typography>
                      <Typography variant="body2">{defaults.max_merge_gap}s</Typography>
                    </Box>
                    <Box>
                      <Typography variant="caption" color="text.secondary">呼吸间隔</Typography>
                      <Typography variant="body2">{defaults.inter_gap}s</Typography>
                    </Box>
                    <Box>
                      <Typography variant="caption" color="text.secondary">单条最大时长</Typography>
                      <Typography variant="body2">{defaults.max_duration}s</Typography>
                    </Box>
                  </Box>
                </AccordionDetails>
              </Accordion>
            )}

            {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}

            {result && !optimizing && (
              <Alert severity="success" icon={false}>
                <Typography variant="body2" fontWeight={600}>优化完成</Typography>
                <Box sx={{ display: 'flex', gap: 2, mt: 0.5 }}>
                  <Chip label={`总 ${result.stats.total} 条`} size="small" />
                  <Chip label={`调整 ${result.stats.adjusted} 条`} size="small" color="primary" />
                  <Chip label={`合并 ${result.stats.merged} 条`} size="small" color="secondary" />
                </Box>
              </Alert>
            )}

            {optimizing && (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                <CircularProgress size={20} />
                <Typography variant="body2">正在优化字幕...</Typography>
              </Box>
            )}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose} disabled={optimizing}>取消</Button>
          <Button
            variant="contained"
            startIcon={<AutoFixHighIcon />}
            onClick={handleOptimize}
            disabled={!canOptimize}
          >
            确认优化
          </Button>
        </DialogActions>
      </Dialog>

      <FilePickerDialog
        open={filePickerOpen}
        onSelect={handleFileSelected}
        onClose={() => setFilePickerOpen(false)}
        title={filePickerMode === 'source' ? '选择原文字幕文件' : '选择目标字幕文件'}
        acceptExtensions={SRT_EXTS}
      />
    </>
  )
}
