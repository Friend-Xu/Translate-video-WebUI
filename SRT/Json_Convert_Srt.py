"""
Json_Convert_Srt — 主入口 + 通用基础设施
────────────────────────────────────────
├── Config.yaml 加载          — 多语言预设参数
├── seconds_to_srt_time()     — 秒数 → SRT 时间格式
├── detect_language()         — 日语/英语检测
├── convert_json_to_srt()     — 主转换管线

语言处理器:
  Json_Convert_Srt_EN.py → EnglishProcessor（独立类）
  Json_Convert_Srt_JP.py → JapaneseProcessor（独立类）
"""

import json
import os
import re
import yaml
from datetime import timedelta


# ═══════════════════════════════════════════════════════════
#  Config.yaml 加载
# ═══════════════════════════════════════════════════════════

_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_CONFIG_DIR, 'Config.yaml')

# 多语言预设（模块级，从 Config.yaml 加载）
LANGUAGE_PRESETS = {}


def load_presets(config_path=None):
    """从 YAML 配置文件加载语言预设参数"""
    path = config_path or _CONFIG_PATH
    with open(path, 'r', encoding='utf-8') as f:
        presets = yaml.safe_load(f)
    LANGUAGE_PRESETS.clear()
    LANGUAGE_PRESETS.update(presets)
    return LANGUAGE_PRESETS


# 模块导入时自动加载
load_presets()


# ═══════════════════════════════════════════════════════════
#  通用工具函数
# ═══════════════════════════════════════════════════════════

def seconds_to_srt_time(seconds):
    """将秒数转换为SRT时间格式 (HH:MM:SS,mmm)"""
    td = timedelta(seconds=seconds)
    hours, remainder = divmod(td.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = (seconds - int(seconds)) * 1000
    return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d},{int(milliseconds):03d}"


def detect_language(text):
    """检测文本的主要语言（日语或英语）"""
    # \u4EC5\u7528\u5047\u540D\uFF08\u5E73\u5047\u540D \u3040-\u309F + \u7247\u5047\u540D \u30A0-\u30FF\uFF09\u5224\u65AD\u65E5\u8BED
    # \u79FB\u9664 \u4E00-\u9FFF\uFF08CJK \u6C49\u5B57\uFF09\u907F\u514D\u4E2D\u6587\u88AB\u8BEF\u5224
    japanese_chars = re.compile(r'[\u3040-\u309F\u30A0-\u30FF]')
    if japanese_chars.search(text):
        return 'ja'
    return 'en'


# ═══════════════════════════════════════════════════════════
#  语言处理器导入（延迟导入，避免循环依赖）
# ═══════════════════════════════════════════════════════════

def _get_english_processor():
    from Json_Convert_Srt_EN import EnglishProcessor
    return EnglishProcessor

def _get_japanese_processor():
    from Json_Convert_Srt_JP import JapaneseProcessor
    return JapaneseProcessor


# ═══════════════════════════════════════════════════════════
#  主转换入口
# ═══════════════════════════════════════════════════════════

def convert_json_to_srt(json_input, processor=None):
    """将 Whisper JSON 字幕数据转换为 SRT 格式

    参数:
        json_input: JSON 文件路径 或 dict
        processor:  可选，显式指定处理器实例

    返回:
        SRT 格式文本字符串
    """
    if isinstance(json_input, str) and os.path.exists(json_input):
        with open(json_input, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
    elif isinstance(json_input, dict):
        json_data = json_input
    else:
        raise ValueError("不支持的输入类型，应为JSON文件路径或字典数据")

    segments = json_data.get("segments", [])

    # 语言检测
    sample_text = " ".join(seg["text"] for seg in segments[:5])
    language = detect_language(sample_text)
    print(f"检测到音频语言: {'日语' if language == 'ja' else '英语'}")

    # 选择处理器
    if processor is not None:
        proc = processor
    elif language == 'ja':
        jp_preset = LANGUAGE_PRESETS.get("ja", {})
        JapaneseProcessor = _get_japanese_processor()
        proc = JapaneseProcessor(
            max_duration=jp_preset.get("merge_dur_max", 5.0),
            max_chars=jp_preset.get("max_chars", 35),
            min_duration=jp_preset.get("min_duration", 0.8),
        )
    else:
        en_preset = LANGUAGE_PRESETS.get("en", {})
        EnglishProcessor = _get_english_processor()
        proc = EnglishProcessor(
            max_chars=en_preset.get("max_chars", 50),
            min_duration=en_preset.get("min_duration", 0.7),
            max_gap=en_preset.get("max_gap", 1.0),
            space_optimization=en_preset.get("space_optimization", True),
        )

    proc.process_segments(segments)
    return proc.generate_srt_output()


# ═══════════════════════════════════════════════════════════
#  独立运行测试
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        json_path = sys.argv[1]
    else:
        json_path = r'D:\Github\20240708Move_video_2\source_file\temp\merged_subtitles.json'

    if not os.path.exists(json_path):
        print(f"错误: JSON文件不存在 - {json_path}")
        sys.exit(1)

    print(f"配置文件: {_CONFIG_PATH}")
    print(f"已加载语言预设: {list(LANGUAGE_PRESETS.keys())}")

    srt_content = convert_json_to_srt(json_path)
    srt_path = os.path.splitext(json_path)[0] + '.srt'

    with open(srt_path, 'w', encoding='utf-8') as f:
        f.write(srt_content)

    print(f"SRT文件转换完成！已保存至: {srt_path}")
