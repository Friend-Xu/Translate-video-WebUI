# 视频翻译工具 - GUI 版本

将视频翻译工具封装为双击运行的桌面应用程序。

## 快速开始

### 方法一：直接运行（开发模式）

```bash
# 激活虚拟环境
.venv\Scripts\activate

# 运行简化版 GUI（推荐）
python run_gui.py

# 或运行完整版 GUI
python translate_gui.py
```

### 方法二：打包为 exe

**一键打包（推荐）：**
```bash
# 双击运行
build.bat
```

**手动打包：**
```bash
# 激活虚拟环境
.venv\Scripts\activate

# 安装 PyInstaller
pip install PyInstaller

# 运行打包脚本
python build_exe.py
```

打包完成后，在 `dist/视频翻译工具` 目录找到可执行文件。

## 文件说明

| 文件 | 说明 |
|------|------|
| `run_gui.py` | 简化版 GUI（推荐，启动快） |
| `translate_gui.py` | 完整版 GUI（功能更全） |
| `build_exe.py` | PyInstaller 打包脚本 |
| `build_single.py` | 单文件版本打包脚本 |
| `build.bat` | 一键打包批处理 |
| `启动GUI.bat` | 快速启动 GUI |
| `test_gui.py` | 环境测试脚本 |
| `使用说明_打包exe.txt` | 详细打包说明 |

## 系统要求

- Windows 10/11
- Python 3.8+
- FFmpeg（需在 PATH 中）
- 显卡（可选，用于 GPU 加速）

## 功能特性

### run_gui.py（简化版）
- 调用现有 `main.py` 的所有功能
- 实时显示处理日志
- 暗色主题界面
- 支持所有命令行参数
- 启动速度快

### translate_gui.py（完整版）
- 内置完整处理逻辑
- 更丰富的设置选项
- 进度显示
- 多线程处理

## 使用方法

1. **选择视频**：点击"浏览"按钮选择要翻译的视频文件

2. **设置参数**：
   - **源语言**：视频的原始语言（自动检测或指定）
   - **模型**：Whisper 模型大小（tiny 最快，large 最准）
   - **TTS**：语音合成引擎（edge 在线，chattts 离线）

3. **高级选项**：
   - 跳过字幕提取：已有字幕时使用
   - 跳过翻译：只做提取和 TTS
   - 跳过 TTS：只做提取和翻译
   - 强制重新执行：忽略缓存

4. **开始翻译**：点击"开始翻译"按钮

5. **查看日志**：在输出区域查看实时进度

## 打包选项

### 目录版本（推荐）
- 运行 `build.bat`
- 输出到 `dist/视频翻译工具/`
- 优点：启动快，可调试
- 缺点：需要整个文件夹

### 单文件版本
- 运行 `python build_single.py`
- 输出 `dist/视频翻译工具.exe`
- 优点：便于分发
- 缺点：启动慢

## 常见问题

**Q: PySide6 安装失败？**
```bash
pip install PySide6 -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**Q: 打包后运行提示缺少 DLL？**
安装 [Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)

**Q: 程序启动慢？**
单文件版本首次启动需要解压，建议使用目录版本

**Q: 如何自定义界面？**
修改 `run_gui.py` 或 `translate_gui.py`

**Q: 如何添加图标？**
在打包命令中添加 `--icon=your_icon.ico`

## 开发说明

### 架构
```
GUI (run_gui.py)
    ↓ 调用
main.py (命令行入口)
    ↓ 委托
extract_subtitles.py → SRT_Translator → TtsPipeline
```

### 添加新功能
1. 在 `run_gui.py` 中添加 UI 控件
2. 将参数传递给 `main.py`
3. 测试打包

### 调试
```bash
# 开发模式运行
python run_gui.py

# 测试环境
python test_gui.py

# 查看详细日志
# GUI 中的"输出日志"标签页
```

## 更新日志

- v1.0 (2026-05-01): 初始版本
  - 创建 GUI 界面
  - 集成现有翻译功能
  - 添加打包支持

## 技术支持

遇到问题请：
1. 运行 `python test_gui.py` 检查环境
2. 查看 GUI 中的日志输出
3. 检查 `使用说明_打包exe.txt`

## 许可证

与原项目相同
