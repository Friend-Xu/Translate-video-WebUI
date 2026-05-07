# Python 3.10 降级计划

*2026-05-07 | 目标: CosyVoice 本地模式可用 | 原则: 不污染系统，全在项目目录内*

## 目录规划

```
D:\Workspace\Translate_video\
├── .python/          ← 保留不动 (Python 3.12 embeddable)
├── .venv/            ← 保留不动 (3.12 venv，可随时切回)
├── .python310/       ← 新建：Python 3.10 embeddable
├── .venv310/         ← 新建：Python 3.10 venv（成为默认）
```

## Step 1: 下载 Python 3.10 Embeddable

```bash
# 华为云镜像（3.10.11 = 最后一个 3.10.x）
# 下载到项目根目录
curl -L -o python-3.10.11-embed-amd64.zip \
  "https://mirrors.huaweicloud.com/python/3.10.11/python-3.10.11-embed-amd64.zip"

# 备选：清华镜像
# "https://mirrors.tuna.tsinghua.edu.cn/python/3.10.11/python-3.10.11-embed-amd64.zip"

# 解压
mkdir .python310
unzip python-3.10.11-embed-amd64.zip -d .python310/
```

修改 `.python310/python310._pth`：取消 `#import site` 注释（启用 pip）。

## Step 2: 安装 pip + 配置镜像

```bash
# 安装 pip（从 bootstrap）
.python310/python.exe -c "import urllib.request; urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', 'get-pip.py')"
.python310/python.exe get-pip.py --no-setuptools --no-wheel
.python310/python.exe -m pip install setuptools wheel

# pip 镜像 → 阿里云（国内最快之一）
.python310/python.exe -m pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
.python310/python.exe -m pip config set global.trusted-host mirrors.aliyun.com
```

## Step 3: 创建项目 venv

```bash
.python310/python.exe -m venv .venv310
# .venv310/ 会继承 pip 镜像配置
```

## Step 4: 安装依赖

```bash
# PyTorch CUDA 12.4（必须单独指定 index）
.venv310/Scripts/pip install torch==2.6.0+cu124 torchaudio==2.6.0+cu124 \
  --index-url https://download.pytorch.org/whl/cu124

# 其余依赖走阿里云镜像
.venv310/Scripts/pip install -r requirements.txt

# CosyVoice 依赖
.venv310/Scripts/pip install -r models/CosyVoice/requirements.txt
.venv310/Scripts/pip install modelscope

# 验证
.venv310/Scripts/python -c "
import torch; print(f'torch {torch.__version__} CUDA={torch.cuda.is_available()}')
import faster_whisper; print('faster_whisper OK')
import ctranslate2; print(f'ctranslate2 OK')
"
```

## Step 5: 下载 CosyVoice 模型

```bash
.venv310/Scripts/python -c "
from modelscope import snapshot_download
snapshot_download('iic/CosyVoice2-0.5B', cache_dir='models/')
"
```

## Step 6: 更新项目引用

- `CLAUDE.md`: `.venv` → `.venv310`，移除 Python 3.12 标记
- `vc_cosyvoice.py`: 降级 RuntimeError → warning（3.10 本地模式可用）

## Step 7: 验证

```bash
# 冒烟
.venv310/Scripts/python -c "from pipeline.vc_cosyvoice import CosyVoiceCloner; print('OK')"

# 全流程
.venv310/Scripts/python main.py test.mp4 --lang ja --voice-clone-engine cosyvoice
```

## 风险

| 风险 | 概率 | 应对 |
|------|:--:|------|
| PyTorch cu124 cp310 wheel 缺失 | 低 | 切 cu121 或 PyTorch 2.5 |
| CosyVoice modelscope 下载慢 | 中 | 挂代理或手动下载 |
| requirements.txt 中有包不支持 3.10 | 低 | 逐个确认，降版本 |

## 回滚

```bash
# 原命令不变，仍指向旧 venv
.venv/Scripts/python main.py ...
```
