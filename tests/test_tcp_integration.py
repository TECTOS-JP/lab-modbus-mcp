from __future__ import annotations

import asyncio
import inspect
import socket

import pytest
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext
from pymodbus.server import ServerAsyncStop, StartAsyncTcpServer

from lab_modbus_mcp.backend import ModbusBackend


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _server_context() -> ModbusServerContext:
    try:
        from pymodbus.datastore import ModbusDeviceContext

        device_type = ModbusDeviceContext
        block_address = 1
    except ImportError:  # pymodbus 3.6-3.9
        from pymodbus.datastore import ModbusSlaveContext

        device_type = ModbusSlaveContext
        block_address = 0

    device_kwargs = {
        "di": ModbusSequentialDataBlock(block_address, [True] * 256),
        "co": ModbusSequentialDataBlock(block_address, [False] * 256),
        "hr": ModbusSequentialDataBlock(block_address, [0] * 256),
        "ir": ModbusSequentialDataBlock(block_address, [13] * 256),
    }
    if "zero_mode" in inspect.signature(device_type).parameters:
        device_kwargs["zero_mode"] = True
    device = device_type(**device_kwargs)

    parameters = inspect.signature(ModbusServerContext).parameters
    if "devices" in parameters:
        return ModbusServerContext(devices={1: device}, single=False)
    return ModbusServerContext(slaves={1: device}, single=False)


async def _wait_for_server(port: int) -> None:
    for _ in range(100):
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            await asyncio.sleep(0.01)
            continue
        writer.close()
        await writer.wait_closed()
        del reader
        return
    raise AssertionError("pymodbus test server did not start")


@pytest.mark.asyncio
async def test_real_async_tcp_server_round_trips_all_register_types_and_bits():
    """Exercise real Modbus TCP framing over a loopback TCP socket."""
    port = _free_tcp_port()
    context = _server_context()
    server_task = asyncio.create_task(
        StartAsyncTcpServer(context=context, address=("127.0.0.1", port))
    )
    await _wait_for_server(port)
    resource = f"MODBUS::127.0.0.1::{port}::1"
    backend = ModbusBackend([resource])

    try:
        cases = [
            (0, "u16", 65530),
            (4, "s16", -1234),
            (8, "u32be", 0x11223344),
            (12, "u32le", 0x55667788),
            (16, "s32be", -12345678),
            (20, "s32le", -8765432),
            (24, "float32be", 25.5),
            (28, "float32le", -12.25),
        ]
        for address, data_type, value in cases:
            await backend.write(resource, f"WH {address} {data_type} {value}")
            returned = float(await backend.query(resource, f"RH {address} {data_type}"))
            assert returned == pytest.approx(value)

        await backend.write(resource, "WH 40 u16 s0.1 25.0")
        assert float(await backend.query(resource, "RH 40 u16 s0.1")) == 25.0
        assert float(await backend.query(resource, "RI 0 u16")) == 13.0
        assert await backend.query(resource, "RD 0") == "1"
        await backend.write(resource, "WC 2 1")
        assert await backend.query(resource, "RC 2") == "1"
    finally:
        backend.close()
        await ServerAsyncStop()
        await asyncio.wait_for(server_task, timeout=2)
