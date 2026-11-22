# ⚡ AIO Lite Streamer

**AIO Lite Streamer** là công cụ Python mã nguồn mở siêu nhẹ dùng để stream video, GIF và ảnh tĩnh trực tiếp lên màn hình LCD của các bộ tản nhiệt nước AIO (All-In-One Cooler).

Thay vì phải chạy phần mềm chính hãng nặng nề ngốn hàng trăm MB RAM và CPU chạy nền, dự án giao tiếp trực tiếp với chip điều khiển màn hình qua USB, đồng thời **cache toàn bộ vòng lặp đã encode vào RAM** để từ vòng lặp thứ 2 trở đi mức tiêu thụ CPU gần như bằng `0%`.

---

## 📂 Cấu trúc dự án

```text
AIO_Lite_Streamer/
│
├── core/
│   ├── media_engine.py      # Luồng nền: đọc video/ảnh, xoay, crop/fit/stretch, giảm FPS & cache RAM.
│   ├── color_utils.py       # Bộ encoder màu biên dịch sẵn (UYVY, YUYV, RGB565, BGR565, RGBA, JPEG...).
│   ├── usb_transport.py     # Lớp giao tiếp PyUSB/libusb dùng chung + bộ đọc chuỗi hex & control transfer.
│   └── __init__.py
│
├── drivers/                 # THƯ MỤC CỐT LÕI CHO CỘNG ĐỒNG (tự động phát hiện khi thêm file mới)
│   ├── base_driver.py       # Bản thiết kế gốc (Abstract Base Class - BaseDriver).
│   ├── valkyrie_ms9132.py   # Driver cho Valkyrie B360-GT (chip MacroSilicon MS9132 - giao thức ms912x/raw).
│   ├── nzxt_kraken.py       # Driver mẫu cho NZXT Kraken (Z53/Z63/Z73, Kraken 2023, Elite).
│   ├── thermalright_xx.py   # Driver USB Bulk tổng quát (cấu hình header/length/footer trực tiếp từ JSON).
│   └── __init__.py          # Tự động quét & đăng ký mọi lớp kế thừa BaseDriver.
│
├── tests/
│   └── test_core.py         # Bộ unit test kiểm tra chuyển đổi màu, đóng gói giao thức & MediaEngine.
│
├── main.py                  # Điểm vào CLI: đọc config -> kết nối driver -> stream & tự kết nối lại.
├── config.json              # File cấu hình thiết bị, video và chuỗi lệnh khởi tạo USB.
├── requirements.txt         # Danh sách thư viện Python.
└── README.md                # Hướng dẫn sử dụng & kỹ thuật bắt gói tin USB (Sniffing).
```

---

## ✨ Điểm nổi bật về kiến trúc & tối ưu

1. **Giải mã luồng nền + Cache vòng lặp vào RAM (`cache_mb`)**:
   - Việc đọc video, xoay, cắt khung và chuyển đổi hệ màu chạy trên worker thread riêng, không chặn luồng gửi USB.
   - Nếu 1 vòng lặp video sau khi encode nhỏ hơn `cache_mb` (mặc định `256 MB`), toàn bộ payload sẽ được giữ trong RAM — các vòng lặp tiếp theo không cần giải mã hay chuyển màu lại.
2. **Chuyển đổi màu chuẩn phần cứng (`core/color_utils.py`)**:
   - Hỗ trợ **UYVY / YUYV (BT.601)** với cả dải màu `limited` (`Y: 16..235`, chuẩn chip cầu USB/HDMI như MS9132) và `full` (`0..255`).
   - Hỗ trợ **RGB565 / BGR565** (Little-Endian & Big-Endian), **RGB888 / BGR888 / RGBA8888** và **JPEG**.
3. **Không cần copy `libusb-1.0.dll` thủ công**:
   - Tích hợp `libusb-package` tự nạp backend `libusb` trên Windows.
