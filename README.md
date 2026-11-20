# ⚡ AIO Lite Streamer

**AIO Lite Streamer** là bộ công cụ mã nguồn mở siêu nhẹ, đa nền tảng bằng Python dùng để stream video và ảnh động trực tiếp lên màn hình LCD của các bộ tản nhiệt nước AIO (All-In-One Cooler).

Thay vì phải chạy các phần mềm chính hãng cồng kềnh (ngốn hàng trăm MB RAM và CPU chạy nền), dự án này giao tiếp trực tiếp với vi điều khiển màn hình qua giao thức USB (Bulk / HID / Serial) với độ trễ thấp và tối ưu tài nguyên tối đa.

---

## 📂 Cấu trúc thư mục

```text
AIO_Lite_Streamer/
│
├── core/
│   ├── media_engine.py      # Đọc video, crop, resize, đồng bộ FPS chính xác.
│   ├── color_utils.py       # Kho hàm chuyển đổi màu (UYVY, RGB565, JPEG, YUYV...).
│
├── drivers/                 # THƯ MỤC CỐT LÕI CHO CỘNG ĐỒNG ĐÓNG GÓP
│   ├── base_driver.py       # Bản thiết kế gốc (Abstract Base Class - ABC).
│   ├── valkyrie_ms9132.py   # Driver cho Valkyrie B360-GT (chip MacroSilicon MS9132).
│   ├── nzxt_kraken.py       # Driver mẫu cho NZXT Kraken (Z53/Z63/Z73, Elite).
│   └── thermalright_xx.py   # Driver mẫu cho Thermalright (Frozen Warframe, TR-Vision).
│
├── main.py                  # Load config -> Gọi đúng Driver -> Chạy luồng stream.
├── config.json              # Khai báo xài màn nào (VD: "device": "valkyrie_ms9132").
├── requirements.txt         # Thư viện Python cần thiết.
└── README.md                # Tài liệu hướng dẫn & kỹ thuật Sniffing gói tin USB.
```

---

## 🚀 Cài đặt & Chuẩn bị môi trường

### 1. Cài đặt Python Dependencies
Khuyến nghị sử dụng Python 3.9+:

```bash
pip install -r requirements.txt
```

