"""
Color conversion utilities for various AIO LCD display formats.
Supports UYVY, YUYV, RGB565, NV12, JPEG, and standard RGB/BGR formats.
"""

from typing import Optional
import numpy as np
import cv2


def bgr_to_rgb(frame: np.ndarray) -> np.ndarray:
    """Convert BGR (OpenCV default) to RGB."""
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def bgr_to_uyvy(frame: np.ndarray) -> bytes:
    """
    Convert BGR frame to UYVY (YUV 4:2:2 interleaved).
    Commonly used by MacroSilicon MS9132 and USB display capture bridges.
    Byte ordering: U0, Y0, V0, Y1, U2, Y2, V2, Y3...
    """
    try:
        uyvy = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_UYVY)
        return uyvy.tobytes()
    except Exception:
        # Fallback manual calculation if OpenCV lacks direct UYVY flag
        yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV)
        h, w, _ = yuv.shape
        # YUV422 packed UYVY format
        # U and V are sampled horizontally every 2 pixels
        y = yuv[:, :, 0]
        u = yuv[:, :, 1]
        v = yuv[:, :, 2]
        
        # Subsample U and V
        u_sub = u[:, 0::2]
        v_sub = v[:, 0::2]
        y0 = y[:, 0::2]
        y1 = y[:, 1::2]
        
        # Interleave into UYVY: [U0, Y0, V0, Y1]
        uyvy = np.empty((h, w * 2), dtype=np.uint8)
        uyvy[:, 0::4] = u_sub
        uyvy[:, 1::4] = y0
        uyvy[:, 2::4] = v_sub
        uyvy[:, 3::4] = y1
        return uyvy.tobytes()


def bgr_to_yuyv(frame: np.ndarray) -> bytes:
    """
    Convert BGR frame to YUYV / YUY2 (YUV 4:2:2 interleaved).
    Byte ordering: Y0, U0, Y1, V0, Y2, U2, Y3, V2...
    """
    try:
        yuyv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_YUY2)
        return yuyv.tobytes()
    except Exception:
        yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV)
        h, w, _ = yuv.shape
        y = yuv[:, :, 0]
        u = yuv[:, :, 1]
        v = yuv[:, :, 2]
        
        u_sub = u[:, 0::2]
        v_sub = v[:, 0::2]
        y0 = y[:, 0::2]
        y1 = y[:, 1::2]
        
        yuyv = np.empty((h, w * 2), dtype=np.uint8)
        yuyv[:, 0::4] = y0
        yuyv[:, 1::4] = u_sub
        yuyv[:, 2::4] = y1
        yuyv[:, 3::4] = v_sub
        return yuyv.tobytes()


def bgr_to_rgb565(frame: np.ndarray, byteorder: str = "little") -> bytes:
    """
    Convert BGR frame to RGB565 (16-bit per pixel: 5-bit R, 6-bit G, 5-bit B).
    Very common in embedded SPI/USB LCDs (ST7789, ILI9341, etc.).
    
    Args:
        frame: Input BGR image (H, W, 3).
        byteorder: "little" (default) or "big".
    """
    b = frame[:, :, 0].astype(np.uint16)
    g = frame[:, :, 1].astype(np.uint16)
    r = frame[:, :, 2].astype(np.uint16)

    # 5 bits R, 6 bits G, 5 bits B
    r5 = (r >> 3) & 0x1F
    g6 = (g >> 2) & 0x3F
    b5 = (b >> 3) & 0x1F

    rgb565 = (r5 << 11) | (g6 << 5) | b5

    if byteorder == "big":
        rgb565 = rgb565.byteswap()

    return rgb565.astype(np.uint16).tobytes()


def bgr_to_bgr565(frame: np.ndarray, byteorder: str = "little") -> bytes:
    """Convert BGR frame to BGR565 (16-bit per pixel)."""
    b = frame[:, :, 0].astype(np.uint16)
    g = frame[:, :, 1].astype(np.uint16)
    r = frame[:, :, 2].astype(np.uint16)

    b5 = (b >> 3) & 0x1F
    g6 = (g >> 2) & 0x3F
    r5 = (r >> 3) & 0x1F

    bgr565 = (b5 << 11) | (g6 << 5) | r5

    if byteorder == "big":
        bgr565 = bgr565.byteswap()

    return bgr565.astype(np.uint16).tobytes()


def bgr_to_jpeg(frame: np.ndarray, quality: int = 90) -> bytes:
    """
    Encode BGR frame as JPEG buffer.
    Commonly used by NZXT Kraken and some Thermalright displays.
    """
    quality = max(1, min(100, quality))
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    success, encoded_img = cv2.imencode(".jpg", frame, encode_params)
    if not success:
        raise ValueError("Failed to encode frame to JPEG")
    return encoded_img.tobytes()


def bgr_to_nv12(frame: np.ndarray) -> bytes:
    """
    Convert BGR frame to NV12 format.
    Y-plane followed by interleaved U/V subsampled 2x2.
    """
    nv12 = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420)
    # I420 is Y + U + V separate planes. Convert to NV12 (interleaved UV)
    h, w, _ = frame.shape
    y_size = h * w
    y = nv12[:h, :]
    u = nv12[h:h + h // 4, :].reshape(-1)
    v = nv12[h + h // 4:, :].reshape(-1)
    
    uv_interleaved = np.empty((h // 2, w), dtype=np.uint8)
    uv_interleaved.reshape(-1)[0::2] = u
    uv_interleaved.reshape(-1)[1::2] = v
    
    return y.tobytes() + uv_interleaved.tobytes()


def convert_frame(frame: np.ndarray, target_format: str, **kwargs) -> bytes:
    """
    Convenience router to convert a BGR frame into the requested format string.
    Supported: 'uyvy', 'yuyv', 'rgb565', 'bgr565', 'jpeg', 'rgb24', 'bgr24', 'nv12'.
    """
    fmt = target_format.lower().strip()
    if fmt == "uyvy":
        return bgr_to_uyvy(frame)
    elif fmt in ("yuyv", "yuy2"):
        return bgr_to_yuyv(frame)
    elif fmt == "rgb565":
        byteorder = kwargs.get("byteorder", "little")
        return bgr_to_rgb565(frame, byteorder=byteorder)
    elif fmt == "bgr565":
        byteorder = kwargs.get("byteorder", "little")
        return bgr_to_bgr565(frame, byteorder=byteorder)
    elif fmt in ("jpeg", "jpg"):
        quality = kwargs.get("quality", 90)
        return bgr_to_jpeg(frame, quality=quality)
    elif fmt == "rgb24":
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).tobytes()
    elif fmt == "bgr24":
        return frame.tobytes()
    elif fmt == "nv12":
        return bgr_to_nv12(frame)
    else:
        raise ValueError(f"Unsupported target color format: '{target_format}'")
