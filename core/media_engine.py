"""
Media Engine — đọc video/ảnh, xoay, crop/fit/stretch, giảm FPS và encode trong luồng nền.

Luồng xử lý:

    Nguồn (video / ảnh / test_pattern)
      → bỏ khung thừa (video 60fps phát ở 30fps vẫn đúng tốc độ)
      → FrameScaler (xoay + crop/fit/stretch, kế hoạch cắt được tính sẵn)
      → encoder của driver (UYVY / RGB565 / JPEG ...)
      → Queue → luồng chính gửi lên màn hình

Nếu cả vòng lặp video vừa với `cache_mb`, các khung đã encode được giữ trong RAM:
từ vòng thứ 2 trở đi không cần giải mã/encode nữa (CPU gần như bằng 0).
"""

from __future__ import annotations

import logging
import math
import os
import queue
import threading
import time
from typing import Any, Callable, Iterator, List, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)

TEST_PATTERN = "test_pattern"
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"})
SCALE_MODES = ("crop", "fit", "stretch")
_ROTATIONS = {
    0: None,
    90: cv2.ROTATE_90_CLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_COUNTERCLOCKWISE,
}
_END = object()

Encoder = Callable[[np.ndarray], Any]


def payload_nbytes(payload: Any) -> int:
    """Kích thước (byte) của payload: bytes, bytearray, memoryview hoặc ndarray."""
    if isinstance(payload, (bytes, bytearray)):
        return len(payload)
    if isinstance(payload, tuple):
        return sum(payload_nbytes(p) for p in payload)
    return int(getattr(payload, "nbytes", 0))


# --------------------------------------------------------------------------- #
#  Scale / crop / xoay                                                         #
# --------------------------------------------------------------------------- #
class FrameScaler:
    """
    Đưa khung hình về đúng (width, height) của màn hình.

    mode:
        crop    — cắt giữa để lấp đầy (khuyên dùng cho màn tròn AIO)
        fit     — giữ tỷ lệ, thêm viền đen
        stretch — kéo giãn
    rotate: 0 / 90 / 180 / 270 (theo chiều kim đồng hồ) khi màn lắp xoay.
    """

    def __init__(self, width: int, height: int, mode: str = "crop", rotate: int = 0):
        if width <= 0 or height <= 0:
            raise ValueError(f"Kích thước không hợp lệ: {width}x{height}")
        mode = str(mode).lower()
        if mode not in SCALE_MODES:
            raise ValueError(f"scale_mode phải là một trong {SCALE_MODES} (nhận '{mode}')")
        rotate = int(rotate) % 360
        if rotate not in _ROTATIONS:
            raise ValueError(f"rotate chỉ nhận 0/90/180/270 (nhận {rotate})")

        self.width = width
        self.height = height
        self.mode = mode
        self._rotate_code = _ROTATIONS[rotate]
        self._src_shape: Optional[Tuple[int, int]] = None
        self._plan: Tuple[Any, Tuple[int, int], Any] = (None, (width, height), None)

    def _make_plan(self, w: int, h: int):
        W, H = self.width, self.height
        crop = pad = None
        size = (W, H)

        if self.mode == "crop":
            if w * H > W * h:  # nguồn rộng hơn màn → cắt 2 bên
                new_w = max(1, round(h * W / H))
                x0 = (w - new_w) // 2
                crop = (0, h, x0, x0 + new_w)
            elif w * H < W * h:  # nguồn cao hơn màn → cắt trên/dưới
                new_h = max(1, round(w * H / W))
                y0 = (h - new_h) // 2
                crop = (y0, y0 + new_h, 0, w)
        elif self.mode == "fit":
            scale = min(W / w, H / h)
            sw = min(W, max(1, round(w * scale)))
            sh = min(H, max(1, round(h * scale)))
            size = (sw, sh)
            if (sw, sh) != (W, H):
                top, left = (H - sh) // 2, (W - sw) // 2
                pad = (top, H - sh - top, left, W - sw - left)
        return crop, size, pad

    def __call__(self, frame: np.ndarray) -> np.ndarray:
        if self._rotate_code is not None:
            frame = cv2.rotate(frame, self._rotate_code)

        h, w = frame.shape[:2]
        if self._src_shape != (h, w):  # chỉ tính lại khi kích thước nguồn đổi
            self._plan = self._make_plan(w, h)
            self._src_shape = (h, w)
        crop, size, pad = self._plan

        if crop is not None:
            y0, y1, x0, x1 = crop
            frame = frame[y0:y1, x0:x1]
        ch, cw = frame.shape[:2]
        if (cw, ch) != size:
            shrink = size[0] < cw or size[1] < ch
            frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA if shrink else cv2.INTER_LINEAR)
        if pad is not None:
            frame = cv2.copyMakeBorder(frame, *pad, cv2.BORDER_CONSTANT, value=(0, 0, 0))
        return np.ascontiguousarray(frame)


