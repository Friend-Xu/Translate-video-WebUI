"""core/passes — 业务 Pass 实现

- AudioPreprocessCompositePass: MediaValidator + Demucs + VAD → IR (Ch10)
- ASRToIRPass:          raw segments → TimelineProjectState (向后兼容)
- ASRCompositePass:     Whisper + wav2vec2 → Patch → IR (Ch3)
- SpeakerCompositePass: pyannote + clustering → IR (Ch4)
- TTSCompositePass:     ChatTTS + emotion + duration → IR (Ch5)
- CosyVoiceCompositePass: CosyVoice + speed + cross_lingual → IR (Ch6)
- IndexTTSCompositePass: IndexTTS + voice_memory + retrieval → IR (Ch7)
- OpenVoiceCompositePass: OpenVoice + fallback transfer → IR (Ch8)
- EdgeTTSCompositePass: Edge TTS + last resort → IR (Ch9)
- SemanticMergePass:    合并同 speaker 短间隔相邻事件
- LLMTranslationPass:   标签化纯文本 LLM 翻译
- SRTExportPass:        SynthesisEngine.render_all() → .srt
- VideoExportPass:      TTS 音频 → 视频段 → ffmpeg 合并 → 成品视频
"""
from core.passes.asr_to_ir_pass import ASRToIRPass
from core.passes.asr_composite_pass import ASRCompositePass
from core.passes.speaker_composite_pass import SpeakerCompositePass
from core.passes.tts_composite_pass import TTSCompositePass
from core.passes.cosyvoice_composite_pass import CosyVoiceCompositePass
from core.passes.indextts_composite_pass import IndexTTSCompositePass
from core.passes.openvoice_composite_pass import OpenVoiceCompositePass
from core.passes.edge_tts_composite_pass import EdgeTTSCompositePass
from core.passes.audio_preprocess_composite_pass import AudioPreprocessCompositePass
from core.passes.semantic_merge_pass import SemanticMergePass
from core.passes.llm_translation_pass import LLMTranslationPass
from core.passes.translation_quality_pass import TranslationQualityPass
from core.passes.emotion_composite_pass import EmotionCompositePass
from core.passes.srt_export_pass import SRTExportPass
from core.passes.video_export_pass import VideoExportPass

__all__ = [
    "ASRToIRPass",
    "ASRCompositePass",
    "SpeakerCompositePass",
    "TTSCompositePass",
    "CosyVoiceCompositePass",
    "IndexTTSCompositePass",
    "OpenVoiceCompositePass",
    "EdgeTTSCompositePass",
    "AudioPreprocessCompositePass",
    "SemanticMergePass",
    "LLMTranslationPass",
    "TranslationQualityPass",
    "EmotionCompositePass",
    "SRTExportPass",
]
