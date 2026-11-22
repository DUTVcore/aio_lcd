"""
Driver MẪU cho NZXT Kraken có màn LCD — chưa cài đặt giao thức phần cứng.

Thông tin đã biết (tham khảo dự án liquidctl):
    VID 0x1E71
    Kraken Z53/Z63/Z73   PID 0x3008   320x320
    Kraken 2023          PID 0x300E   240x240
    Kraken 2023 Elite    PID 0x300C   640x640

Kraken dùng HID cho lệnh điều khiển (chia "bucket" bộ nhớ, chuyển bucket hiển thị) và
endpoint Bulk cho dữ liệu ảnh (RGBA thô hoặc GIF). Trình tự này khá phức tạp và chưa được
cài ở đây — nếu bạn có Kraken, hãy đối chiếu mã nguồn liquidctl (driver kraken3) và
bản bắt gói tin của NZXT CAM, rồi cài `_open` / `_write` / `_close`.

Hiện tại driver chỉ chạy được ở chế độ giả lập (--sim) để thử pipeline.
"""

from __future__ import annotations

from core.usb_transport import parse_int

from .base_driver import BaseDriver

_MODELS = {
    "kraken_z": (0x3008, 320, 320),
    "kraken_2023": (0x300E, 240, 240),
    "kraken_elite": (0x300C, 640, 640),
}


class NZXTKrakenDriver(BaseDriver):
    DRIVER_ID = "nzxt_kraken"
    ALIASES = ("kraken",)
    DISPLAY_NAME = "NZXT Kraken (mẫu)"
    COLOR_FORMAT = "rgba8888"
    DEFAULT_FPS = 24
    VERIFIED = False
    VID = 0x1E71

    def __init__(self, options=None, *, simulate: bool = False):
        opts = dict(options or {})
        model = str(opts.get("model", "kraken_z")).lower()
        if model not in _MODELS:
            raise ValueError(f"model phải là một trong {sorted(_MODELS)} (nhận '{model}')")
        pid, width, height = _MODELS[model]
        opts.setdefault("width", width)
        opts.setdefault("height", height)
        super().__init__(opts, simulate=simulate)
        self.model = model
        self.vid = parse_int(opts.get("vid"), self.VID)
        self.pid = parse_int(opts.get("pid"), pid)

    def _open(self) -> None:
        raise NotImplementedError(
            f"Driver Kraken ({self.model}, {self.vid:04X}:{self.pid:04X}) mới là bản mẫu, chưa có giao thức "
            "phần cứng. Chạy với --sim để thử, hoặc đóng góp phần cài đặt (xem README)."
        )

    def _write(self, payload: bytes) -> None:
        raise NotImplementedError

    def _close(self) -> None:
        pass
