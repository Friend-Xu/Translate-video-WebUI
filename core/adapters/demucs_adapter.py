"""
DemucsAdapter — Demucs 人声/背景分离适配器 (Chapter 10 §10.2)

封装现有 demucs_instr.extract_instrumental()。
输出 ANNOTATE patch 写入 audio 槽位:
  - audio.vocals_ref: 人声轨（供 ASR/VAD 使用，更干净的语音输入）
  - audio.bgm_ref: 背景轨（供最终合成保留 BGM）
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.patch import Patch, OpCode


@dataclass
class DemucsContext:
    """Demucs 分离输入。"""
    audio_path: str
    output_dir: str = ""
    model_name: str = "htdemucs"
    device: str = "cuda"


class DemucsAdapter:
    """封装 Demucs extract_instrumental() → ANNOTATE patch。

    将人声/背景分离结果写入 audio 槽位。
    分离后的 vocals 提供更干净的语音输入给 ASR 和 VAD。
    分离后的 bgm 保留给最终合成阶段混入背景音乐。
    """

    def configure(self, event_config = None):
        if not event_config: return
        if "skip_demucs" in event_config: self._skip = event_config["skip_demucs"]
        if "demucs_model" in event_config: self._model = event_config["demucs_model"]
    def separate(self, ctx: DemucsContext) -> Patch:
        """运行 Demucs 分离，返回 ANNOTATE patch。

        如果 Demucs 不可用（无模型/无 GPU），返回 fallback patch
        （vocals_ref 指向原始音频，bgm_ref 为空）。
        """
        import os

        try:
            from pipeline.demucs_instr import extract_instrumental

            output_dir = ctx.output_dir or os.path.dirname(ctx.audio_path) or "."
            instrumental_path = extract_instrumental(
                ctx.audio_path, output_dir,
                model_name=ctx.model_name,
            )

            base = os.path.basename(ctx.audio_path)
            stem = os.path.splitext(base)[0]
            demucs_dir = os.path.join(output_dir, ctx.model_name, stem)
            vocals_path = os.path.join(demucs_dir, "vocals.wav")
            no_vocals_path = instrumental_path

            return Patch(
                id=f"demucs_{self._slug(ctx.audio_path)}",
                target_id="audio",
                op=OpCode.ANNOTATE,
                value={
                    "vocals_ref": vocals_path if os.path.isfile(vocals_path) else ctx.audio_path,
                    "bgm_ref": no_vocals_path if os.path.isfile(no_vocals_path) else "",
                    "model": ctx.model_name,
                    "device": ctx.device,
                    "source": "demucs",
                },
                author="system",
                confidence=0.90,
            )
        except Exception:
            return Patch(
                id=f"demucs_fallback_{self._slug(ctx.audio_path)}",
                target_id="audio",
                op=OpCode.ANNOTATE,
                value={
                    "vocals_ref": ctx.audio_path,
                    "bgm_ref": "",
                    "model": "none",
                    "device": ctx.device,
                    "source": "demucs_fallback",
                },
                author="system",
                confidence=0.50,
            )

    @staticmethod
    def _slug(path: str) -> str:
        import hashlib
        return hashlib.md5(path.encode()).hexdigest()[:8]
