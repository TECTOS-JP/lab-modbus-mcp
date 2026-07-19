from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest
from pymodbus.exceptions import ConnectionException

import lab_modbus_mcp.backend as backend_module
from lab_modbus_mcp.backend import (
    ModbusBackend,
    ModbusBackendError,
    ModbusCommunicationError,
    ModbusDeviceError,
    ModbusTimeoutError,
)
from lab_modbus_mcp.resource import parse_resource_name


TCP_1 = "MODBUS::127.0.0.1::1502::1"
TCP_2 = "MODBUS::127.0.0.1::1502::2"
RTU_1 = "MODBUS::COM3::1"
RTU_2 = "MODBUS::COM3::2"


@dataclass
class FakeResponse:
    registers: list[int] | None = None
    bits: list[bool] | None = None
    exception_code: int | None = None

    def isError(self) -> bool:
        return self.exception_code is not None


class FakeClient:
    def __init__(self) -> None:
        self.connected = False
        self.connect_calls = 0
        self.close_calls = 0
        self.calls: list[tuple[str, int, Any, int]] = []
        self.read_effects: list[Any] = []
        self.write_effects: list[Any] = []
        self.active = 0
        self.max_active = 0
        self.delay = 0.0

    async def connect(self) -> bool:
        self.connect_calls += 1
        self.connected = True
        return True

    def close(self) -> None:
        self.close_calls += 1
        self.connected = False

    async def _effect(self, effects: list[Any], default: FakeResponse) -> FakeResponse:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            effect = effects.pop(0) if effects else default
            if isinstance(effect, BaseException):
                raise effect
            return effect
        finally:
            self.active -= 1

    async def read_holding_registers(
        self, address: int, *, count: int = 1, device_id: int = 1
    ) -> FakeResponse:
        self.calls.append(("read_holding_registers", address, count, device_id))
        return await self._effect(
            self.read_effects, FakeResponse(registers=[7] * count)
        )

    async def read_input_registers(
        self, address: int, *, count: int = 1, device_id: int = 1
    ) -> FakeResponse:
        self.calls.append(("read_input_registers", address, count, device_id))
        return await self._effect(
            self.read_effects, FakeResponse(registers=[8] * count)
        )

    async def read_coils(
        self, address: int, *, count: int = 1, device_id: int = 1
    ) -> FakeResponse:
        self.calls.append(("read_coils", address, count, device_id))
        return await self._effect(self.read_effects, FakeResponse(bits=[True]))

    async def read_discrete_inputs(
        self, address: int, *, count: int = 1, device_id: int = 1
    ) -> FakeResponse:
        self.calls.append(("read_discrete_inputs", address, count, device_id))
        return await self._effect(self.read_effects, FakeResponse(bits=[False]))

    async def write_register(
        self, address: int, value: int, *, device_id: int = 1
    ) -> FakeResponse:
        self.calls.append(("write_register", address, value, device_id))
        return await self._effect(self.write_effects, FakeResponse())

    async def write_registers(
        self, address: int, values: list[int], *, device_id: int = 1
    ) -> FakeResponse:
        self.calls.append(("write_registers", address, values, device_id))
        return await self._effect(self.write_effects, FakeResponse())

    async def write_coil(
        self, address: int, value: bool, *, device_id: int = 1
    ) -> FakeResponse:
        self.calls.append(("write_coil", address, value, device_id))
        return await self._effect(self.write_effects, FakeResponse())


class Factory:
    def __init__(self, clients: list[FakeClient]) -> None:
        self.clients = clients
        self.created: list[FakeClient] = []

    def __call__(self, _resource: Any) -> FakeClient:
        client = self.clients[len(self.created)]
        self.created.append(client)
        return client


@pytest.mark.asyncio
async def test_tcp_reads_writes_coils_and_reuses_connection():
    client = FakeClient()
    backend = ModbusBackend([TCP_1], _client_factory=Factory([client]))

    assert await backend.query(TCP_1, "RH 1 u16") == "7.0"
    assert await backend.query(TCP_1, "RI 2 u16") == "8.0"
    assert await backend.query(TCP_1, "RC 3") == "1"
    assert await backend.query(TCP_1, "RD 4") == "0"
    await backend.write(TCP_1, "WH 5 u16 9")
    await backend.write(TCP_1, "WC 6 1")

    assert client.connect_calls == 1
    assert [call[0] for call in client.calls] == [
        "read_holding_registers",
        "read_input_registers",
        "read_coils",
        "read_discrete_inputs",
        "write_register",
        "write_coil",
    ]


@pytest.mark.asyncio
async def test_32bit_read_and_write_are_single_two_register_transactions():
    client = FakeClient()
    client.read_effects = [FakeResponse(registers=[0x1122, 0x3344])]
    backend = ModbusBackend([TCP_1], _client_factory=Factory([client]))

    assert await backend.query(TCP_1, "RH 10 u32be") == str(0x11223344 * 1.0)
    await backend.write(TCP_1, f"WH 20 u32be {0x11223344}")

    assert client.calls[0] == ("read_holding_registers", 10, 2, 1)
    assert client.calls[1] == ("write_registers", 20, [0x1122, 0x3344], 1)


@pytest.mark.asyncio
async def test_read_communication_failure_retries_with_new_connection():
    first = FakeClient()
    first.read_effects = [ConnectionException("lost")]
    second = FakeClient()
    factory = Factory([first, second])
    backend = ModbusBackend([TCP_1], read_retries=1, _client_factory=factory)

    assert await backend.query(TCP_1, "RH 0 u16") == "7.0"
    assert len(factory.created) == 2
    assert first.close_calls == 1


