"""In-memory Modbus backend for tests and backend conformance."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from lab_modbus_mcp.backend import ModbusBackendError
from lab_modbus_mcp.resource import parse_resource_name
from lab_modbus_mcp.wire import (
    WireCommand,
    decode_scaled_value,
    encode_scaled_value,
    parse_wire_command,
    register_count,
)


DEFAULT_MOCK_RESOURCE = "MODBUS::COM3::1"
CONFORMANCE_QUERY = "*IDN?"
CONFORMANCE_WRITE = "CONF"


class ModbusRegisterError(ModbusBackendError):
    """A requested mock register or bit has not been initialized."""


def _copy_registers(values: Mapping[int, int] | None, label: str) -> dict[int, int]:
    copied: dict[int, int] = {}
    for address, value in (values or {}).items():
        if (
            isinstance(address, bool)
            or not isinstance(address, int)
            or not 0 <= address <= 65535
        ):
            raise ValueError(f"{label} addresses must be integers from 0 to 65535")
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 0xFFFF
        ):
            raise ValueError(f"{label} values must be 16-bit unsigned words")
        copied[address] = value
    return copied


def _copy_bits(values: Mapping[int, bool] | None, label: str) -> dict[int, bool]:
    copied: dict[int, bool] = {}
    for address, value in (values or {}).items():
        if (
            isinstance(address, bool)
            or not isinstance(address, int)
            or not 0 <= address <= 65535
        ):
            raise ValueError(f"{label} addresses must be integers from 0 to 65535")
        if not isinstance(value, bool):
            raise ValueError(f"{label} values must be bool")
        copied[address] = value
    return copied


class MockModbusBackend:
    """A deterministic register map with no transport or raw-write helper API."""

    backend_id = "mock-modbus"

    def __init__(
        self,
        *,
        resources: Iterable[str] | None = None,
        holding_registers: Mapping[int, int] | None = None,
        input_registers: Mapping[int, int] | None = None,
        coils: Mapping[int, bool] | None = None,
        discrete_inputs: Mapping[int, bool] | None = None,
        initial_values: Mapping[str, int | float | bool] | None = None,
        allow_conformance_probes: bool = True,
    ) -> None:
        normalized: list[str] = []
        selected_resources = (
            (DEFAULT_MOCK_RESOURCE,) if resources is None else resources
        )
        for resource in selected_resources:
            parse_resource_name(resource)
            if resource in normalized:
                raise ValueError(f"duplicate Modbus resource: {resource!r}")
            normalized.append(resource)
        self._resources = tuple(normalized)
        holding_seed = _copy_registers(holding_registers, "holding register")
        input_seed = _copy_registers(input_registers, "input register")
        coil_seed = _copy_bits(coils, "coil")
        discrete_seed = _copy_bits(discrete_inputs, "discrete input")
        self._holding = {resource: dict(holding_seed) for resource in self._resources}
        self._input = {resource: dict(input_seed) for resource in self._resources}
        self._coils = {resource: dict(coil_seed) for resource in self._resources}
        self._discrete = {resource: dict(discrete_seed) for resource in self._resources}
        self._allow_conformance_probes = allow_conformance_probes
        self._closed = False
        for command, value in (initial_values or {}).items():
            parsed = parse_wire_command(command)
            for resource in self._resources:
                self._inject_initial_value(resource, parsed, value)

    async def list_resources(self) -> list[str]:
        return list(self._resources)

    def _require_open_resource(self, resource_name: str) -> None:
        if self._closed:
            raise ModbusBackendError("backend is closed")
        parse_resource_name(resource_name)
        if resource_name not in self._resources:
            raise ModbusBackendError(f"resource is not configured: {resource_name!r}")

    def _inject_initial_value(
        self,
        resource: str,
        command: WireCommand,
        value: int | float | bool,
    ) -> None:
        if not command.is_read:
            raise ValueError("initial_values keys must be read commands")
        if command.opcode in {"RC", "RD"}:
            if not isinstance(value, bool):
                raise ValueError("coil and discrete initial values must be bool")
            target = (
                self._coils[resource]
                if command.opcode == "RC"
                else self._discrete[resource]
            )
            target[command.address] = value
            return
        if isinstance(value, bool):
            raise ValueError("register initial values must be numeric, not bool")
        assert command.data_type is not None
        words = encode_scaled_value(value, command.data_type, command.scale)
        target = (
            self._holding[resource] if command.opcode == "RH" else self._input[resource]
        )
        for offset, word in enumerate(words):
            target[command.address + offset] = word

    @staticmethod
    def _read_words(registers: dict[int, int], command: WireCommand) -> list[int]:
        assert command.data_type is not None
        words: list[int] = []
        for offset in range(register_count(command.data_type)):
            address = command.address + offset
            if address not in registers:
                raise ModbusRegisterError(f"register {address} is not initialized")
            words.append(registers[address])
        return words

    async def query(
        self,
        resource_name: str,
        command: str,
        timeout_ms: int = 5000,
        read_termination: str = "\n",
        write_termination: str = "\n",
    ) -> str:
        del timeout_ms, read_termination, write_termination
        self._require_open_resource(resource_name)
        if self._allow_conformance_probes and command == CONFORMANCE_QUERY:
            return "TECTOS,MockModbusBackend,0,0.1.0"
        parsed = parse_wire_command(command)
        if not parsed.is_read:
            raise ModbusBackendError("query accepts read wire commands only")
        if parsed.opcode in {"RC", "RD"}:
            source = (
                self._coils[resource_name]
                if parsed.opcode == "RC"
                else self._discrete[resource_name]
            )
            if parsed.address not in source:
                raise ModbusRegisterError(f"bit {parsed.address} is not initialized")
            return "1" if source[parsed.address] else "0"
        source = (
            self._holding[resource_name]
            if parsed.opcode == "RH"
            else self._input[resource_name]
        )
        assert parsed.data_type is not None
        value = decode_scaled_value(
            self._read_words(source, parsed),
            parsed.data_type,
            parsed.scale,
        )
        return str(value)

    async def write(
        self,
        resource_name: str,
        command: str,
        timeout_ms: int = 5000,
        read_termination: str = "\n",
        write_termination: str = "\n",
    ) -> None:
        del timeout_ms, read_termination, write_termination
        self._require_open_resource(resource_name)
        if self._allow_conformance_probes and command == CONFORMANCE_WRITE:
            return
        parsed = parse_wire_command(command)
        if not parsed.is_write:
            raise ModbusBackendError("write accepts write wire commands only")
        if parsed.opcode == "WC":
            assert isinstance(parsed.value, bool)
            self._coils[resource_name][parsed.address] = parsed.value
            return
        assert parsed.data_type is not None
        assert isinstance(parsed.value, float)
        words = encode_scaled_value(parsed.value, parsed.data_type, parsed.scale)
        for offset, word in enumerate(words):
            self._holding[resource_name][parsed.address + offset] = word

    def close(self) -> None:
        self._closed = True


__all__ = [
    "CONFORMANCE_QUERY",
    "CONFORMANCE_WRITE",
    "DEFAULT_MOCK_RESOURCE",
    "MockModbusBackend",
    "ModbusRegisterError",
]
