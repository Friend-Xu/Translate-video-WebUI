"""Single-terminal launcher for backend + frontend. Ctrl+C stops both."""
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
print(f"  Frontend: http://localhost:5173")
print(f"  Logs:     {os.path.join(LOG_DIR, 'server.log')}")
print("  Press Ctrl+C to stop all servers.")
print("=" * 50)

time.sleep(3)
webbrowser.open("http://localhost:5173")

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
