"""
DurationController — TTS 时长硬约束控制 (Chapter 5 §5.5)

三级策略:
  Level 1 — 预检通过: deviation ≤ tolerance → "accept"
  Level 2 — 语速调整: tolerance < deviation ≤ 30% → "stretch"
  Level 3 — 分段重生成: deviation > 30% → "split"

SpeedDecision — 调速决策的 IR 载体，作为 VideoExportPass 的唯一真相源。
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class SpeedDecision:
    """调速决策结果 — 写入 es.tts.speed_decision。

    由各引擎 Composite Pass 在 TTS 阶段填充，
    VideoExportPass 只读不写。
    """
    strategy: str = "accept"
    """最终策略: "accept" | "rubberband_stretch" | "video_slowdown" """

    # 时长
    original_duration: float = 0.0
    """TTS 引擎原始输出时长 (秒)"""
    final_duration: float = 0.0
    """优化后最终时长 (strategy=accept 时等于 original)"""

    # 搜索过程元数据
    search_method: str = "none"
    """搜索方式: "binary" | "oneshot" | "none" """
    search_iterations: int = 0
    search_reached_limit: bool = False

    # 应用的操作
    tts_rate: str = "+0%"
    """Edge TTS 使用的最终 rate 参数"""
    stretch_ratio: float = 1.0
    """RubberBand 实际应用的 rate (>1=加速, 1.0=未拉伸)"""
    video_speed_factor: float = 1.0
    """视频变速因子 (1.0=不变速, <1=减速)"""

    # 质量指标
    deviation: float = 0.0
    """最终偏差 = |final_duration - target| / target"""
    deviation_before: float = 0.0
    """优化前偏差"""

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "original_duration": round(self.original_duration, 3),
            "final_duration": round(self.final_duration, 3),
            "search_method": self.search_method,
            "search_iterations": self.search_iterations,
            "search_reached_limit": self.search_reached_limit,
            "tts_rate": self.tts_rate,
            "stretch_ratio": round(self.stretch_ratio, 4),
            "video_speed_factor": round(self.video_speed_factor, 4),
            "deviation": round(self.deviation, 4),
            "deviation_before": round(self.deviation_before, 4),
        }


class DurationController:
    """TTS 时长硬约束控制器。"""

    LEVEL2_FACTOR = 0.3
    MAX_STRETCH = 2.0
    MIN_STRETCH = 0.5
    CHARS_PER_SECOND = 5.0

    def check(self, actual_duration: float, target_duration: float,
              tolerance: float = 0.15) -> str:
        """判定时长处理策略: "accept" | "stretch" | "split" """
        if target_duration <= 0:
            return "accept"
        deviation = abs(actual_duration - target_duration) / target_duration
        if deviation <= tolerance:
            return "accept"
        if deviation <= self.LEVEL2_FACTOR:
            ratio = target_duration / actual_duration
            if self.MIN_STRETCH <= ratio <= self.MAX_STRETCH:
                return "stretch"
        return "split"

    def compute_stretch_ratio(self, actual: float, target: float) -> float:
        """计算 RubberBand 拉伸比，限制在 [0.5, 2.0]。

        rate > 1 = 加速缩短, rate < 1 = 减速拉长。
        """
        if actual <= 0:
            return 1.0
        ratio = actual / target
        return max(self.MIN_STRETCH, min(self.MAX_STRETCH, ratio))

    # ── 完整调速决策 (IR 载体) ────────────────────────────

    def decide_speed(self, actual: float, target: float,
                     tolerance: float = 0.15,
                     engine_has_native_rate: bool = False,
                     video_speed_min: float = 0.60) -> SpeedDecision:
        """计算完整调速决策 — 各引擎 Composite Pass 调用此方法填充 IR。

        Args:
            actual: TTS 实际输出时长 (秒)
            target: 目标时长 = segment.end - segment.start (秒)
            tolerance: 可接受偏差比例
            engine_has_native_rate: True 时跳过 RubberBand 级别
            video_speed_min: 视频减速下限

        Returns:
            SpeedDecision — 写入 es.tts.speed_decision
        """
        sd = SpeedDecision(
            original_duration=actual,
            final_duration=actual,
        )

        if target <= 0:
            return sd

        sd.deviation_before = abs(actual - target) / target

        # Level 1: accept — within tolerance OR TTS is shorter than target (fits naturally)
        if sd.deviation_before <= tolerance or actual <= target:
            sd.deviation = sd.deviation_before
            return sd

        # TTS is longer than target — need to shorten or slow video
        # Level 2: RubberBand stretch (only for engines without native rate)
        if not engine_has_native_rate:
            stretch_ratio = self.compute_stretch_ratio(actual, target)
            if stretch_ratio != 1.0:
                sd.strategy = "rubberband_stretch"
                sd.stretch_ratio = stretch_ratio
                sd.search_method = "oneshot"
                sd.search_iterations = 1
                sd.final_duration = actual / stretch_ratio
                sd.deviation = abs(sd.final_duration - target) / target
                if sd.deviation <= tolerance:
                    return sd

        # Level 3: video slowdown (only when TTS still too long after stretch/retry)
        sd.strategy = "video_slowdown"
        effective_dur = sd.final_duration  # use stretched duration if any
        sd.video_speed_factor = max(video_speed_min, target / effective_dur)
        sd.deviation = abs(effective_dur * sd.video_speed_factor - target) / target
        sd.search_reached_limit = True
        return sd

    @staticmethod
    def apply_rubberband(wav_path: str, stretch_ratio: float) -> str:
        """对 WAV 文件执行 RubberBand 拉伸，原地修改。

        Args:
            wav_path: WAV 文件路径
            stretch_ratio: >1 = 加速缩短, <1 = 减速拉长

        Returns:
            wav_path (与输入相同路径，文件内容已被拉伸覆盖)
        """
        import os
        import tempfile
        from pipeline.audio_stretch import stretch_audio

        tmp = wav_path + ".rb_tmp.wav"
        try:
            stretch_audio(wav_path, tmp, stretch_ratio)
            os.replace(tmp, wav_path)
        finally:
            if os.path.isfile(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        return wav_path

    def suggest_split(self, text: str, target_duration: float) -> list[str]:
        """将过长文本按标点拆分为多个子句。"""
        if not text or target_duration <= 0:
            return [text] if text else []

        max_chars = int(target_duration * self.CHARS_PER_SECOND)
        if max_chars <= 0 or len(text) <= max_chars:
            return [text]

        parts = []
        current = ""
        for ch in text:
            current += ch
            if ch in "。！？.!?,;；：:" and len(current) >= max_chars * 0.5:
                parts.append(current.strip())
                current = ""
        if current.strip():
            parts.append(current.strip())
        return parts if parts else [text]


def duration_fit_score(actual: float, target: float) -> float:
    """时长匹配度评分。deviation 50% 以上得 0。"""
    if target <= 0:
        return 1.0
    deviation = abs(actual - target) / target
    return round(max(0.0, 1.0 - deviation / 0.5), 4)
