"""
Test nhanh phần lõi (không cần phần cứng):   python -m pytest -q
"""

import os
import struct
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.color_utils import frame_size, make_encoder  # noqa: E402
from core.media_engine import TEST_PATTERN, FrameScaler, MediaEngine  # noqa: E402
from core.usb_transport import parse_control_sequence, parse_hex_bytes, parse_int  # noqa: E402
from drivers import available_drivers, get_driver  # noqa: E402


def solid(w, h, bgr):
    return np.full((h, w, 3), bgr, dtype=np.uint8)


# ---------------------------------------------------------------- màu ------
@pytest.mark.parametrize("fmt", ["uyvy", "yuyv", "rgb565", "bgr565", "rgb888", "bgr888", "rgba8888"])
def test_raw_sizes(fmt):
    assert len(make_encoder(fmt)(solid(32, 16, (10, 20, 30)))) == frame_size(fmt, 32, 16)


def test_uyvy_white_black_limited():
    enc = make_encoder("uyvy")
    assert enc(solid(2, 1, (255, 255, 255))) == bytes([128, 235, 128, 235])
    assert enc(solid(2, 1, (0, 0, 0))) == bytes([128, 16, 128, 16])


def test_yuyv_order_full_range():
    assert make_encoder("yuyv", yuv_range="full")(solid(2, 1, (255, 255, 255))) == bytes([255, 128, 255, 128])


def test_uyvy_red_chroma():
    u, y0, v, y1 = make_encoder("uyvy")(solid(2, 1, (0, 0, 255)))
    assert (y0, y1) == (81, 81) and u == 90 and v == 240


def test_rgb565_endianness():
    red = solid(1, 1, (0, 0, 255))
    assert make_encoder("rgb565")(red) == b"\x00\xf8"
    assert make_encoder("rgb565", big_endian=True)(red) == b"\xf8\x00"
    assert make_encoder("bgr565")(red) == b"\x1f\x00"


def test_jpeg_magic():
    assert make_encoder("jpeg")(solid(16, 16, (0, 128, 255)))[:2] == b"\xff\xd8"


def test_odd_width_rejected():
    with pytest.raises(ValueError):
        make_encoder("uyvy")(solid(3, 2, (0, 0, 0)))


# ------------------------------------------------------------- scaler ------
@pytest.mark.parametrize("mode", ["crop", "fit", "stretch"])
@pytest.mark.parametrize("src", [(1920, 1080), (720, 1280), (480, 480), (100, 37)])
def test_scaler_output_shape(mode, src):
    out = FrameScaler(480, 480, mode)(solid(*src, (1, 2, 3)))
    assert out.shape == (480, 480, 3) and out.flags["C_CONTIGUOUS"]


def test_fit_letterbox_is_black():
    out = FrameScaler(100, 100, "fit")(solid(200, 100, (255, 255, 255)))
    assert out[0, 50].tolist() == [0, 0, 0] and out[50, 50].tolist() == [255, 255, 255]


def test_rotate_90():
    src = np.zeros((10, 20, 3), np.uint8)
    assert FrameScaler(10, 20, "stretch", rotate=90)(src).shape == (20, 10, 3)


# ------------------------------------------------------------- parsing -----
def test_parsers():
    assert parse_int("0x345F") == 0x345F and parse_int(13407) == 13407 and parse_int(None, 7) == 7
    assert parse_hex_bytes("a6 00 07") == b"\xa6\x00\x07" == parse_hex_bytes("0xA6,0x00,0x7")
    (step,) = parse_control_sequence([{"bmRequestType": "0x21", "bRequest": 9, "wValue": "0x0300",
                                       "data": "a6 00 07 01 02"}])
    assert (step.bm_request_type, step.b_request, step.w_value, step.data) == (0x21, 9, 0x300, b"\xa6\x00\x07\x01\x02")


# ------------------------------------------------------------- drivers -----
def test_registry_discovers_drivers():
    ids = available_drivers()
    assert {"valkyrie_ms9132", "nzxt_kraken", "thermalright_xx"} <= set(ids)


def test_valkyrie_ms912x_payload():
    drv = get_driver("b360_gt", {}, simulate=True)
    payload = drv.encode(solid(480, 480, (0, 0, 0)))
    assert len(payload) == 8 + 480 * 480 * 2 + 8
    assert payload[:8] == struct.pack(">HBHBH", 0xFF00, 0, 0, 30, 480)
    assert payload[-8:] == b"\xff\xc0" + b"\x00" * 6


def test_generic_bulk_length_header():
    drv = get_driver("thermalright_xx", {"width": 4, "height": 2, "header_hex": "AA 55",
                                         "length_field": "le32"}, simulate=True)
    payload = drv.encode(solid(4, 2, (0, 0, 0)))
    assert payload[:6] == b"\xaa\x55" + struct.pack("<I", 16) and len(payload) == 6 + 16


def test_simulated_send_counts():
    with get_driver("nzxt_kraken", {"model": "kraken_2023"}, simulate=True) as drv:
        drv.send_image(solid(240, 240, (0, 0, 0)))
        assert drv.frames_sent == 1 and drv.bytes_sent == 240 * 240 * 4


# -------------------------------------------------------------- engine -----
def test_engine_caches_test_pattern():
    drv = get_driver("valkyrie_ms9132", {"width": 64, "height": 48}, simulate=True)
    engine = MediaEngine(TEST_PATTERN, 64, 48, fps=30, encoder=drv.encode, cache_mb=64)
    try:
        frames = []
        for payload in engine.stream():
            frames.append(payload)
            if len(frames) == 130:  # pattern dài 120 khung → đã sang vòng 2
                break
        assert engine.is_cached
        assert frames[120] == frames[0] and frames[1] != frames[0]
    finally:
        engine.close()


def test_engine_frame_decimation(tmp_path):
    cv2 = pytest.importorskip("cv2")
    path = str(tmp_path / "clip.avi")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 60, (32, 32))
    if not writer.isOpened():
        pytest.skip("Không có codec MJPG")
    for i in range(60):
        writer.write(solid(32, 32, (i * 4, 0, 0)))
    writer.release()

    engine = MediaEngine(path, 32, 32, fps=30, loop=False)
    try:
        assert sum(1 for _ in engine.stream()) == 30
    finally:
        engine.close()
