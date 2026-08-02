[English](README_GUI.md) | [简体中文](README_GUI_CN.md)

# Translate_video — WebUI 使用指南

[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.7-3178C6?logo=typescript)](https://www.typescriptlang.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![Vite](https://img.shields.io/badge/Vite-6-646CFF?logo=vite)](https://vite.dev)
[![MUI](https://img.shields.io/badge/MUI-7-007FFF?logo=mui)](https://mui.com)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

基于浏览器的可视化界面，运行 Translate_video 流水线 — **拖拽、配置、一键启动**。无需命令行。

![项目中心](GUI/screenshoot/项目中心.png)

---

## 快速开始

```bash
# 一键启动
GUI\start_WebUI.bat

# 或手动 — 后端（端口 8000）
.venv\Scripts\python -m uvicorn GUI.server:app --host 127.0.0.1 --port 8000

# 前端开发模式（端口 5173）
cd GUI && npm install && npm run dev
```

打开 `http://localhost:5173`。

> **环境要求：** Python 3.10+ | Node.js 18+ | 后端依赖已装在 `.venv/`

---

## 界面概览

| 面板 | 功能 |
|------|------|
| **主界面** | 拖拽视频 → 一键处理，SSE 实时日志，任务队列状态显示 |
| **步骤配置** | 三步可视化设置：提取（VAD/whisper/wav2vec2）→ 翻译（LLM/术语表/Prompt）→ TTS（引擎/语音/语速） |
| **输出设置** | 字幕样式 — 字体、颜色、描边、位置、大小。视频编码器 & 码率 |
| **字幕校验** | 可视化编辑器：校对翻译、标记问题条目、修改后重新 TTS |
| **批量处理** | 多视频队列，暂停/继续/跳过，逐文件进度 |
| **工具栏** | 配置导入/导出/重置、外挂字幕优化器、文件浏览器 |

---

## 功能特性

### 拖拽上传
直接将视频文件拖到主面板，自动识别路径、语言和工作目录。

### 实时进度
SSE 流式日志，每步计时显示。实时查看流水线各阶段的执行状态。

### GPU 自动检测
启动时检测 NVIDIA GPU 和 VRAM 容量。自动选择硬件编码器（NVENC）并计算 ChatTTS 最优模型副本数。

### 三 TTS 引擎
Edge TTS（云端，快速）、ChatTTS（本地，离线）和 CosyVoice（本地，零样本语音克隆）自由切换。根据目标语言自动匹配语音 — 支持 15 种语言。

### 配置持久化
所有设置保存到 YAML 文件。支持配置导出/导入，便于跨机器共享。一键恢复默认。

### 字幕校验
逐条审核翻译结果。编辑文本，标记问题条目。修改写入 `reviewed.srt` 并重新触发 TTS。

![字幕校验](GUI/screenshoot/字幕校验.png)

### ChatTTS 语音抽卡
即时预览 ChatTTS 语音。随机种子 → 试听 → 锁定满意的音色。预览间无需重载 GPU 模型。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 19, TypeScript 5.7, MUI 7, Vite 6 |
| 后端 | FastAPI 0.136, Python 3.10 |
| 通信 | SSE (Server-Sent Events) 实时日志推送 |
| 流水线 | `main.py` 子进程启动，stdout 流转发到前端 |
| 配置 | YAML — `config/translate.yaml`, `config/tts.yaml`, `config/caption.yaml` |

---

## 目录结构

```
GUI/
├── start_WebUI.bat          # 一键启动脚本
├── server.py                # FastAPI 后端
├── App.tsx                  # React 根组件，侧边栏导航
├── types.ts                 # 共享 TypeScript 类型
├── components/
│   ├── sections/
│   │   ├── MainPanel.tsx        # 拖拽、开始按钮、日志
│   │   ├── CosyVoiceTTSPanel.tsx # CosyVoice 引擎配置
│   │   ├── StepConfig.tsx       # 三步流水线配置
│   │   ├── OutputSettings.tsx   # 字幕样式 & 视频编码
│   │   ├── BatchPanel.tsx       # 多视频批量模式
│   │   ├── SubtitleReview.tsx   # 可视化字幕编辑器
│   │   └── ToolsPanel.tsx       # 配置管理 & 工具
│   ├── CustomPromptDialog.tsx   # 自定义翻译 Prompt 编辑器
│   ├── ApiConfigDialog.tsx      # API 密钥 & 模型设置
│   └── ChatTTSPanel.tsx         # ChatTTS 语音预览（抽卡）
├── hooks/
│   ├── usePipeline.ts       # 流水线启动/状态/取消
│   ├── useBatch.ts          # 批量处理逻辑
│   ├── useSSE.ts            # Server-Sent Events 解析
│   └── useConfig.ts         # 设置持久化
├── spec/                    # 功能规格文档
└── logs/                    # 服务端日志
```

---

## 常见问题

**Q: 前端报错 "npm: command not found"？**
安装 Node.js：https://nodejs.org/（推荐 18+）。

**Q: 端口 8000 / 5173 已被占用？**
```bash
# 改后端端口
.venv\Scripts\python -m uvicorn GUI.server:app --port 8001
# 改前端端口
cd GUI && npm run dev -- --port 5174
```
记得同步更新 `GUI/vite.config.ts` 里的代理目标。

**Q: 如何查看后端日志？**
`GUI/logs/server.log` — 滚动日志文件（每个 5MB，保留 3 个备份）。

**Q: 前端修改不生效？**
开发模式下 HMR 自动热更新。生产模式需重新构建：
```bash
cd GUI && npm run build
```

**Q: 浏览器报 CORS 错误？**
确认 Vite 开发服务器在运行（它会代理 `/api` 到 8000 端口）。开发模式下不要直接访问 8000 端口。

---

## 许可证

MIT — 与主项目相同。
