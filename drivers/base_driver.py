"""
BaseDriver — bản thiết kế gốc cho mọi driver màn hình AIO.

Viết driver mới chỉ cần:
  1. Tạo file trong `drivers/`, kế thừa `BaseDriver`.
  2. Khai báo `DRIVER_ID` (tên dùng trong config.json) và thông số mặc định.
  3. Cài đặt 3 hàm phần cứng: `_open()`, `_write(payload)`, `_close()`.
  4. (Tùy chọn) override `build_payload()` để thêm header/footer của giao thức.

Driver được tự động phát hiện — không cần sửa `drivers/__init__.py`.
Chế độ giả lập (simulate) do lớp gốc xử lý, driver con không cần quan tâm.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, Mapping, Optional, Tuple

import numpy as np

from core.color_utils import frame_size, make_encoder, normalize_format
from core.usb_transport import TransportError, parse_int

__all__ = ["BaseDriver", "TransportError"]


class BaseDriver(ABC):
    # ---- Khai báo của driver con -------------------------------------------
    DRIVER_ID: ClassVar[str] = ""                  # vd "valkyrie_ms9132"
    ALIASES: ClassVar[Tuple[str, ...]] = ()        # tên gọi khác, vd ("b360_gt",)
    DISPLAY_NAME: ClassVar[str] = ""
    DEFAULT_WIDTH: ClassVar[int] = 480
    DEFAULT_HEIGHT: ClassVar[int] = 480
    DEFAULT_FPS: ClassVar[float] = 30.0
    COLOR_FORMAT: ClassVar[str] = "rgb565"
    # False = giao thức chưa được kiểm chứng trên phần cứng thật (sẽ cảnh báo khi chạy).
    VERIFIED: ClassVar[bool] = False

    def __init__(self, options: Optional[Mapping[str, Any]] = None, *, simulate: bool = False):
        self.options: Dict[str, Any] = dict(options or {})
        self.log = logging.getLogger(f"driver.{self.DRIVER_ID or type(self).__name__}")
        self.name = self.DISPLAY_NAME or type(self).__name__
        self.simulate = bool(simulate)

        self.width = parse_int(self.options.get("width"), self.DEFAULT_WIDTH)
        self.height = parse_int(self.options.get("height"), self.DEFAULT_HEIGHT)
        self.fps = float(self.options.get("fps") or self.DEFAULT_FPS)
        self.color_format = normalize_format(self.options.get("color_format") or self.COLOR_FORMAT)
        if self.width <= 0 or self.height <= 0 or self.fps <= 0:
            raise ValueError(f"[{self.name}] width/height/fps phải > 0")

        self._encoder = make_encoder(
            self.color_format,
            yuv_range=str(self.options.get("yuv_range", "limited")),
            big_endian=bool(self.options.get("big_endian", False)),
            jpeg_quality=parse_int(self.options.get("jpeg_quality"), 90),
        )
        self.is_connected = False
        self.frames_sent = 0
        self.bytes_sent = 0

    # ---- Driver con bắt buộc cài đặt ---------------------------------------
    @abstractmethod
    def _open(self) -> None:
        """Tìm và mở thiết bị, gửi lệnh khởi tạo. Lỗi → ném TransportError."""

    @abstractmethod
    def _write(self, payload: bytes) -> None:
        """Gửi 1 khung (đã qua build_payload) xuống thiết bị. Lỗi → ném TransportError."""

    @abstractmethod
    def _close(self) -> None:
        """Giải phóng thiết bị. Không được ném lỗi."""

    # ---- Có thể override ---------------------------------------------------
    def build_payload(self, pixels: bytes) -> bytes:
        """Đóng gói dữ liệu điểm ảnh theo giao thức (header/footer...). Mặc định: giữ nguyên."""
        return pixels

    @property
    def raw_frame_size(self) -> Optional[int]:
        """Số byte điểm ảnh thô mỗi khung (None nếu định dạng nén)."""
        return frame_size(self.color_format, self.width, self.height)

    # ---- API dùng bởi main.py ----------------------------------------------
    def encode(self, frame_bgr: np.ndarray) -> bytes:
        """Khung BGR đúng kích thước → payload sẵn sàng gửi. An toàn khi gọi từ luồng nền."""
        h, w = frame_bgr.shape[:2]
        if (w, h) != (self.width, self.height):
            raise ValueError(f"[{self.name}] Khung {w}x{h} khác độ phân giải màn {self.width}x{self.height}")
        return self.build_payload(self._encoder(frame_bgr))

    def connect(self) -> None:
        if self.is_connected:
            return
        if not self.simulate:
            if not self.VERIFIED:
                self.log.warning("Driver '%s' CHƯA được kiểm chứng trên phần cứng thật — "
                                 "hãy đối chiếu giao thức bằng Wireshark trước khi dùng.", self.DRIVER_ID)
            self._open()
        self.is_connected = True
        self.log.info("%s sẵn sàng (%s).", self.name, "GIẢ LẬP" if self.simulate else "phần cứng")

    def send(self, payload: bytes) -> None:
        if not self.is_connected:
            raise TransportError(f"[{self.name}] Chưa kết nối")
        if not self.simulate:
            self._write(payload)
        self.frames_sent += 1
        self.bytes_sent += len(payload)

    def send_image(self, frame_bgr: np.ndarray) -> None:
        """Tiện ích: encode + gửi 1 khung (dùng khi không cần pipeline nền)."""
        self.send(self.encode(frame_bgr))

    def disconnect(self) -> None:
        if not self.is_connected:
            return
        self.is_connected = False
        if not self.simulate:
            try:
                self._close()
            except Exception as exc:  # không để lỗi dọn dẹp che lỗi chính
                self.log.debug("Lỗi khi đóng thiết bị: %s", exc)
        self.log.info("%s đã ngắt kết nối.", self.name)

    def get_info(self) -> Dict[str, Any]:
        return {
            "id": self.DRIVER_ID,
            "name": self.name,
            "resolution": f"{self.width}x{self.height}",
            "color_format": self.color_format,
            "fps": self.fps,
            "simulate": self.simulate,
            "verified": self.VERIFIED,
            "is_connected": self.is_connected,
            "frames_sent": self.frames_sent,
            "bytes_sent": self.bytes_sent,
        }

    def __enter__(self) -> "BaseDriver":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.disconnect()
