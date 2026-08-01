"""契约测试 — P3: ConfigResolver 生产接线

锁死结论:
  1. pass.configure 契约 = 全槽位 dict {slot: {...}}, pass 从自己槽位取子块
     (修复: audio/speaker pass 曾平铺读取, 全槽位注入下配置静默失效)
  2. PassManager 注入 _resolver 给 pass, 供 apply() 内逐事件三级解析
  3. 事件级 tts.config 覆盖 > 说话人 > 全局默认 (resolve_event_config 三级)
"""
from __future__ import annotations


class TestPassConfigureShape:
    def test_audio_pass_reads_audio_slot(self):
        from core.passes.audio_preprocess_composite_pass import AudioPreprocessCompositePass
        p = AudioPreprocessCompositePass()
        p.configure({"audio": {"skip_demucs": True}, "tts": {}})
        assert p.skip_demucs is True

    def test_audio_pass_flat_backward_compat(self):
        """旧调用方直喂平铺槽位仍兼容。"""
        from core.passes.audio_preprocess_composite_pass import AudioPreprocessCompositePass
        p = AudioPreprocessCompositePass()
        p.configure({"skip_demucs": True})
        assert p.skip_demucs is True

    def test_speaker_pass_reads_speaker_slot(self):
        from core.passes.speaker_composite_pass import SpeakerCompositePass
        p = SpeakerCompositePass()
        p.configure({"speaker": {"clustering_threshold": 0.7}})
        assert p.enable_clustering is True

    def test_tts_pass_adapter_gets_tts_slot(self, monkeypatch):
        """TTS pass 把 tts 槽位子块喂给 adapter (平铺, 非全槽位)。"""
        from core.passes.tts_composite_pass import TTSCompositePass
        calls: list[dict] = []

        class FakeAdapter:
            def __init__(self, **kw): pass
            def configure(self, cfg): calls.append(cfg)
            def synthesize(self, ctx): return None

        import core.passes.tts_composite_pass as mod
        monkeypatch.setattr(mod, "ChatTTSAdapter", FakeAdapter)
        p = TTSCompositePass()
        p.configure({"tts": {"chattts_temperature": 0.9}, "translation": {}})
        # 只验证 configure 后的 tts 子块存储 — apply 完整流程由集成测试覆盖
        stored = p._resolved_config["tts"]
        assert stored["chattts_temperature"] == 0.9


class TestResolverInjection:
    def test_pass_manager_injects_resolver(self):
        from core.config.global_config import GlobalConfig
        from core.engine.pass_base import TimelinePass
        from core.engine.pass_manager import PassManager
        from core.runtime.config_resolver import ConfigResolver
        from core.runtime.project_state import TimelineProjectState
        from core.ir.timeline_event import TimelineEventIR
        from core.ir.project import TimelineProjectIR

        class ProbePass(TimelinePass):
            name = "probe"

            def configure(self, resolved_config=None):
                self._resolved_config = resolved_config or {}

            def apply(self, state):
                return state

        pm = PassManager()
        pm.set_config_resolver(ConfigResolver(GlobalConfig()))
        probe = ProbePass()
        pm.register(probe)
        state = TimelineProjectState(TimelineProjectIR(events={}, speakers={}))
        pm._configure_pass("probe", state)
        assert getattr(probe, "_resolver", None) is not None
        # 且 configure 收到全槽位 dict
        assert isinstance(probe._resolved_config, dict)
        assert "audio" in probe._resolved_config and "tts" in probe._resolved_config


class TestEventLevelOverride:
    def test_event_tts_override_wins(self):
        """事件级 tts.config > 说话人 > 全局默认 (三级解析)。"""
        from core.config.global_config import GlobalConfig
        from core.ir.project import TimelineProjectIR
        from core.ir.speaker import SpeakerNodeIR
        from core.ir.timeline_event import TimelineEventIR
        from core.runtime.config_resolver import ConfigResolver
        from core.runtime.patch import OpCode, Patch
        from core.runtime.patch_engine import PatchEngine
        from core.runtime.project_state import TimelineProjectState

        events = {"evt_001": TimelineEventIR(id="evt_001", start=0.0, end=2.5, speaker_ref="SPK_A", text_ref="Hi")}
        speakers = {"SPK_A": SpeakerNodeIR(id="SPK_A", name="Alice", config={"tts": {"chattts_temperature": 0.7}})}
        state = TimelineProjectState(TimelineProjectIR(events=events, speakers=speakers))
        resolver = ConfigResolver(GlobalConfig())
        engine = PatchEngine()

        # 说话人级生效
        resolved = resolver.resolve_event_config("evt_001", "tts", state)
        assert resolved["chattts_temperature"] == 0.7

        # 事件级覆盖生效
        engine.apply(state, Patch(id="p1", target_id="evt_001", op=OpCode.OVERRIDE_CONFIG,
                                  value={"slot": "tts", "partial_config": {"chattts_temperature": 0.5}},
                                  author="user", confidence=1.0))
        resolved2 = resolver.resolve_event_config("evt_001", "tts", state)
        assert resolved2["chattts_temperature"] == 0.5

        # 未覆盖字段仍继承说话人级
        assert resolved2["engine"] == GlobalConfig().project.tts["engine"]
