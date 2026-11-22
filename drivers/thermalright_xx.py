"""
Driver MẪU "cấu hình được" — dùng cho Thermalright hoặc bất kỳ màn USB Bulk nào.

Cho phép thử giao thức vừa bắt được bằng Wireshark CHỈ bằng config.json, không cần viết code:

    "device": "thermalright_xx",
    "driver_options": {
        "vid": "0x....", "pid": "0x....",          // bắt buộc — lấy từ Device Manager
        "width": 320, "height": 240,
        "color_format": "rgb565", "big_endian": false,
        "header_hex": "",                         // byte cố định đầu mỗi khung
        "length_field": "none",                   // none | le16 | be16 | le32 | be32 (độ dài điểm ảnh, sau header)
        "footer_hex": "",                         // byte cố định cuối khung
        "init_sequence": [],                      // lệnh control transfer khi kết nối
        "chunk_size": 0
    }

Các dòng Thermalright khác nhau dùng giao thức khác nhau (một số dùng USB HID hoặc
cổng COM ảo thay vì Bulk) — chưa có cấu hình nào được kiểm chứng.
Khi đã chạy đúng trên máy bạn, hãy tạo driver riêng (vd thermalright_frozen_warframe.py)
với giá trị mặc định cố định và đặt VERIFIED = True.
"""

from __future__ import annotations

import struct

from core.usb_transport import (
    TransportError,
    UsbBulkDevice,
    parse_control_sequence,
    parse_hex_bytes,
    parse_int,
)

from .base_driver import BaseDriver

_LENGTH_FORMATS = {"none": None, "le16": "<H", "be16": ">H", "le32": "<I", "be32": ">I"}


class ThermalrightDriver(BaseDriver):
    DRIVER_ID = "thermalright_xx"
    ALIASES = ("thermalright", "generic_bulk")
    DISPLAY_NAME = "Thermalright / USB Bulk tổng quát (mẫu)"
    DEFAULT_WIDTH = 320
    DEFAULT_HEIGHT = 240
    COLOR_FORMAT = "rgb565"
    VERIFIED = False

    def __init__(self, options=None, *, simulate: bool = False):
        super().__init__(options, simulate=simulate)
        opts = self.options

        self._header = parse_hex_bytes(opts.get("header_hex"))
        self._footer = parse_hex_bytes(opts.get("footer_hex"))
        length_key = str(opts.get("length_field", "none")).lower()
        if length_key not in _LENGTH_FORMATS:
            raise ValueError(f"[{self.name}] length_field phải là {sorted(_LENGTH_FORMATS)}")
        self._length_fmt = _LENGTH_FORMATS[length_key]
        if self._length_fmt and self.raw_frame_size is not None:
            # Định dạng thô: độ dài cố định → tính sẵn header 1 lần.
            self._header += struct.pack(self._length_fmt, self.raw_frame_size)
            self._length_fmt = None

        self.init_sequence = parse_control_sequence(opts.get("init_sequence"))
        vid = parse_int(opts.get("vid"), None)
        pid = parse_int(opts.get("pid"), None)
        if not simulate and (vid is None or pid is None):
            raise ValueError(f"[{self.name}] Cần khai báo 'vid' và 'pid' trong driver_options")
        self._usb = UsbBulkDevice(
            vid or 0,
            pid or 0,
            interface=parse_int(opts.get("interface"), 0),
            endpoint_out=parse_int(opts.get("endpoint_out"), None),
            timeout_ms=parse_int(opts.get("timeout_ms"), 1000),
            chunk_size=parse_int(opts.get("chunk_size"), 0),
        )

    def build_payload(self, pixels: bytes) -> bytes:
        if self._length_fmt:  # định dạng nén (JPEG): độ dài thay đổi từng khung
            return b"".join((self._header, struct.pack(self._length_fmt, len(pixels)), pixels, self._footer))
        if not self._header and not self._footer:
            return pixels
        return b"".join((self._header, pixels, self._footer))

    def _open(self) -> None:
        self._usb.open()
        try:
            self._usb.run_sequence(self.init_sequence)
        except TransportError:
            self._usb.close()
            raise

    def _write(self, payload: bytes) -> None:
        self._usb.write(payload)

    def _close(self) -> None:
        self._usb.close()
