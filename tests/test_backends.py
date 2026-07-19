from __future__ import annotations

import inspect

import pytest

from lab_executor.backends import InstrumentBackend
from lab_executor.testing.backend_conformance import assert_backend_contract

from lab_modbus_mcp.backend import (
    ModbusBackend,
    ModbusBackendError,
    ModbusTransportUnavailable,
)
from lab_modbus_mcp.mock_backend import (
    DEFAULT_MOCK_RESOURCE,
    MockModbusBackend,
    ModbusRegisterError,
)
from lab_modbus_mcp.wire import WireCommandError


def test_both_backends_satisfy_runtime_protocol():
    assert isinstance(MockModbusBackend(), InstrumentBackend)
    assert isinstance(ModbusBackend(), InstrumentBackend)


@pytest.mark.asyncio
async def test_mock_backend_passes_bef_conformance():
    backend = MockModbusBackend()
    returned = await assert_backend_contract(
        backend,
        sample_resource=DEFAULT_MOCK_RESOURCE,
    )
    assert returned is backend


@pytest.mark.asyncio
async def test_holding_register_scaled_write_read_round_trip():
    backend = MockModbusBackend()
    await backend.write(DEFAULT_MOCK_RESOURCE, "WH 4 u16 s0.1 25.0")
    assert float(await backend.query(DEFAULT_MOCK_RESOURCE, "RH 4 u16 s0.1")) == 25.0


@pytest.mark.asyncio
async def test_signed_and_32bit_write_read_round_trip():
    backend = MockModbusBackend()
    for address, data_type, value in [
        (0, "s16", -12),
        (10, "u32", 0x11223344),
        (20, "s32", -123456),
        (30, "float32be", 12),
        (40, "float32le", 12),
    ]:
        await backend.write(
            DEFAULT_MOCK_RESOURCE,
            f"WH {address} {data_type} {value}",
        )
        response = await backend.query(
            DEFAULT_MOCK_RESOURCE,
            f"RH {address} {data_type}",
        )
        assert float(response) == pytest.approx(value)


@pytest.mark.asyncio
async def test_coil_write_read_round_trip():
    backend = MockModbusBackend()
    await backend.write(DEFAULT_MOCK_RESOURCE, "WC 8 1")
    assert await backend.query(DEFAULT_MOCK_RESOURCE, "RC 8") == "1"
    await backend.write(DEFAULT_MOCK_RESOURCE, "WC 8 0")
    assert await backend.query(DEFAULT_MOCK_RESOURCE, "RC 8") == "0"


@pytest.mark.asyncio
async def test_initial_values_inject_type_scale_and_read_area():
    backend = MockModbusBackend(
        initial_values={
            "RH 0 u16 s0.1": 25.0,
            "RI 10 s16": -4,
            "RC 20": True,
            "RD 21": False,
            "RH 30 float32le": 5,
        }
    )
    assert await backend.query(DEFAULT_MOCK_RESOURCE, "RH 0 u16 s0.1") == "25.0"
    assert await backend.query(DEFAULT_MOCK_RESOURCE, "RI 10 s16") == "-4.0"
    assert await backend.query(DEFAULT_MOCK_RESOURCE, "RC 20") == "1"
    assert await backend.query(DEFAULT_MOCK_RESOURCE, "RD 21") == "0"
    assert float(await backend.query(DEFAULT_MOCK_RESOURCE, "RH 30 float32le")) == 5


@pytest.mark.asyncio
async def test_missing_register_and_bit_fail_closed():
    backend = MockModbusBackend()
    with pytest.raises(ModbusRegisterError):
        await backend.query(DEFAULT_MOCK_RESOURCE, "RH 0 u16")
    with pytest.raises(ModbusRegisterError):
        await backend.query(DEFAULT_MOCK_RESOURCE, "RC 0")


