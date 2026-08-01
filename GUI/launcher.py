"""Single-terminal launcher for backend + frontend. Ctrl+C stops both.

进程健康: launcher 挂 Windows Job Object (KILL_ON_JOB_CLOSE) — 无论以何种
方式退出 (Ctrl+C / 关终端窗口 / 被杀), OS 自动终止整棵子进程树
(uvicorn + npm/vite), 不留孤儿。
"""
import subprocess
import sys
import os
import time
import webbrowser
import signal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI_DIR = os.path.join(ROOT, "GUI")
LOG_DIR = os.path.join(GUI_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def _setup_kill_on_close():
    """Windows Job Object: launcher 死亡 → OS 杀 job 内全部进程 (含后代)。

    子进程默认继承父进程的 job (Win8+), 无需逐个 Assign。非 Windows 或
    launcher 已在别的 job 中 (Assign 失败) 时静默降级 — 清理是辅助能力,
    失败只影响"关窗不留孤儿", 不影响启动本身。
    """
    if os.name != "nt":
        return

    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # 显式句柄类型声明 — 缺失时 ctypes 按 32 位截断句柄,
    # AssignProcessToJobObject 报 ERROR_INVALID_HANDLE, job 形同虚设
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    JobObjectExtendedLimitInformation = 9

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
            job, JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info)):
        return
    # launcher 自己入 job → 其后代 (uvicorn/vite) 自动继承; launcher 退出时整树被杀
    if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        return


_setup_kill_on_close()

backend_log = open(os.path.join(LOG_DIR, "server.log"), "w", encoding="utf-8")

backend = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "GUI.server:app", "--host", "127.0.0.1", "--port", "8000"],
    cwd=ROOT,
    stdout=backend_log,       # uvicorn 内部日志 → 文件
    stderr=subprocess.PIPE,   # 系统日志 → 管道，实时输出到终端
)

# 将 stderr 管道实时输出到终端
import threading

def _pipe_stderr():
    try:
        for line in iter(backend.stderr.readline, b""):
            print(line.decode("utf-8", errors="replace"), end="", flush=True)
    except Exception:
        pass

_thread = threading.Thread(target=_pipe_stderr, daemon=True)
_thread.start()

frontend = subprocess.Popen(
    ["cmd", "/c", "npm run dev -- --clearScreen=false"],
    cwd=GUI_DIR,
)

print("=" * 50)
print("  Translate Video GUI")
print(f"  Backend:  http://127.0.0.1:8000")
print(f"  Frontend: http://localhost:5199")
print(f"  Logs:     {os.path.join(LOG_DIR, 'server.log')}")
print("  Press Ctrl+C to stop all servers.")
print("=" * 50)

time.sleep(3)
webbrowser.open("http://localhost:5199")

def cleanup():
    for proc, name in [(frontend, "Frontend"), (backend, "Backend")]:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            print(f"{name} stopped.")

signal.signal(signal.SIGINT, lambda sig, frame: (cleanup(), sys.exit(0)))
signal.signal(signal.SIGTERM, lambda sig, frame: (cleanup(), sys.exit(0)))

try:
    frontend.wait()
finally:
    cleanup()
    backend_log.close()
