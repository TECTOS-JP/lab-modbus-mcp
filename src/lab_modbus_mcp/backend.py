"""MB-1 Modbus backend skeleton; transport arrives in MB-2."""

from __future__ import annotations

from collections.abc import Iterable

from lab_modbus_mcp.resource import parse_resource_name
from lab_modbus_mcp.wire import parse_wire_command


class ModbusBackendError(RuntimeError):
    """Base error for backend-level failures."""


class ModbusTransportUnavailable(ModbusBackendError):
    """A syntactically valid operation cannot run before MB-2 transport exists."""


class ModbusBackend:
    """Protocol-compatible, intentionally unconnected MB-1 backend.

    It validates resources and wire commands before reporting that transport is
    unavailable. No pymodbus import or bus access occurs in MB-1.
    """

    backend_id = "modbus"

    def __init__(self, resources: Iterable[str] | None = None) -> None:
        normalized: list[str] = []
        for resource in resources or ():
            parse_resource_name(resource)
            if resource in normalized:
                raise ValueError(f"duplicate Modbus resource: {resource!r}")
            normalized.append(resource)
        self._resources = tuple(normalized)
        self._closed = False

    async def list_resources(self) -> list[str]:
        return list(self._resources)

    def _validate(self, resource_name: str, command: str, *, read: bool) -> None:
        if self._closed:
            raise ModbusBackendError("backend is closed")
        parse_resource_name(resource_name)
        if resource_name not in self._resources:
            raise ModbusBackendError(f"resource is not configured: {resource_name!r}")
        parsed = parse_wire_command(command)
        if parsed.is_read != read:
            expected = "read" if read else "write"
            raise ModbusBackendError(f"{expected} method received the wrong operation")

    async def query(
        self,
        resource_name: str,
        command: str,
        timeout_ms: int = 5000,
        read_termination: str = "\n",
        write_termination: str = "\n",
    ) -> str:
        del timeout_ms, read_termination, write_termination
        self._validate(resource_name, command, read=True)
        raise ModbusTransportUnavailable("Modbus transport is scheduled for MB-2")

    async def write(
        self,
        resource_name: str,
        command: str,
        timeout_ms: int = 5000,
        read_termination: str = "\n",
        write_termination: str = "\n",
    ) -> None:
        del timeout_ms, read_termination, write_termination
        self._validate(resource_name, command, read=False)
        raise ModbusTransportUnavailable("Modbus transport is scheduled for MB-2")

    def close(self) -> None:
        self._closed = True


__all__ = [
    "ModbusBackend",
    "ModbusBackendError",
    "ModbusTransportUnavailable",
]
