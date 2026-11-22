"""
Bộ chuyển đổi màu cho màn LCD của tản AIO.

Mọi encoder nhận khung hình BGR uint8 (định dạng mặc định của OpenCV), shape (H, W, 3),
và trả về `bytes` đúng định dạng phần cứng cần.

Cách dùng khuyến nghị: tạo encoder một lần rồi gọi lại cho từng khung hình
(không phải tra cứu / dựng lại tham số mỗi lần):

    encode = make_encoder("uyvy", yuv_range="limited")
    payload = encode(frame)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional

import cv2
import numpy as np

Encoder = Callable[[np.ndarray], bytes]


@dataclass(frozen=True)
class PixelFormat:
    name: str
    bytes_per_pixel: Optional[int]  # None = định dạng nén, kích thước thay đổi theo khung
    even_width: bool = False        # YUV 4:2:2 cần chiều rộng chẵn
    description: str = ""


FORMATS: Dict[str, PixelFormat] = {
    "uyvy": PixelFormat("uyvy", 2, True, "YUV 4:2:2 đóng gói U Y0 V Y1 (MacroSilicon MS91xx...)"),
    "yuyv": PixelFormat("yuyv", 2, True, "YUV 4:2:2 đóng gói Y0 U Y1 V (YUY2)"),
    "rgb565": PixelFormat("rgb565", 2, False, "16-bit, R ở bit cao (ST7789, ILI9341...)"),
    "bgr565": PixelFormat("bgr565", 2, False, "16-bit, B ở bit cao"),
    "rgb888": PixelFormat("rgb888", 3, False, "24-bit R G B"),
    "bgr888": PixelFormat("bgr888", 3, False, "24-bit B G R (nguyên bản OpenCV)"),
    "rgba8888": PixelFormat("rgba8888", 4, False, "32-bit R G B A (A = 255)"),
    "jpeg": PixelFormat("jpeg", None, False, "Ảnh nén JPEG"),
}

ALIASES: Dict[str, str] = {
    "yuy2": "yuyv",
    "yuv422": "uyvy",
    "rgb24": "rgb888",
    "bgr24": "bgr888",
    "rgba": "rgba8888",
    "rgba32": "rgba8888",
    "jpg": "jpeg",
    "mjpeg": "jpeg",
}

# Ma trận RGB -> YUV (BT.601) theo thứ tự kênh B, G, R + cột hằng số (offset).
# Dùng cv2.transform: tính trong C, tự làm tròn và bão hòa về uint8.
_YUV_MATRICES: Dict[str, np.ndarray] = {
    # "Studio swing": Y 16..235, UV 16..240 — phổ biến với chip cầu USB/HDMI.
    "limited": (
        np.array(
            [
                [24.966, 128.553, 65.481, 16.0 * 255],
                [112.000, -74.203, -37.797, 128.0 * 255],
                [-18.214, -93.786, 112.000, 128.0 * 255],
            ],
            dtype=np.float64,
        )
        / 255.0
    ).astype(np.float32),
    # "Full swing" (JPEG): Y 0..255.
    "full": np.array(
        [
            [0.114, 0.587, 0.299, 0.0],
            [0.5, -0.331264, -0.168736, 128.0],
            [-0.081312, -0.418688, 0.5, 128.0],
        ],
        dtype=np.float32,
    ),
}


def normalize_format(name: str) -> str:
    """Chuẩn hóa tên định dạng (chấp nhận alias). Ném ValueError nếu không hỗ trợ."""
    key = str(name).lower().strip()
    key = ALIASES.get(key, key)
    if key not in FORMATS:
        supported = ", ".join(sorted(FORMATS))
        raise ValueError(f"Định dạng màu không hỗ trợ: '{name}'. Hỗ trợ: {supported}")
    return key


def frame_size(fmt: str, width: int, height: int) -> Optional[int]:
    """Số byte của 1 khung hình thô; None với định dạng nén (JPEG)."""
    info = FORMATS[normalize_format(fmt)]
    if info.bytes_per_pixel is None:
        return None
    return width * height * info.bytes_per_pixel


# --------------------------------------------------------------------------- #
#  Các bộ encode                                                               #
# --------------------------------------------------------------------------- #
def _check_bgr(frame: np.ndarray) -> None:
    if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError(f"Cần khung BGR uint8 (H, W, 3), nhận {frame.dtype} {frame.shape}")


def _make_yuv422(order: str, yuv_range: str) -> Encoder:
    matrix = _YUV_MATRICES[yuv_range]
    uyvy = order == "uyvy"

    def encode(frame: np.ndarray) -> bytes:
        _check_bgr(frame)
        h, w = frame.shape[:2]
        if w % 2:
            raise ValueError(f"YUV 4:2:2 cần chiều rộng chẵn (nhận {w})")

        yuv = cv2.transform(frame, matrix)          # (h, w, 3) uint8: Y, U, V
        pairs = yuv.reshape(h, w // 2, 2, 3)        # gom từng cặp pixel ngang
        # Lấy trung bình U/V của 2 pixel (chính xác hơn lấy mẫu pixel chẵn).
        uv = pairs[:, :, :, 1:].astype(np.uint16)
        uv = ((uv[:, :, 0] + uv[:, :, 1] + 1) >> 1).astype(np.uint8)  # (h, w/2, 2)

        out = np.empty((h, w // 2, 4), dtype=np.uint8)
        if uyvy:
            out[..., 0] = uv[..., 0]
            out[..., 1] = pairs[:, :, 0, 0]
            out[..., 2] = uv[..., 1]
            out[..., 3] = pairs[:, :, 1, 0]
        else:
            out[..., 0] = pairs[:, :, 0, 0]
            out[..., 1] = uv[..., 0]
            out[..., 2] = pairs[:, :, 1, 0]
            out[..., 3] = uv[..., 1]
        return out.tobytes()

    return encode


def _make_565(blue_high: bool, big_endian: bool) -> Encoder:
    dtype = np.dtype(">u2" if big_endian else "<u2")
    hi_idx, lo_idx = (0, 2) if blue_high else (2, 0)  # chỉ số kênh trong BGR

    def encode(frame: np.ndarray) -> bytes:
        _check_bgr(frame)
        hi = frame[..., hi_idx].astype(np.uint16)
        mid = frame[..., 1].astype(np.uint16)
        lo = frame[..., lo_idx].astype(np.uint16)
        packed = ((hi & 0xF8) << 8) | ((mid & 0xFC) << 3) | (lo >> 3)
        return packed.astype(dtype, copy=False).tobytes()

    return encode


def _make_cvt(code: Optional[int]) -> Encoder:
    def encode(frame: np.ndarray) -> bytes:
        _check_bgr(frame)
        return (frame if code is None else cv2.cvtColor(frame, code)).tobytes()

    return encode


def _make_jpeg(quality: int) -> Encoder:
    params = [int(cv2.IMWRITE_JPEG_QUALITY), max(1, min(100, int(quality)))]

    def encode(frame: np.ndarray) -> bytes:
        _check_bgr(frame)
        ok, buf = cv2.imencode(".jpg", frame, params)
        if not ok:
            raise RuntimeError("Nén JPEG thất bại")
        return buf.tobytes()

    return encode


def make_encoder(
    fmt: str,
    *,
    yuv_range: str = "limited",
    big_endian: bool = False,
    jpeg_quality: int = 90,
) -> Encoder:
    """
    Tạo hàm encode BGR -> bytes cho định dạng `fmt`.

    Args:
        fmt: uyvy | yuyv | rgb565 | bgr565 | rgb888 | bgr888 | rgba8888 | jpeg (hoặc alias).
        yuv_range: "limited" (16-235) hoặc "full" (0-255) — chỉ dùng cho YUV.
        big_endian: thứ tự byte cho định dạng 16-bit (rgb565/bgr565).
        jpeg_quality: 1..100 — chỉ dùng cho JPEG.
    """
    key = normalize_format(fmt)
    if key in ("uyvy", "yuyv"):
        if yuv_range not in _YUV_MATRICES:
            raise ValueError(f"yuv_range phải là 'limited' hoặc 'full' (nhận '{yuv_range}')")
        return _make_yuv422(key, yuv_range)
    if key == "rgb565":
        return _make_565(blue_high=False, big_endian=bool(big_endian))
    if key == "bgr565":
        return _make_565(blue_high=True, big_endian=bool(big_endian))
    if key == "rgb888":
        return _make_cvt(cv2.COLOR_BGR2RGB)
    if key == "bgr888":
        return _make_cvt(None)
    if key == "rgba8888":
        return _make_cvt(cv2.COLOR_BGR2RGBA)
    return _make_jpeg(jpeg_quality)


def convert_frame(frame: np.ndarray, fmt: str, **options) -> bytes:
    """Chuyển 1 khung hình (tiện cho thử nghiệm; khi stream hãy dùng make_encoder)."""
    return make_encoder(fmt, **options)(frame)