@pytest.mark.asyncio
async def test_write_timeout_is_never_retried():
    client = FakeClient()
    client.delay = 0.1
    factory = Factory([client])
    backend = ModbusBackend([TCP_1], read_retries=5, _client_factory=factory)

    with pytest.raises(ModbusTimeoutError, match="WH address=0.*timeout"):
        await backend.write(TCP_1, "WH 0 u16 1", timeout_ms=10)

    assert [call[0] for call in client.calls] == ["write_register"]
    assert len(factory.created) == 1


@pytest.mark.asyncio
async def test_write_disconnect_is_never_retried():
    client = FakeClient()
    client.write_effects = [ConnectionException("lost after send")]
    factory = Factory([client])
    backend = ModbusBackend([TCP_1], read_retries=5, _client_factory=factory)

    with pytest.raises(ModbusCommunicationError, match="communication failure"):
        await backend.write(TCP_1, "WH 0 u16 1")

    assert [call[0] for call in client.calls] == ["write_register"]
    assert len(factory.created) == 1


@pytest.mark.asyncio
async def test_modbus_exception_is_not_retried_and_has_code_meaning_context():
    client = FakeClient()
    client.read_effects = [FakeResponse(exception_code=2)]
    backend = ModbusBackend([TCP_1], read_retries=3, _client_factory=Factory([client]))

    with pytest.raises(ModbusDeviceError) as caught:
        await backend.query(TCP_1, "RH 19 u16")

    assert caught.value.exception_code == 2
    assert caught.value.exception_meaning == "IllegalDataAddress"
    assert TCP_1 in str(caught.value)
    assert "RH address=19" in str(caught.value)
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_malformed_read_response_is_a_retriable_communication_error():
    first = FakeClient()
    first.read_effects = [FakeResponse(registers=[])]
    second = FakeClient()
    backend = ModbusBackend(
        [TCP_1], _client_factory=Factory([first, second]), read_retries=1
    )

    assert await backend.query(TCP_1, "RH 0 u16") == "7.0"
    assert first.close_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("resources", [(TCP_1, TCP_2), (RTU_1, RTU_2)])
async def test_bus_lock_is_shared_across_unit_ids(resources):
    client = FakeClient()
    client.delay = 0.03
    backend = ModbusBackend(resources, _client_factory=Factory([client]))

    await asyncio.gather(
        backend.query(resources[0], "RH 0 u16"),
        backend.query(resources[1], "RH 0 u16"),
    )

    assert client.max_active == 1
    assert {call[3] for call in client.calls} == {1, 2}


@pytest.mark.asyncio
async def test_rtu_factory_receives_configured_serial_parameters(monkeypatch):
    captured: dict[str, Any] = {}

    def serial_client(port: str, **kwargs: Any) -> FakeClient:
        captured.update(port=port, **kwargs)
        return FakeClient()

    monkeypatch.setattr(backend_module, "AsyncModbusSerialClient", serial_client)
    backend = ModbusBackend([RTU_1], baudrate=19200, bytesize=7, parity="e", stopbits=2)
    backend._new_client(parse_resource_name(RTU_1))

    assert captured == {
        "port": "COM3",
        "baudrate": 19200,
        "bytesize": 7,
        "parity": "E",
        "stopbits": 2,
        "timeout": 86_400,
        "retries": 0,
        "reconnect_delay": 0,
    }


@pytest.mark.asyncio
async def test_tcp_factory_disables_pymodbus_internal_retries(monkeypatch):
    captured: dict[str, Any] = {}

    def tcp_client(host: str, **kwargs: Any) -> FakeClient:
        captured.update(host=host, **kwargs)
        return FakeClient()

    monkeypatch.setattr(backend_module, "AsyncModbusTcpClient", tcp_client)
    backend = ModbusBackend([TCP_1])
    backend._new_client(parse_resource_name(TCP_1))

    assert captured == {
        "host": "127.0.0.1",
        "port": 1502,
        "timeout": 86_400,
        "retries": 0,
        "reconnect_delay": 0,
    }


@pytest.mark.asyncio
async def test_close_twice_closes_connection_once_and_never_raises():
    client = FakeClient()
    backend = ModbusBackend([TCP_1], _client_factory=Factory([client]))
    await backend.query(TCP_1, "RH 0 u16")

    assert backend.close() is None
    assert backend.close() is None
    assert client.close_calls == 1
    with pytest.raises(ModbusBackendError, match="closed"):
        await backend.query(TCP_1, "RH 0 u16")


@pytest.mark.asyncio
async def test_invalid_input_and_timeout_fail_before_client_creation():
    factory = Factory([FakeClient()])
    backend = ModbusBackend([TCP_1], _client_factory=factory)

    with pytest.raises(ModbusBackendError, match="not configured"):
        await backend.query(TCP_2, "RH 0 u16")
    with pytest.raises(ModbusBackendError, match="timeout_ms"):
        await backend.query(TCP_1, "RH 0 u16", timeout_ms=0)
    assert factory.created == []


@pytest.mark.asyncio
async def test_read_timeout_exhaustion_reports_communication_context():
    first = FakeClient()
    first.delay = 0.05
    second = FakeClient()
    second.delay = 0.05
    backend = ModbusBackend(
        [TCP_1], read_retries=1, _client_factory=Factory([first, second])
    )

    with pytest.raises(ModbusCommunicationError, match="RH address=7.*timeout"):
        await backend.query(TCP_1, "RH 7 u16", timeout_ms=5)

    assert len(first.calls) == len(second.calls) == 1
