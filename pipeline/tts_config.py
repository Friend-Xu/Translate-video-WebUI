"""
TTS 配置模块 — TTSConfig 数据类 + YAML 配置管理

提供 TTS 引擎、视频段变速、情感克隆等全部参数的集中配置。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Optional, List


@dataclass
class TTSConfig:
    """TTS 全局配置，所有参数经由此类统一管理。

    可通过 YAML 文件加载，也可以代码中直接构造。
    调用 `TTSConfig.from_yaml()` 加载配置，`TTSConfig.to_yaml()` 生成默认配置。
    """

    # ── TTS 引擎配置 ──────────────────────────────────────
    engine_type: str = "edge"
    """TTS 引擎类型: edge | chattts | coqui | azure"""

    voice: str = "zh-CN-XiaoxiaoNeural"
    """TTS 音色名称（EdgeTTS/Coqui 使用）"""

    base_speed: int = 30
    """TTS 基础语速: +30% (对应 edge-tts rate 参数, 实际值为 +30%)"""

    max_speed: int = 50
    """TTS 最大语速: +50% (降低此值可提升音质。超出此值不再加速，进入兜底逻辑)"""

    # ── ChatTTS 专用参数 ──────────────────────────────────
    chattts_speaker_seed: Optional[int] = None
    """ChatTTS 说话人种子。固定种子保持音色一致，None 为随机。"""

    chattts_model_source: str = "local"
    """ChatTTS 模型来源: local | huggingface | custom"""

    chattts_model_path: Optional[str] = None
    """ChatTTS 自定义模型路径（source=custom 时使用）"""

    # ── 速度策略 ────────────────────────────────────────
    speed_mode: str = "per_segment"
    """速度控制模式: "per_segment" | "global"

    - per_segment: 逐段精细调速。每条字幕独立决策 TTS rate 和视频速度，
      使用原版 compare_audio_time 算法，含 gap 借时、初始系数跳转。
    - global: 全局统一调速。预扫所有字幕 → 算整体 ratio → 统一 rate 生成。
      执行更快但精细度略低。
    """

    search_method: str = "linear"
    """TTS rate 搜索方式: "linear" | "binary"

    - linear: 从初始系数逐次 +1%，与原版一致
    - binary: 二分搜索，减少 API 调用次数
    """

    # ── 视频段变速调节参数（核心功能） ────────────────────
    speed_tolerance: float = 0.15
    """视频段变速容忍度。

    两级决策逻辑:
    - 若 TTS时长 / 视频时长 在 [1 - tolerance, 1 + tolerance] 内:
      → 优先微调视频速度（视觉影响小，省一次 TTS 网络请求）
    - 若超出此范围:
      → 启用 TTS 语速调速（EdgeTTS rate 参数）
    """

    video_speed_min: float = 0.75
    """视频最低加速因子（<1=减速，>1=加速）。默认 0.75 = 最多减速到原速 75%。"""

    video_speed_max: float = 1.25
    """视频最高加速因子。默认 1.25 = 最多加速 25%。"""

    search_step: int = 1
    """linear 模式搜索步长百分比。原版为 1，可适当提高减少循环次数。"""

    # ── 情感克隆（预留） ────────────────────────────────────
    enable_emotion: bool = False
    """是否启用情感克隆（预留，默认为 False）"""

    emotion_engine: str = ""
    """情感克隆引擎标识，如 emotion_clone_v1"""

    emotion_ref_audio: Optional[str] = None
    """情感参考音频路径（参考音频式情感克隆时使用）"""

    default_emotion: str = "neutral"
    """默认情感标签（参数式情感克隆的 fallback）"""

    # ── 并发 ──────────────────────────────────────────────
    threading_workers: int = 7
    """工作线程数"""

    # ── 声音克隆（OpenVoice） ──────────────────────────────
    enable_openvoice: bool = False
    """是否启用 OpenVoice 声音克隆"""

    voice_clone_sample: Optional[str] = None
    """声音克隆参考音频路径。为 None 时自动从视频目录查找 Vocals.wav"""

    openvoice_model_version: str = "v2"
    """OpenVoice 模型版本: v1 或 v2"""

    # ── 字幕 ──────────────────────────────────────────────
    enable_caption: bool = True
    """是否为输出视频叠加字幕"""

    caption_font: str = "./models/font/Minecraft_font/5_Minecraft_AE_zh_en.ttf"
    """字幕字体文件路径"""

    caption_font_size: int = 0
    """字幕字号（像素），0 表示根据视频宽度自动计算"""

    caption_stroke_width: float = 0.0
    """字幕描边宽度，0.0 表示使用默认值"""

    # ── 断点续传 ──────────────────────────────────────────
    enable_resume: bool = True
    """是否启用断点续传"""

    resume_file: str = "file/wav_path.txt"
    """断点续传进度记录文件"""

    # ── 输出路径 ──────────────────────────────────────────
    output_dir: str = "file/EdgeTTS_Audio_file"
    """TTS 音频输出目录（临时）"""

    video_output_dir: str = "file/Video_file"
    """视频段输出目录"""

    # ── 视频合并 ──────────────────────────────────────────
    enable_merge: bool = True
    """TtsPipeline.run() 完成后是否合并视频段为完整视频"""

    merge_strategy: str = "ffmpeg"
    """合并策略: "ffmpeg" | "moviepy"（ffmpeg 更快，推荐）"""

    final_output_path: str = "output/final_video.mp4"
    """最终合并输出路径"""

    # ── 编码参数（保留原值） ─────────────────────────────
    audio_codec: str = "aac"
    """音频编码器"""

    audio_bitrate: str = "192k"
    """音频比特率"""

    video_codec: str = "libx264"
    """视频编码器（需要 GPU 支持）"""

    video_preset: str = "medium"
    """视频编码 preset。硬件编码器需要对应值（如 AMF: balanced, nvenc: p4）
    GPU 自动检测时会根据编码器类型调整此值。"""

    video_audio_codec: str = "aac"
    """视频音频编码器"""

    video_bitrate: str = "5M"
    """视频比特率。1080p 推荐 '5M' (5 Mbps)，720p 可用 '3M'"""

    write_logger: Optional[str] = None
    """moviepy write_videofile logger 参数，默认 None 表示无日志"""

    # ── ImageMagick（字幕渲染需要） ─────────────────────
    imagemagick_binary: str = r"F:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"
    """ImageMagick 可执行文件路径（字幕渲染依赖）"""

    # ── 模型路径 ──────────────────────────────────────────
    openvoice_v1_dir: str = "./models/openvoice_v1"
    """OpenVoice V1 模型目录"""

    openvoice_v2_dir: str = "./models/openvoice_v2"
    """OpenVoice V2 模型目录"""

    def __post_init__(self) -> None:
        """校验参数合法性"""
        if self.engine_type not in ("edge", "chattts", "coqui", "azure"):
            raise ValueError(f"不支持的 TTS 引擎类型: {self.engine_type}")
        if self.speed_mode not in ("per_segment", "global"):
            raise ValueError(f"不支持的 speed_mode: {self.speed_mode}，仅支持 per_segment/global")
        if self.search_method not in ("linear", "binary"):
            raise ValueError(f"不支持的 search_method: {self.search_method}，仅支持 linear/binary")
        if not 0 <= self.speed_tolerance < 1.0:
            raise ValueError(f"speed_tolerance 应在 [0, 1) 范围内，当前: {self.speed_tolerance}")
        if self.threading_workers < 1:
            raise ValueError(f"threading_workers 不能小于 1，当前: {self.threading_workers}")
        if self.merge_strategy not in ("ffmpeg", "moviepy"):
            raise ValueError(f"不支持的合并策略: {self.merge_strategy}，仅支持 ffmpeg/moviepy")
        if not 0 < self.video_speed_min <= 2.0:
            raise ValueError(f"video_speed_min 应在 (0, 2] 范围内，当前: {self.video_speed_min}")
        if not 0 < self.video_speed_max <= 2.0:
            raise ValueError(f"video_speed_max 应在 (0, 2] 范围内，当前: {self.video_speed_max}")

    @classmethod
    def from_yaml(cls, path: str) -> "TTSConfig":
        """从 YAML 文件加载配置。

        Args:
            path: YAML 文件路径

        Returns:
            TTSConfig 实例

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: YAML 格式错误或参数不合法
        """
        import yaml

        if not os.path.exists(path):
            raise FileNotFoundError(f"配置文件不存在: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data is None:
            data = {}

        tts_data = data.get("tts", data)
        return cls(**tts_data)

    def to_yaml(self, path: Optional[str] = None) -> Optional[str]:
        """将当前配置导出为 YAML 格式。

        Args:
            path: 输出路径。为 None 时返回 YAML 字符串。

        Returns:
            若 path 为 None，返回 YAML 字符串。
            若 path 指定，写入文件后返回 None。
        """
        import yaml

        data = {"tts": asdict(self)}
        yaml_str = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)

        if path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(yaml_str)
            return None

        return yaml_str

    def to_old_params(self) -> dict:
        """将配置映射为旧 `SrtTxtToAudio` 类的构造参数。

        用于兼容层，无需手动参数映射。

        Returns:
            可解包到旧构造函数的 dict
        """
        return {
            "threading_workers": self.threading_workers,
            "clone_color": self.enable_openvoice,
            "speed_max": self.max_speed // 10,
            "edgeTTS_vocal": self.voice,
            "base_speed": self.base_speed // 10,
            "caption": self.enable_caption,
            "voice": self.voice_clone_sample,
        }


def _fix_corrupted_timestamps(subs: list) -> None:
    """修正 SRT 时间戳错误。

    Json_Convert_Srt 偶发 bug：末尾字幕 start 回退到 0ms，
    导致 sub[n].start << sub[n-1].end，整条字幕时空错乱。
    """
    if not subs:
        return
    for i in range(1, len(subs)):
        s, e, t = subs[i]
        prev_s, prev_e, _ = subs[i - 1]
        # 检测：当前 sub 起始远小于前一条结束（如 start=0ms 但上一条在 35s）
        if s < prev_e and s < 1000:
            import warnings
            warnings.warn(f"SRT 时间戳异常: sub[{i}] start={s}ms < sub[{i-1}] end={prev_e}ms → 自动修正为 {prev_e + 1}")
            subs[i] = (prev_e + 1, e, t)


def parse_srt(path: str) -> list[tuple[int, int, str]]:
    """解析 SRT 字幕文件为结构化列表。

    自动修正反转的时间戳（start > end 时交换）、过滤零时长条目。

    Args:
        path: SRT 文件路径

    Returns:
        [(start_ms, end_ms, text), ...]
    """
    import re

    subs = []
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    for block in re.split(r"\n\s*\n", content):
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        m = re.match(
            r"(\d+):(\d+):(\d+)[,.]?(\d*)\s*-->>?\s*(\d+):(\d+):(\d+)[,.]?(\d*)",
            lines[1],
        )
        if not m:
            continue
        h1, m1, s1, ms1 = int(m[1]), int(m[2]), int(m[3]), m[4] or "0"
        h2, m2, s2, ms2 = int(m[5]), int(m[6]), int(m[7]), m[8] or "0"
        # 兼容 comma(,) 和 dot(.) 两种毫秒分隔符
        ms1 = int(ms1.ljust(3, "0")[:3])
        ms2 = int(ms2.ljust(3, "0")[:3])
        start = h1 * 3600000 + m1 * 60000 + s1 * 1000 + ms1
        end = h2 * 3600000 + m2 * 60000 + s2 * 1000 + ms2

        # 自动修正反转时间戳
        if start > end:
            import warnings
            warnings.warn(f"SRT 时间戳反转: {lines[1]} → 自动交换")
            start, end = end, start

        # 过滤零时长条目
        if start == end:
            continue

        text = "\n".join(lines[2:])
        subs.append((start, end, text))

    # 后处理：修正 SRT 时间戳错误（如 sub 索引回零导致 start=0ms）
    # Json_Convert_Srt 偶发 bug：末尾字幕 start 回退到 0ms
    _fix_corrupted_timestamps(subs)

    return subs


def create_default_config(path: str = "config/tts.yaml") -> TTSConfig:
    """创建默认配置并写入 YAML 文件。

    Args:
        path: 输出路径

    Returns:
        TTSConfig 实例
    """
    cfg = TTSConfig()
    cfg.to_yaml(path)
    return cfg
