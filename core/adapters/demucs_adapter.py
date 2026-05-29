"""
DemucsAdapter — Demucs 人声/背景分离适配器 (CLI Runtime 计划书 §5)

封装现有 demucs_instr.extract_instrumental()。
输出 ANNOTATE patch 写入 audio 槽位:
  - audio.vocals_ref: 人声轨（供 ASR/VAD 使用）
  - audio.bgm_ref: 背景轨（供最终合成保留 BGM）

实现 AdapterProtocol，capability_id = "separation.demucs"。
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.patch import Patch, OpCode
from core.adapters.protocol import (
    AdapterProtocol, AdapterCapability, AdapterResult,
    ErrorCategory, ResourceRequirement,
)


@dataclass
class DemucsContext:
    """Demucs 分离输入。"""
    audio_path: str
    output_dir: str = ""
    model_name: str = "htdemucs"
    device: str = "cuda"


class DemucsAdapter(AdapterProtocol):
    """封装 Demucs extract_instrumental() → ANNOTATE patch。

    将人声/背景分离结果写入 audio 槽位。
    分离后的 vocals 提供更干净的语音输入给 ASR 和 VAD。
    分离后的 bgm 保留给最终合成阶段混入背景音乐。
    """

    def configure(self, event_config = None):
        if not event_config: return
        if "skip_demucs" in event_config: self._skip = event_config["skip_demucs"]
        if "demucs_model" in event_config: self._model = event_config["demucs_model"]

    # ── AdapterProtocol 实现 ──────────────────────────────────

    @property
    def capability(self) -> AdapterCapability:
        return AdapterCapability(
            capability_id="separation.demucs",
            display_name="Demucs (htdemucs) vocal/instrumental separation",
            resources=ResourceRequirement(gpu=True, vram_mb=2000),
            failure_policy="degrade",
        )

    def execute(self, **kwargs) -> AdapterResult:
        demucs_ctx = kwargs.get("demucs_ctx")
        if demucs_ctx is None:
            return AdapterResult(ok=False, error="missing demucs_ctx", error_category=ErrorCategory.CONFIG)
        try:
            patch = self.separate(demucs_ctx)
            return AdapterResult(ok=True, patches=[patch])
        except Exception as exc:
            msg = str(exc).lower()
            cat = ErrorCategory.DEGRADABLE if ("cuda" in msg or "gpu" in msg) else ErrorCategory.RETRYABLE
            return AdapterResult(ok=False, error=str(exc), error_category=cat)

    # ── 核心分离逻辑 ─────────────────────────────────────────

    def separate(self, ctx: DemucsContext) -> Patch:
        """运行 Demucs 分离，返回 ANNOTATE patch。

        如果 Demucs 不可用（无模型/无 GPU），返回 fallback patch
        （vocals_ref 指向原始音频，bgm_ref 为空）。
        """
        import os

        try:
            from pipeline.demucs_instr import extract_instrumental

            output_dir = ctx.output_dir or os.path.dirname(ctx.audio_path) or "."
            extract_dir = os.path.join(output_dir, "01_extract") if not output_dir.endswith("01_extract") else output_dir
            os.makedirs(extract_dir, exist_ok=True)
            instrumental_path = extract_instrumental(
                ctx.audio_path, extract_dir,
                model_name=ctx.model_name,
            )

            base = os.path.basename(ctx.audio_path)
            stem = os.path.splitext(base)[0]
            demucs_dir = os.path.join(extract_dir, ctx.model_name, stem)
            vocals_path = os.path.join(demucs_dir, "vocals.wav")
            no_vocals_path = instrumental_path

            return Patch(
                id=f"demucs_{self._slug(ctx.audio_path)}",
                target_id="audio",
                op=OpCode.ANNOTATE,
                value={
                    "_global": True,
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
                    "_global": True,
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
