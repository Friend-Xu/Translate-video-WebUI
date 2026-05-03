# Translate Video — WebUI 使用说明

React + Python 的 Web 界面，在浏览器中运行视频翻译流水线。

## 快速开始

### 一键启动

双击 `GUI\start.bat`，自动启动后端和前端：

```
==========================================
  Translate Video GUI - Starting...
==========================================

[1/2] Starting backend server...
  Backend: http://127.0.0.1:8000
[2/2] Starting frontend dev server...
  Frontend: http://localhost:5173

Opening browser...
==========================================
```

浏览器会自动打开 `http://localhost:5173`。

### 手动启动

```bash
# 激活虚拟环境
.venv\Scripts\activate

# 启动后端（端口 8000）
python -m uvicorn GUI.server:app --host 127.0.0.1 --port 8000

# 新终端，启动前端（端口 5173）
cd GUI
npm install   # 首次需安装依赖
npm run dev
```

### 前置要求

- Python 3.11+（虚拟环境 `.venv/` 已配置）
- Node.js（用于前端，`npm` 需在 PATH）
- 后端依赖已在 `.venv/` 中安装（uvicorn, fastapi 等）

## 功能

- **选择视频文件**：选择要翻译的视频
- **配置步骤**：勾选/取消 字幕提取、翻译、TTS 合成
- **参数设置**：源语言、Whisper 模型、TTS 引擎
- **高级选项**：视频编码器、字幕字体、语速参数
- **实时日志**：WebSocket 推送流水线进度
- **任务管理**：后台持久化任务队列

## 文件说明

| 文件 | 说明 |
|------|------|
| `GUI/server.py` | Python 后端 (FastAPI + WebSocket) |
| `GUI/start.bat` | 一键启动脚本 |
| `GUI/App.tsx` | React 主界面 |
| `GUI/components/` | UI 组件 |
| `GUI/hooks/` | 自定义 hooks |
| `GUI/spec/` | 功能规格文档 |

## 常见问题

**Q: 前端启动报错 "npm: command not found"？**
需要安装 Node.js：https://nodejs.org/

**Q: 端口被占用？**
```bash
# 修改后端端口
python -m uvicorn GUI.server:app --host 127.0.0.1 --port 8001

# 修改前端端口
cd GUI && npm run dev -- --port 5174
```

**Q: 如何查看后端日志？**
日志文件在 `GUI/logs/server.log`。

## 许可证

与原项目相同 — MIT License
