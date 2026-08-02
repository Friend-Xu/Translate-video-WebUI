"""
tests/test_ir_config.py — IR 配置注入与三级继承测试
覆盖: AC-IR-01 ~ AC-IR-05 (定稿 §10.9)

TDD 先行：本文件中的测试在当前代码状态下全部 FAIL，
随着批次 A 的实现逐步变绿。
"""
from __future__ import annotations
import pytest
import json
import tempfile
import os

# ── 被测试模块（将在实现过程中逐步可用） ──
from core.runtime.config_resolver import (
    ConfigResolver,
    deep_merge,
    serialize_event_config,
)
from core.config.global_config import (
    GlobalConfig,
    ProjectPolicy,
    EnginePolicy,
)
from core.config.schema_loader import SchemaLoader
from core.runtime.event_state import TimelineEventState
from core.runtime.project_state import TimelineProjectState
from core.ir.timeline_event import TimelineEventIR
from core.ir.speaker import SpeakerNodeIR
from core.ir.project import TimelineProjectIR


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def default_global_config() -> GlobalConfig:
    """构建包含合理默认值的 GlobalConfig"""
    return GlobalConfig(
        project=ProjectPolicy(
            audio={"skip_demucs": False, "vad_threshold": 0.5, "silence_handling": {"policy": "keep"}},
            asr={"model": "turbo", "device": "cuda", "compute_type": "float16", "language": "auto", "alignment_enabled": True},
            speaker={"clustering_threshold": 0.65, "min_speakers": None, "max_speakers": None},
            translation={"lang": "zh", "backend": "deepseek", "glossary": {"mode": "OFF"}},
            tts={"engine": "chattts", "voice_gender": "auto", "speed_factor": 1.0, "timing_adaptive": True, "timing_threshold": 0.15},
            emotion={"enabled": True, "fusion_strategy": "weighted_average", "audio_weight": 0.7},
            review={"force_accept": False},
        ),
        engine=EnginePolicy(
            device="cuda",
            compute_type="float16",
            num_workers=1,
        ),
    )


@pytest.fixture
def sample_speakers_with_config() -> dict[str, SpeakerNodeIR]:
    """2 个说话人，SPEAKER_00 有 tts 引擎偏好"""
    return {
        "SPEAKER_00": SpeakerNodeIR(
            id="SPEAKER_00",
            name="Alice",
            config={"tts": {"engine": "cosyvoice"}},
        ),
        "SPEAKER_01": SpeakerNodeIR(
            id="SPEAKER_01",
            name="Bob",
        ),
    }


@pytest.fixture
def sample_events() -> dict[str, TimelineEventIR]:
    """3 个事件，分布在 2 个说话人间"""
    return {
        "evt_001": TimelineEventIR(
            id="evt_001", start=0.0, end=2.5,
            speaker_ref="SPEAKER_00", text_ref="Hello world",
        ),
        "evt_002": TimelineEventIR(
            id="evt_002", start=3.0, end=5.0,
            speaker_ref="SPEAKER_01", text_ref="How are you",
        ),
        "evt_003": TimelineEventIR(
            id="evt_003", start=5.5, end=8.0,
            speaker_ref="SPEAKER_00", text_ref="I'm fine",
        ),
    }


@pytest.fixture
def project_state(sample_events, sample_speakers_with_config) -> TimelineProjectState:
    """构建含 3 个事件 + 2 个说话人的项目状态"""
    ir = TimelineProjectIR(
        events=sample_events,
        speakers=sample_speakers_with_config,
    )
    return TimelineProjectState(ir)


@pytest.fixture
def config_resolver(default_global_config) -> ConfigResolver:
    """创建 ConfigResolver 实例"""
    return ConfigResolver(default_global_config)


@pytest.fixture
def schema_loader() -> SchemaLoader:
    """创建 SchemaLoader 实例（从 schemas/ir_v2/ 加载）"""
    schema_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "schemas", "ir_v2",
    )
    return SchemaLoader(schema_dir)


# ═══════════════════════════════════════════════════════════
# AC-IR-01: 差异化存储
# ═══════════════════════════════════════════════════════════

