"""
Danh mục driver — TỰ ĐỘNG phát hiện mọi lớp BaseDriver trong thư mục `drivers/`.

Thêm màn mới: chỉ cần thả file .py có lớp kế thừa BaseDriver và khai báo DRIVER_ID.
Một driver lỗi khi import sẽ được ghi log và bỏ qua, không làm hỏng các driver khác.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any, Dict, Mapping, Optional, Type

from .base_driver import BaseDriver

log = logging.getLogger(__name__)

_registry: Optional[Dict[str, Type[BaseDriver]]] = None
_load_errors: Dict[str, str] = {}


def _all_subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _all_subclasses(sub)


def _discover() -> Dict[str, Type[BaseDriver]]:
    global _registry
    if _registry is not None:
        return _registry

    for module in pkgutil.iter_modules(__path__):
        if module.name.startswith("_") or module.name == "base_driver":
            continue
        try:
            importlib.import_module(f"{__name__}.{module.name}")
        except Exception as exc:
            _load_errors[module.name] = f"{type(exc).__name__}: {exc}"
            log.warning("Bỏ qua driver '%s' do lỗi import: %s", module.name, exc)

    registry: Dict[str, Type[BaseDriver]] = {}
    for cls in _all_subclasses(BaseDriver):
        if not cls.DRIVER_ID or getattr(cls, "__abstractmethods__", None):
            continue
        for key in (cls.DRIVER_ID, *cls.ALIASES):
            key = key.lower()
            if key in registry and registry[key] is not cls:
                log.warning("Tên driver '%s' bị trùng (%s và %s) — giữ bản đầu tiên.",
                            key, registry[key].__name__, cls.__name__)
                continue
            registry[key] = cls
    _registry = registry
    return registry


def available_drivers() -> Dict[str, Type[BaseDriver]]:
    """{DRIVER_ID: lớp driver} — chỉ tên chính, không gồm alias."""
    return {cls.DRIVER_ID: cls for cls in _discover().values()}


def load_errors() -> Dict[str, str]:
    _discover()
    return dict(_load_errors)


def get_driver(name: str, options: Optional[Mapping[str, Any]] = None, *, simulate: bool = False) -> BaseDriver:
    """Tạo driver theo tên (hoặc alias) trong config.json."""
    registry = _discover()
    cls = registry.get(str(name).lower().strip())
    if cls is None:
        names = ", ".join(sorted(available_drivers()))
        raise ValueError(f"Không có driver '{name}'. Hiện có: {names}")
    return cls(options, simulate=simulate)


__all__ = ["BaseDriver", "available_drivers", "get_driver", "load_errors"]