# --------------------------------------------------------------------------- #
#  Đồng bộ FPS                                                                 #
# --------------------------------------------------------------------------- #
class FramePacer:
    """Giữ nhịp gửi khung hình theo FPS, không bị trôi (drift) theo thời gian."""

    def __init__(self, fps: float):
        if fps <= 0:
            raise ValueError("fps phải > 0")
        self.interval = 1.0 / fps
        self._deadline: Optional[float] = None

    def wait(self) -> None:
        now = time.perf_counter()
        if self._deadline is None:
            self._deadline = now + self.interval
            return
        delay = self._deadline - now
        if delay > 0:
            time.sleep(delay)
            self._deadline += self.interval
        elif -delay > self.interval:
            # Trễ hơn 1 khung (máy bận / USB nghẽn): đặt lại mốc, không "đuổi" khung.
            self._deadline = now + self.interval
        else:
            self._deadline += self.interval


# --------------------------------------------------------------------------- #
#  Nguồn khung hình                                                            #
# --------------------------------------------------------------------------- #
class _Source:
    fps: float = 30.0
    is_static: bool = False

    def read(self) -> Optional[np.ndarray]:
        raise NotImplementedError

    def skip(self, count: int) -> bool:
        for _ in range(count):
            if self.read() is None:
                return False
        return True

    def rewind(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class _ImageSource(_Source):
    is_static = True

    def __init__(self, path: str):
        # np.fromfile + imdecode: đọc được cả đường dẫn có dấu tiếng Việt trên Windows.
        data = np.fromfile(path, dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError(f"Không đọc được ảnh: {path}")
        self._image = image
        self._served = False
        self.fps = 1.0

    def read(self) -> Optional[np.ndarray]:
        if self._served:
            return None
        self._served = True
        return self._image

    def rewind(self) -> None:
        self._served = False


class _VideoSource(_Source):
    def __init__(self, path: str, hw_decode: bool = False):
        self._path = path
        self._hw_decode = hw_decode
        self._cap = self._open()
        fps = self._cap.get(cv2.CAP_PROP_FPS)
        self.fps = float(fps) if fps and math.isfinite(fps) and 1.0 <= fps <= 240.0 else 30.0

    def _open(self) -> "cv2.VideoCapture":
        cap = None
        if self._hw_decode and hasattr(cv2, "CAP_PROP_HW_ACCELERATION"):
            try:
                cap = cv2.VideoCapture(
                    self._path,
                    cv2.CAP_ANY,
                    [cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_ANY],
                )
            except cv2.error:
                cap = None
        if cap is None or not cap.isOpened():
            cap = cv2.VideoCapture(self._path)
        if not cap.isOpened():
            hint = ""
            if not self._path.isascii():
                hint = " (OpenCV trên Windows hay lỗi với đường dẫn có dấu — hãy đổi tên/thư mục không dấu)"
            raise RuntimeError(f"Không mở được video: {self._path}{hint}")
        return cap

    def read(self) -> Optional[np.ndarray]:
        ok, frame = self._cap.read()
        return frame if ok else None

    def skip(self, count: int) -> bool:
        # grab() bỏ qua bước chuyển màu/retrieve → nhẹ hơn read() nhiều.
        for _ in range(count):
            if not self._cap.grab():
                return False
        return True

    def rewind(self) -> None:
        # Mở lại thay vì seek: seek theo POS_FRAMES không tin cậy với nhiều codec/GIF.
        self._cap.release()
        self._cap = self._open()

    def close(self) -> None:
        self._cap.release()


class _PatternSource(_Source):
    """Hình test động sinh trực tiếp ở độ phân giải đích (không cần file video)."""

    def __init__(self, width: int, height: int, fps: float = 30.0, seconds: float = 4.0):
        self.fps = fps
        self._w, self._h = width, height
        self._count = max(1, int(fps * seconds))
        self._index = 0

        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        dist = np.sqrt((xx - width / 2) ** 2 + (yy - height / 2) ** 2) / (max(width, height) / 2)
        glow = np.clip(1.0 - dist, 0.0, 1.0) * 70.0
        self._background = np.dstack([glow, glow * 0.45, glow * 0.15]).astype(np.uint8)

    def read(self) -> Optional[np.ndarray]:
        if self._index >= self._count:
            return None
        frame = self._render(self._index)
        self._index += 1
        return frame

    def rewind(self) -> None:
        self._index = 0

    def _render(self, i: int) -> np.ndarray:
        w, h = self._w, self._h
        frame = self._background.copy()
        t = i / self._count
        center = (w // 2, h // 2)
        side = min(w, h)
        radius = max(4, side // 2 - max(4, side // 16))
        thick = max(2, side // 48)

        hue = np.uint8([[[int(180 * t) % 180, 255, 255]]])
        color = tuple(int(c) for c in cv2.cvtColor(hue, cv2.COLOR_HSV2BGR)[0, 0])
        start = int(360 * t)
        cv2.circle(frame, center, radius, (60, 60, 60), max(1, thick // 2), cv2.LINE_AA)
        cv2.ellipse(frame, center, (radius, radius), 0, start, start + 100, color, thick, cv2.LINE_AA)
        cv2.ellipse(frame, center, (radius - 3 * thick, radius - 3 * thick), 0,
                    -2 * start, -2 * start + 60, (255, 200, 80), thick, cv2.LINE_AA)

        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = side / 600
        for text, dy, s, col in (
            ("AIO LITE STREAMER", -0.04, scale, (255, 255, 255)),
            (f"{w}x{h}  #{i:04d}", 0.08, scale * 0.75, (180, 180, 180)),
        ):
            (tw, th), _ = cv2.getTextSize(text, font, s, 1 + int(s))
            org = (center[0] - tw // 2, center[1] + int(dy * h) + th // 2)
            cv2.putText(frame, text, org, font, s, col, 1 + int(s), cv2.LINE_AA)
        return frame


# --------------------------------------------------------------------------- #
#  Media Engine                                                                #
# --------------------------------------------------------------------------- #
class MediaEngine:
    """
    Giải mã + scale + encode trong luồng nền và trả payload qua `stream()`.

    Args:
        source: đường dẫn video/ảnh, hoặc "test_pattern".
        width, height: độ phân giải màn hình.
        fps: FPS mong muốn (None = theo video). Không vượt quá FPS gốc của video.
        static_fps: tần số gửi lại với ảnh tĩnh.
        scale_mode: crop | fit | stretch.
        rotate: 0 | 90 | 180 | 270.
        loop: phát lặp.
        encoder: hàm frame BGR -> payload (thường là `driver.encode`).
        prefetch: số khung chuẩn bị sẵn trong hàng đợi.
        cache_mb: RAM tối đa để cache 1 vòng lặp đã encode (0 = tắt).
        hw_decode: thử giải mã phần cứng (OpenCV >= 4.5.2).
    """

    def __init__(
        self,
        source: str,
        width: int,
        height: int,
        *,
        fps: Optional[float] = None,
        static_fps: float = 1.0,
        scale_mode: str = "crop",
        rotate: int = 0,
        loop: bool = True,
        encoder: Optional[Encoder] = None,
        prefetch: int = 3,
        cache_mb: float = 256.0,
        hw_decode: bool = False,
    ):
        if static_fps <= 0:
            raise ValueError("static_fps phải > 0")
        if fps is not None and fps <= 0:
            raise ValueError("fps phải > 0")

        self.scaler = FrameScaler(width, height, scale_mode, rotate)
        self.width, self.height = width, height
        self.loop = bool(loop)
        self.encoder: Encoder = encoder or (lambda frame: frame)
        self._source = self._open_source(source, width, height, hw_decode)

        if self._source.is_static:
            self.fps = float(static_fps)
            self._step = 1.0
        else:
            src_fps = self._source.fps
            self.fps = min(float(fps), src_fps) if fps else src_fps
            self._step = src_fps / self.fps

        self._cache_budget = max(0, int(float(cache_mb) * 1024 * 1024))
        self._cache: Optional[List[Any]] = None
        self._queue: "queue.Queue[Any]" = queue.Queue(maxsize=max(1, int(prefetch)))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._error: Optional[BaseException] = None

    # ---------------------------------------------------------------- props --
    @property
    def is_static(self) -> bool:
        return self._source.is_static

    @property
    def source_fps(self) -> float:
        return self._source.fps

    @property
    def is_cached(self) -> bool:
        """True khi đang phát lại từ cache RAM (không còn giải mã)."""
        return bool(self._cache)

    # ------------------------------------------------------------- internal --
    @staticmethod
    def _open_source(source: str, width: int, height: int, hw_decode: bool) -> _Source:
        if source == TEST_PATTERN:
            return _PatternSource(width, height)
        if not os.path.isfile(source):
            raise FileNotFoundError(f"Không tìm thấy file media: {source}")
        if os.path.splitext(source)[1].lower() in IMAGE_EXTENSIONS:
            return _ImageSource(source)
        return _VideoSource(source, hw_decode)

    def _one_pass(self) -> Iterator[np.ndarray]:
        """Đọc 1 vòng nguồn, bỏ bớt khung khi FPS nguồn > FPS đích."""
        src_pos = 0
        out_index = 0
        while not self._stop.is_set():
            wanted = int(out_index * self._step + 0.5)
            if wanted > src_pos:
                if not self._source.skip(wanted - src_pos):
                    return
                src_pos = wanted
            frame = self._source.read()
            if frame is None:
                return
            src_pos += 1
            out_index += 1
            yield frame

    def _put(self, item: Any) -> bool:
        while not self._stop.is_set():
            try:
                self._queue.put(item, timeout=0.1)
                return True
            except queue.Full:
                continue
        return False

    def _worker(self) -> None:
        try:
            cache: Optional[List[Any]] = [] if (self.loop and self._cache_budget) else None
            cache_bytes = 0
            first_pass = True
            while not self._stop.is_set():
                produced = 0
                for frame in self._one_pass():
                    item = self.encoder(self.scaler(frame))
                    produced += 1
                    if cache is not None:
                        cache_bytes += payload_nbytes(item)
                        if cache_bytes > self._cache_budget:
                            log.info("Video lớn hơn cache_mb=%.0f MB → giải mã liên tục (không cache).",
                                     self._cache_budget / 1048576)
                            cache = None
                        else:
                            cache.append(item)
                    if not self._put(item):
                        return
                if produced == 0:
                    if first_pass:
                        raise RuntimeError("Nguồn media không có khung hình nào")
                    raise RuntimeError("Không đọc lại được nguồn media sau khi tua về đầu")
                if not self.loop:
                    return
                if cache is not None:
                    self._cache = cache
                    log.info("Đã cache %d khung (%.1f MB) vào RAM → các vòng sau không cần giải mã.",
                             len(cache), cache_bytes / 1048576)
                    return
                first_pass = False
                self._source.rewind()
        except BaseException as exc:  # chuyển lỗi sang luồng chính
            self._error = exc
        finally:
            self._source.close()
            self._put(_END)

    # --------------------------------------------------------------- public --
    def stream(self) -> Iterator[Any]:
        """Trả lần lượt payload đã encode. Chỉ gọi một lần cho mỗi engine."""
        if self._thread is not None:
            raise RuntimeError("stream() chỉ được gọi một lần")
        self._thread = threading.Thread(target=self._worker, name="media-worker", daemon=True)
        self._thread.start()

        while True:
            try:
                item = self._queue.get(timeout=0.2)  # có timeout để Ctrl+C phản hồi trên Windows
            except queue.Empty:
                if self._stop.is_set():
                    return
                continue
            if item is _END:
                break
            yield item

        if self._error is not None:
            raise self._error
        cache = self._cache
        while cache and not self._stop.is_set():
            yield from cache

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        if thread is None:
            self._source.close()
        self._cache = None
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def __enter__(self) -> "MediaEngine":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
