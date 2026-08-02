"""
GlobalConfig — 全局配置数据模型 (定稿 §1.4, §1.6)

三层配置体系:
  ProjectPolicy — 项目级默认配置 (What)
  EnginePolicy  — 引擎能力默认值 (How)
  GlobalConfig  — 顶层容器

所有字段均提供合理默认值，确保新用户零配置即可跑通完整流水线。
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ProjectPolicy:
    """项目级默认配置 — 用户可逐项覆盖的全局参数。

    所有槽位的默认值集中于此。新项目创建时从 project_config.yaml
    加载，未指定的字段使用类默认值。
    """
    audio: dict = field(default_factory=lambda: {
        "skip_demucs": False,
        "vad_threshold": 0.5,
        "silence_handling": {"policy": "keep"},
        "loudness_compensation": True,
        "target_loudness": -23.0,
        "high_pass_filter": False,
        "demucs_model": "htdemucs",
    })

    asr: dict = field(default_factory=lambda: {
        "model": "turbo",
        "device": "cuda",
        "compute_type": "float16",
        "language": "auto",
        "alignment_enabled": True,
        "num_workers": 1,
        "beam_size": 5,
        "word_timestamps": True,
    })

    speaker: dict = field(default_factory=lambda: {
        "clustering_threshold": 0.65,
        "min_speakers": None,
        "max_speakers": None,
        "clustering_method": "agglomerative",
        "gender": "auto",
        "embedding_model": "pyannote/embedding",
        "min_segment_duration": 0.5,
        "merge_similar_speakers_threshold": 0.85,
    })

    translation: dict = field(default_factory=lambda: {
        "lang": "zh",
        "backend": "deepseek",
        "glossary": {"mode": "OFF"},
        "custom_prompt": "",
        "gate": {
            "mode": "xcomet",
            "threshold_accept": 0.86,
            "threshold_reject": 0.64,
            "beta": 0.6,
            "gamma": 0.4,
            "sim_drop_limit": 0.05,
        },
    })

    tts: dict = field(default_factory=lambda: {
        "engine": "chattts",
        "voice_gender": "auto",
        "speed_factor": 1.0,
        "timing_adaptive": True,
        "timing_threshold": 0.15,
        "max_speed_adjustment": 1.0,
        "fallback_chain": ["cosyvoice", "chattts", "edge"],
        "auto_switch_on_low_quality": False,
        "quality_threshold": 0.60,
    })

    emotion: dict = field(default_factory=lambda: {
        "enabled": True,
        "audio_model": "iic/emotion2vec_plus_large",
        "audio_context_window": 3,
        "energy_normalize": True,
        "text_model": "distiluse",
        "text_label_mapping": "ekman",
        "text_confidence_threshold": 0.5,
        "text_emotion_injection": True,
        "fusion_strategy": "weighted_average",
        "audio_weight": 0.7,
        "text_weight": 0.3,
        "fallback_threshold": 0.4,
        "gate": {
            "mode": "strict",
            "max_break": 1.5,
            "min_confidence": 0.3,
            "max_conflict": 1.0,
        },
        "scorer": {
            "weights": {
                "consistency": 0.30,
                "intensity": 0.25,
                "speaker_fit": 0.25,
                "translation_alignment": 0.20,
            },
            "accept_threshold": 0.60,
        },
    })

    review: dict = field(default_factory=lambda: {
        "force_accept": False,
        "notes": "",
    })

    def apply_slot_overrides(self, overrides: dict) -> None:
        """槽位级覆盖 (P2): overrides = {slot: {field: value}}。

        与 ConfigResolver 的 deep_merge 语义一致: 嵌套 dict 递归合并,
        未知槽位/字段直接写入 (引擎专属参数由 SchemaLoader 负责校验)。
        这是前端全局设置进入 core 配置体系的唯一正门。
        """
        from core.runtime.config_resolver import deep_merge
        for slot, fields in overrides.items():
            if not isinstance(fields, dict):
                continue
            target = getattr(self, slot, None)
            if isinstance(target, dict):
                deep_merge(target, fields)

    def get_slot_defaults(self, slot: str) -> dict:
        """获取指定槽位的全局默认配置（深拷贝）。"""
        from copy import deepcopy
        slot_config = getattr(self, slot, {})
        return deepcopy(slot_config) if slot_config else {}


@dataclass
class EnginePolicy:
    """引擎能力默认值 — 基于运行时环境自动推导。

    这些值由 gpu_detect.py 自动检测，用户也可手动覆盖。
    """
    device: str = "cuda"
    compute_type: str = "float16"
    num_workers: int = 1
    # CosyVoice 专属
    cosyvoice_device: str = "cuda"
    cosyvoice_fp16: bool = True
    # ChatTTS 专属
    chattts_vram_mode: str = "auto"
    chattts_vram_limit_mb: int = 0
    # 并发控制
    max_concurrent_tts: int = 2
    max_concurrent_translation: int = 3


@dataclass
class GlobalConfig:
    """全局配置顶层容器。

    用法:
        config = GlobalConfig()                            # 全部默认值
        config = GlobalConfig.load("project_config.yaml")  # 从文件加载
        resolved = config.get_slot_defaults("asr")         # 获取某槽位全局默认
    """
    project: ProjectPolicy = field(default_factory=ProjectPolicy)
    engine: EnginePolicy = field(default_factory=EnginePolicy)

    def get_slot_defaults(self, slot: str) -> dict:
        """获取指定槽位的全局默认配置（深拷贝）。"""
        return self.project.get_slot_defaults(slot)

    def apply_slot_overrides(self, overrides: dict) -> None:
        """槽位级覆盖入口 — 转发到 ProjectPolicy (P2 前端设置桥)。"""
        self.project.apply_slot_overrides(overrides)

    @classmethod
    def load(cls, path: str) -> "GlobalConfig":
        """从 YAML 文件加载配置，未指定的字段使用默认值。"""
        import os
        import yaml

        config = cls()
        if not os.path.exists(path):
            return config

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        if "project" in data:
            for slot, overrides in data["project"].items():
                if hasattr(config.project, slot) and isinstance(overrides, dict):
                    target = getattr(config.project, slot)
                    _deep_update(target, overrides)

        if "engine" in data:
            for key, value in data["engine"].items():
                if hasattr(config.engine, key):
                    setattr(config.engine, key, value)

        return config

    @classmethod
    def from_legacy_yaml(
        cls,
        translate_cfg_path: str = "",
        tts_cfg_path: str = "",
    ) -> "GlobalConfig":
        """从旧格式 YAML 构建 GlobalConfig。(批次03 §四)

        读取旧 config/translate.yaml（顶层键 "translate"）和
        config/tts.yaml（顶层键 "tts"），映射到 ProjectPolicy 嵌套结构。
        不读取 api_key 等凭证字段——它们属于运行时环境变量。
        """
        import os
        import yaml

        config = cls()

        if translate_cfg_path and os.path.exists(translate_cfg_path):
            with open(translate_cfg_path, "r", encoding="utf-8") as f:
                translate_data = yaml.safe_load(f) or {}
            translate_cfg = translate_data.get("translate", {})
            target = config.project.translation
            if isinstance(translate_cfg, dict):
                _map_leaf(translate_cfg, target, {
                    "model": "backend_model",
                    "target_lang": "lang",
                })
                gate_cfg = target.setdefault("gate", {})
                _map_leaf(translate_cfg, gate_cfg, {
                    "verification_mode": "mode",
                    "semantic_threshold": "threshold_accept",
                    "sim_drop_limit": "sim_drop_limit",
                })
                # 显式 gate 段 (threshold_accept/reject 等) 直接映射,
                # 覆盖 legacy semantic_threshold 映射 — translate.yaml 的
                # semantic_threshold 仍保留给 logic_gate 语义检查使用
                explicit_gate = translate_cfg.get("gate")
                if isinstance(explicit_gate, dict):
                    _map_leaf(explicit_gate, gate_cfg, {
                        "mode": "mode",
                        "threshold_accept": "threshold_accept",
                        "threshold_reject": "threshold_reject",
                        "beta": "beta",
                        "gamma": "gamma",
                        "sim_drop_limit": "sim_drop_limit",
                    })

        if tts_cfg_path and os.path.exists(tts_cfg_path):
            with open(tts_cfg_path, "r", encoding="utf-8") as f:
                tts_data = yaml.safe_load(f) or {}
            tts_cfg = tts_data.get("tts", {})
            target = config.project.tts
            if isinstance(tts_cfg, dict):
                _map_leaf(tts_cfg, target, {
                    "engine_type": "engine",
                    "fallback_chain": "fallback_chain",
                })

        return config

    def save(self, path: str) -> None:
        """保存当前配置到 YAML 文件。"""
        import os
        import yaml

        data = {
            "project": {
                slot: getattr(self.project, slot)
                for slot in ["audio", "asr", "speaker", "translation", "tts", "emotion", "review"]
            },
            "engine": {
                "device": self.engine.device,
                "compute_type": self.engine.compute_type,
                "num_workers": self.engine.num_workers,
                "max_concurrent_tts": self.engine.max_concurrent_tts,
            },
        }

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)


def _deep_update(target: dict, source: dict) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


def _map_leaf(
    source: dict, target: dict, mapping: dict[str, str],
) -> None:
    """将 source 中键按 mapping 映射写入 target（仅当源键存在时）。"""
    for src_key, dst_key in mapping.items():
        if src_key in source:
            target[dst_key] = source[src_key]