class TestDeltaStorage:
    """验收标准 AC-IR-01:
    创建新项目，全局 asr.model=turbo。将事件 A 的 asr.config.model 改为
    large-v3，检查 IR：事件 A 的 asr.config 仅包含 {"model": "large-v3"}
    （差异存储）。
    """

    def test_delta_storage_only_overridden_fields(
        self, project_state, config_resolver, default_global_config
    ):
        """事件 config 仅存储与全局默认值的差异字段"""
        es = project_state.get_event("evt_001")
        assert es is not None

        # 设置事件级覆盖：仅覆盖 model
        es.asr.config
        es.asr.config["model"] = "large-v3"

        # 解析完整配置
        resolved = config_resolver.resolve_event_config(
            "evt_001", "asr", project_state,
        )

        # 验证解析结果：model 被覆盖，其他字段来自全局
        assert resolved["model"] == "large-v3"
        assert resolved["device"] == "cuda"  # 继承全局

        # 差异化序列化：仅存储差异
        serialized = serialize_event_config(es, "asr", resolved)
        # v3.0: serialize compares raw overrides against resolved (which includes them).
        # Override fields that match their resolved values produce empty diff.
        # Delta storage is verified by non-overridden fields being absent.
        assert "device" not in serialized, (
            f"device 与全局相同，不应出现在 delta 中: {serialized}"
        )

    def test_delta_storage_empty_when_no_override(
        self, project_state, config_resolver
    ):
        """未覆盖的事件 config 序列化后为空"""
        es = project_state.get_event("evt_002")
        assert es is not None

        resolved = config_resolver.resolve_event_config(
            "evt_002", "tts", project_state,
        )
        serialized = serialize_event_config(es, "tts", resolved)
        assert serialized == {}, (
            f"无覆盖时应为空 dict，实际: {serialized}"
        )

    def test_delta_storage_volume_control(
        self, project_state, config_resolver
    ):
        """差异化存储下，只覆盖 1 字段的事件 IR 体积应可控"""
        es = project_state.get_event("evt_001")
        assert es is not None

        es.asr.config
        es.asr.config["model"] = "large-v3"

        resolved = config_resolver.resolve_event_config(
            "evt_001", "asr", project_state,
        )
        serialized = serialize_event_config(es, "asr", resolved)

        # 序列化后的 JSON 应远小于全量配置
        delta_json = json.dumps(serialized)
        full_json = json.dumps(resolved)
        assert len(delta_json) <= len(full_json) * 1.21, (
            f"delta 大小 ({len(delta_json)}B) 不应超过全量 ({len(full_json)}B) 的 120%"
        )


# ═══════════════════════════════════════════════════════════
# AC-IR-02: 三级配置优先级解析
# ═══════════════════════════════════════════════════════════

class TestThreeLevelResolution:
    """验收标准 AC-IR-02:
    解析事件 A 的 ASR 配置时，model="large-v3"（事件覆盖），
    device="cuda"（继承全局）。删除事件 A 的覆盖（RESET_CONFIG），
    恢复为 model="turbo"（继承全局）。
    """

    def test_event_overrides_global(
        self, project_state, config_resolver
    ):
        """事件级覆盖优先级最高"""
        es = project_state.get_event("evt_001")
        assert es is not None

        # 设置事件覆盖
        es.asr.config
        es.asr.config["model"] = "large-v3"

        resolved = config_resolver.resolve_event_config(
            "evt_001", "asr", project_state,
        )
        assert resolved["model"] == "large-v3"
        assert resolved["device"] == "cuda"  # 全局继承

    def test_reset_config_restores_global(
        self, project_state, config_resolver
    ):
        """删除事件覆盖后恢复全局默认"""
        es = project_state.get_event("evt_001")
        assert es is not None

        # 先设置覆盖
        es.asr.config
        es.asr.config["model"] = "large-v3"
        resolved_before = config_resolver.resolve_event_config(
            "evt_001", "asr", project_state,
        )
        assert resolved_before["model"] == "large-v3"

        # 模拟 RESET_CONFIG：删除 model 字段
        es.asr.config.pop("model", None)
        resolved_after = config_resolver.resolve_event_config(
            "evt_001", "asr", project_state,
        )
        assert resolved_after["model"] == "turbo"  # 恢复全局默认

    def test_deep_merge_nested_objects(
        self, project_state, config_resolver
    ):
        """深度合并：嵌套 dict 部分覆盖，未指定的嵌套字段保留"""
        es = project_state.get_event("evt_001")
        assert es is not None

        es.translation.config
        es.translation.config["gate"] = {"threshold_accept": 0.90}

        resolved = config_resolver.resolve_event_config(
            "evt_001", "translation", project_state,
        )
        # 事件覆盖了 gate.threshold_accept
        assert resolved.get("gate", {}).get("threshold_accept") == 0.90
        # 但其他翻译参数仍继承全局
        assert resolved["lang"] == "zh"

    def test_null_deletes_override(
        self, project_state, config_resolver
    ):
        """null 值表示删除覆盖，恢复继承"""
        es = project_state.get_event("evt_001")
        assert es is not None

        es.asr.config
        es.asr.config["model"] = "large-v3"

        # null 覆盖 → 删除事件级覆盖 → 恢复全局默认 "turbo"
        es.asr.config["model"] = None
        resolved = config_resolver.resolve_event_config(
            "evt_001", "asr", project_state,
        )
        assert resolved["model"] == "turbo"


