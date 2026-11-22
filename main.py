"""
AIO Lite Streamer — điểm vào chương trình.

Đọc config.json → tạo đúng driver → chạy luồng stream (giải mã/encode ở luồng nền,
luồng chính chỉ giữ nhịp FPS và gửi USB), tự kết nối lại khi USB bị ngắt.

    python main.py                     # chạy theo config.json
    python main.py --sim --preview     # thử không cần phần cứng, xem trên desktop
    python main.py -v video.mp4 --fps 24
    python main.py --list-drivers
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Any, Dict, Optional

# Luôn chạy được dù gọi main.py từ thư mục khác.
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.media_engine import TEST_PATTERN, FramePacer, MediaEngine  # noqa: E402
from core.usb_transport import TransportError  # noqa: E402
from drivers import available_drivers, get_driver, load_errors  # noqa: E402

log = logging.getLogger("aio")

PREVIEW_WINDOW = "AIO Lite Streamer - Preview (q/Esc de thoat)"

DEFAULT_CONFIG: Dict[str, Any] = {
    "device": "valkyrie_ms9132",
    "simulate": False,
    "preview": False,
    "log_level": "INFO",
    "stats_interval": 5,
    "media": {
        "source": TEST_PATTERN,
        "scale_mode": "crop",
        "rotate": 0,
        "loop": True,
        "fps": None,
        "static_fps": 1,
        "cache_mb": 256,
        "prefetch": 3,
        "hw_decode": False,
    },
    "driver_options": {},
    "reconnect": {"enabled": True, "delay_sec": 2.0, "max_attempts": 0},
}


class StopStreaming(Exception):
    """Người dùng yêu cầu dừng (đóng cửa sổ preview / hết --duration)."""


# --------------------------------------------------------------------------- #
#  Cấu hình                                                                    #
# --------------------------------------------------------------------------- #
def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str) -> Dict[str, Any]:
    user: Dict[str, Any] = {}
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8-sig") as f:
            try:
                user = json.load(f)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"config.json lỗi cú pháp (dòng {exc.lineno}, cột {exc.colno}): {exc.msg}")
    else:
        print(f"[!] Không thấy {path} — dùng cấu hình mặc định.")
    cfg = _merge(DEFAULT_CONFIG, user)

    # Tương thích khóa cũ.
    media, drv = cfg["media"], cfg["driver_options"]
    if "file_path" in media and "source" not in user.get("media", {}):
        media["source"] = media["file_path"]
    if "target_fps" in media and "fps" not in user.get("media", {}):
        media["fps"] = media["target_fps"]
    if "preview_window" in user and "preview" not in user:
        cfg["preview"] = user["preview_window"]
    if "simulation_mode" in drv and "simulate" not in user:
        cfg["simulate"] = drv["simulation_mode"]
    return cfg


def resolve_source(source: Optional[str], base_dir: str) -> str:
    if not source or source == TEST_PATTERN:
        return TEST_PATTERN
    path = os.path.expanduser(str(source))
    if not os.path.isabs(path):
        path = os.path.join(base_dir, path)
    if not os.path.isfile(path):
        log.warning("Không thấy file media '%s' → dùng hình test.", source)
        return TEST_PATTERN
    return path


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AIO Lite Streamer — stream video lên màn LCD tản nhiệt AIO")
    p.add_argument("-c", "--config", default=os.path.join(ROOT, "config.json"), help="đường dẫn config.json")
    p.add_argument("-d", "--device", help="ghi đè driver (vd valkyrie_ms9132)")
    p.add_argument("-v", "--video", help="ghi đè nguồn media (video/ảnh/test_pattern)")
    p.add_argument("--fps", type=float, help="ghi đè FPS")
    p.add_argument("--scale", choices=("crop", "fit", "stretch"), help="ghi đè scale_mode")
    p.add_argument("--rotate", type=int, choices=(0, 90, 180, 270), help="ghi đè góc xoay")
    p.add_argument("-s", "--sim", action="store_true", help="chế độ giả lập (không ghi USB)")
    p.add_argument("-p", "--preview", action="store_true", help="hiện cửa sổ xem trước")
    p.add_argument("--duration", type=float, default=0, help="tự dừng sau N giây (0 = chạy mãi)")
    p.add_argument("--list-drivers", action="store_true", help="liệt kê driver rồi thoát")
    p.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), help="mức log")
    return p.parse_args(argv)


def list_drivers() -> None:
    print("Driver hiện có:")
    for driver_id, cls in sorted(available_drivers().items()):
        status = "đã kiểm chứng" if cls.VERIFIED else "chưa kiểm chứng"
        aliases = f" (alias: {', '.join(cls.ALIASES)})" if cls.ALIASES else ""
        print(f"  {driver_id:<18} {cls.DISPLAY_NAME} — {cls.DEFAULT_WIDTH}x{cls.DEFAULT_HEIGHT} "
              f"{cls.COLOR_FORMAT.upper()} [{status}]{aliases}")
    for name, err in load_errors().items():
        print(f"  {name:<18} LỖI IMPORT: {err}")


# --------------------------------------------------------------------------- #
#  Stream                                                                      #
# --------------------------------------------------------------------------- #
def connect_with_retry(driver, reconnect: Dict[str, Any], first: bool) -> None:
    """Kết nối driver; lần đầu thất bại thì thoát luôn, sau đó thử lại theo cấu hình."""
    attempt = 0
    max_attempts = int(reconnect.get("max_attempts") or 0)
    delay = max(0.2, float(reconnect.get("delay_sec") or 2.0))
    while True:
        try:
            driver.connect()
            return
        except (TransportError, NotImplementedError) as exc:
            if first or not reconnect.get("enabled", True):
                raise
            attempt += 1
            if max_attempts and attempt >= max_attempts:
                raise
            log.warning("Kết nối lại thất bại (%d): %s — thử lại sau %.1fs", attempt, exc, delay)
            time.sleep(delay)


def run(cfg: Dict[str, Any], args: argparse.Namespace) -> int:
    media_cfg = cfg["media"]
    simulate = bool(args.sim or cfg.get("simulate"))
    preview = bool(args.preview or cfg.get("preview"))

    driver = get_driver(args.device or cfg["device"], cfg["driver_options"], simulate=simulate)
    source = resolve_source(args.video or media_cfg.get("source"), os.path.dirname(os.path.abspath(args.config)))
    fps = args.fps or media_cfg.get("fps") or driver.fps

    cv2 = None
    if preview:
        import cv2  # noqa: F811

        def encoder(frame):  # giữ lại khung BGR để hiện preview
            return frame, driver.encode(frame)
    else:
        encoder = driver.encode

    engine = MediaEngine(
        source,
        driver.width,
        driver.height,
        fps=fps,
        static_fps=float(media_cfg.get("static_fps") or 1),
        scale_mode=args.scale or media_cfg.get("scale_mode", "crop"),
        rotate=args.rotate if args.rotate is not None else int(media_cfg.get("rotate") or 0),
        loop=bool(media_cfg.get("loop", True)),
        encoder=encoder,
        prefetch=int(media_cfg.get("prefetch") or 3),
        cache_mb=float(media_cfg.get("cache_mb", 256)),
        hw_decode=bool(media_cfg.get("hw_decode", False)),
    )

    log.info("Thiết bị : %s | %dx%d %s%s", driver.name, driver.width, driver.height,
             driver.color_format.upper(), " | GIẢ LẬP" if simulate else "")
    log.info("Nguồn    : %s | %.2f fps%s", "hình test" if source == TEST_PATTERN else source, engine.fps,
             "" if engine.is_static else f" (gốc {engine.source_fps:.2f})")

    reconnect = cfg.get("reconnect") or {}
    stats_every = max(1.0, float(cfg.get("stats_interval") or 5))
    deadline = time.monotonic() + args.duration if args.duration > 0 else None
    pacer = FramePacer(engine.fps)
    errors = 0

    try:
        connect_with_retry(driver, reconnect, first=True)
        log.info("Đang stream — nhấn Ctrl+C để dừng.")
        t_stats, n_stats = time.perf_counter(), 0

        for item in engine.stream():
            if preview:
                frame, payload = item
                cv2.imshow(PREVIEW_WINDOW, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27) or cv2.getWindowProperty(PREVIEW_WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    raise StopStreaming
            else:
                payload = item

            pacer.wait()
            try:
                driver.send(payload)
                errors = 0
            except TransportError as exc:
                errors += 1
                log.error("Gửi khung thất bại: %s", exc)
                if not reconnect.get("enabled", True):
                    raise
                if errors >= 3:
                    log.warning("USB lỗi liên tục → kết nối lại thiết bị...")
                    driver.disconnect()
                    connect_with_retry(driver, reconnect, first=False)
                    errors = 0

            n_stats += 1
            now = time.perf_counter()
            if now - t_stats >= stats_every:
                log.info("FPS %5.1f | %6d khung | %8.1f MB đã gửi%s",
                         n_stats / (now - t_stats), driver.frames_sent, driver.bytes_sent / 1048576,
                         " | phát từ cache RAM" if engine.is_cached else "")
                t_stats, n_stats = now, 0
            if deadline and time.monotonic() >= deadline:
                raise StopStreaming
    except (KeyboardInterrupt, StopStreaming):
        log.info("Đang dừng...")
    finally:
        engine.close()
        driver.disconnect()
        if cv2 is not None:
            cv2.destroyAllWindows()
    log.info("Hoàn tất: %d khung, %.1f MB.", driver.frames_sent, driver.bytes_sent / 1048576)
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    cfg = load_config(args.config)
    level = args.log_level or str(cfg.get("log_level", "INFO")).upper()
    logging.basicConfig(level=getattr(logging, level, logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")

    if args.list_drivers:
        list_drivers()
        return 0
    try:
        return run(cfg, args)
    except (TransportError, NotImplementedError, FileNotFoundError, ValueError, RuntimeError) as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
