"""
EventBus — Runtime 事件总线 (设计文档 §11.1-§11.5)

轻量级发布/订阅，线程安全。CLI 和 WebUI 各自注册 subscriber 消费同一事件流。
"""
from __future__ import annotations
import threading
from typing import Callable, Protocol
from core.engine.runtime_event import RuntimeEvent, RuntimeEventType


class EventSubscriber(Protocol):
    """事件订阅者协议 — 任何实现 on_event(event) 的对象都可以订阅。"""
    def on_event(self, event: RuntimeEvent) -> None: ...


class EventBus:
    """运行时事件总线 — 单例，线程安全。

    Usage:
        bus = EventBus()
        bus.subscribe(my_handler)
        bus.emit_now(RuntimeEvent(...))
    """
    _instance: EventBus | None = None
    _lock = threading.Lock()

    def __new__(cls) -> EventBus:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._subscribers: list[EventSubscriber | Callable] = []
                    cls._instance._event_log: list[RuntimeEvent] = []
                    cls._instance._log_limit = 10000
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """重置单例（仅用于测试）。"""
        with cls._lock:
            cls._instance = None

    def subscribe(self, subscriber: EventSubscriber | Callable) -> None:
        """注册事件订阅者。"""
        with self._lock:
            if subscriber not in self._subscribers:
                self._subscribers.append(subscriber)

    def unsubscribe(self, subscriber: EventSubscriber | Callable) -> None:
        """取消订阅。"""
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def emit_now(self, event: RuntimeEvent) -> None:
        """同步分发事件到所有 subscriber。"""
        with self._lock:
            self._event_log.append(event)
            if len(self._event_log) > self._log_limit:
                self._event_log = self._event_log[-self._log_limit:]

        subs = list(self._subscribers)
        for sub in subs:
            try:
                if hasattr(sub, "on_event"):
                    sub.on_event(event)
                else:
                    sub(event)
            except Exception:
                pass

    def emit(self, event: RuntimeEvent) -> None:
        """分发事件（当前为同步，未来可扩展为异步队列）。"""
        self.emit_now(event)

    @property
    def events(self) -> list[RuntimeEvent]:
        """返回事件日志的副本。"""
        with self._lock:
            return list(self._event_log)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def clear_log(self) -> None:
        """清空事件日志。"""
        with self._lock:
            self._event_log.clear()


def event_bus() -> EventBus:
    """获取全局 EventBus 单例。"""
    return EventBus()


def emit(event: RuntimeEvent) -> None:
    """便捷函数 — 向全局 EventBus 发布事件。"""
    EventBus().emit_now(event)
