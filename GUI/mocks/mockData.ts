/**
 * mockData.ts — 开发环境 Mock 数据
 *
 * 至少 25 个事件、2 个说话人、3 个 patch 示例，
 * 足以测试高密度场景下的时间轴渲染和交互。
 */
import type { EventViewModel, WaveformData, TimelinePatchData, SpeakerLoadResponse } from '../types'
import type { IssueItem } from '../types/modes'

// ── 说话人 ──

const SPEAKER_A = 'SPEAKER_00'
const SPEAKER_B = 'SPEAKER_01'

// ── 辅助 ──

function t(seconds: number): number {
  return Math.round(seconds * 10) / 10
}

// ── Mock Events (25 个) ──

export const MOCK_EVENTS: EventViewModel[] = [
  { id: 'seg_001', start: t(0.0), end: t(2.5), speaker: SPEAKER_A, displayName: '主持人', text: '大家好，欢迎收看今天的节目。', translation: 'Hello everyone, welcome to today\'s show.', source: 'asr', confidence: 0.95, visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_002', start: t(2.8), end: t(5.0), speaker: SPEAKER_B, displayName: '嘉宾李', text: '谢谢主持人，很高兴来到这里。', translation: 'Thank you, host. Glad to be here.', source: 'asr', confidence: 0.91, visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_003', start: t(5.3), end: t(8.0), speaker: SPEAKER_A, displayName: '主持人', text: '今天我们要讨论的话题是人工智能在医疗领域的应用。', translation: 'Today we\'re discussing AI applications in healthcare.', source: 'asr', confidence: 0.87, visualState: { hasPatches: false, hasAiSuggestion: true, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_004', start: t(8.3), end: t(11.2), speaker: SPEAKER_B, displayName: '嘉宾李', text: '是的，AI在医学影像诊断方面已经取得了很大的突破。', translation: 'Yes, AI has made great breakthroughs in medical imaging diagnostics.', source: 'asr', confidence: 0.92, visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_005', start: t(11.5), end: t(14.0), speaker: SPEAKER_A, displayName: '主持人', text: '能不能给我们举一个具体的例子呢？', translation: 'Could you give us a specific example?', source: 'asr', confidence: 0.88, visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_006', start: t(14.3), end: t(18.5), speaker: SPEAKER_B, displayName: '嘉宾李', text: '比如说，现在有一些AI系统可以在几秒钟内分析CT扫描结果，准确率超过95%。', translation: 'For example, some AI systems can analyze CT scan results in seconds with over 95% accuracy.', source: 'asr', confidence: 0.45, visualState: { hasPatches: true, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [{ patch_id: 'p1', opcode: 'SET_TRANSLATION', targets: ['seg_006'], payload: { translation: 'For instance, some AI systems can analyze CT scans within seconds, achieving over 95% accuracy.' }, reason: ['improve fluency'], score: 0.85, confidence: 0.9, parent_version: 'abc123', idempotency_key: 'ik1', author: 'AI', timestamp: '2026-05-25T10:00:00Z' }], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_007', start: t(18.8), end: t(21.0), speaker: SPEAKER_A, displayName: '主持人', text: '那这些系统的数据安全性如何保证呢？', translation: 'How is the data security of these systems ensured?', source: 'asr', confidence: 0.82, visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_008', start: t(21.3), end: t(25.0), speaker: SPEAKER_B, displayName: '嘉宾李', text: '这是一个非常重要的问题。目前业界普遍采用联邦学习的技术来解决数据隐私问题。', translation: 'This is a very important question. The industry widely uses federated learning to address data privacy.', source: 'asr', confidence: 0.78, visualState: { hasPatches: false, hasAiSuggestion: true, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_009', start: t(25.3), end: t(27.5), speaker: SPEAKER_A, displayName: '主持人', text: '联邦学习是什么？能简单解释一下吗？', translation: 'What is federated learning? Can you explain it simply?', source: 'asr', confidence: 0.90, visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_010', start: t(27.8), end: t(32.5), speaker: SPEAKER_B, displayName: '嘉宾李', text: '简单来说，就是数据不出本地，模型在各地训练后再汇总，这样既保护了隐私又能利用多方数据。', translation: 'Simply put, data stays local, models train locally and then aggregate, protecting privacy while leveraging multi-party data.', source: 'asr', confidence: 0.86, visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_011', start: t(32.8), end: t(35.0), speaker: SPEAKER_A, displayName: '主持人', text: '除了医疗领域，AI还在哪些行业有突破性应用？', translation: 'Besides healthcare, what other industries have AI breakthroughs?', source: 'asr', confidence: 0.93, visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_012', start: t(35.3), end: t(39.8), speaker: SPEAKER_B, displayName: '嘉宾李', text: '自动驾驶、智能客服、个性化教育都是很热门的应用方向。特别是在教育领域，AI可以实现真正的因材施教。', translation: 'Autonomous driving, smart customer service, and personalized education are all hot areas. Especially in education, AI can truly enable personalized teaching.', source: 'asr', confidence: 0.35, visualState: { hasPatches: false, hasAiSuggestion: true, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_013', start: t(40.0), end: t(42.0), speaker: SPEAKER_A, displayName: '主持人', text: '听起来AI的前景确实非常广阔。', translation: 'It sounds like AI has a very broad future indeed.', source: 'asr', confidence: 0.94, visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_014', start: t(42.3), end: t(46.0), speaker: SPEAKER_B, displayName: '嘉宾李', text: '是的，但同时我们也要注意AI的伦理问题，比如算法偏见、就业影响等。', translation: 'Yes, but we also need to pay attention to AI ethics, such as algorithmic bias and employment impact.', source: 'asr', confidence: 0.81, visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_015', start: t(46.3), end: t(48.5), speaker: SPEAKER_A, displayName: '主持人', text: '说到算法偏见，这个问题具体表现在哪些方面？', translation: 'Speaking of algorithmic bias, how does this problem specifically manifest?', source: 'asr', confidence: 0.89, visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_016', start: t(48.8), end: t(53.5), speaker: SPEAKER_B, displayName: '嘉宾李', text: '比如在人脸识别系统中，对某些肤色人群的识别准确率明显偏低。这就需要我们在训练数据上做更多平衡。', translation: 'For instance, facial recognition systems show markedly lower accuracy for certain skin tones. This requires better training data balance.', source: 'asr', confidence: 0.76, visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_017', start: t(53.8), end: t(55.5), speaker: SPEAKER_A, displayName: '主持人', text: '我们稍作休息，马上回来。', translation: 'Let\'s take a short break, we\'ll be right back.', source: 'asr', confidence: 0.96, visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_018', start: t(58.0), end: t(60.0), speaker: SPEAKER_A, displayName: '主持人', text: '欢迎回来，我们继续讨论。', translation: 'Welcome back, let\'s continue our discussion.', source: 'asr', confidence: 0.97, visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_019', start: t(60.3), end: t(64.5), speaker: SPEAKER_B, displayName: '嘉宾李', text: '我想补充一点，在AI治理方面，中国已经出台了一系列的政策法规来规范AI的发展和应用。', translation: 'I\'d like to add that in AI governance, China has introduced a series of policies to regulate AI development and application.', source: 'asr', confidence: 0.83, visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_020', start: t(64.8), end: t(67.0), speaker: SPEAKER_A, displayName: '主持人', text: '这对于行业发展来说是个好消息。', translation: 'That\'s good news for the industry\'s development.', source: 'asr', confidence: 0.91, visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_021', start: t(67.3), end: t(71.8), speaker: SPEAKER_B, displayName: '嘉宾李', text: '没错，技术创新和规范治理需要两手抓。我相信在未来五年内，我们会看到更多负责任的人工智能应用落地。', translation: 'Exactly, technological innovation and governance need to go hand in hand. I believe we\'ll see more responsible AI applications in the next five years.', source: 'asr', confidence: 0.72, visualState: { hasPatches: true, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [{ patch_id: 'p2', opcode: 'SET_TRANSLATION', targets: ['seg_021'], payload: { translation: 'Right, tech innovation and regulatory governance must go hand in hand. We\'ll see more responsible AI deployments within five years.' }, reason: ['conciseness'], score: 0.78, confidence: 0.85, parent_version: 'abc124', idempotency_key: 'ik2', author: 'AI', timestamp: '2026-05-25T10:05:00Z' }], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_022', start: t(72.0), end: t(74.0), speaker: SPEAKER_A, displayName: '主持人', text: '非常感谢李老师今天的精彩分享。', translation: 'Thank you very much, Professor Li, for today\'s wonderful sharing.', source: 'asr', confidence: 0.95, visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_023', start: t(74.3), end: t(76.0), speaker: SPEAKER_B, displayName: '嘉宾李', text: '谢谢主持人，也谢谢各位观众。', translation: 'Thank you, host, and thank you to the audience.', source: 'asr', confidence: 0.94, visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_024', start: t(76.3), end: t(78.5), speaker: SPEAKER_A, displayName: '主持人', text: '下期节目我们将讨论量子计算的最新进展，敬请期待。', translation: 'Next episode, we\'ll discuss the latest advances in quantum computing. Stay tuned.', source: 'asr', confidence: 0.90, visualState: { hasPatches: false, hasAiSuggestion: true, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
  { id: 'seg_025', start: t(78.8), end: t(80.0), speaker: SPEAKER_A, displayName: '主持人', text: '再见！', translation: 'Goodbye!', source: 'asr', confidence: 0.99, visualState: { hasPatches: false, hasAiSuggestion: false, isSelected: false, isMultiSelected: false }, patches: [], passTrace: ['ASR', 'Alignment'] },
]

// ── Mock WaveformData (80 秒) ──

function generatePeaks(durationSec: number, sampleRate: number = 100): number[] {
  const count = durationSec * sampleRate
  const peaks: number[] = []
  for (let i = 0; i < count; i++) {
    const sec = i / sampleRate
    const hasSpeech = MOCK_EVENTS.some(e => sec >= e.start && sec <= e.end)
    peaks.push(hasSpeech ? 0.2 + Math.random() * 0.7 : Math.random() * 0.1)
  }
  return peaks
}

export const MOCK_WAVEFORM: WaveformData = {
  peaks: generatePeaks(80),
  duration: 80.0,
  sampleRate: 44100,
}

// ── Mock Patches ──

export const MOCK_AI_PATCHES: TimelinePatchData[] = [
  {
    patch_id: 'p_ai_001',
    opcode: 'SET_TRANSLATION',
    targets: ['seg_006'],
    payload: { translation: 'For instance, some AI systems can analyze CT scans within seconds, achieving over 95% accuracy.' },
    reason: ['improve fluency'],
    score: 0.85,
    confidence: 0.90,
    parent_version: 'abc123',
    idempotency_key: 'ik_ai_001',
    author: 'AI',
    timestamp: '2026-05-25T10:00:00Z',
  },
  {
    patch_id: 'p_ai_002',
    opcode: 'SET_TRANSLATION',
    targets: ['seg_021'],
    payload: { translation: 'Right, tech innovation and regulatory governance must go hand in hand.' },
    reason: ['conciseness'],
    score: 0.78,
    confidence: 0.85,
    parent_version: 'abc124',
    idempotency_key: 'ik_ai_002',
    author: 'AI',
    timestamp: '2026-05-25T10:05:00Z',
  },
  {
    patch_id: 'p_ai_003',
    opcode: 'RETAG_SPEAKER',
    targets: ['seg_012'],
    payload: { new_speaker: 'SPEAKER_01', reason: 'speaker continuity check' },
    reason: ['speaker verification'],
    score: 0.65,
    confidence: 0.72,
    parent_version: 'abc125',
    idempotency_key: 'ik_ai_003',
    author: 'AI',
    timestamp: '2026-05-25T10:08:00Z',
  },
]

// ── Mock Issues ──

export const MOCK_ISSUES: IssueItem[] = [
  { eventId: 'seg_006', type: 'low_confidence', severity: 'warning', message: 'ASR 置信度过低 (0.45)', detail: { confidence: 0.45, threshold: 0.7 }, start: 14.3, end: 18.5 },
  { eventId: 'seg_012', type: 'low_confidence', severity: 'warning', message: 'ASR 置信度过低 (0.35)', detail: { confidence: 0.35, threshold: 0.7 }, start: 35.3, end: 39.8 },
  { eventId: 'seg_008', type: 'speaker_drift', severity: 'warning', message: '说话人特征漂移 (相似度 0.52)', detail: { similarity: 0.52, threshold: 0.7 }, start: 21.3, end: 25.0 },
  { eventId: 'seg_016', type: 'term_conflict', severity: 'error', message: '术语冲突: "训练数据" vs "training data"', detail: { term: '训练数据' }, start: 48.8, end: 53.5 },
  { eventId: 'seg_021', type: 'cps_high', severity: 'warning', message: '字幕字符速率过高 (CPS 28.5)', detail: { cps: 28.5, threshold: 20 }, start: 67.3, end: 71.8 },
]

// ── Mock SpeakerLoadResponse ──

export const MOCK_SPEAKER_LOAD: SpeakerLoadResponse = {
  audio_id: 'mock_audio_001',
  version: '1.0',
  speaker_lanes: [
    { speaker: SPEAKER_A, segments: MOCK_EVENTS.filter(e => e.speaker === SPEAKER_A).map(e => ({ start: e.start, end: e.end, text: e.text, confidence: e.confidence })) },
    { speaker: SPEAKER_B, segments: MOCK_EVENTS.filter(e => e.speaker === SPEAKER_B).map(e => ({ start: e.start, end: e.end, text: e.text, confidence: e.confidence })) },
  ],
  patches: {
    patches: MOCK_AI_PATCHES,
    high: [MOCK_AI_PATCHES[0]],
    medium: [MOCK_AI_PATCHES[1]],
    low: [MOCK_AI_PATCHES[2]],
  },
  patch_log: [],
  pass_trace: ['ASR', 'Alignment', 'Fusion', 'SpeakerDiarization'],
  inspector_data: {},
  speakerNames: {
    [SPEAKER_A]: '主持人',
    [SPEAKER_B]: '嘉宾李',
  },
}