@pytest.mark.asyncio
async def test_method_operation_mismatch_rejected_without_write():
    backend = MockModbusBackend(holding_registers={0: 7})
    with pytest.raises(ModbusBackendError):
        await backend.write(DEFAULT_MOCK_RESOURCE, "RH 0 u16")
    assert await backend.query(DEFAULT_MOCK_RESOURCE, "RH 0 u16") == "7.0"
    with pytest.raises(ModbusBackendError):
        await backend.query(DEFAULT_MOCK_RESOURCE, "WH 0 u16 8")
    assert await backend.query(DEFAULT_MOCK_RESOURCE, "RH 0 u16") == "7.0"


@pytest.mark.asyncio
async def test_unknown_resource_rejected():
    backend = MockModbusBackend()
    with pytest.raises(ModbusBackendError, match="not configured"):
        await backend.query("MODBUS::COM4::1", "RH 0 u16")


@pytest.mark.asyncio
async def test_multiple_mock_resources_have_isolated_state():
    first = "MODBUS::COM3::1"
    second = "MODBUS::COM3::2"
    backend = MockModbusBackend(resources=[first, second], holding_registers={0: 1})
    await backend.write(first, "WH 0 u16 9")
    assert await backend.query(first, "RH 0 u16") == "9.0"
    assert await backend.query(second, "RH 0 u16") == "1.0"


@pytest.mark.asyncio
async def test_explicit_empty_resource_list_remains_empty():
    backend = MockModbusBackend(resources=[])
    assert await backend.list_resources() == []
    with pytest.raises(ModbusBackendError, match="not configured"):
        await backend.query(DEFAULT_MOCK_RESOURCE, "RH 0 u16")


@pytest.mark.asyncio
async def test_conformance_probes_are_exact_safe_mock_only_noops():
    backend = MockModbusBackend(holding_registers={0: 9})
    assert "MockModbusBackend" in await backend.query(DEFAULT_MOCK_RESOURCE, "*IDN?")
    assert await backend.write(DEFAULT_MOCK_RESOURCE, "CONF") is None
    assert await backend.query(DEFAULT_MOCK_RESOURCE, "RH 0 u16") == "9.0"
    strict = MockModbusBackend(allow_conformance_probes=False)
    with pytest.raises(WireCommandError):
        await strict.query(DEFAULT_MOCK_RESOURCE, "*IDN?")
    with pytest.raises(WireCommandError):
        await strict.write(DEFAULT_MOCK_RESOURCE, "CONF")


def test_mock_exposes_no_separate_raw_register_write_api():
    backend = MockModbusBackend()
    for name in ("raw_write", "write_register", "set_register", "write_registers"):
        assert not hasattr(backend, name)


@pytest.mark.asyncio
async def test_backend_skeleton_validates_then_reports_transport_unavailable():
    backend = ModbusBackend(resources=[DEFAULT_MOCK_RESOURCE])
    assert await backend.list_resources() == [DEFAULT_MOCK_RESOURCE]
    with pytest.raises(ModbusTransportUnavailable):
        await backend.query(DEFAULT_MOCK_RESOURCE, "RH 0 u16")
    with pytest.raises(ModbusTransportUnavailable):
        await backend.write(DEFAULT_MOCK_RESOURCE, "WH 0 u16 1")
    with pytest.raises(WireCommandError):
        await backend.query(DEFAULT_MOCK_RESOURCE, "*IDN?")


@pytest.mark.asyncio
async def test_close_is_synchronous_idempotent_and_blocks_io():
    backend = MockModbusBackend()
    assert not inspect.iscoroutinefunction(backend.close)
    assert backend.close() is None
    assert backend.close() is None
    with pytest.raises(ModbusBackendError, match="closed"):
        await backend.query(DEFAULT_MOCK_RESOURCE, "RH 0 u16")


def test_constructor_rejects_invalid_initial_maps_and_commands():
    with pytest.raises(ValueError):
        MockModbusBackend(holding_registers={-1: 0})
    with pytest.raises(ValueError):
        MockModbusBackend(holding_registers={0: 65536})
    with pytest.raises(ValueError):
        MockModbusBackend(coils={0: 1})  # type: ignore[dict-item]
    with pytest.raises(ValueError):
        MockModbusBackend(initial_values={"WH 0 u16 1": 1})
