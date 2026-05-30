"""
whisperx_local — 独立的 wav2vec2 强制对齐模块

从 whisperX 剥离的 alignment.py + 必要依赖。
仅包含 wav2vec2 对齐功能，不依赖完整的 whisperX 包。
"""
from whisperx_local.alignment import load_align_model, align
