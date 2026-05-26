"""
Timeline 引擎配置 — 统一配置入口

支持从 config/timeline.yaml 加载（可选），文件不存在或格式错误时静默回退默认值。
"""

from __future__ import annotations
from dataclasses import dataclass
import logging
import os

logger = logging.getLogger("timeline.config")

DEFAULT_CONFIG = {
    "MIN_CONFIDENCE": 0.7,
    "MAX_GAP_SECONDS": 1.0,
    "MERGE_SAME_SPEAKER_THRESHOLD": 0.8,
    "SPLIT_SILENCE_THRESHOLD": 2.0,
}


@dataclass
class TimelineConfig:
    """Timeline 引擎配置 — 可从 YAML 文件加载覆盖默认值"""

    MIN_CONFIDENCE: float = 0.7
    MAX_GAP_SECONDS: float = 1.0
    MERGE_SAME_SPEAKER_THRESHOLD: float = 0.8
    SPLIT_SILENCE_THRESHOLD: float = 2.0

    @classmethod
    def load(cls, config_path: str | None = None) -> "TimelineConfig":
        """从 YAML 文件加载配置，文件不存在或格式错误时返回默认配置。"""
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "config", "timeline.yaml",
            )

        if not os.path.isfile(config_path):
            logger.debug("配置文件不存在，使用默认值: %s", config_path)
            return cls()

        try:
            import yaml
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                logger.warning("配置文件格式错误 (非 dict)，使用默认值")
                return cls()
            return cls(**{k: data[k] for k in DEFAULT_CONFIG if k in data})
        except Exception as e:
            logger.warning("加载配置文件失败 (%s)，使用默认值: %s", e, config_path)
            return cls()

    @classmethod
    def get(cls, key: str, default=None):
        """获取单个配置项的值"""
        return getattr(cls(), key, default)
