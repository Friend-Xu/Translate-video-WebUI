"""
VideoExportPass — 复用旧管线 VideoSegmenter + VideoMerger

调速策略 (slow_down_video_to_file):
  TTS 时长 ≈ 视频段时长 → 视频不变速
  TTS 时长 > 视频段时长 → 减速视频 (speed_factor < 1)
  TTS 时长 < 视频段时长 → 视频正常播放，TTS 音频自然结束
"""
from __future__ import annotations
import os
from core.engine.pass_base import TimelinePass
from core.runtime import TimelineProjectState


class VideoExportPass(TimelinePass):
    """TTS 音频 → 视频段 → ffmpeg 合并 → 成品视频"""

    name = "video_export"
    depends_on: list[str] = []

    def __init__(self, video_path: str = "", output_dir: str = "",
                 workspace_dir: str = "", caption: bool = False,
                 caption_config: dict | None = None):
        self.video_path = video_path
        self.output_dir = output_dir or ""
        self.workspace_dir = workspace_dir or ""
        self.caption = caption
        self.caption_config = caption_config or {}

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        events = state.sorted_events()
        tasks = []
        for es in events:
            # audio_ref 由 UPDATE_TTS_AUDIO 写入 tts slot (Phase 3b)
            audio_ref = es.tts.audio_ref
            if not audio_ref:
                continue
            audio_path = os.path.join(self.workspace_dir, audio_ref) if not os.path.isabs(audio_ref) else audio_ref
            if not os.path.isfile(audio_path):
                continue
            start_ms = int(es.start * 1000)
            end_ms = int(es.end * 1000)
            # translation 是 dict (Phase 3a/3b 统一), 正确取 text, 不再把 dict 当字符串
            trans = es.translation
            text = (trans.get("text", "") if isinstance(trans, dict) else str(trans or "")) or es.ir.text_ref
            tasks.append({
                "start": start_ms,
                "end": end_ms,
                "text": text,
                "audio_path": audio_path,
                "speed_decision": es.tts.speed_decision,
            })
        if not tasks:
            return state

        # 对齐旧管线目录: video → 05_tts/video/, final → 06_export/dubbed.mp4
        video_dir = os.path.join(self.output_dir, "05_tts", "video")
        export_dir = os.path.join(self.output_dir, "06_export")
        output_path = os.path.join(export_dir, "dubbed.mp4")
        os.makedirs(video_dir, exist_ok=True)
        os.makedirs(export_dir, exist_ok=True)

        from pipeline.tts_video import VideoSegmenter
        from moviepy import VideoFileClip, AudioFileClip

        # GPU 编码器自动检测 (复用 gpu_detect — legacy step_tts 独占, 桥入 core)
        video_codec = "libx264"
        video_preset: str | None = "medium"
        try:
            from pipeline.gpu_detect import detect_best_encoder, _ENCODER_PRESETS
            from pipeline.utils import get_ffmpeg_exe
            best = detect_best_encoder(get_ffmpeg_exe())
            if best:
                video_codec = best
                video_preset = _ENCODER_PRESETS.get(best, "medium")
        except Exception:
            pass  # GPU 检测失败回退 libx264 — 编码器不影响正确性, 只影响速度

        seg = VideoSegmenter(video_output_dir=video_dir,
                             caption=self.caption or bool(self.caption_config),
                             video_codec=video_codec,
                             video_preset=video_preset)

        # 读取 Demucs 分离的背景乐
        bgm_ref = state.get_global_bgm_ref()
        audio_instrumental = None
        if bgm_ref:
            bgm_path = os.path.join(self.workspace_dir, bgm_ref) if not os.path.isabs(bgm_ref) else bgm_ref
            if os.path.isfile(bgm_path):
                audio_instrumental = AudioFileClip(bgm_path)

        for i, task in enumerate(tasks):
            next_start = tasks[i + 1]["start"] if i + 1 < len(tasks) else task["end"]
            task["video_end"] = next_start

        video = VideoFileClip(self.video_path)

        # ── 字幕拆分优化 ──
        caption_groups_all = None
        if self.caption_config.get("enable_subtitle_optimization", True):
            try:
                from pipeline.tts_caption import CaptionRenderer
                from pipeline.subtitle_optimizer import optimize

                cap_cfg = self.caption_config
                renderer = CaptionRenderer(
                    font_path=cap_cfg.get("font", "./models/font/Minecraft_font/5_Minecraft_AE_zh_en.ttf"),
                    font_size=cap_cfg.get("font_size") or None,
                    font_color=cap_cfg.get("font_color", "white"),
                    stroke_color=cap_cfg.get("stroke_color", "black"),
                    stroke_width=cap_cfg.get("stroke_width", 0.5),
                    bg_color=cap_cfg.get("bg_color", (0, 0, 0, 128)),
                    max_lines=cap_cfg.get("max_lines", 2),
                    caption_width_ratio=cap_cfg.get("width_ratio", 0.85),
                    alignment=cap_cfg.get("alignment", "center"),
                    position=cap_cfg.get("position", "bottom"),
                    font_size_factor=cap_cfg.get("font_size_factor", 0.030),
                    font_size_mode=cap_cfg.get("font_size_mode", "adaptive"),
                    max_font_size=cap_cfg.get("max_font_size") or None,
                )

                subs_target = [(t["start"], t["end"], t["text"]) for t in tasks]
                subs_source = [(t["start"], t["end"], "") for t in tasks]

                caption_groups_all = optimize(subs_target, subs_source, renderer, video.w)
                total_caps = sum(len(g) for g in caption_groups_all)
                if total_caps > len(tasks):
                    from pipeline.logger import get_logger
                    get_logger(__name__).info(
                        f"字幕优化: {len(tasks)} → {total_caps} 段"
                    )
            except Exception:
                caption_groups_all = None

        for i, task in enumerate(tasks):
            tts_path = task["audio_path"]
            clip = video.subclipped(task["start"] / 1000, task["video_end"] / 1000)
            tts_audio = AudioFileClip(tts_path)
            sd = task.get("speed_decision", {})
            sf_override = sd.get("video_speed_factor") if sd.get("strategy") == "video_slowdown" else None
            cg = caption_groups_all[i] if caption_groups_all and i < len(caption_groups_all) else None
            try:
                seg.slow_down_video_to_file(
                    current_video=clip,
                    audio_instrumental=audio_instrumental,
                    tts_audio=tts_audio,
                    tts_audio_path=tts_path,
                    start=task["start"],
                    text=task["text"],
                    text_eng="",
                    end=task["end"],
                    caption_groups=cg,
                    speed_factor_override=sf_override,
                )
            finally:
                clip.close()
                tts_audio.close()
                # Windows: 确保 moviepy 内部 ffmpeg 进程释放文件句柄
                import time; time.sleep(0.05)

        video.close()
        if audio_instrumental is not None:
            audio_instrumental.close()

        from pipeline.video_merger import VideoMerger, MergerConfig
        merger = VideoMerger(MergerConfig(strategy="ffmpeg"))
        result = merger.merge(video_dir, output_path)
        if result and os.path.isfile(output_path):
            from pipeline.logger import get_logger
            logger = get_logger(__name__)
            sz = os.path.getsize(output_path) / 1024 / 1024
            logger.info(f"最终视频已保存: {output_path} ({sz:.1f}MB)")

        return state
