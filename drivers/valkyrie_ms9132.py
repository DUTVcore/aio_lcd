"""
Driver Valkyrie B360-GT — chip cầu hiển thị USB MacroSilicon MS9132.

Giao thức khung hình (frame_protocol = "ms912x"), tham khảo driver Linux mã nguồn mở
`ms912x` (MS9120/MS9132):

    Header 8 byte : FF 00 | x/16 (1B) | y (2B, big-endian) | w/16 (1B) | h (2B, big-endian)
    Điểm ảnh      : UYVY (YUV 4:2:2), w*h*2 byte, dải "limited" (Y 16..235)
    Kết thúc      : FF C0 00 00 00 00 00 00

    → 480x480: 8 + 460800 + 8 = 460816 byte / khung, gửi qua endpoint Bulk OUT.

⚠ Chưa kiểm chứng trên B360-GT thật:
  - VID/PID mặc định 345F:9132 là ID phổ biến của MS9132, hãy xem đúng ID trong Device Manager.
  - MS91xx thường cần lệnh khởi tạo (bật nguồn / đặt độ phân giải) qua HID control transfer
    trước khi nhận khung. Bắt các lệnh này từ phần mềm gốc bằng Wireshark rồi điền vào
    `driver_options.init_sequence` (xem README). `deinit_sequence` chạy khi thoát.
  - Nếu màn chỉ nhận dữ liệu thô, đặt "frame_protocol": "raw".
"""

from __future__ import annotations

import struct

from core.usb_transport import (
    TransportError,
    UsbBulkDevice,
    parse_control_sequence,
    parse_int,
)

from .base_driver import BaseDriver

_MS912X_END = bytes((0xFF, 0xC0, 0, 0, 0, 0, 0, 0))
_PROTOCOLS = ("ms912x", "raw")


class ValkyrieMS9132Driver(BaseDriver):
    DRIVER_ID = "valkyrie_ms9132"
    ALIASES = ("b360_gt", "valkyrie_b360", "ms9132")
    DISPLAY_NAME = "Valkyrie B360-GT (MS9132)"
    DEFAULT_WIDTH = 480
    DEFAULT_HEIGHT = 480
    DEFAULT_FPS = 30
    COLOR_FORMAT = "uyvy"
    VERIFIED = False

    DEFAULT_VID = 0x345F
    DEFAULT_PID = 0x9132

    def __init__(self, options=None, *, simulate: bool = False):
        super().__init__(options, simulate=simulate)
        opts = self.options

        self.protocol = str(opts.get("frame_protocol", "ms912x")).lower()
        if self.protocol not in _PROTOCOLS:
            raise ValueError(f"[{self.name}] frame_protocol phải là {_PROTOCOLS} (nhận '{self.protocol}')")

        if self.protocol == "ms912x":
            if self.color_format not in ("uyvy", "yuyv"):
                raise ValueError(f"[{self.name}] Giao thức ms912x cần định dạng YUV 4:2:2")
            if self.width % 16:
                raise ValueError(f"[{self.name}] Giao thức ms912x cần width chia hết cho 16 (nhận {self.width})")
            off_x = parse_int(opts.get("offset_x"), 0)
            off_y = parse_int(opts.get("offset_y"), 0)
            if off_x % 16:
                raise ValueError(f"[{self.name}] offset_x phải chia hết cho 16")
            # Header tính sẵn 1 lần — mỗi khung chỉ còn việc ghép bytes.
            self._header = struct.pack(">HBHBH", 0xFF00, off_x // 16, off_y, self.width // 16, self.height)
            self._footer = _MS912X_END
        else:
            self._header = self._footer = b""

        self.init_sequence = parse_control_sequence(opts.get("init_sequence"))
        self.deinit_sequence = parse_control_sequence(opts.get("deinit_sequence"))
        self._usb = UsbBulkDevice(
            parse_int(opts.get("vid"), self.DEFAULT_VID),
            parse_int(opts.get("pid"), self.DEFAULT_PID),
            interface=parse_int(opts.get("interface"), 0),
            endpoint_out=parse_int(opts.get("endpoint_out"), None),
            timeout_ms=parse_int(opts.get("timeout_ms"), 1000),
            chunk_size=parse_int(opts.get("chunk_size"), 0),
        )

    def build_payload(self, pixels: bytes) -> bytes:
        if not self._header:
            return pixels
        return b"".join((self._header, pixels, self._footer))

    def _open(self) -> None:
        usb = self._usb
        self.log.info("Đang mở USB %04X:%04X ...", usb.vid, usb.pid)
        usb.open()
        try:
            if self.init_sequence:
                self.log.info("Gửi %d lệnh khởi tạo.", len(self.init_sequence))
                usb.run_sequence(self.init_sequence)
            elif self.protocol == "ms912x":
                self.log.warning("init_sequence trống — nếu màn không hiện hình, hãy bắt lệnh khởi tạo "
                                 "bằng Wireshark (xem README).")
        except TransportError:
            usb.close()
            raise
        self.log.info("Endpoint OUT 0x%02X | %d byte/khung | giao thức %s",
                      usb.endpoint_address, self.raw_frame_size + len(self._header) + len(self._footer),
                      self.protocol)

    def _write(self, payload: bytes) -> None:
        self._usb.write(payload)

    def _close(self) -> None:
        try:
            if self.deinit_sequence and self._usb.is_open:
                self._usb.run_sequence(self.deinit_sequence)
        except TransportError as exc:
            self.log.debug("deinit_sequence lỗi: %s", exc)
        finally:
            self._usb.close()
