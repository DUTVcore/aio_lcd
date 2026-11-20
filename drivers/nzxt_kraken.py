"""
Driver for NZXT Kraken AIO series (Z53/Z63/Z73, Kraken 2023 / Elite).
Example implementation for community developers.
Protocol based on USB HID / Bulk transfer with JPEG frame compression.
"""

from typing import Optional, Dict, Any
from .base_driver import BaseDriver

try:
    import hid
    HAS_HID = True
except ImportError:
    HAS_HID = False


class NZXTKrakenDriver(BaseDriver):
    """
    Driver template for NZXT Kraken coolers.
    Resolution: 320x320 (Kraken Z) or 640x640 (Kraken Elite)
    Format: JPEG
    Protocol: USB HID / Bulk transfer with bucketed packet headers
    """

    NZXT_VID = 0x1E71
    PID_KRAKEN_Z = 0x3008      # Kraken Z53 / Z63 / Z73
    PID_KRAKEN_ELITE = 0x300E  # Kraken Elite 2023

    def __init__(self, options: Optional[Dict[str, Any]] = None):
        opts = options or {}
        model = opts.get("model", "kraken_z").lower()

        if model == "kraken_elite":
            width, height = 640, 640
            pid = self.PID_KRAKEN_ELITE
        else:
            width, height = 320, 320
            pid = self.PID_KRAKEN_Z

        super().__init__(
            name=f"NZXT Kraken ({model.upper()})",
            target_width=opts.get("width", width),
            target_height=opts.get("height", height),
            color_format="jpeg",
            fps=opts.get("fps", 30),
            options=opts,
        )

        self.vid = opts.get("vid", self.NZXT_VID)
        self.pid = opts.get("pid", pid)
        self.jpeg_quality = opts.get("jpeg_quality", 85)
        self.simulation_mode = opts.get("simulation_mode", False)
        self.device = None

    def connect(self) -> bool:
        """Connect to NZXT Kraken HID interface."""
        if self.simulation_mode:
            print(f"[{self.name}] SIMULATION MODE ENABLED: Virtual Kraken connected.")
            self.is_connected = True
            return True

        if not HAS_HID:
            print(f"[{self.name}] 'hidapi' library not found. Install with: pip install hidapi")
            print(f"[{self.name}] Switching to Simulation Mode.")
            self.simulation_mode = True
            self.is_connected = True
            return True

        try:
            print(f"[{self.name}] Opening HID device VID=0x{self.vid:04X}, PID=0x{self.pid:04X}...")
            self.device = hid.device()
            self.device.open(self.vid, self.pid)
            self.device.set_nonblocking(1)
            self.is_connected = True
            print(f"[{self.name}] Successfully opened NZXT Kraken HID!")
            return True
        except Exception as e:
            print(f"[{self.name}] Failed to open Kraken HID: {e}")
            print(f"[{self.name}] Falling back to Simulation Mode for demonstration.")
            self.simulation_mode = True
            self.is_connected = True
            return True

    def send_frame(self, frame_bytes: bytes) -> bool:
        """
        Sends JPEG frame to Kraken.
        In Kraken Z protocol:
        1. A start packet (e.g., [0x12, 0xfa, total_size...]) announces the incoming frame.
        2. Bucketed packets (often 512 bytes with sequence ID) follow with JPEG data.
        """
        if not self.is_connected:
            return False

        if self.simulation_mode:
            return True

        try:
            # Kraken bucketed transfer logic:
            packet_size = 512
            total_size = len(frame_bytes)

            # Start transaction header
            header = bytearray(64)
            header[0] = 0x12
            header[1] = 0xFA
            header[2] = (total_size >> 8) & 0xFF
            header[3] = total_size & 0xFF
            self.device.write(header)

            # Send payload chunks
            offset = 0
            bucket_idx = 0
            while offset < total_size:
                chunk = frame_bytes[offset : offset + (packet_size - 4)]
                packet = bytearray(packet_size)
                packet[0] = 0x12
                packet[1] = 0xFB
                packet[2] = bucket_idx & 0xFF
                packet[3] = len(chunk) & 0xFF
                packet[4 : 4 + len(chunk)] = chunk

                self.device.write(packet)
                offset += len(chunk)
                bucket_idx += 1

            return True
        except Exception as e:
            print(f"[{self.name}] Error sending frame: {e}")
            return False

    def disconnect(self) -> None:
        """Close HID handle."""
        if self.device is not None and not self.simulation_mode:
            try:
                self.device.close()
            except Exception:
                pass
        self.is_connected = False
        print(f"[{self.name}] Disconnected.")
