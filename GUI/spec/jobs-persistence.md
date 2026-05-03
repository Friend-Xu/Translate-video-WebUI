# Spec: GUI Jobs 持久化

## Objective
解决服务器重启后任务历史丢失的问题。用户重启 `start.bat` 后能查看之前任务的状态和日志，不需要重新选文件就能对同一视频重新执行。

### 用户故事
- 作为用户，我希望重启服务后能看到之前处理过的任务列表，包括状态和日志
- 作为用户，我希望从历史任务中获取 video_path，直接重新执行而不用重新选文件

## Tech Stack
- 存储：JSON 文件，每个 job 一个文件
- 目录：`GUI/jobs/`（不进 git）
- 无外部依赖

## Commands
```bash
# 启动后端（开发）
cd C:/Workspace/Translate_video
.venv/Scripts/python.exe -m uvicorn GUI.server:app --host 127.0.0.1 --port 8000 --reload

# 构建前端
cd GUI && npm run build

# 启动（生产）
start.bat
```

## Project Structure
```
GUI/
├── server.py              # 主要改动文件
├── jobs/                  # 新增：job 持久化目录（gitignore）
│   ├── a1b2c3d4.json
│   └── ...
└── .gitignore             # 新增：忽略 jobs/
```

## Job JSON Schema
```json
{
  "id": "a1b2c3d4",
  "status": "completed",
  "progress": 100,
  "current_step": "处理完成",
  "logs": ["[INFO] 启动中...", "..."],
  "video_path": "C:/videos/test.mp4",
  "created_at": "2026-05-02T14:30:00"
}
```

- `logs`：最多保留最近 200 条
- `status`：running 的 job 重启后标记为 `failed`，`current_step` 改为 "服务重启，任务中断"

## Code Style
```python
# 类型注解使用 `from __future__ import annotations`
# 路径操作统一使用 pathlib.Path
# JSON 写入统一 utf-8 编码
from __future__ import annotations
from pathlib import Path

JOBS_DIR = Path(__file__).resolve().parent / "jobs"
```

## Testing Strategy
- 手动验证：启动服务 → 执行任务 → 重启服务 → 检查历史 job 可访问
- 验证命令：
  ```bash
  # 重启后检查 job 文件
  ls GUI/jobs/
  cat GUI/jobs/{job_id}.json
  # API 验证
  curl http://127.0.0.1:8000/api/pipeline/{job_id}/status
  curl http://127.0.0.1:8000/api/pipeline/{job_id}/logs
  ```

## Boundaries
- **Always**: 每次 job 状态变更写盘；启动时从 `GUI/jobs/` 恢复；running 状态重启后标记 failed
- **Ask first**: 自动清理策略（保留最近 N 个）；历史任务列表 API；任务删除 API
- **Never**: 不恢复 running 子进程；不把 jobs 目录提交 git；不修改 main.py

## Success Criteria
1. 重启 `uvicorn GUI.server:app` 后，`GET /api/pipeline/{job_id}/status` 返回之前 job 状态
2. `GET /api/pipeline/{job_id}/logs` 流式返回之前 job 的历史日志
3. running 状态的 job 重启后自动标记为 `failed`
4. `GUI/jobs/` 下每个 job 一个 JSON 文件，可直接阅读
5. 前端可通过新 API `GET /api/jobs` 获取历史任务列表（含 video_path）
6. `GUI/jobs/` 加入 `.gitignore`

## Open Questions
- 无
