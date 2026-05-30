import { useState, useCallback } from 'react'
import {
  Box, Typography, Tabs, Tab, TextField, Button, Chip,
  Divider, Breadcrumbs, List, ListItem,
} from '@mui/material'
import EditIcon from '@mui/icons-material/EditRounded'
import SplitIcon from '@mui/icons-material/CallSplitRounded'
import MergeIcon from '@mui/icons-material/MergeRounded'
import VoiceIcon from '@mui/icons-material/RecordVoiceOverRounded'
import OpenInNewIcon from '@mui/icons-material/OpenInNewRounded'
import CheckCircleIcon from '@mui/icons-material/CheckCircleRounded'
import { useAppStore } from '../../store/useAppStore'
import { LAYOUT_PRESETS } from '../../types/modes'
import DiagnosisCard from '../DiagnosisCard'
import InspectorPanel from '../InspectorPanel'
import { useConfigInspector } from '../../hooks/useConfigInspector'
import SpeakerInspectorTab from './SpeakerInspectorTab'
import { MOCK_ISSUES } from '../../mocks/mockData'
import type { EventViewModel } from '../../types'
import type { InspectorTab, PatchDraft } from '../../types/modes'

interface Props {
  event: EventViewModel | null
}

const TAB_LABELS: Record<InspectorTab, string> = {
  content: 'Content', timing: 'Timing', speaker: 'Speaker',
  tts: 'TTS', patch: 'Patch', history: 'History', config: 'Config', review: 'Review',
}

