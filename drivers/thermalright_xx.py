"""
Driver for Thermalright AIO series (Frozen Warframe, TR-Vision, Frozen Horizon).
Example implementation for community developers.
Supports RGB565 / JPEG payload framing over USB Bulk or Serial COM bridge.
"""

from typing import Optional, Dict, Any
from .base_driver import BaseDriver


class ThermalrightDriver(BaseDriver):
    """
    Driver template for Thermalright LCD screens.
    Resolution: typically 320x240 or 480x480.
    Format: RGB565 (16-bit color) or JPEG.
    """

    # Common Thermalright / CH340 / Custom USB IDs
    DEFAULT_VID = 0x1A86  # QinHeng CH340 / USB Serial or custom vendor
    DEFAULT_PID = 0x7523
    DEFAULT_WIDTH = 320
    DEFAULT_HEIGHT = 240
    DEFAULT_FPS = 30

    def __init__(self, options: Optional[Dict[str, Any]] = None):
        opts = options or {}
        super().__init__(
            name="Thermalright AIO (Generic/Warframe)",
            target_width=opts.get("width", self.DEFAULT_WIDTH),
            target_height=opts.get("height", self.DEFAULT_HEIGHT),
            color_format=opts.get("color_format", "rgb565"),
            fps=opts.get("fps", self.DEFAULT_FPS),
            options=opts,
        )

        self.vid = opts.get("vid", self.DEFAULT_VID)
        self.pid = opts.get("pid", self.DEFAULT_PID)
        self.simulation_mode = opts.get("simulation_mode", False)
        self.packet_header = bytes.fromhex(opts.get("header_hex", "AA550100"))

    def connect(self) -> bool:
        """Initialize connection to Thermalright display."""
        if self.simulation_mode:
            print(f"[{self.name}] SIMULATION MODE ENABLED: Virtual Thermalright connected.")
            self.is_connected = True
            return True

        # Template for hardware connection:
        # 1. If USB Bulk / PyUSB: find device by self.vid, self.pid
        # 2. If Serial COM (pyserial): open port (e.g., COM3) at 115200 or 921600 baud
        print(f"[{self.name}] Connecting to Thermalright display VID=0x{self.vid:04X}, PID=0x{self.pid:04X}...")
        print(f"[{self.name}] Note: Set 'simulation_mode': true in config.json if testing without hardware.")
        
        # Defaulting to simulation for template safety
        self.simulation_mode = True
        self.is_connected = True
        return True

    def send_frame(self, frame_bytes: bytes) -> bool:
        """
        Sends frame payload to Thermalright screen.
        Structure typically consists of:
        [Header Magic (e.g. 0xAA, 0x55)] + [Length (4 bytes)] + [Frame Data (RGB565)] + [Checksum]
        """
        if not self.is_connected:
            return False

        if self.simulation_mode:
            return True

        try:
            payload_len = len(frame_bytes)
            # Example framing:
            header = self.packet_header + payload_len.to_bytes(4, byteorder="little")
            packet = header + frame_bytes

            # TODO: Write to hardware transport (Serial write or USB bulk write)
            # self.serial_port.write(packet)
            return True
        except Exception as e:
            print(f"[{self.name}] Send frame failed: {e}")
            return False

    def disconnect(self) -> None:
        """Clean up handles."""
        self.is_connected = False
        print(f"[{self.name}] Disconnected.")
