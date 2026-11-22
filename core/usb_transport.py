"""
Lớp vận chuyển USB dùng chung cho các driver (PyUSB + libusb).

- Tự dùng libusb-1.0.dll đi kèm gói `libusb-package` nếu đã cài (Windows không cần copy DLL).
- Import pyusb kiểu "lazy": máy chưa cài pyusb vẫn chạy được chế độ giả lập / driver khác.
- Kèm các hàm đọc cấu hình: số dạng "0x345F", chuỗi hex "a6 00 07", chuỗi lệnh khởi tạo
  (control transfer) chép từ Wireshark.
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping, Optional

log = logging.getLogger(__name__)

_MISSING = object()


class TransportError(RuntimeError):
    """Lỗi giao tiếp USB."""


class DeviceNotFoundError(TransportError):
    """Không tìm thấy thiết bị với VID/PID đã cho."""


# --------------------------------------------------------------------------- #
#  Đọc cấu hình                                                                #
# --------------------------------------------------------------------------- #
def parse_int(value: Any, default: Any = _MISSING) -> Any:
    """Đọc số nguyên: 13407, "13407", "0x345F". Giá trị rỗng → default (nếu có)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if default is _MISSING:
            raise ValueError("Thiếu giá trị số")
        return default
    if isinstance(value, bool):
        raise ValueError(f"Giá trị số không hợp lệ: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        for base in (0, 10):
            try:
                return int(text, base)
            except ValueError:
                continue
    raise ValueError(f"Giá trị số không hợp lệ: {value!r}")


def parse_hex_bytes(value: Any) -> bytes:
    """Đọc dữ liệu byte: "a6 00 07", "a60007", "0xA6,0x00", [166, 0, 7]."""
    if value is None:
        return b""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        tokens = value.replace(",", " ").replace(":", " ").split()
        cleaned = []
        for token in tokens:
            if token.lower().startswith("0x"):
                token = token[2:]
            if len(token) == 1:
                token = "0" + token
            cleaned.append(token)
        try:
            return bytes.fromhex("".join(cleaned))
        except ValueError as exc:
            raise ValueError(f"Chuỗi hex không hợp lệ: {value!r}") from exc
    if isinstance(value, Iterable):
        return bytes(parse_int(v) for v in value)
    raise ValueError(f"Dữ liệu byte không hợp lệ: {value!r}")


@dataclass(frozen=True)
class ControlTransfer:
    """Một lệnh control transfer (tên trường giống cột trong Wireshark)."""

    bm_request_type: int
    b_request: int
    w_value: int = 0
    w_index: int = 0
    data: bytes = b""
    length: int = 0      # số byte cần đọc với lệnh IN (bmRequestType & 0x80)
    delay_ms: int = 0    # chờ sau lệnh

    @property
    def is_in(self) -> bool:
        return bool(self.bm_request_type & 0x80)


def parse_control_sequence(steps: Any) -> List[ControlTransfer]:
    """
    Đọc danh sách lệnh khởi tạo từ config.json, ví dụ:
        [{"bmRequestType": "0x21", "bRequest": "0x09", "wValue": "0x0300",
          "wIndex": 0, "data": "a6 00 07 01 02 00 00 00", "delay_ms": 10}]
    """
    result: List[ControlTransfer] = []
    for i, step in enumerate(steps or []):
        if not isinstance(step, Mapping):
            raise ValueError(f"init_sequence[{i}] phải là object JSON")
        try:
            result.append(
                ControlTransfer(
                    bm_request_type=parse_int(step["bmRequestType"]),
                    b_request=parse_int(step["bRequest"]),
                    w_value=parse_int(step.get("wValue"), 0),
                    w_index=parse_int(step.get("wIndex"), 0),
                    data=parse_hex_bytes(step.get("data")),
                    length=parse_int(step.get("wLength"), 0),
                    delay_ms=parse_int(step.get("delay_ms"), 0),
                )
            )
        except KeyError as exc:
            raise ValueError(f"init_sequence[{i}] thiếu khóa {exc}") from exc
    return result


# --------------------------------------------------------------------------- #
#  PyUSB                                                                       #
# --------------------------------------------------------------------------- #
def _import_pyusb():
    try:
        import usb.core
        import usb.util
    except ImportError as exc:
        raise TransportError("Thiếu thư viện 'pyusb'. Cài: pip install pyusb libusb-package") from exc
    return usb


def _libusb_backend():
    try:
        import libusb_package  # type: ignore

        return libusb_package.get_libusb1_backend()
    except Exception:
        return None  # để pyusb tự tìm libusb trên hệ thống


def _platform_hint() -> str:
    if sys.platform == "win32":
        return ("\n  → Windows: dùng Zadig cài driver WinUSB cho thiết bị (xem README), "
                "và tắt phần mềm gốc của hãng đang chiếm thiết bị.")
    return "\n  → Linux: thêm udev rule hoặc chạy với quyền phù hợp để truy cập thiết bị USB."


class UsbBulkDevice:
    """Mở thiết bị theo VID/PID, claim interface và ghi qua endpoint Bulk OUT."""

    def __init__(
        self,
        vid: int,
        pid: int,
        *,
        interface: int = 0,
        endpoint_out: Optional[int] = None,
        timeout_ms: int = 1000,
        chunk_size: int = 0,
    ):
        self.vid = vid
        self.pid = pid
        self.interface = interface
        self.endpoint_out = endpoint_out
        self.timeout_ms = timeout_ms
        self.chunk_size = max(0, chunk_size)  # 0 = gửi cả khung trong 1 lần (libusb tự chia gói)
        self._usb = None
        self._dev = None
        self._ep = None
        self._claimed = False
        self._detached = False

    @property
    def is_open(self) -> bool:
        return self._ep is not None

    @property
    def endpoint_address(self) -> Optional[int]:
        return None if self._ep is None else int(self._ep.bEndpointAddress)

    def open(self) -> None:
        if self.is_open:
            return
        usb = self._usb = _import_pyusb()
        try:
            dev = usb.core.find(idVendor=self.vid, idProduct=self.pid, backend=_libusb_backend())
        except usb.core.NoBackendError as exc:
            raise TransportError("Không tìm thấy libusb. Cài: pip install libusb-package") from exc
        if dev is None:
            raise DeviceNotFoundError(
                f"Không tìm thấy thiết bị USB {self.vid:04X}:{self.pid:04X}. "
                "Kiểm tra cáp USB nội bộ và VID/PID trong config.json."
            )
        self._dev = dev
        try:
            if sys.platform != "win32":
                try:
                    if dev.is_kernel_driver_active(self.interface):
                        dev.detach_kernel_driver(self.interface)
                        self._detached = True
                except (NotImplementedError, usb.core.USBError):
                    pass
            try:
                dev.set_configuration()
            except usb.core.USBError as exc:
                log.debug("set_configuration bỏ qua (có thể đã cấu hình sẵn): %s", exc)

            cfg = dev.get_active_configuration()
            intf = usb.util.find_descriptor(cfg, bInterfaceNumber=self.interface)
            if intf is None:
                raise TransportError(f"Thiết bị không có interface {self.interface}")
            usb.util.claim_interface(dev, self.interface)
            self._claimed = True

            if self.endpoint_out is not None:
                ep = usb.util.find_descriptor(intf, bEndpointAddress=self.endpoint_out)
            else:
                ep = usb.util.find_descriptor(
                    intf,
                    custom_match=lambda e: (
                        usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
                        and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK
                    ),
                )
            if ep is None:
                raise TransportError(
                    f"Không tìm thấy endpoint Bulk OUT trên interface {self.interface} "
                    "(đặt 'endpoint_out' trong config.json theo kết quả Wireshark)."
                )
            self._ep = ep
        except usb.core.USBError as exc:
            self.close()
            raise TransportError(f"Lỗi mở USB: {exc}{_platform_hint()}") from exc
        except Exception:
            self.close()
            raise

    def write(self, data: bytes) -> None:
        if self._ep is None:
            raise TransportError("Thiết bị USB chưa được mở")
        try:
            size = self.chunk_size
            if size and len(data) > size:
                for offset in range(0, len(data), size):
                    self._ep.write(data[offset:offset + size], self.timeout_ms)
            else:
                self._ep.write(data, self.timeout_ms)
        except self._usb.core.USBError as exc:
            raise TransportError(f"Ghi Bulk thất bại: {exc}") from exc

    def control_transfer(self, step: ControlTransfer) -> Optional[bytes]:
        if self._dev is None:
            raise TransportError("Thiết bị USB chưa được mở")
        try:
            if step.is_in:
                data = self._dev.ctrl_transfer(step.bm_request_type, step.b_request, step.w_value,
                                               step.w_index, step.length or len(step.data), self.timeout_ms)
                return bytes(data)
            self._dev.ctrl_transfer(step.bm_request_type, step.b_request, step.w_value,
                                    step.w_index, step.data, self.timeout_ms)
            return None
        except self._usb.core.USBError as exc:
            raise TransportError(
                f"Control transfer {step.bm_request_type:02X}/{step.b_request:02X} thất bại: {exc}"
            ) from exc

    def run_sequence(self, steps: Iterable[ControlTransfer]) -> None:
        for step in steps:
            self.control_transfer(step)
            if step.delay_ms:
                time.sleep(step.delay_ms / 1000.0)

    def close(self) -> None:
        usb, dev = self._usb, self._dev
        self._ep = None
        if dev is None:
            return
        if self._claimed:
            try:
                usb.util.release_interface(dev, self.interface)
            except Exception:
                pass
        if self._detached:
            try:
                dev.attach_kernel_driver(self.interface)
            except Exception:
                pass
        try:
            usb.util.dispose_resources(dev)
        except Exception:
            pass
        self._dev = None
        self._claimed = self._detached = False
