# CosyVoice 在 Windows 上生成"意义不明"乱码音频的深度排查与修复指南

> Windows 10/11 · Python 3.10 · PyTorch 2.3.1 / 2.6.0 · CosyVoice2-0.5B · RTX 3060 Ti · 2026-05-15

## 一、这篇教程解决什么问题

**一句话定位**：CosyVoice 在 Windows 上推理不报错、不崩溃，但生成的音频文件"完全听不出内容"——不是语言、不是慢速、不是噪音，而是随机的、意义不明的乱码。本文追溯该错误的底层机制（PyTorch 版本差异 → BFloat16 精度路径 → Qwen2LM 计算偏差），给出版本隔离方案和嵌入式 Python 环境搭建方法。

<span id="jump-guide"></span>

**跳读指南**：
- 如果你只是想**快速修复能跑起来**，直接跳到 [第三节 解决方案 A：嵌入式 Python 版本隔离](#fix-venv-isolation)
- 如果你想**理解为什么 PyTorch 2.6.0 会生成乱码而 2.3.1 正常**，跳到 [第二节 原理速览](#principle)
- 如果你需要**完整排查类似的"不报错但结果异常"问题**，按顺序读 [第四节 Debug 排查链](#debug-chain)
- 如果你想**直接用 CosyVoice 做声音克隆而非 TTS**，跳到 [第五节 解决方案 B](#fix-vc-fallback)

**阅读前提**：
- 你的 CosyVoice 运行在 Windows 10/11 上，有 NVIDIA GPU
- CosyVoice 模型能正常加载、推理不报错
- 生成的 `.wav` 文件有时长、有波形（RMS > 0），但人耳完全听不懂
- 你知道 `torchaudio.save` 和 WAV 格式的基本概念

**读完能得到什么**：
- 理解 PyTorch 版本差异如何导致"静默错误"（不抛异常的计算偏差）
- 一套嵌入式 Python 隔离环境，不影响项目原有 venv
- 完整的 CosyVoice 版本兼容矩阵（PyTorch / ONNX / transformers / NumPy）

---

<span id="principle"></span>

## 二、原理速览：为什么 GPU 推理"成功"却生成乱码

### 2.1 正常路径 vs 异常路径

```
正常路径（PyTorch 2.3.1 + transformers 4.41.2）：
  文本 → wetext 前端 → tokenizer → Qwen2LM (BFloat16) → speech token
  → Flow Matching (CausalMaskedDiffWithXvec) → mel spectrogram
  → HiFT-GAN vocoder → 24000Hz 单声道 float32 WAV
  结果：可辨识的中文语音

异常路径（PyTorch 2.6.0 + transformers 4.51.3）：
  文本 → wetext 前端 → tokenizer → Qwen2LM (BFloat16) → speech token ⚡
  → Flow Matching → mel spectrogram (帧数异常)
  → HiFT-GAN → 24000Hz 单声道 float32 WAV
  结果：完全不可辨识的乱码，但 RMS 能量正常
```

关键差异在 **Qwen2LM 生成 speech token** 这一步。模型内部的 `torch.nn.functional.scaled_dot_product_attention` 和 BFloat16 autocast 在 PyTorch 2.3 → 2.6 之间发生了行为变化，导致 LLM 生成了"看起来正常"但语义完全错误的 speech token 序列。

### 2.2 为什么没有报错？

这是一个**静默错误（silent error）**——GPU 计算没有触发 NaN、没有越界、没有 dtype 不匹配。每个算子都正常执行，但浮点精度路径的细微差异在自回归生成中逐 token 放大，最终产生一段"有波形、有能量、但毫无意义"的音频。

### 2.3 版本兼容矩阵

| 组件 | ✅ 可用 | ❌ 乱码 | 差异 |
|------|---------|---------|------|
| PyTorch | 2.3.1+cu121 | 2.6.0+cu124 | 3 个大版本 |
| torchaudio | 2.3.1 | 2.6.0 | 跟随 PyTorch |
| onnxruntime | 1.18.0 | 1.20.1 | 2 个小版本 |
| transformers | 4.41.2 | 4.51.3 | 引入了 flex_attention |
| NumPy | 1.26.4 | 2.2.6 | 不兼容 onnxruntime 1.18 |

---

<span id="fix-venv-isolation"></span>

## 三、解决方案 A：嵌入式 Python 版本隔离

核心思路：在项目目录内放置一个**完整的 Python 3.10.11 embedded + pip**，用它创建独立 venv，所有 CosyVoice 相关依赖（包含特定版本的 PyTorch）只安装在这个 venv 中。项目的 `.venv` 不受任何影响。

### 3.1 依赖清单

| 组件 | 版本 | 来源 |
|------|------|------|
| Python | 3.10.11 embedded | python.org |
| PyTorch | 2.3.1+cu121 | 本地 `.whl` |
| torchaudio | 2.3.1+cu121 | PyTorch 官方源 |
| onnxruntime | 1.18.0 | PyPI (Windows CPU) |
| onnx | 1.16.0 | PyPI |
| transformers | 4.41.2 | PyPI |
| NumPy | 1.26.4 | PyPI |

### 3.2 步骤

**Step 1：下载嵌入式 Python**

从 `https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-amd64.zip` 下载（约 7MB），解压到 `models/CosyVoice/.python310/`。

**Step 2：启用 pip**

编辑 `python310._pth`，去掉最后一行的 `#`：

```ini
python310.zip
.

# Uncomment to run site.main() automatically
import site
```

**Step 3：安装 pip**

```powershell
# 下载 get-pip.py
Invoke-WebRequest -Uri https://bootstrap.pypa.io/get-pip.py -OutFile .python310\get-pip.py
.python310\python.exe get-pip.py
```

**Step 4：安装 torch（本地 wheel）**

```powershell
.python310\python.exe -m pip install `
  models\Pytorch\torch-2.3.1+cu121-cp310-cp310-win_amd64.whl `
  --target=.cosyvenv\Lib\site-packages
```

**Step 5：安装 torchaudio**

```powershell
.python310\python.exe -m pip install torchaudio==2.3.1 `
  --target=.cosyvenv\Lib\site-packages `
  --index-url https://download.pytorch.org/whl/cu121 `
  --trusted-host download.pytorch.org
```

**Step 6：安装其余依赖（使用阿里云镜像）**

```powershell
.python310\python.exe -m pip install `
  onnx==1.16.0 onnxruntime==1.18.0 transformers==4.41.2 diffusers==0.29.0 `
  --target=.cosyvenv\Lib\site-packages `
  -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host=mirrors.aliyun.com
```

**Step 7：自动补完缺失依赖**

```python
# 保存为 install_deps.py，在嵌入式 Python 下运行
import sys, subprocess, re
sys.path.insert(0, r'.cosyvenv\Lib\site-packages')
sys.path.insert(0, r'.')
sys.path.insert(0, r'third_party\Matcha-TTS')

for attempt in range(30):
    try:
        from cosyvoice.cli.cosyvoice import CosyVoice2
        CosyVoice2(r'..\CosyVoice2-0.5B', fp16=True)
        print('OK')
        break
    except Exception as e:
        for m in re.findall(r"No module named '(\w+)'", str(e)):
            subprocess.run([
                '.python310\python.exe', '-m', 'pip', 'install', m,
                '--target', '.cosyvenv\Lib\site-packages',
                '-i', 'https://mirrors.aliyun.com/pypi/simple/',
                '--trusted-host=mirrors.aliyun.com'
            ], capture_output=True)
            print(f'Installed: {m}')
```

### 3.3 验证

```powershell
.python310\python.exe -c "
import sys
sys.path.insert(0, r'.cosyvenv\Lib\site-packages')
sys.path.insert(0, r'.')
sys.path.insert(0, r'third_party\Matcha-TTS')
from cosyvoice.cli.cosyvoice import CosyVoice2
import numpy as np, soundfile as sf

model = CosyVoice2(r'..\CosyVoice2-0.5B', fp16=True)
for r in model.inference_zero_shot('你好，这是一个测试。', '希望你以后能够做得比我还好哟', 'asset/zero_shot_prompt.wav'):
    audio = r['tts_speech'].squeeze().cpu().numpy()
    sf.write('test_output.wav', audio, model.sample_rate, subtype='FLOAT')
    dur = len(audio)/model.sample_rate
    print(f'OK: {dur:.1f}s (预期 2-4s 为正常语速)')
    break
"
```

预期输出：时长约 2-4 秒，听起来是正常中文语音。如果时长超过 8 秒或完全听不懂，说明版本仍有问题。

---

<span id="debug-chain"></span>

## 四、Debug 排查链 — 七个排查步骤

以下是本次完整排查中经历的 7 个 Debug 步骤。如果你遇到类似问题，按顺序排查。

<span id="debug1-wav-format"></span>

### Debug #1 — WAV 格式：float32 vs int16 PCM

**报错现象**：
Windows Media Player 打开生成的 `.wav` 文件播放全是噪音/静电。`wave.open()` 报错 `unknown format: 3`。

**根因**：
`torchaudio.save()` 对 float32 tensor 默认写 32-bit floating-point WAV（format code 3），而非标准 16-bit PCM（format code 1）。Windows 播放器将 IEEE 754 浮点字节当作 int16 整数解析 → 全频噪音。

**对比表**：

| 对比维度 | 修复前 | 修复后 |
|---------|--------|--------|
| WAV 格式 | 32-bit float (code 3) | 16-bit PCM (code 1) |
| 参数 | `torchaudio.save(path, tensor, sr)` | `torchaudio.save(path, tensor, sr, bits_per_sample=16)` |
| Windows 播放 | 全频噪音 | 正常 |

**代码修复**：

文件：`pipeline/tts_cosyvoice.py`

```python
# 修复前
torchaudio.save(output_path, combined, sample_rate)

# 修复后
combined = torch.cat(segments, dim=1).clamp(-1, 1)
torchaudio.save(output_path, combined, sample_rate, bits_per_sample=16)
```

**验证**：`wave.open(file).getsampwidth()` 应返回 `2`（16-bit）。

<span id="debug2-onnx-cpu"></span>

### Debug #2 — ONNX Runtime：CPU 版导致说话人嵌入异常

**报错现象**：
CUDAExecutionProvider 不可用，campplus（说话人嵌入提取）和 speech tokenizer 在 CPU 上运行。

**根因**：
`pip install onnxruntime` 安装的是 CPU-only 版本。Windows 上需要 `onnxruntime-gpu`。campplus 生成的 192 维说话人嵌入在 CPU/GPU 之间存在精度差异，影响下游 LLM 推理。

**对比表**：

| 对比维度 | 修复前 (onnxruntime) | 修复后 (onnxruntime-gpu) |
|---------|---------------------|-------------------------|
| Providers | CPUExecutionProvider | CUDAExecutionProvider, CPUExecutionProvider |
| campplus 推理 | CPU（与 GPU 精度差异） | GPU（与 PyTorch 一致） |
| 模型加载速度 | 正常 | 稍快 |

**代码修复**：

```powershell
pip install onnxruntime-gpu==1.18.0
```

**验证**：

```python
import onnxruntime as ort
assert 'CUDAExecutionProvider' in ort.get_available_providers()
```

> **注意**：CosyVoice 官方 `requirements.txt` 中 Windows 平台用的是 `onnxruntime==1.18.0`（CPU），Linux 才用 `onnxruntime-gpu==1.18.0`。在 Windows 上强制安装 `onnxruntime-gpu` 需要 CUDA 版本匹配（1.18.0 对应 CUDA 12.x）。

<span id="debug3-transformers-version"></span>

### Debug #3 — transformers 版本：flex_attention 不兼容 PyTorch 2.3.1

**报错日志**：

```
RuntimeError: Failed to import transformers.models.qwen2.modeling_qwen2
because of the following error:
ModuleNotFoundError: No module named 'torch.nn.attention.flex_attention'
```

**根因**：
`torch.nn.attention.flex_attention` 是 PyTorch 2.5.0 引入的新 API。transformers 4.51.3 的 Qwen2 模型实现使用了该 API。当 PyTorch 是 2.3.1 时，导入直接崩溃。

**对比表**：

| 对比维度 | 修复前 | 修复后 |
|---------|--------|--------|
| PyTorch | 2.6.0 | 2.3.1 |
| transformers | 4.51.3 | 4.41.2 |
| Qwen2 导入 | flex_attention 缺失 | 正常 |
| CosyVoice 加载 | 崩溃 | 正常 |

**代码修复**：

```powershell
pip install transformers==4.41.2
```

> transformers 4.40.1 ~ 4.41.x 是兼容 PyTorch 2.3.1 的最后版本。4.42+ 引入 flex_attention 要求 PyTorch ≥ 2.5。

<span id="debug4-numpy-conflict"></span>

### Debug #4 — NumPy 版本冲突：1.x ABI vs 2.x

**报错日志**：

```
A module that was compiled using NumPy 1.x cannot be run in NumPy 2.2.6
AttributeError: _ARRAY_API not found
```

**根因**：
onnxruntime 1.18.0 的 C 扩展是针对 NumPy 1.x ABI 编译的。NumPy 2.x 更改了 C 级别的 `_ARRAY_API` 符号表，导致 onnxruntime 的 `_pybind_state` 模块初始化失败。

**修复**：

```powershell
# 强制安装 numpy 1.x（不要和现有 numpy 2.x 共存）
pip install "numpy<2" --force-reinstall
```

> 关键：必须删除残留的 `numpy-2.x.x.dist-info` 目录。存在多个 dist-info 时 transformers 的版本检查会读取错误的版本号。

<span id="debug5-split-generator"></span>

### Debug #5 — 生成器提前 break：只取了第一段分句

**报错现象**：
长字幕（>20 字）合成的音频异常短（0.8s），短字幕正常（2-3s）。

**根因**：
CosyVoice 的 `inference_*` 方法内部调用 `text_normalize(split=True)` 将长文本拆成多句，每句 yield 一段语音。我们的代码只取第一段就 `break` 了。

**对比表**：

| 对比维度 | 修复前 | 修复后 |
|---------|--------|--------|
| 长字幕 30 字 | 0.8s（只有第一句） | 6-8s（完整） |
| 短字幕 10 字 | 2-3s（正常） | 2-3s（正常） |

**代码修复**：

```python
# 修复前：只取第一段
for _, result in enumerate(generator):
    torchaudio.save(output_path, result["tts_speech"].cpu(), sample_rate)
    break  # ← 丢弃了后续分句

# 修复后：拼接所有分句
segments = []
for _, result in enumerate(generator):
    segments.append(result["tts_speech"].cpu())
combined = torch.cat(segments, dim=1)
torchaudio.save(output_path, combined, sample_rate, bits_per_sample=16)
```

<span id="debug6-v3-crosslingual"></span>

### Debug #6 — CosyVoice3 cross_lingual：`<|endofprompt|>` token 断言失败

**报错日志**：

```
AssertionError: <|endofprompt|> not detected in CosyVoice3 text or prompt_text, check your input!
```

**根因**：
CosyVoice3 的 `Qwen2LM.inference()` 硬编码了 `assert 151646 in text`，要求输入文本中必须包含 `<|endofprompt|>` token（ID 151646）。但 `inference_cross_lingual` 内部调用 `frontend_zero_shot(tts_text, '', ...)` 传递了空 `prompt_text`，不包含该 token。

**修复**：在 CosyVoice3 cross_lingual 模式的文本前手动添加 `<|endofprompt|>` token。

> CosyVoice2 不受影响。CosyVoice3 的 cross_lingual 在我们的 vendored 代码（commit ace7c47）中仍存在未修复的 bug，建议生产环境使用 CosyVoice2。

<span id="debug7-model-duration"></span>

### Debug #7 — 语速异常：PyTorch 2.6.0 导致 3.5 倍慢速

**报错现象**：
隔离环境搭建完成后，同样的文本在旧环境（PyTorch 2.6.0）生成 9.6s，新环境（2.3.1）生成 2.7s。差值 3.5 倍。

**根因**：
这是最终的确认性证据——PyTorch 2.6.0 的 Qwen2LM 在自回归生成 speech token 时，每个 token 的生成概率分布发生了系统性的偏移，导致生成过多 padding/fill token，音频被"拉长"了 3-4 倍。这不是某个参数错误，而是底层 transformer 算子的浮点行为差异。

**对比表**：

| 对比维度 | PyTorch 2.6.0 | PyTorch 2.3.1 |
|---------|--------------|--------------|
| 9 字中文时长 | 9.6s | 2.7s |
| 语速 | 0.9 字/s | 3.3 字/s |
| 听感 | 极慢速 + 乱码 | 正常中文 |
| RMS 能量 | 0.09 | 0.07 |
| LLM 推理 | 无报错 | 无报错 |

---

<span id="fix-vc-fallback"></span>

## 五、解决方案 B：EdgeTTS + CosyVoice VC（备选）

如果版本隔离方案不可行（如无法下载特定 Python 版本），可以使用备用架构：

```
EdgeTTS 合成中文（快速、准确、稳定）→ CosyVoice inference_vc 换成目标人声音色
```

CosyVoice 的 `inference_vc()`（声音转换）在版本兼容性方面远优于 `inference_zero_shot()`（TTS 合成），因为 VC 流程不依赖 LLM 自回归生成 speech token，只走 Flow + HiFT-GAN。

---

## 六、速查卡

### 6.1 版本对照速查

| 组件 | 正确版本 | 错误版本（乱码） |
|------|---------|----------------|
| torch | 2.3.1+cu121 | 2.6.0+cu124 |
| torchaudio | 2.3.1+cu121 | 2.6.0+cu124 |
| onnxruntime | 1.18.0 | 1.20.1 |
| onnx | 1.16.0 | 任意 |
| transformers | 4.41.2 | 4.51.3 |
| NumPy | 1.26.4 | 2.2.6 |
| tokenizers | 0.21.x | 0.19.x |

### 6.2 报错→修复映射

| 报错关键词 | 对应 Debug |
|-----------|----------|
| `unknown format: 3` | [Debug #1 — WAV 格式](#debug1-wav-format) |
| `CUDAExecutionProvider is not in available` | [Debug #2 — ONNX CPU](#debug2-onnx-cpu) |
| `No module named 'torch.nn.attention.flex_attention'` | [Debug #3 — transformers 版本](#debug3-transformers-version) |
| `_ARRAY_API not found` | [Debug #4 — NumPy 冲突](#debug4-numpy-conflict) |
| 长字幕音频极短（<1s） | [Debug #5 — 生成器 break](#debug5-split-generator) |
| `<|endofprompt|> not detected` | [Debug #6 — CosyVoice3 cross_lingual](#debug6-v3-crosslingual) |
| 音频时长异常长（>3 倍正常） | [Debug #7 — PyTorch 版本](#debug7-model-duration) |

### 6.3 项目路径速查

```
models/CosyVoice/
├── .python310/              ← 嵌入式 Python 3.10.11
│   └── python310._pth       ← 需要启用 import site
├── .cosyvenv/               ← 隔离 venv (site-packages)
│   └── Lib/site-packages/   ← 所有 CosyVoice 依赖
├── cosyvoice/               ← vendored 源码
└── third_party/Matcha-TTS/  ← vendored Matcha-TTS
```

---

## 七、扩展阅读

本系列相关文章：
- [TxF WinError 6714 深度排查与修复](debug-txf-winerror-6714.md) — CosyVoice vendored 源码放置引发的 NTFS 事务问题
- 模型管理面板与系统日志 — 12 模型注册表 + WebUI 管理面板 + SSE 下载进度

---

## 参考文献

1. [CosyVoice GitHub — FunAudioLLM/CosyVoice](https://github.com/FunAudioLLM/CosyVoice) — 官方仓库及 requirements.txt
2. [grantjr1842/CosyVoice #36 — Fix TTS Audio and CUDA Issues](https://github.com/grantjr1842/CosyVoice/issues/36) — flow.py 冗余上采样 + 设备一致性修复
3. [pytorch/audio #1258 — Adding encoding and bits_per_sample options to save](https://github.com/pytorch/audio/issues/1258) — torchaudio.save float32 → int16
4. [FunAudioLLM/CosyVoice #1704 — Regression: CosyVoice zeroshot prompt issue](https://github.com/FunAudioLLM/CosyVoice/issues/1704) — CosyVoice3 第二句乱码 workaround
5. [Fun-CosyVoice3-0.5B-2512 HuggingFace Discussion — Bad audio](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512/discussions/10) — 模型端乱码讨论
6. [tts_server #10 — Manage separate venvs per TTS engine](https://github.com/hyang0129/tts_server/issues/10) — 多引擎 venv 隔离架构设计
