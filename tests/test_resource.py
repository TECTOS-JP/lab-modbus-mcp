from __future__ import annotations

import pytest

from lab_modbus_mcp.resource import ModbusResourceError, parse_resource_name


def test_parse_windows_rtu_resource():
    parsed = parse_resource_name("MODBUS::COM3::1")
    assert parsed.transport == "rtu"
    assert parsed.serial_port == "COM3"
    assert parsed.unit_id == 1
    assert parsed.host is None
    assert parsed.tcp_port is None


def test_parse_posix_rtu_resource():
    parsed = parse_resource_name("MODBUS::/dev/ttyUSB0::247")
    assert parsed.transport == "rtu"
    assert parsed.serial_port == "/dev/ttyUSB0"
    assert parsed.unit_id == 247


@pytest.mark.parametrize("host", ["192.168.0.10", "controller.lab", "localhost"])
def test_parse_tcp_resource(host):
    parsed = parse_resource_name(f"MODBUS::{host}::502::7")
    assert parsed.transport == "tcp"
    assert parsed.host == host
    assert parsed.tcp_port == 502
    assert parsed.unit_id == 7


@pytest.mark.parametrize(
    "resource",
    [
        "",
        "MODBUS::",
        "modbus::COM3::1",
        "MODBUS::COM0::1",
        "MODBUS::COM3::0",
        "MODBUS::COM3::248",
        "MODBUS::COM3::-1",
        "MODBUS::relative/path::1",
        "MODBUS::/tmp/device::1",
        "MODBUS::/dev/../ttyUSB0::1",
        "MODBUS::/dev//ttyUSB0::1",
        "MODBUS::/dev/ttyUSB0/::1",
        "MODBUS::192.168.0.999::502::1",
        "MODBUS::bad_host!::502::1",
        "MODBUS::host::0::1",
        "MODBUS::host::65536::1",
        "MODBUS::host::502::0",
        "MODBUS::host::502::1::extra",
        " MODBUS::COM3::1",
        "MODBUS::COM3::1 ",
        "MODBUS::COM 3::1",
    ],
)
def test_invalid_resource_fails_explicitly(resource):
    with pytest.raises(ModbusResourceError):
        parse_resource_name(resource)


def test_non_string_resource_rejected():
    with pytest.raises(ModbusResourceError):
        parse_resource_name(None)  # type: ignore[arg-type]
