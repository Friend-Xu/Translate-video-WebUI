"""
Windows NTSTATUS / Unix signal exit code decoder.

Map raw process exit codes to human-readable status names and
descriptions, especially for native crashes that Python cannot catch.

Supported codes:
- NTSTATUS (>= 0xC0000000): STATUS_HEAP_CORRUPTION, STATUS_ACCESS_VIOLATION, etc.
- Negative Unix signals: -SIGABRT (-6), -SIGSEGV (-11), etc.

Usage:
    from pipeline.ntstatus import decode_exit_code
    name, desc = decode_exit_code(3221226356)
    # ('STATUS_HEAP_CORRUPTION', '堆损坏 — ...')
"""
from __future__ import annotations

_NTSTATUS: dict[int, tuple[str, str]] = {
    0xC0000005: (
        "STATUS_ACCESS_VIOLATION",
        "内存访问违规 — 空指针解引用或释放后使用。通常由 CUDA kernel 越界访问引起。"
    ),
    0xC00000FD: (
        "STATUS_STACK_OVERFLOW",
        "线程栈耗尽 — 可能是无限递归或过深的 Python 调用栈。"
    ),
    0xC000013A: (
        "STATUS_ENTRYPOINT_NOT_FOUND",
        "DLL 入口点未找到 — CUDA/cuDNN 版本不匹配或 DLL 冲突。"
        "通常由 PyTorch 与系统 CUDA 库版本不一致引起。"
        "重启后重试，如持续发生需检查 CUDA 环境。"
    ),
    0xC0000374: (
        "STATUS_HEAP_CORRUPTION",
        "堆损坏 — 两个本机内存分配器（PyTorch CUDA 缓存 / CTranslate2 cudaMalloc）"
        "在同一 CUDA 上下文内竞争，Windows 堆管理器检测到不一致后终止进程。"
        "重启或清理 GPU 显存后重试通常可恢复。"
    ),
    0xC0000409: (
        "STATUS_STACK_BUFFER_OVERRUN",
        "栈缓冲区溢出 — 本机代码写入了超出栈缓冲区的数据。"
    ),
    0xC0000135: (
        "STATUS_DLL_NOT_FOUND",
        "缺少 DLL — 动态链接库未找到。检查 CUDA/cuBLAS/cuDNN 安装。"
    ),
    0xC0000142: (
        "STATUS_DLL_INIT_FAILED",
        "DLL 初始化失败 — 动态库加载后初始化失败。通常由版本不匹配引起。"
    ),
}

_UNIX_SIGNALS: dict[int, tuple[str, str]] = {
    6: ("SIGABRT", "进程异常终止 (abort)。通常由 C 运行时或本机库触发。"),
    11: ("SIGSEGV", "段错误 — 访问了无效的内存地址。"),
    8: ("SIGFPE", "浮点异常 — 除以零或无效浮点运算。"),
    5: ("SIGTRAP", "调试陷阱 — 断点或断言失败。"),
}

_RETRYABLE_CODES: set[int] = {
    0xC0000005,  # ACCESS_VIOLATION
    0xC000013A,  # ENTRYPOINT_NOT_FOUND (DLL version mismatch)
    0xC0000374,  # HEAP_CORRUPTION
}


def decode_exit_code(code: int) -> tuple[str, str]:
    """Decode a process exit code to (name, description).

    Handles NTSTATUS codes (>= 0xC0000000), negative Unix signals,
    and unrecognised values.
    """
    if code >= 0xC0000000:
        name, desc = _NTSTATUS.get(
            code, (f"NTSTATUS_{code:08X}", f"未识别的 NT 状态码 0x{code:08X}")
        )
        return name, desc
    if code < 0:
        sig = -code
        name, desc = _UNIX_SIGNALS.get(
            sig, (f"SIGNAL_{sig}", f"未识别的信号 {sig}")
        )
        return name, desc
    return (f"EXIT_{code}", f"标准退出码 {code}")


def is_native_crash(code: int) -> bool:
    """True if this exit code represents a native crash (not a Python exception)."""
    return code >= 0xC0000000 or code < 0


def is_retryable(code: int) -> bool:
    """True if this crash code is likely transient and worth retrying."""
    return code in _RETRYABLE_CODES
