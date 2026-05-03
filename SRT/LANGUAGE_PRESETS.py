"""
多语言预设参数
──────────────
控制字幕拆分、合并、格式化行为的语言特定配置。
被 Json_Convert_Srt_EN、Json_Convert_Srt_JP、Json_to_Srt 等模块引用。
"""

LANGUAGE_PRESETS = {
    # 日语预设
    "ja": {
        "max_chars": 35,
        "min_duration": 0.8,
        "max_gap": 0.3,
        "space_optimization": False,  # 禁用空格优化
        "formatter": "japanese"
    },
    # 英语预设
    "en": {
        "max_chars": 50,
        "min_duration": 0.7,
        "max_gap": 1.0,
        "space_optimization": True,   # 保留单词间空格
        "formatter": "english"
    },
    # 中文预设
    "zh": {
        "max_chars": 25,              # 中文字符较宽
        "min_duration": 0.9,
        "max_gap": 0.8,
        "space_optimization": False,
        "formatter": "chinese"
    },
    # 韩语预设
    "ko": {
        "max_chars": 30,
        "min_duration": 0.85,
        "max_gap": 0.75,
        "space_optimization": False,
        "formatter": "korean"
    },
    # 默认预设（其他语言）
    "default": {
        "max_chars": 45,
        "min_duration": 0.75,
        "max_gap": 0.85,
        "space_optimization": True,
        "formatter": "general"
    }
}
