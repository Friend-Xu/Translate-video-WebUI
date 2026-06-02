"""timeline/ui_adapter — WebUI 隔离层

纯转换层：core/ runtime state → WebUI JSON 格式。
无业务逻辑，无副作用。
"""
from timeline.ui_adapter.mapper import UIMapper

__all__ = ["UIMapper"]
