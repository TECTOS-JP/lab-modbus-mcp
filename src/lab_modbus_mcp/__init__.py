"""Modbus backend package for lab-executor-mcp."""

from lab_modbus_mcp.backend import (
    ModbusBackend,
    ModbusBackendError,
    ModbusCommunicationError,
    ModbusDeviceError,
    ModbusTimeoutError,
)
from lab_modbus_mcp.mock_backend import MockModbusBackend

__version__ = "0.1.0"

__all__ = [
    "ModbusBackend",
    "ModbusBackendError",
    "ModbusCommunicationError",
    "ModbusDeviceError",
    "ModbusTimeoutError",
    "MockModbusBackend",
    "__version__",
]
