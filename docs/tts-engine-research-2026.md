# TTS 引擎调研报告（2026年5月）

*Generated: 2026-05-05 | Sources: 25+ | Confidence: High*

## Executive Summary

当前项目使用 EdgeTTS（Microsoft 免费代理）作为主力 TTS 引擎。本次调研覆盖 20+ 款 TTS 引擎，结论：**Kokoro 是 CPU 环境下升级 EdgeTTS 的最优选择**（Apache 2.0, MOS 4.2+, 82M 参数, pip install 即用）。GPU 用户可选 Fish Speech S2 或 CosyVoice 3.0（另见音色克隆调研）。FreeTTS/eidosSpeech 等"免费 API"实质是 EdgeTTS/Azure 的代理，音质无提升。

## 1. 需求背景

- **项目场景**: 视频翻译配音，中英文为主，逐字幕段合成
- **当前方案**: EdgeTTS（Microsoft 神经网络语音，免费，云端）
- **约束**: 开发环境无 GPU，用户可能有 GPU
- **目标**: 寻找音质更好、可本地运行、商用友好的 TTS 引擎

## 2. 候选引擎总览

### 2.1 核心指标对比

| 项目 | License | 参数量 | CPU可用 | 语言数 | MOS | RTF(CPU) | 音色克隆 | API |
|------|---------|--------|---------|--------|-----|----------|---------|-----|
| **Kokoro** | Apache 2.0 | 82M | 是 | 9 | 4.2-4.5 | ~1.0 | 否(presets) | pip/ONNX |
| **MeloTTS** | MIT | 25M | 是 | 6 | ~4.0 | 0.4-0.5 | 否 | pip |
| **Piper** | MIT | ~20M | 是 | 30+ | 3.3-3.5 | 0.008 | 否 | ONNX/CLI |
| **Fish Speech S2** | Research* | 4B/0.5B | 否 | 50+ | 4.4+ | N/A | 是(3-10s) | FastAPI/SGLang |
| **Chatterbox** | MIT | 0.5B | 否 | 12 | 4.0 | N/A | 是(短参考) | Python |
| **XTTS v2** | CPML+ | 467M | 否 | 17 | 4.0-4.5 | N/A | 是(6s) | Python |
| **F5-TTS** | CC-BY-NC | 336M | 否 | 中英为主 | 4.1 | N/A | 是(5-15s) | Gradio |
| **Dia 1.6B** | Apache 2.0 | 1.6B | 否 | 15 | 4.0-4.3 | N/A | 否 | Python |
| **Orca (Picovoice)** | 商业 | ~7MB | 是 | 多 | - | 0.16 | 否 | SDK |
| **ElevenLabs** | 商业云 | - | N/A | 32-70+ | 4.6-4.8 | N/A | 是 | REST API |
| **Google Cloud TTS** | 商业云 | - | N/A | 75+ | 4.4-4.7 | N/A | 是(10s) | REST/gRPC |
| **EdgeTTS (当前)** | 免费代理 | - | N/A | 75+ | ~3.8 | N/A | 否 | Python |

> \* Fish Speech S2 使用 FISH AUDIO RESEARCH LICENSE，非标准开源协议，商用需确认
> \+ XTTS v2 使用 Coqui Public Model License，非商用

### 2.2 MOS 质量排名（含商业对比）

| # | 模型 | 类型 | MOS | Year |
|---|------|------|-----|------|
| 1 | ElevenLabs Turbo v2.5 | 商业云 | 4.8 | 2024 |
| 2 | Sesame CSM | 开源 | 4.7 | 2025 |
| 3 | OpenAI TTS HD | 商业云 | 4.7 | 2023 |
| 4 | Gemini 2.5 Pro TTS | 商业云 | 4.7 | 2025 |
| 5 | ElevenLabs Flash v2.5 | 商业云 | 4.6 | 2025 |
| 6 | Orpheus TTS | 开源 | 4.6 | 2025 |
| 7 | **Kokoro v1.0** | **开源** | **4.5** | 2025 |
| 8 | XTTS v2 | 开源 | 4.5 | 2024 |
| 9 | Fish Speech 1.5 | 开源 | 4.4 | 2025 |
| 10 | F5-TTS | 开源 | 4.4 | 2024 |
| 11 | Dia 1.6B | 开源 | 4.3 | 2025 |
| 12 | **MeloTTS** | **开源** | **~4.0** | 2024 |
| 13 | **Piper** | **开源** | **3.6** | 2023 |
| 14 | **EdgeTTS (当前)** | 免费代理 | **~3.8** | - |

