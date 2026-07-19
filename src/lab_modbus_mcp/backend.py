"""Async pymodbus transport for configured Modbus RTU and TCP resources."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
import inspect
from typing import Any, TypeAlias

from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusIOException

from lab_modbus_mcp.resource import ModbusResource, parse_resource_name
from lab_modbus_mcp.wire import (
    WireCommand,
    decode_scaled_value,
    encode_scaled_value,
    parse_wire_command,
    register_count,
)


class ModbusBackendError(RuntimeError):
    """Base error for backend-level failures."""


class ModbusTransportUnavailable(ModbusBackendError):
    """A compatibility alias for transport-unavailable communication errors."""


class ModbusCommunicationError(ModbusTransportUnavailable):
    """The request could not complete because communication failed."""


class ModbusTimeoutError(ModbusCommunicationError):
    """The configured per-attempt timeout expired."""


class ModbusDeviceError(ModbusBackendError):
    """A Modbus device returned an explicit exception response."""

    def __init__(
        self,
        message: str,
        *,
        exception_code: int,
        exception_meaning: str,
    ) -> None:
        super().__init__(message)
        self.exception_code = exception_code
        self.exception_meaning = exception_meaning


BusKey: TypeAlias = tuple[str, str, int | None]
ClientFactory: TypeAlias = Callable[[ModbusResource], Any]

_EXCEPTION_MEANINGS = {
    1: "IllegalFunction",
    2: "IllegalDataAddress",
    3: "IllegalDataValue",
    4: "SlaveDeviceFailure",
    5: "Acknowledge",
    6: "SlaveDeviceBusy",
    7: "NegativeAcknowledge",
    8: "MemoryParityError",
    10: "GatewayPathUnavailable",
    11: "GatewayTargetDeviceFailedToRespond",
}


def _positive_timeout(timeout_ms: int) -> float:
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int):
        raise ModbusBackendError("timeout_ms must be a positive integer")
    if timeout_ms <= 0:
        raise ModbusBackendError("timeout_ms must be a positive integer")
    return timeout_ms / 1000


def _serial_settings(
    baudrate: int,
    bytesize: int,
    parity: str,
    stopbits: int | float,
) -> tuple[int, int, str, int | float]:
    if isinstance(baudrate, bool) or not isinstance(baudrate, int) or baudrate <= 0:
        raise ValueError("baudrate must be a positive integer")
    if isinstance(bytesize, bool) or bytesize not in {5, 6, 7, 8}:
        raise ValueError("bytesize must be one of 5, 6, 7, or 8")
    if not isinstance(parity, str) or parity.upper() not in {"N", "E", "O"}:
        raise ValueError("parity must be N, E, or O")
    if isinstance(stopbits, bool) or stopbits not in {1, 1.5, 2}:
        raise ValueError("stopbits must be 1, 1.5, or 2")
    return baudrate, bytesize, parity.upper(), stopbits


class ModbusBackend:
    """A lazy, reusable async Modbus TCP/RTU backend.

    Locks and client connections are shared by physical bus, not unit id. The
    pymodbus client's own retry mechanism is disabled so writes are never
    silently repeated; read retries are implemented explicitly here.
    """

    backend_id = "modbus"

    def __init__(
        self,
        resources: Iterable[str] | None = None,
        *,
        read_retries: int = 1,
        baudrate: int = 9600,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: int | float = 1,
        _client_factory: ClientFactory | None = None,
    ) -> None:
        if (
            isinstance(read_retries, bool)
            or not isinstance(read_retries, int)
            or read_retries < 0
        ):
            raise ValueError("read_retries must be a non-negative integer")
        baudrate, bytesize, parity, stopbits = _serial_settings(
            baudrate, bytesize, parity, stopbits
        )

        normalized: list[str] = []
        parsed_resources: dict[str, ModbusResource] = {}
        for resource_name in resources or ():
            resource = parse_resource_name(resource_name)
            if resource_name in parsed_resources:
                raise ValueError(f"duplicate Modbus resource: {resource_name!r}")
            normalized.append(resource_name)
            parsed_resources[resource_name] = resource

        self._resources = tuple(normalized)
        self._parsed_resources = parsed_resources
        self._read_retries = read_retries
        self._baudrate = baudrate
        self._bytesize = bytesize
        self._parity = parity
        self._stopbits = stopbits
        self._client_factory = _client_factory
        self._clients: dict[BusKey, Any] = {}
        self._locks: dict[BusKey, asyncio.Lock] = {}
        self._closed = False

    async def list_resources(self) -> list[str]:
        """Return configured resources without probing either transport."""
        return list(self._resources)

    @staticmethod
    def _bus_key(resource: ModbusResource) -> BusKey:
        if resource.transport == "rtu":
            assert resource.serial_port is not None
            return ("rtu", resource.serial_port.casefold(), None)
        assert resource.host is not None and resource.tcp_port is not None
        return ("tcp", resource.host.casefold(), resource.tcp_port)

    def _validate(
        self, resource_name: str, command: str, *, read: bool
    ) -> tuple[ModbusResource, WireCommand]:
        """Validate all caller-controlled syntax before any transport access."""
        if self._closed:
            raise ModbusBackendError("backend is closed")
        parse_resource_name(resource_name)
        resource = self._parsed_resources.get(resource_name)
        if resource is None:
            raise ModbusBackendError(f"resource is not configured: {resource_name!r}")
        parsed = parse_wire_command(command)
        if parsed.is_read != read:
            expected = "read" if read else "write"
            raise ModbusBackendError(f"{expected} method received the wrong operation")
        return resource, parsed

    def _new_client(self, resource: ModbusResource) -> Any:
        if self._client_factory is not None:
            return self._client_factory(resource)
        # The large client timeout is only a fallback. asyncio.wait_for below
        # owns the public, per-call deadline. Internal retries stay disabled.
        common = {"timeout": 86_400, "retries": 0, "reconnect_delay": 0}
        if resource.transport == "tcp":
            assert resource.host is not None and resource.tcp_port is not None
            return AsyncModbusTcpClient(
                resource.host,
                port=resource.tcp_port,
                **common,
            )
        assert resource.serial_port is not None
        return AsyncModbusSerialClient(
            resource.serial_port,
            baudrate=self._baudrate,
            bytesize=self._bytesize,
            parity=self._parity,
            stopbits=self._stopbits,
            **common,
        )

    @staticmethod
    def _close_client(client: Any) -> None:
        try:
            result = client.close()
            if inspect.isawaitable(result):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    asyncio.run(result)
                else:
                    loop.create_task(result)
        except Exception:
            # close() is a synchronous, idempotent, best-effort cleanup API.
            pass

    async def _drop_client(self, key: BusKey, client: Any) -> None:
        if self._clients.get(key) is client:
            self._clients.pop(key, None)
        self._close_client(client)

    async def _connected_client(self, resource: ModbusResource) -> Any:
        key = self._bus_key(resource)
        client = self._clients.get(key)
        if client is not None and bool(getattr(client, "connected", False)):
            return client
        if client is not None:
            await self._drop_client(key, client)
        client = self._new_client(resource)
        self._clients[key] = client
        connected = await client.connect()
        if connected is False or not bool(getattr(client, "connected", connected)):
            await self._drop_client(key, client)
            raise ConnectionException("connection attempt did not connect")
        return client

    @staticmethod
    def _unit_keyword(method: Callable[..., Any], unit_id: int) -> dict[str, int]:
        """Bridge pymodbus 3.6 ``slave`` and newer ``device_id`` APIs."""
        try:
            parameters = inspect.signature(method).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "device_id" in parameters:
            return {"device_id": unit_id}
        return {"slave": unit_id}

    async def _request(
        self, client: Any, resource: ModbusResource, command: WireCommand
    ) -> Any:
        operation = command.opcode
        address = command.address
        if operation == "RH":
            method = client.read_holding_registers
            return await method(
                address,
                count=register_count(command.data_type or ""),
                **self._unit_keyword(method, resource.unit_id),
            )
        if operation == "RI":
            method = client.read_input_registers
            return await method(
                address,
                count=register_count(command.data_type or ""),
                **self._unit_keyword(method, resource.unit_id),
            )
        if operation == "RC":
            method = client.read_coils
            return await method(
                address,
                count=1,
                **self._unit_keyword(method, resource.unit_id),
            )
        if operation == "RD":
            method = client.read_discrete_inputs
            return await method(
                address,
                count=1,
                **self._unit_keyword(method, resource.unit_id),
            )
        if operation == "WC":
            method = client.write_coil
            return await method(
                address,
                bool(command.value),
                **self._unit_keyword(method, resource.unit_id),
            )

        assert operation == "WH" and command.data_type is not None
        words = list(
            encode_scaled_value(command.value, command.data_type, command.scale)  # type: ignore[arg-type]
        )
        if len(words) == 1:
            method = client.write_register
            return await method(
                address,
                words[0],
                **self._unit_keyword(method, resource.unit_id),
            )
        # Safety invariant: a 32-bit value is one multi-register transaction.
        method = client.write_registers
        return await method(
            address,
            words,
            **self._unit_keyword(method, resource.unit_id),
        )

    @staticmethod
    def _raise_for_response(response: Any, context: str) -> None:
        try:
            is_error = bool(response.isError())
        except (AttributeError, TypeError) as exc:
            raise ModbusCommunicationError(
                f"{context}: malformed response without isError()"
            ) from exc
        if not is_error:
            return
        raw_code = getattr(response, "exception_code", 0)
        try:
            code = int(raw_code)
        except (TypeError, ValueError):
            code = 0
        meaning = _EXCEPTION_MEANINGS.get(code, "UnknownModbusException")
        raise ModbusDeviceError(
            f"{context}: Modbus exception {code} ({meaning})",
            exception_code=code,
            exception_meaning=meaning,
        )

    @staticmethod
    def _validate_read_payload(
        response: Any, command: WireCommand, context: str
    ) -> None:
        if not command.is_read:
            return
        if command.opcode in {"RC", "RD"}:
            bits = getattr(response, "bits", None)
            if not isinstance(bits, list) or not bits:
                raise ModbusCommunicationError(f"{context}: response contains no bit")
            return
        assert command.data_type is not None
        count = register_count(command.data_type)
        registers = getattr(response, "registers", None)
        if not isinstance(registers, list) or len(registers) < count:
            raise ModbusCommunicationError(
                f"{context}: response contains fewer than {count} registers"
            )

    async def _attempt(
        self,
        resource: ModbusResource,
        command: WireCommand,
        context: str,
    ) -> Any:
        client = await self._connected_client(resource)
        response = await self._request(client, resource, command)
        self._raise_for_response(response, context)
        self._validate_read_payload(response, command, context)
        return response

    async def _transact(
        self,
        resource_name: str,
        resource: ModbusResource,
        command: WireCommand,
        timeout_seconds: float,
    ) -> Any:
        key = self._bus_key(resource)
        lock = self._locks.setdefault(key, asyncio.Lock())
        context = f"{resource_name} {command.opcode} address={command.address}"
        attempts = self._read_retries + 1 if command.is_read else 1

        async with lock:
            for attempt in range(attempts):
                client_before = self._clients.get(key)
                try:
                    return await asyncio.wait_for(
                        self._attempt(resource, command, context),
                        timeout=timeout_seconds,
                    )
                except ModbusDeviceError:
                    raise
                except asyncio.TimeoutError:
                    client = self._clients.get(key) or client_before
                    if client is not None:
                        await self._drop_client(key, client)
                    error: ModbusCommunicationError = ModbusTimeoutError(
                        f"{context}: timeout after {timeout_seconds * 1000:g} ms"
                    )
                except ModbusCommunicationError as exc:
                    client = self._clients.get(key) or client_before
                    if client is not None:
                        await self._drop_client(key, client)
                    error = exc
                except asyncio.CancelledError:
                    client = self._clients.get(key) or client_before
                    if client is not None:
                        await self._drop_client(key, client)
                    raise
                except (ConnectionException, ModbusIOException, OSError) as exc:
                    client = self._clients.get(key) or client_before
                    if client is not None:
                        await self._drop_client(key, client)
                    error = ModbusCommunicationError(
                        f"{context}: communication failure: {exc}"
                    )
                if attempt + 1 == attempts:
                    raise error
        raise AssertionError("unreachable")

    async def query(
        self,
        resource_name: str,
        command: str,
        timeout_ms: int = 5000,
        read_termination: str = "\n",
        write_termination: str = "\n",
    ) -> str:
        del read_termination, write_termination
        resource, parsed = self._validate(resource_name, command, read=True)
        timeout_seconds = _positive_timeout(timeout_ms)
        response = await self._transact(
            resource_name, resource, parsed, timeout_seconds
        )
        if parsed.opcode in {"RC", "RD"}:
            bits = getattr(response, "bits", None)
            if not isinstance(bits, list) or not bits:
                raise ModbusCommunicationError(
                    f"{resource_name} {parsed.opcode} address={parsed.address}: "
                    "response contains no bit"
                )
            return "1" if bool(bits[0]) else "0"

        assert parsed.data_type is not None
        count = register_count(parsed.data_type)
        registers = getattr(response, "registers", None)
        if not isinstance(registers, list) or len(registers) < count:
            raise ModbusCommunicationError(
                f"{resource_name} {parsed.opcode} address={parsed.address}: "
                f"response contains fewer than {count} registers"
            )
        value = decode_scaled_value(registers[:count], parsed.data_type, parsed.scale)
        return str(value)

    async def write(
        self,
        resource_name: str,
        command: str,
        timeout_ms: int = 5000,
        read_termination: str = "\n",
        write_termination: str = "\n",
    ) -> None:
        del read_termination, write_termination
        resource, parsed = self._validate(resource_name, command, read=False)
        timeout_seconds = _positive_timeout(timeout_ms)
        await self._transact(resource_name, resource, parsed, timeout_seconds)

    def close(self) -> None:
        """Close every connection; this method is idempotent and never raises."""
        if self._closed:
            return
        self._closed = True
        clients = tuple(self._clients.values())
        self._clients.clear()
        for client in clients:
            self._close_client(client)


__all__ = [
    "ModbusBackend",
    "ModbusBackendError",
    "ModbusCommunicationError",
    "ModbusDeviceError",
    "ModbusTimeoutError",
    "ModbusTransportUnavailable",
]
