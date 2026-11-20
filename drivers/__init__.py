"""
Drivers registry for AIO Lite Streamer.
Allows dynamic loading of driver classes based on device name.
"""

from typing import Dict, Type, Any
from .base_driver import BaseDriver
from .valkyrie_ms9132 import ValkyrieMS9132Driver
from .nzxt_kraken import NZXTKrakenDriver
from .thermalright_xx import ThermalrightDriver

# Registered driver catalog
DRIVER_REGISTRY: Dict[str, Type[BaseDriver]] = {
    "valkyrie_ms9132": ValkyrieMS9132Driver,
    "b360_gt": ValkyrieMS9132Driver,
    "nzxt_kraken": NZXTKrakenDriver,
    "thermalright_xx": ThermalrightDriver,
    "thermalright": ThermalrightDriver,
}


def get_driver(driver_name: str, options: Dict[str, Any] = None) -> BaseDriver:
    """
    Factory function to instantiate driver by device identifier.

    Args:
        driver_name: Name key in DRIVER_REGISTRY (e.g. "valkyrie_ms9132").
        options: Dictionary of driver configurations from config.json.

    Returns:
        Instance of BaseDriver.
    """
    key = driver_name.lower().strip()
    driver_cls = DRIVER_REGISTRY.get(key)

    if driver_cls is None:
        available = ", ".join(DRIVER_REGISTRY.keys())
        raise ValueError(f"Unknown device driver: '{driver_name}'. Available drivers: {available}")

    return driver_cls(options=options)


__all__ = [
    "BaseDriver",
    "ValkyrieMS9132Driver",
    "NZXTKrakenDriver",
    "ThermalrightDriver",
    "DRIVER_REGISTRY",
    "get_driver",
]