> 来源: CodeSOTA TTS Benchmark 2026, Trelis Research 2026

## 3. 重点引擎评估

### 3.1 Kokoro — CPU 环境首选（强烈推荐）

**基本信息**: 82M 参数 | Apache 2.0 | Hexgrad 开发 | 2025 年发布

**优势**：
- **CPU 可用且音质顶尖**：MOS 4.2-4.5，在独立盲测中与商业 API 持平（CodeSOTA UTMOS 4.48）
- **安装极简**：`pip install kokoro>=0.9.4 soundfile` + `apt install espeak-ng`，5 分钟可跑
- **资源极低**：推理 <1GB RAM，GPU RTF 0.03（33x 实时），CPU 也可实时
- **多语言**：英语（美/英）、日语、中文、韩语、西班牙语、法语、印地语、意大利语、葡萄牙语
- **商用友好**：Apache 2.0，无任何限制
- **社区活跃**：持续更新，ONNX 导出可用，DirectML 支持 Windows GPU

**劣势**：
- **无音色克隆**：只有预设音色（af_heart, af_nicole, bf_emma 等 54 种），不能克隆任意声音
- **中文需额外安装**：`pip install misaki[zh]`，中文音色少于英文
- **不能微调**：架构限制不易 fine-tune
- **需要 espeak-ng 系统依赖**：Windows 部署稍麻烦

**安装示例**：
```python
from kokoro import KPipeline
import soundfile as sf

pipeline = KPipeline(lang_code='a')  # 'a'=美英, 'z'=中文
generator = pipeline("Hello world!", voice='af_heart', speed=1.0)
for i, (gs, ps, audio) in enumerate(generator):
    sf.write(f'{i}.wav', audio, 24000)
```

**适配本项目**：
```python
class KokoroEngine(BaseTTSEngine):
    def synthesize(self, text, output_path, rate="+0%", emotion=None) -> float:
        # rate 映射到 speed 参数: +30% -> speed=1.3
        speed = 1.0 + int(rate.strip('%')) / 100
        pipeline = KPipeline(lang_code=self._lang_code)
        generator = pipeline(text, voice=self._voice, speed=speed)
        # 拼接所有 chunk 写入 WAV
```

### 3.2 MeloTTS — 中文场景的轻量备选

**基本信息**: 25M 参数 | MIT | MyShell.ai 开发

**优势**：
- **MIT 协议**：商用完全自由
- **极致轻量**：180MB 单文件，CPU RTF 0.4-0.5（i7-12700 上 85ms/句子）
- **中英混合原生支持**：无需切换模型，一条语句中可混用中英文
- **多口音**：英（美/英/印/澳）、西、法、中、日、韩
- **可微调**：LoRA 方式，30 分钟数据 + 无 GPU 即可

**劣势**：
- 音质不如 Kokoro（~4.0 vs 4.2+）
- 社区活跃度下降（最后更新 2024.12）
- 语言覆盖较少（6 种 vs Kokoro 9 种）
- 中文音色仅一个女声

### 3.3 Piper — 超低配/Raspberry Pi 方案

**基本信息**: ~20M 参数 | MIT | Rhasspy 开发

**优势**：
- **RTF 0.008**：10 秒音频仅需 80ms，可在树莓派运行
- **30+ 语言**：预训练音色最丰富
- **ONNX 生态**：跨平台部署成熟

**劣势**：
- 音质明显偏低（MOS 3.3-3.5），听感有"气息声"和断断续续感
- 无音色克隆
- 仅适合功能性场景（智能家居、无障碍），不适合内容创作

### 3.4 Fish Speech S2 — GPU 用户的高质量选择

