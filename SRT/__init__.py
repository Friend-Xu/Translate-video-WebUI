"""
SRT Package — 字幕提取、转化、翻译全套工具链

├── VAD_Segmenter.py          — Silero VAD 音频分割
├── VocalSeparator.py         — 人声分离（Demucs / Spleeter）
├── MediaValidator.py         — 视频时长缺陷检测 + aresample 修复
├── Config.yaml               — 多语言预设参数（由 Json_Convert_Srt.py 加载）
├── LANGUAGE_PRESETS.py       — 多语言预设参数（Python 常量版，备用）
├── Json_Convert_Srt_EN.py   — JSON 转 SRT（英语，segment 级处理，从 Json_to_Srt.py 复刻）
├── Json_Convert_Srt_JP.py   — JSON 转 SRT（日语，MeCab 分词 + segment 级切分）
├── Json_Convert_Srt.py      — 主入口（加载 Config.yaml，调度 EN/JP 处理器）
├── Json_to_Srt.py            — 原始单文件转换器（不动，供参考）
├── SRT_Extract.py            — (旧线) WhisperX 完整包转录，已不推荐使用
├── SRT_Translator.py         — DeepSeek API 翻译 + 语义核对 + 术语替换
├── TranslationVerifier.py    — 跨语言语义相似度核验（sentence-transformers）
├── TargetedRecognizer.py     — 定点重转录验证（faster-whisper）
├── TermReplacer.py           — 技术术语词典替换
├── Video_subtitle_pipeline.py— 完整管线编排（旧）
├── Wav2Vec2Aligner.py        — wav2vec2 对齐封装（基于 whisperx_local/）
├══ whisperx_local/           — 从 whisperX 剥离的 wav2vec2 对齐模块
║   ├── alignment.py          — load_align_model + align (原版)
║   ├── audio.py              — 音频工具
║   ├── utils.py              — 工具函数
║   └── types.py              — 类型定义
├══ pipeline/ (项目根目录下)   — 主线模块
║   ├── utils.py              — 共享工具
║   ├── video_info.py         — 视频信息采集
║   ├── audio.py              — 音频提取修复
║   └── transcriber.py        — VAD + 转录 + wav2vec2 对齐
└── extract_subtitles.py (项目根目录) — 主线编排器

依赖说明：
  - MeCab 日语分词 (可选): pip install fugashi ipadic
  - 语义核对 (可选): pip install sentence-transformers numpy
  - 对齐模型: 运行时自动从 HF 镜像下载 (Wav2Vec2ForCTC)
"""
