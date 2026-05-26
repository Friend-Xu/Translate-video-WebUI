"""
统一错误类型 — 遵循 "明确失败、可恢复、可追踪" 原则。

三类错误:
  USER_ERROR      — 用户输入错误（文件不存在、格式不支持），阻止执行 + 给出修复建议
  INFRA_ERROR     — 运行时错误（模型加载失败、GPU不可用、ffmpeg超时），保留状态 + 允许重试
  APP_ERROR       — 逻辑冲突错误（patch依赖循环、speaker冲突、时间轴重叠），进入待人工确认状态
"""
from __future__ import annotations


class PipelineError(Exception):
    """流水线异常基类。"""
    category: str = "APPLICATION"
    recoverable: bool = False
    suggestion: str = ""

    def __init__(self, message: str, *,
                 category: str | None = None,
                 recoverable: bool | None = None,
                 suggestion: str = ""):
        super().__init__(message)
        if category is not None:
            self.category = category
        if recoverable is not None:
            self.recoverable = recoverable
        self.suggestion = suggestion

    def to_dict(self) -> dict:
        return {
            "error": str(self),
            "category": self.category,
            "recoverable": self.recoverable,
            "suggestion": self.suggestion,
        }


class UserError(PipelineError):
    """用户输入错误 — 阻止执行，给出修复建议。"""
    category = "USER"
    recoverable = False


class InfraError(PipelineError):
    """基础设施错误 — 保留中间状态，允许重试。"""
    category = "INFRASTRUCTURE"
    recoverable = True


class AppError(PipelineError):
    """应用程序逻辑错误 — 需人工确认。"""
    category = "APPLICATION"
    recoverable = False


# ── 预定义常见错误工厂 ──

def file_not_found(path: str, hint: str = "") -> UserError:
    return UserError(f"文件不存在: {path}",
        suggestion=hint or "请检查文件路径是否正确，或将文件拖拽到窗口导入。")

def model_load_failed(model: str, detail: str = "") -> InfraError:
    return InfraError(f"模型加载失败: {model}",
        suggestion=detail or "请检查模型文件是否完整，或尝试重新下载。")

def gpu_unavailable() -> InfraError:
    return InfraError("GPU 不可用，已回退到 CPU",
        suggestion="可继续运行但速度较慢。检查 CUDA 驱动或设置 device=cpu。")

def tts_timeout(segment: str) -> InfraError:
    return InfraError(f"TTS 合成超时: {segment}",
        suggestion="请重试或降低并发数 (numWorkers)。")

def patch_conflict(patch_id: str, detail: str = "") -> AppError:
    return AppError(f"补丁冲突: {patch_id}",
        suggestion=detail or "请在 Patch Management 中手动解决冲突后重新应用。")

def speaker_conflict(speakers: list[str]) -> AppError:
    return AppError(f"说话人冲突: {', '.join(speakers)}",
        suggestion="请在 Speaker Review 中手动审核冲突的说话人分配。")

def timeline_overlap(event_a: str, event_b: str) -> AppError:
    return AppError(f"时间轴重叠: {event_a} ↔ {event_b}",
        suggestion="请在 Timeline Studio 中调整事件边界或使用拆分/合并工具。")