**基本信息**: 4B(S2-Pro)/0.5B(S2-Mini) | FISH AUDIO RESEARCH LICENSE

**优势**：
- SOTA 级性能：TTS-Arena2 排名第一，WER/CER 业界最低
- 50+ 语言，80+ 语言训练数据
- 原生多说话人生成（单次推理可含多人对话）
- Docker/API Server/SGLang 部署成熟
- 音色克隆 + 情感丰富

**劣势**：
- **协议非标准开源**：FISH AUDIO RESEARCH LICENSE，商用限制待确认
- **需 GPU**：4B 模型至少 16GB VRAM
- 原始 Fish Speech 1.5 是 Apache 2.0，S2 改了协议

### 3.5 不推荐的"伪替代"

- **FreeTTS**：后端是 Microsoft Azure TTS，与 EdgeTTS 同源，音质无提升，且有 watermar/free tier 限制
- **eidosSpeech**：同样是 EdgeTTS/Azure 代理，1,000 字符/次限制，仅 30 次/天
- **Dia TTS**：云端 API，依赖 Nari Labs 的 Dia 1.6B，质量和稳定性待验证

## 4. 场景化推荐

| 场景 | 首选 | 备选 | 理由 |
|------|------|------|------|
| **无 GPU 开发环境** | **Kokoro** | MeloTTS | Apache 2.0, pip install, CPU 实时 |
| **中文为主视频翻译** | **Kokoro**+misaki[zh] | MeloTTS | Kokoro 音质更好, MeloTTS 中英混合原生 |
| **GPU 可用时追求音质** | Fish Speech S2 | CosyVoice 3.0 | 50+ 语言, SOTA 性能 |
| **需要音色克隆** | CosyVoice 3.0 | Fish Speech S2 | Apache 2.0, 3-10s 参考 (另见语音克隆调研) |
| **超低配/嵌入式** | Piper | Kokoro(CPU) | <100MB RAM, RTF 0.008 |
| **商业云 API** | ElevenLabs | Google Cloud TTS | 质量最高, 按量付费 |

## 5. 接入建议

### 5.1 推荐方案：Kokoro 作为 CPU 主力引擎

**理由**：
1. Apache 2.0，商用完全自由
2. `pip install kokoro` 即可，无需 Docker/GPU/额外服务
3. MOS 4.2+ 远优于 EdgeTTS，盲测接近商业 API
4. 9 种语言覆盖项目中英日韩需求
5. CPU 可实时推理，零运维成本

**接入步骤**：
1. `pip install kokoro>=0.9.4 soundfile` + Windows 安装 espeak-ng
2. 实现 `KokoroEngine` 类，满足 `BaseTTSEngine` Protocol
3. 在 `TTSConfig` 中添加 `engine_type: "kokoro"` 及 `kokoro_lang_code`, `kokoro_voice` 字段
4. Kokoro 不支持情感参数和音色克隆，`supports_emotion()` 返回 False

### 5.2 保留当前引擎作为 fallback

- **EdgeTTS** 保留为默认引擎（零成本、多语言、免安装）
- **ChatTTS** 保留为本地备选（已有集成）
- **Kokoro** 作为"高质量 CPU 本地引擎"新增
- 架构天然支持多引擎切换（Protocol），用户体验：配置里改一行 `engine_type`

### 5.3 完整引擎分层策略

```
用户环境              引擎选择                    质量/成本
---------------------------------------------------------
无 GPU + 本地优先  ->  Kokoro (CPU)            高质量/免费
无 GPU + 云可用    ->  EdgeTTS (默认)           中等/免费
有 GPU + 本地      ->  CosyVoice 3.0 / Fish S2   顶级/免费
有预算 + 云 API    ->  ElevenLabs              顶级/付费
低配/嵌入式        ->  Piper                    可用/免费
```

## 6. Key Takeaways