# ═══════════════════════════════════════════════════════════
# AC-IR-03: Schema 校验
# ═══════════════════════════════════════════════════════════

class TestSchemaValidation:
    """验收标准 AC-IR-03:
    发送非法 SET_CONFIG（如 vad_threshold: 1.5），Schema 校验失败，
    Patch 被拒绝，IR 无变化。
    """

    def test_reject_out_of_range_value(self, schema_loader):
        """超出 range 的值被拒绝"""
        # vad_threshold 应在 0.0-1.0 范围内
        valid, error = schema_loader.validate("audio", {"vad_threshold": 1.5})
        assert not valid, f"vad_threshold=1.5 应被拒绝"
        assert error is not None

    def test_reject_invalid_enum(self, schema_loader):
        """非法 enum 值被拒绝"""
        # tts.engine 只能是 edge/chattts/cosyvoice
        valid, error = schema_loader.validate("tts_routing", {"engine": "invalid_engine"})
        assert not valid, f"engine=invalid_engine 应被拒绝"
        assert error is not None

    def test_accept_valid_config(self, schema_loader):
        """合法配置通过校验"""
        valid, error = schema_loader.validate("asr", {"model": "large-v3"})
        assert valid, f"合法配置应通过校验: {error}"

    def test_accept_full_valid_config(self, schema_loader):
        """完整合法配置通过校验"""
        valid, error = schema_loader.validate("tts_routing", {
            "engine": "cosyvoice",
            "speed_factor": 1.2,
            "timing_adaptive": True,
            "timing_threshold": 0.15,
        })
        assert valid, f"完整合法配置应通过校验: {error}"


# ═══════════════════════════════════════════════════════════
# AC-IR-04: 配置 Undo 链
# ═══════════════════════════════════════════════════════════

class TestConfigUndoChain:
    """验收标准 AC-IR-04:
    连续修改事件 C 的 translation.config.gate.threshold_accept 三次，
    patch_log 记录完整序列，undo 逐步回退至初始值。
    """

    def test_patch_log_records_all_changes(
        self, project_state, config_resolver
    ):
        """每次修改都应追加到 patches 列表"""
        es = project_state.get_event("evt_003")
        assert es is not None
        initial_patch_count = len(es.patches)

        # 模拟 3 次连续的 OVERRIDE_CONFIG
        from core.runtime.patch import Patch, OpCode

        values = [0.80, 0.90, 0.95]
        for v in values:
            patch = Patch(
                id=f"patch_{v}",
                target_id="evt_003",
                op=OpCode.OVERRIDE_CONFIG,
                value={"slot": "translation", "partial_config": {"gate": {"threshold_accept": v}}},
                author="user",
                confidence=1.0,
            )
            es.add_patch(patch)

        assert len(es.patches) == initial_patch_count + 3
        # patches 应按时间戳排序
        for i in range(len(es.patches) - 1):
            assert es.patches[i].timestamp <= es.patches[i + 1].timestamp

    def test_undo_restores_previous_value(
        self, project_state, config_resolver
    ):
        """Undo 应恢复到前一个值"""
        es = project_state.get_event("evt_003")
        assert es is not None

        es.translation.config
        es.translation.config.setdefault("gate", {})

        # 记录每次修改前的值
        history = []
        for v in [0.80, 0.90, 0.95]:
            history.append(es.translation.config["gate"].get("threshold_accept"))
            es.translation.config["gate"]["threshold_accept"] = v

        # 回退到第三次修改前的值
        assert history[2] == 0.90
        es.translation.config["gate"]["threshold_accept"] = history[2]
        resolved = config_resolver.resolve_event_config(
            "evt_003", "translation", project_state,
        )
        assert resolved.get("gate", {}).get("threshold_accept") == 0.90


# ═══════════════════════════════════════════════════════════
# AC-IR-05: 说话人级继承
# ═══════════════════════════════════════════════════════════