export default function IRInspector({ event }: Props) {
  const mode = useAppStore(s => s.mode)
  const addDraft = useAppStore(s => s.addDraft)
  const setMode = useAppStore(s => s.setMode)
  const navigateToEvent = useAppStore(s => s.navigateToEvent)
  const preset = LAYOUT_PRESETS[mode]
  const visibleTabs = preset.inspectorTabs
  const [activeTab, setActiveTab] = useState<InspectorTab>(visibleTabs[0] || 'content')

  const [editText, setEditText] = useState('')
  const [editTranslation, setEditTranslation] = useState('')
  const [editing, setEditing] = useState(false)

  // Config inspector hook
  const configInspector = useConfigInspector(event?.id ?? null)

  const handleStartEdit = useCallback(() => {
    if (!event) return
    setEditText(event.text)
    setEditTranslation(event.translation || '')
    setEditing(true)
  }, [event])

  const handleSaveDraft = useCallback(() => {
    if (!event) return
    const draft: PatchDraft = {
      eventId: event.id,
      opcode: 'SET_TRANSLATION',
      payload: { text: editText, translation: editTranslation },
      before: { text: event.text, translation: event.translation },
      after: { text: editText, translation: editTranslation },
      timestamp: Date.now(),
    }
    addDraft(draft)
    setEditing(false)
  }, [event, editText, editTranslation, addDraft])

  if (!event) {
    return (
      <Box sx={{ p: 3, textAlign: 'center' }}>
        <Typography variant="body2" color="text.secondary">
          选择一个事件以查看详情
        </Typography>
      </Box>
    )
  }

  const eventIssues = MOCK_ISSUES.filter(i => i.eventId === event.id)

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Tab bar */}
      <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
        <Tabs
          value={activeTab}
          onChange={(_, v) => setActiveTab(v)}
          variant="scrollable"
          scrollButtons="auto"
          sx={{ minHeight: 36, '& .MuiTab-root': { minHeight: 36, py: 0, fontSize: '0.72rem' } }}
        >
          {visibleTabs.map(tab => (
            <Tab key={tab} label={TAB_LABELS[tab]} value={tab} />
          ))}
        </Tabs>
      </Box>

      <Box sx={{ flexGrow: 1, overflow: 'hidden auto', p: 1.5 }}>
        {/* Content tab */}
        {activeTab === 'content' && (
          <Box>
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 1, gap: 0.5, flexWrap: 'wrap' }}>
              <Typography variant="subtitle2">{event.id}</Typography>
              <Chip label={`${event.start.toFixed(1)}s - ${event.end.toFixed(1)}s`} size="small" variant="outlined" />
              <Chip label={event.displayName || event.speaker || '?'} size="small"
                sx={{ bgcolor: 'grey.500', color: 'common.white' }} />
            </Box>
            <Divider sx={{ mb: 1 }} />

            {!editing ? (
              <>
                <Box sx={{ mb: 1.5 }}>
                  <Chip label="原文" size="small" color="default" variant="outlined" sx={{ mb: 0.5 }} />
                  <Typography variant="body2" sx={{ color: 'text.secondary', fontStyle: 'italic' }}>
                    {event.text}
                  </Typography>
                </Box>
                <Box sx={{ mb: 1.5 }}>
                  <Chip label="译文" size="small" color="primary" variant="outlined" sx={{ mb: 0.5 }} />
                  <Typography variant="body2">{event.translation || '(未翻译)'}</Typography>
                </Box>
                {event.patches.length > 0 && (
                  <Box sx={{ mb: 1.5 }}>
                    <Chip label={`补丁 (${event.patches.length})`} size="small" color="warning" variant="outlined" sx={{ mb: 0.5 }} />
                    <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                      {event.patches.map(p => (
                        <Chip key={p.patch_id} label={`${p.opcode} · ${p.author}`} size="small" sx={{ fontSize: '0.6rem' }} />
                      ))}
                    </Box>
                  </Box>
                )}
                <Box sx={{ mb: 1.5 }}>
                  <Typography variant="caption" color="text.secondary">Pass Trace:</Typography>
                  <Breadcrumbs separator="→" sx={{ fontSize: '0.65rem' }}>
                    {event.passTrace.length > 0
                      ? event.passTrace.map(name => (
                        <Chip key={name} label={name} size="small" variant="outlined" sx={{ fontSize: '0.55rem' }} />
                      ))
                      : <Typography variant="caption" color="text.secondary">(无)</Typography>}
                  </Breadcrumbs>
                </Box>
                <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 1 }}>
                  <Button size="small" variant="outlined" startIcon={<EditIcon />} onClick={handleStartEdit}>编辑翻译</Button>
                  <Button size="small" variant="outlined" startIcon={<SplitIcon />}>切分</Button>
                  <Button size="small" variant="outlined" startIcon={<MergeIcon />}>合并上文</Button>
                  <Button size="small" variant="outlined" startIcon={<VoiceIcon />}>重标说话人</Button>
                </Box>

                {eventIssues.map(issue => (
                  <DiagnosisCard key={issue.eventId + issue.type} issue={issue} />
                ))}
              </>
            ) : (
              <>
                <TextField label="原文" value={editText} onChange={e => setEditText(e.target.value)}
                  multiline rows={2} fullWidth size="small" sx={{ mb: 1.5 }} />
                <TextField label="译文" value={editTranslation} onChange={e => setEditTranslation(e.target.value)}
                  multiline rows={2} fullWidth size="small" sx={{ mb: 1.5 }} />
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <Button size="small" variant="contained" onClick={handleSaveDraft}>保存草案</Button>
                  <Button size="small" variant="outlined" onClick={() => setEditing(false)}>取消</Button>
                </Box>
              </>
            )}
          </Box>
        )}

        {/* Timing tab */}
        {activeTab === 'timing' && (
          <Box>
            <Typography variant="subtitle2" gutterBottom>时间信息</Typography>
            <Box sx={{ display: 'flex', gap: 2, mb: 1 }}>
              <Box><Typography variant="caption" color="text.secondary">起始</Typography>
                <Typography>{event.start.toFixed(2)}s</Typography></Box>
              <Box><Typography variant="caption" color="text.secondary">结束</Typography>
                <Typography>{event.end.toFixed(2)}s</Typography></Box>
              <Box><Typography variant="caption" color="text.secondary">时长</Typography>
                <Typography>{(event.end - event.start).toFixed(2)}s</Typography></Box>
            </Box>
            <Divider sx={{ my: 1 }} />
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
              与相邻事件间距: {(event.start - (eventIssues.length > 0 ? eventIssues[0].start : 0)).toFixed(2)}s
            </Typography>
            <Button size="small" variant="outlined" color="warning" fullWidth sx={{ mt: 1 }}>
              局部重算此片段
            </Button>
          </Box>
        )}

        {/* Speaker tab */}
        {activeTab === 'speaker' && (
          <SpeakerInspectorTab event={event} />
        )}

        {/* TTS tab */}
        {activeTab === 'tts' && (
          <Box>
            <Typography variant="subtitle2" gutterBottom>TTS 信息</Typography>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              <Box>
                <Typography variant="caption" color="text.secondary">片段时长</Typography>
                <Typography variant="body2">{(event.end - event.start).toFixed(2)}s</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">预估语音时长</Typography>
                <Typography variant="body2">
                  {event.text ? (event.text.length * 0.25).toFixed(2) : '—'}s
                  <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                    (按 {event.text ? (event.text.length * 0.25 / (event.end - event.start) * 100).toFixed(0) : '—'}% 速率)
                  </Typography>
                </Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">TTS 引擎</Typography>
                <Chip label="edge-tts (默认)" size="small" variant="outlined" sx={{ fontSize: '0.65rem' }} />
              </Box>
            </Box>
            <Divider sx={{ my: 1.5 }} />
            <Typography variant="caption" color="text.secondary">
              TTS 预览与语速调节将在集成真实引擎后可用
            </Typography>
          </Box>
        )}

        {/* Patch tab */}
        {activeTab === 'patch' && (
          <Box>
            <Typography variant="subtitle2" gutterBottom>补丁与草案</Typography>
            {event.patches.length === 0 ? (
              <Typography variant="body2" color="text.secondary">此事件无关联补丁</Typography>
            ) : (
              <List dense disablePadding>
                {event.patches.map(p => (
                  <ListItem key={p.patch_id} sx={{ flexDirection: 'column', alignItems: 'flex-start', px: 1, py: 0.5, mb: 0.5, borderRadius: 1, bgcolor: 'action.hover' }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, width: '100%' }}>
                      <Chip label={p.opcode} size="small" color="primary" variant="outlined" sx={{ fontSize: '0.6rem', height: 18 }} />
                      <Typography variant="caption" sx={{ flexGrow: 1 }}>{p.author}</Typography>
                      <Typography variant="caption" color="text.secondary">{new Date(p.timestamp).toLocaleTimeString()}</Typography>
                    </Box>
                    {p.payload && (
                      <Typography variant="caption" color="text.secondary" sx={{ mt: 0.25 }}>
                        {JSON.stringify(p.payload).slice(0, 80)}{JSON.stringify(p.payload).length > 80 ? '...' : ''}
                      </Typography>
                    )}
                  </ListItem>
                ))}
              </List>
            )}
            <Divider sx={{ my: 1.5 }} />
            <Button size="small" variant="outlined" startIcon={<OpenInNewIcon />}
              onClick={() => { setMode('patch'); navigateToEvent(event.id, event.start, 'timeline') }}>
              切换到 Patch Management 模式
            </Button>
          </Box>
        )}

        {/* History tab */}
        {activeTab === 'history' && (
          <Box>
            <Typography variant="subtitle2" gutterBottom>处理历史</Typography>
            {event.passTrace.length === 0 ? (
              <Typography variant="body2" color="text.secondary">无处理记录</Typography>
            ) : (
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                {event.passTrace.map((name, idx) => (
                  <Box key={idx} sx={{
                    display: 'flex', alignItems: 'center', gap: 1,
                    p: 1, borderRadius: 1, bgcolor: 'action.hover',
                  }}>
                    <CheckCircleIcon sx={{ fontSize: 16, color: 'success.main' }} />
                    <Box>
                      <Typography variant="body2" sx={{ fontSize: '0.75rem' }}>{name}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        Pass {idx + 1} of {event.passTrace.length}
                      </Typography>
                    </Box>
                  </Box>
                ))}
              </Box>
            )}
          </Box>
        )}

        {/* Config tab — slot-level parameter editor */}
        {activeTab === 'config' && (
          <InspectorPanel
            eventId={event.id}
            config={configInspector.config}
            inheritedFrom={configInspector.inheritedFrom}
            overriddenFields={configInspector.overriddenFields}
            loading={configInspector.loading}
            onConfigChange={configInspector.handleConfigChange}
            onResetField={configInspector.handleResetField}
            onResetSlot={configInspector.handleResetSlot}
            onPreviewTTS={configInspector.handlePreviewTTS}
          />
        )}
      </Box>
    </Box>
  )
}
