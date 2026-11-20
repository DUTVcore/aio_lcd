"""
Driver for Valkyrie B360-GT AIO Cooler (MacroSilicon MS9132 USB Display Controller).
Uses USB Bulk Transfer to stream UYVY / YUV422 frames directly to the circular screen.
"""

import sys
import time
from typing import Optional, Dict, Any
from .base_driver import BaseDriver

try:
    import usb.core
    import usb.util
    HAS_PYUSB = True
except ImportError:
    HAS_PYUSB = False


class ValkyrieMS9132Driver(BaseDriver):
    """
    Driver for Valkyrie B360-GT AIO (MS9132 Bridge).
    Resolution: 480x480 (IPS Circle)
    Format: UYVY (YUV422 Interleaved)
    Transfer: USB Bulk OUT
    """

    # Typical USB Vendor and Product IDs for MacroSilicon MS9132 display controller
    DEFAULT_VID = 0x345F  # MacroSilicon VID (or customize via config)
    DEFAULT_PID = 0x9132  # MS9132 PID
    DEFAULT_WIDTH = 480
    DEFAULT_HEIGHT = 480
    DEFAULT_FPS = 30
    DEFAULT_CHUNK_SIZE = 16384  # 16KB bulk packets

    def __init__(self, options: Optional[Dict[str, Any]] = None):
        opts = options or {}
        super().__init__(
            name="Valkyrie B360-GT (MS9132)",
            target_width=opts.get("width", self.DEFAULT_WIDTH),
            target_height=opts.get("height", self.DEFAULT_HEIGHT),
            color_format="uyvy",
            fps=opts.get("fps", self.DEFAULT_FPS),
            options=opts,
        )

        self.vid = opts.get("vid", self.DEFAULT_VID)
        self.pid = opts.get("pid", self.DEFAULT_PID)
        self.chunk_size = opts.get("chunk_size", self.DEFAULT_CHUNK_SIZE)
        self.simulation_mode = opts.get("simulation_mode", False)

        self.device = None
        self.ep_out = None
        self.interface_num = 0

    def connect(self) -> bool:
        """Find device via PyUSB, set configuration, and claim OUT bulk endpoint."""
        if self.simulation_mode:
            print(f"[{self.name}] SIMULATION MODE ENABLED: Virtual connection established.")
            self.is_connected = True
            return True

        if not HAS_PYUSB:
            print(f"[{self.name}] ERROR: 'pyusb' is not installed. Run 'pip install pyusb'.")
            print(f"[{self.name}] Falling back to Simulation Mode for testing.")
            self.simulation_mode = True
            self.is_connected = True
            return True

        print(f"[{self.name}] Searching for USB device VID=0x{self.vid:04X}, PID=0x{self.pid:04X}...")

        try:
            self.device = usb.core.find(idVendor=self.vid, idProduct=self.pid)
            if self.device is None:
                print(f"[{self.name}] WARNING: Physical device 0x{self.vid:04X}:0x{self.pid:04X} not found.")
                print(f"[{self.name}] Tip: Check USB cable or verify VID/PID in config.json.")
                print(f"[{self.name}] Switching to Simulation Mode to verify video pipeline.")
                self.simulation_mode = True
                self.is_connected = True
                return True

            # Reset and detach kernel driver if necessary (Linux/WinUSB)
            try:
                if self.device.is_kernel_driver_active(0):
                    self.device.detach_kernel_driver(0)
            except Exception:
                pass

            self.device.set_configuration()
            cfg = self.device.get_active_configuration()
            intf = cfg[(0, 0)]

            # Locate Bulk OUT endpoint
            self.ep_out = usb.util.find_descriptor(
                intf,
                custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
                and usb.util.endpoint_type(e.bEndpointAddress) == usb.util.ENDPOINT_TYPE_BULK,
            )

            if self.ep_out is None:
                raise RuntimeError("Could not find Bulk OUT endpoint on Valkyrie MS9132.")

            self.is_connected = True
            print(f"[{self.name}] Successfully connected to Valkyrie MS9132! Endpoint: 0x{self.ep_out.bEndpointAddress:02X}")
            return True

        except Exception as e:
            print(f"[{self.name}] Failed to connect: {e}")
            print(f"[{self.name}] Note: On Windows, use Zadig to install WinUSB/libusb-win32 driver for this device.")
            print(f"[{self.name}] Continuing in Simulation Mode.")
            self.simulation_mode = True
            self.is_connected = True
            return True

    def send_frame(self, frame_bytes: bytes) -> bool:
        """
        Sends raw UYVY frame data to the MS9132 controller via bulk OUT endpoint.
        UYVY frame size = width * height * 2 bytes (e.g. 480*480*2 = 460,800 bytes).
        """
        if not self.is_connected:
            return False

        if self.simulation_mode:
            # Emulate transfer timing (no physical USB I/O)
            return True

        try:
            # Send bulk data in chunks to prevent USB buffer overflow
            total_len = len(frame_bytes)
            offset = 0

            while offset < total_len:
                chunk = frame_bytes[offset : offset + self.chunk_size]
                self.ep_out.write(chunk, timeout=1000)
                offset += len(chunk)

            return True
        except Exception as e:
            print(f"[{self.name}] Error streaming frame: {e}")
            return False

    def disconnect(self) -> None:
        """Release device handles."""
        if self.device is not None and not self.simulation_mode:
            try:
                usb.util.dispose_resources(self.device)
            except Exception:
                pass
        self.is_connected = False
        print(f"[{self.name}] Disconnected.")