> **Lưu ý:** Thư viện `pyusb` cần có backend `libusb-1.0.dll` trên Windows. Bạn có thể tải file DLL này từ [libusb releases](https://github.com/libusb/libusb/releases) và đặt vào thư mục `C:\Windows\System32` hoặc cùng cấp thư mục dự án.

### 2. Cấu hình Driver USB trên Windows (Bắt buộc cho PyUSB)
Windows mặc định sẽ gán màn hình AIO cho driver của hãng hoặc driver Generic USB. Để Python có thể can thiệp:
1. Tải công cụ **[Zadig](https://zadig.akeo.ie/)**.
2. Chọn `Options` -> tích chọn `List All Devices`.
3. Tìm thiết bị tản nhiệt của bạn (Ví dụ: `MS9132`, `Valkyrie LCD`, `Kraken Z`).
4. Tại mục target driver bên phải, chọn **WinUSB** (hoặc **libusb-win32**).
5. Bấm **Replace Driver** hoặc **Install Driver**.

---

## ⚙️ Cấu hình (`config.json`)

Mở file `config.json` để chọn thiết bị và video:

```json
{
  "device": "valkyrie_ms9132",
  "media": {
    "file_path": "assets/my_animation.mp4",
    "scale_mode": "crop",
    "loop": true,
    "target_fps": 30
  },
  "driver_options": {
    "vid": 13407,
    "pid": 37170,
    "width": 480,
    "height": 480,
    "fps": 30,
    "chunk_size": 16384,
    "simulation_mode": false
  },
  "preview_window": false
}
```

### Các tùy chọn `scale_mode`:
- `"crop"`: Cắt ảnh từ trung tâm để lấp đầy toàn bộ màn hình tròn/vuông (khuyến nghị cho màn AIO).
- `"fit"`: Giữ nguyên tỷ lệ video, thêm viền đen hai bên hoặc trên/dưới.
- `"stretch"`: Kéo giãn video cho vừa khít kích thước màn hình.

---

## 🎮 Cách chạy chương trình

Chạy trực tiếp với cấu hình mặc định:
```bash
python main.py
```

Các tham số mở rộng:
- Bật cửa sổ xem thử trước trên màn hình máy tính:
  ```bash
  python main.py --preview
  ```
- Chạy thử nghiệm chế độ giả lập (Simulation Mode - không cần cắm phần cứng):
  ```bash
  python main.py --sim
  ```
- Chỉ định video khác:
  ```bash
  python main.py -v path/to/video.mp4
  ```

---

## 🛠️ HƯỚNG DẪN CỘNG ĐỒNG: CÁCH BẮT GÓI TIN (SNIFFING) ĐỂ THÊM DRIVER MỚI

Nếu bạn sở hữu một mẫu tản nhiệt AIO khác (Thermalright, ID-Cooling, Lian Li, Asus ROG, DeepCool...) và muốn viết driver để đưa vào dự án, hãy làm theo hướng dẫn từng bước dưới đây:

### Bước 1: Chuẩn bị công cụ bắt gói tin
1. Tải và cài đặt **[Wireshark](https://www.wireshark.org/)**.
2. Trong quá trình cài đặt, **BẮT BUỘC** tích chọn cài đặt thêm tiện ích **USBPcap**.
3. Khởi động lại máy tính để USBPcap driver có hiệu lực.

### Bước 2: Xác định cổng USB của màn hình AIO
1. Mở **Device Manager** trên Windows.
2. Tìm mục `Universal Serial Bus controllers` hoặc `Human Interface Devices`.
3. Chuột phải vào màn hình tản nhiệt của bạn -> `Properties` -> Thẻ `Details` -> Chọn `Hardware Ids`.
4. Ghi lại:
   - **VID (Vendor ID)**: Ví dụ `VID_345F` (hệ Hex).
   - **PID (Product ID)**: Ví dụ `PID_9132` (hệ Hex).

### Bước 3: Bắt gói tin truyền video với Wireshark
1. Mở **Wireshark**.
2. Tại màn hình chào, bạn sẽ thấy các interface tên là `USBPcap1`, `USBPcap2`, v.v.
3. Chọn interface mà thiết bị AIO đang cắm (hoặc mở lần lượt từng USBPcap).
4. Mở phần mềm chính hãng của tản nhiệt (Valkyrie Control Center, NZXT CAM, v.v.).
5. Đổi hình nền hoặc truyền 1 đoạn video ngắn lên màn hình.
6. Ngay lập tức trong Wireshark sẽ xuất hiện hàng ngàn gói tin liên tục được gửi đi. Nhấn nút **Stop** (nút màu đỏ) trên thanh công cụ Wireshark để dừng bắt.

### Bước 4: Phân tích cấu trúc gói tin (Reverse Engineering)

Gõ vào thanh bộ lọc (Filter) của Wireshark:
```wireshark
usb.transfer_type == 0x03
```
*(Nếu là giao thức HID Interrupt, dùng `usb.transfer_type == 0x01`)*

Kiểm tra các thông số kỹ thuật sau:
1. **Endpoint Address (Hướng gửi dữ liệu OUT):**
   - Xem trường `Endpoint: 0x01, Direction: OUT` hoặc `0x02 OUT`. Đây là endpoint ta sẽ ghi dữ liệu vào trong Python.
2. **Kích thước Payload mỗi frame:**
   - Ví dụ màn hình 480x480:
     - Nếu payload = `480 * 480 * 2 = 460,800 bytes` -> Dữ liệu là **UYVY** hoặc **RGB565** (16-bit).
     - Nếu payload = `480 * 480 * 3 = 691,200 bytes` -> Dữ liệu là **RGB24 / BGR24**.
     - Nếu kích thước thay đổi linh hoạt theo từng frame và bắt đầu bằng các byte hex `FF D8` -> Định dạng là **JPEG**!
3. **Magic Header / Chunk Framing:**
   - Quan sát xem trước khi gửi ảnh, phần mềm có gửi một gói tin nhỏ (ví dụ 64 bytes) bắt đầu bằng các byte cố định (Magic bytes như `0xAA 0x55` hay `0x12 0xFA`) chứa thông tin độ dài frame hay không.
   - Kích thước mỗi chunk USB gửi đi là bao nhiêu (512 bytes, 1024 bytes, 4096 bytes, hay 16384 bytes).

### Bước 5: Viết Driver mới

1. Tạo file mới trong thư mục `drivers/`, ví dụ: `drivers/my_aio_display.py`.
2. Kế thừa class `BaseDriver` từ `drivers/base_driver.py`:

```python
from drivers.base_driver import BaseDriver
import usb.core
import usb.util

class MyAIODisplayDriver(BaseDriver):
    def __init__(self, options=None):
        opts = options or {}
        super().__init__(
            name="My Cool AIO Display",
            target_width=480,
            target_height=480,
            color_format="uyvy",  # Hoặc 'rgb565', 'jpeg'...
            fps=30,
            options=opts
        )
        self.vid = 0xXXXX
        self.pid = 0xYYYY
        self.dev = None
        self.ep_out = None

    def connect(self) -> bool:
        self.dev = usb.core.find(idVendor=self.vid, idProduct=self.pid)
        if self.dev is None:
            return False
        self.dev.set_configuration()
        # Tìm endpoint OUT
        # ...
        self.is_connected = True
        return True

    def send_frame(self, frame_bytes: bytes) -> bool:
        if not self.is_connected:
            return False
        # Gửi dữ liệu ra endpoint OUT
        self.ep_out.write(frame_bytes, timeout=1000)
        return True

    def disconnect(self) -> None:
        if self.dev:
            usb.util.dispose_resources(self.dev)
        self.is_connected = False
```

3. Đăng ký driver mới vào `drivers/__init__.py`:
```python
from .my_aio_display import MyAIODisplayDriver

DRIVER_REGISTRY["my_cooler"] = MyAIODisplayDriver
```

4. Trong `config.json`, đổi `"device": "my_cooler"` và thưởng thức!

---

## 🤝 Đóng góp (Contributing)
Các đóng góp thêm driver mới từ cộng đồng cho các dòng tản nhiệt nước AIO luôn được hoan nghênh nồng nhiệt! Hãy mở một Pull Request với file driver của bạn trong thư mục `drivers/`.