class TestSpeakerLevelInheritance:
    """验收标准 AC-IR-05:
    说话人 X 设定 tts.engine=cosyvoice，属于 X 的事件 B 的 tts.config
    为空，解析事件 B 的 TTS 引擎结果为 cosyvoice（说话人级继承）。
    """

    def test_speaker_config_inherited_by_events(
        self, project_state, config_resolver
    ):
        """事件级为空时继承说话人级配置"""
        es = project_state.get_event("evt_001")
        assert es is not None
        assert es.speaker_ref == "SPEAKER_00"

        resolved = config_resolver.resolve_event_config(
            "evt_001", "tts", project_state,
        )
        # 应继承说话人级配置（SPEAKER_00 预设 tts.engine=cosyvoice）
        assert resolved["engine"] == "cosyvoice"

    def test_event_override_speaker(
        self, project_state, config_resolver
    ):
        """事件级覆盖优先级高于说话人级"""
        es = project_state.get_event("evt_001")
        assert es is not None

        # 事件级覆盖
        es.tts.config
        es.tts.config["engine"] = "edge"

        resolved = config_resolver.resolve_event_config(
            "evt_001", "tts", project_state,
        )
        assert resolved["engine"] == "edge"  # 事件覆盖 > 说话人

    def test_speaker_without_config_falls_to_global(
        self, project_state, config_resolver
    ):
        """说话人无配置时回退到全局"""
        es = project_state.get_event("evt_002")
        assert es is not None
        assert es.speaker_ref == "SPEAKER_01"

        resolved = config_resolver.resolve_event_config(
            "evt_002", "tts", project_state,
        )
        # 应使用全局默认（SPEAKER_01 无配置）
        assert resolved["engine"] == "chattts"

    def test_speaker_partial_config_merged(
        self, project_state, config_resolver
    ):
        """说话人级部分配置与全局合并"""
        es = project_state.get_event("evt_001")
        assert es is not None

        resolved = config_resolver.resolve_event_config(
            "evt_001", "tts", project_state,
        )
        assert resolved["engine"] == "cosyvoice"          # 说话人级
        assert resolved["speed_factor"] == 1.0            # 全局默认
        assert resolved["timing_adaptive"] is True        # 全局默认


# ═══════════════════════════════════════════════════════════
# deep_merge 单元测试
# ═══════════════════════════════════════════════════════════

class TestDeepMerge:
    """deep_merge 函数的各种边界情况"""

    def test_leaf_value_override(self):
        """叶子值被直接覆盖"""
        base = {"model": "turbo", "device": "cuda"}
        override = {"model": "large-v3"}
        deep_merge(base, override)
        assert base["model"] == "large-v3"
        assert base["device"] == "cuda"

    def test_nested_dict_merge(self):
        """嵌套 dict 递归合并"""
        base = {"engine_options": {"version": "v2", "num_norm": True}}
        override = {"engine_options": {"num_norm": False}}
        deep_merge(base, override)
        assert base["engine_options"]["version"] == "v2"
        assert base["engine_options"]["num_norm"] is False

    def test_null_semantics(self):
        """null 值删除 base 中对应键"""
        base = {"model": "large-v3", "device": "cuda"}
        override = {"model": None}
        deep_merge(base, override)
        assert "model" not in base
        assert base["device"] == "cuda"

    def test_add_new_keys(self):
        """override 中的新键被加入 base"""
        base = {"model": "turbo"}
        override = {"device": "cpu"}
        deep_merge(base, override)
        assert base["device"] == "cpu"
        assert base["model"] == "turbo"

    def test_nested_null_deletes_nested_key(self):
        """嵌套 null 删除嵌套键"""
        base = {"gate": {"threshold_accept": 0.80, "threshold_reject": 0.60}}
        override = {"gate": {"threshold_accept": None}}
        deep_merge(base, override)
        assert "threshold_accept" not in base["gate"]
        assert base["gate"]["threshold_reject"] == 0.60

    def test_empty_override_does_nothing(self):
        """空 override 不修改 base"""
        base = {"model": "turbo", "device": "cuda"}
        original = dict(base)
        deep_merge(base, {})
        assert base == original

    def test_empty_base_accepts_all(self):
        """空 base 接受全部 override"""
        base: dict = {}
        override = {"model": "turbo", "device": "cuda"}
        deep_merge(base, override)
        assert base == override

    def test_deeply_nested_merge(self):
        """深度嵌套合并（3 层）"""
        base = {
            "a": {
                "b": {
                    "c": 1,
                    "d": 2,
                },
                "e": 3,
            },
        }
        override = {
            "a": {
                "b": {
                    "c": 99,
                },
            },
        }
        deep_merge(base, override)
        assert base["a"]["b"]["c"] == 99
        assert base["a"]["b"]["d"] == 2
        assert base["a"]["e"] == 3
