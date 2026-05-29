"""core/constants — 命名注册表与全局常量"""
from core.constants.naming import (
    AdapterRegistry, PassRegistry, GateRegistry,
    resolve_adapter, resolve_pass, resolve_gate, validate_name,
)

__all__ = [
    "AdapterRegistry", "PassRegistry", "GateRegistry",
    "resolve_adapter", "resolve_pass", "resolve_gate", "validate_name",
]