1. **Kokoro 是 EdgeTTS 升级的最优解**：Apache 2.0, CPU 可用, MOS 4.2+, pip install 即用, 多语言包括中文
2. **FreeTTS/eidosSpeech 等"免费 API"本质是 EdgeTTS 包装器**，音质无区别，不建议集成
3. **现有 BaseTTSEngine Protocol 无需修改**，Kokoro 接入只需实现 `synthesize()` 一个方法
4. **GPU 路线见另一份调研**：CosyVoice 3.0 / Fish Speech S2 覆盖音色克隆场景
5. **MeloTTS 保留关注**：中英混合原生支持独有优势，MIT 协议，适合纯中文场景

## Sources

1. [CodeSOTA TTS Models Comparison 2026](https://www.codesota.com/guides/tts-models) — 18 款模型 MOS/RTF/VRAM 全面对比
2. [CodeSOTA TTS Benchmarks](https://www.codesota.com/text-to-speech) — MOS 排名, 开源 vs 商业差距近乎消失
3. [Trelis Research TTS Models 2026](https://trelis.substack.com/p/top-text-to-speech-tts-models-in) — 10 款模型 CER/MOS 硬核评测
4. [Kokoro PyPI](https://pypi.org/project/kokoro/) — 官方 pip 包, 82M 参数, Apache 2.0
5. [pykokoro GitHub](https://github.com/holgern/pykokoro) — ONNX 加速, GPU/CPU/DirectML 多后端
6. [Kokoro Clore.ai Guide](https://docs.clore.ai/guides/audio-and-voice/kokoro-tts) — 部署指南, CPU 推理可行
7. [Picovoice TTS Latency Benchmark](https://picovoice.ai/docs/benchmark/tts/) — Orca/Kokoro/Piper 等 15 款延迟实测
8. [GigaGPU TTS Latency Benchmarks](https://gigagpu.com/tts-latency-benchmarks/) — 各 GPU 下 first-audio latency 数据
9. [MeloTTS GitHub](https://github.com/myshell-ai/MeloTTS) — MIT, 25M 参数, 中英混, CPU 实时
10. [Fish Speech GitHub](https://github.com/fishaudio/fish-speech) — S2 模型, Dual-AR 架构, SGLang 推理
11. [Fish Audio Server Docs](https://speech.fish.audio/server/) — FastAPI 部署, Docker Compose
12. [TTS.ai Open Source Guide 2026](https://tts.ai/blog/open-source-text-to-speech-guide-2026/) — Kokoro/Chatterbox/CosyVoice2/Dia 对比
13. [Apatero Open Source TTS 2026](https://apatero.com/blog/open-source-text-to-speech-models-beyond-elevenlabs-2026) — XTTS/StyleTTS2/Bark/Piper 综述
14. [DataRoot Labs TTS Comparison](https://datarootlabs.com/blog/text-to-speech-models) — 5 款模型 LibriTTS 基准测评
15. [VoicePing Offline TTS Eval](https://voiceping.net/en/blog/research-offline-tts-eval/) — 18 款端侧 TTS 速度/内存实测
16. [Instavar TTS Decision Tree 2026](https://instavar.com/blog/ai-production-stack/TTS_Model_Decision_Tree_2026) — RTX 3090 Ti 实测, 微调方案
17. [Geeky Gadgets TTS 2026](https://www.geeky-gadgets.com/text-to-speech-tts-ai-models/) — 开源 vs 商业综合对比
18. [TTS Insider Open Source 2026](https://www.ttsinsider.com/open-source-tts/) — Chatterbox/XTTS/Kokoro/VibeVoice 横向对比
19. [ElevenLabs API](https://elevenlabs.io/text-to-speech-api) — 商业方案参考
20. [Google Cloud TTS](https://cloud.google.com/text-to-speech) — Gemini-TTS, Chirp 3 HD

## Methodology

Searched 15+ queries across web. Analyzed 25+ sources including benchmark data, GitHub repos, deployment guides, and community comparisons. Sub-questions investigated:
- 当前项目 TTS 架构与可替代引擎的兼容性
- CPU 可用的高质量开源 TTS 引擎
- GPU 环境下与音色克隆引擎的协同
- 商业云 API 的定价与适用场景
- 各引擎 MOS 质量、RTF 速度、VRAM 需求、License 对比
