"""Modbus backend package for lab-executor-mcp."""

from lab_modbus_mcp.backend import ModbusBackend
from lab_modbus_mcp.mock_backend import MockModbusBackend

__version__ = "0.1.0"

__all__ = ["ModbusBackend", "MockModbusBackend", "__version__"]
