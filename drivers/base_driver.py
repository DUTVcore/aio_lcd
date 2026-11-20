"""
Base Driver (Abstract Base Class) for AIO LCD devices.
All hardware-specific drivers must inherit from BaseDriver.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import numpy as np

import sys
import os
# Ensure core is importable
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.color_utils import convert_frame


class BaseDriver(ABC):
    """
    Abstract interface for AIO LCD screen drivers.
    Community contributors: subclass this to add support for any new AIO cooler screen!
    """

    def __init__(
        self,
        name: str,
        target_width: int,
        target_height: int,
        color_format: str,
        fps: int = 30,
        options: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            name: Human-readable device name.
            target_width: Screen pixel width.
            target_height: Screen pixel height.
            color_format: 'uyvy', 'rgb565', 'jpeg', 'yuyv', etc.
            fps: Desired / supported refresh rate (FPS).
            options: Driver-specific dictionary config (VID, PID, chunk size, etc.).
        """
        self.name = name
        self.target_width = target_width
        self.target_height = target_height
        self.color_format = color_format.lower()
        self.fps = fps
        self.options = options or {}
        self.is_connected = False
        self.frames_sent = 0
        self.bytes_sent = 0

    @abstractmethod
    def connect(self) -> bool:
        """
        Locate USB device, claim interface, and initialize the LCD.
        Returns:
            True if connected and ready, False otherwise.
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """
        Release USB endpoints, close handles, and reset display if needed.
        """
        pass

    @abstractmethod
    def send_frame(self, frame_bytes: bytes) -> bool:
        """
        Send raw encoded frame bytes (matching self.color_format) to the device.
        Must handle protocol framing, chunking, and USB endpoints.

        Args:
            frame_bytes: Pre-converted byte payload.

        Returns:
            True on success, False on error.
        """
        pass

    def send_image(self, frame_bgr: np.ndarray) -> bool:
        """
        Helper method: Automatically converts OpenCV BGR numpy frame into
        the driver's native color_format, then dispatches to send_frame().
        """
        if not self.is_connected:
            return False

        # Convert using core color utilities
        encoded = convert_frame(frame_bgr, self.color_format)
        success = self.send_frame(encoded)

        if success:
            self.frames_sent += 1
            self.bytes_sent += len(encoded)

        return success

    def get_info(self) -> Dict[str, Any]:
        """Return diagnostic info for logging / CLI."""
        return {
            "name": self.name,
            "resolution": f"{self.target_width}x{self.target_height}",
            "color_format": self.color_format,
            "fps": self.fps,
            "is_connected": self.is_connected,
            "frames_sent": self.frames_sent,
            "bytes_sent": self.bytes_sent,
        }

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
