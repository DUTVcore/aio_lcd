"""Lõi xử lý media của AIO Lite Streamer."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .color_utils import FORMATS, convert_frame, frame_size, make_encoder, normalize_format
    from .media_engine import TEST_PATTERN, FramePacer, FrameScaler, MediaEngine, payload_nbytes

__all__ = [
    "FORMATS",
    "TEST_PATTERN",
    "FramePacer",
    "FrameScaler",
    "MediaEngine",
    "convert_frame",
    "frame_size",
    "make_encoder",
    "normalize_format",
    "payload_nbytes",
]

_COLOR_ATTRS = {"FORMATS", "convert_frame", "frame_size", "make_encoder", "normalize_format"}
_MEDIA_ATTRS = {"TEST_PATTERN", "FramePacer", "FrameScaler", "MediaEngine", "payload_nbytes"}


def __getattr__(name: str):
    if name in _COLOR_ATTRS:
        from . import color_utils

        return getattr(color_utils, name)
    if name in _MEDIA_ATTRS:
        from . import media_engine

        return getattr(media_engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