4. **Hỗ trợ `init_sequence` ngay trong `config.json`**:
   - Nhiều màn hình AIO cần một vài lệnh USB Control Transfer để bật màn hình hoặc đặt độ phân giải trước khi nhận luồng Bulk. Bạn có thể dán trực tiếp các lệnh bắt được từ Wireshark vào `config.json` mà không cần sửa code.

---

## 🚀 Cài đặt

### 1. Cài đặt thư viện Python (Python 3.9+)

```bash
pip install -r requirements.txt
```

### 2. Gán Driver WinUSB trên Windows (khi chạy với phần cứng thật)
Để Python (`pyusb`) gửi dữ liệu trực tiếp tới màn hình:
1. Tắt phần mềm điều khiển gốc của hãng (tránh tranh chấp thiết bị USB).
2. Tải và mở **[Zadig](https://zadig.akeo.ie/)**.
3. Chọn `Options` -> `List All Devices`.
4. Chọn thiết bị màn hình AIO (ví dụ `MS9132`, `USB Display`, v.v.).
5. Chọn driver đích là **WinUSB** rồi bấm **Replace Driver** / **Install Driver**.

---

## 🎮 Cách sử dụng

```bash
# Chạy theo config.json
python main.py

# Chạy thử ở chế độ giả lập + mở cửa sổ xem trước trên màn hình máy tính (không cần cắm màn AIO)
python main.py --sim --preview

# Chọn nhanh file video hoặc ảnh tĩnh, giới hạn FPS và góc xoay
python main.py -v assets/anime.mp4 --fps 24 --rotate 90

# Liệt kê tất cả các driver hiện có trong thư mục drivers/
python main.py --list-drivers
```

---

## ⚙️ Cấu hình (`config.json`)

```json
{
  "device": "valkyrie_ms9132",
  "simulate": false,
  "preview": false,
  "log_level": "INFO",
  "stats_interval": 5,

  "media": {
    "source": "test_pattern",
    "scale_mode": "crop",
    "rotate": 0,
    "loop": true,
    "fps": 30,
    "static_fps": 1,
    "cache_mb": 256,
    "prefetch": 3,
    "hw_decode": false
  },

  "driver_options": {
    "vid": "0x345F",
    "pid": "0x9132",
    "width": 480,
    "height": 480,
    "frame_protocol": "ms912x",
    "yuv_range": "limited",
    "interface": 0,
    "endpoint_out": null,
    "chunk_size": 0,
    "timeout_ms": 1000,
    "init_sequence": [],
    "deinit_sequence": []
  },

  "reconnect": {
    "enabled": true,
    "delay_sec": 2,
    "max_attempts": 0
  }
}
```

### Giải thích các tùy chọn chính:
- `media.source`: Đường dẫn tới file video (`.mp4`, `.gif`, `.avi`, `.webm`...), ảnh tĩnh (`.png`, `.jpg`, `.webp`...), hoặc `"test_pattern"` để phát vòng tròn động thử nghiệm.
- `media.scale_mode`:
  - `"crop"`: Cắt tâm giữ tỷ lệ để lấp đầy màn hình tròn/vuông (khuyên dùng).
  - `"fit"`: Giữ nguyên khung hình, thêm viền đen.
  - `"stretch"`: Kéo giãn vừa khít màn hình.
- `media.rotate`: Xoay khung hình `0`, `90`, `180`, hoặc `270` độ nếu bơm lắp xoay chiều.
- `media.cache_mb`: Dung lượng RAM tối đa (MB) để lưu sẵn 1 vòng lặp đã encode (`0` = tắt cache).

---

## 🛠️ HƯỚNG DẪN CỘNG ĐỒNG: BẮT GÓI TIN USB (SNIFFING) & THÊM MÀN HÌNH MỚI

### Bước 1: Tìm VID & PID của màn hình
1. Mở **Device Manager** -> tìm thiết bị màn hình dưới mục `Universal Serial Bus devices` hoặc `Human Interface Devices`.
2. Chuột phải -> `Properties` -> thẻ `Details` -> chọn `Hardware Ids`.
3. Ghi lại mã `VID_xxxx&PID_yyyy` (ví dụ `VID_345F&PID_9132` tương ứng `"vid": "0x345F", "pid": "0x9132"`).

### Bước 2: Bắt gói tin bằng Wireshark + USBPcap
1. Cài đặt **[Wireshark](https://www.wireshark.org/)** và tích chọn cài kèm **USBPcap**.
2. Mở Wireshark, chọn interface `USBPcap1` / `USBPcap2` tương ứng với cổng USB của màn hình.
3. Mở phần mềm chính hãng, đổi ảnh nền hoặc phát video khoảng 2–3 giây rồi bấm **Stop** trên Wireshark.

### Bước 3: Đọc hiểu gói tin trong Wireshark

1. **Tìm các lệnh khởi tạo (`URB_CONTROL`)**:
   - Lọc với:
     ```wireshark
     usb.transfer_type == 0x02 && usb.endpoint_address.direction == 0
     ```
   - Các gói gửi đi ngay trước khi luồng ảnh bắt đầu chính là `init_sequence`. Bạn có thể chép các trường `bmRequestType`, `bRequest`, `wValue`, `wIndex` và phần `Data Fragment` (hex) vào `driver_options.init_sequence`:
     ```json
     "init_sequence": [
       {
         "bmRequestType": "0x21",
         "bRequest": "0x09",
         "wValue": "0x0300",
         "wIndex": 0,
         "data": "a6 00 07 01 02 00 00 00",
         "delay_ms": 10
       }
     ]
     ```

2. **Tìm luồng dữ liệu khung hình (`URB_BULK out`)**:
   - Lọc với:
     ```wireshark
     usb.transfer_type == 0x03 && usb.endpoint_address.direction == 0
     ```
   - Kiểm tra kích thước và cấu trúc:
     - `W * H * 2` byte (ví dụ `480*480*2 = 460800`): Định dạng **UYVY**, **YUYV**, hoặc **RGB565**.
     - Nếu có thêm 8 byte đầu `FF 00 ...` và 8 byte cuối `FF C0 00 00 00 00 00 00`: Đó là giao thức **MacroSilicon `ms912x`** (đã tích hợp sẵn trong `valkyrie_ms9132`).
     - Nếu kích thước thay đổi theo từng khung và bắt đầu bằng `FF D8`...`FF D9`: Định dạng **JPEG**.

### Bước 4: Thử nghiệm nhanh hoặc viết Driver riêng

- **Cách 1 — Không cần viết code**: Dùng driver `thermalright_xx` (hoặc alias `generic_bulk`), khai báo `vid`, `pid`, `width`, `height`, `color_format`, `header_hex`, `length_field`, `footer_hex` trực tiếp trong `config.json`.
- **Cách 2 — Viết file driver mới**:
  Tạo file `drivers/<ten_man>.py` kế thừa `BaseDriver`:

```python
from core.usb_transport import UsbBulkDevice, parse_int
from .base_driver import BaseDriver


class MyCoolerDriver(BaseDriver):
    DRIVER_ID = "my_cooler"
    DISPLAY_NAME = "My Cooler LCD"
    DEFAULT_WIDTH = 480
    DEFAULT_HEIGHT = 480
    COLOR_FORMAT = "rgb565"
    VERIFIED = True

    def __init__(self, options=None, *, simulate: bool = False):
        super().__init__(options, simulate=simulate)
        self._usb = UsbBulkDevice(
            parse_int(self.options.get("vid"), 0x1234),
            parse_int(self.options.get("pid"), 0x5678),
        )

    def _open(self) -> None:
        self._usb.open()

    def _write(self, payload: bytes) -> None:
        self._usb.write(payload)

    def _close(self) -> None:
        self._usb.close()
```

Hệ thống sẽ **tự động nhận diện** driver mới ngay khi bạn chạy `python main.py --list-drivers`!
