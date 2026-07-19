"""Strict parser for ``MODBUS::`` resource names."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
from typing import Literal


_COM_PORT_RE = re.compile(r"COM[1-9][0-9]*", re.IGNORECASE | re.ASCII)
_POSIX_PORT_RE = re.compile(r"/dev/[A-Za-z0-9._/-]+", re.ASCII)
_HOSTNAME_RE = re.compile(
    r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?",
    re.ASCII,
)
_DECIMAL_RE = re.compile(r"[0-9]+", re.ASCII)


class ModbusResourceError(ValueError):
    """A resource name is not a supported, unambiguous Modbus endpoint."""


@dataclass(frozen=True)
class ModbusResource:
    transport: Literal["rtu", "tcp"]
    unit_id: int
    serial_port: str | None = None
    host: str | None = None
    tcp_port: int | None = None


def _decimal(token: str, label: str, minimum: int, maximum: int) -> int:
    if not _DECIMAL_RE.fullmatch(token):
        raise ModbusResourceError(f"{label} must be a decimal integer")
    value = int(token)
    if not minimum <= value <= maximum:
        raise ModbusResourceError(f"{label} must be between {minimum} and {maximum}")
    return value


def _valid_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        # Numeric dotted input is intended as IPv4 and must not fall through
        # to the more permissive DNS hostname grammar.
        if all(character in "0123456789." for character in host):
            return False
        return _HOSTNAME_RE.fullmatch(host) is not None


def parse_resource_name(resource_name: str) -> ModbusResource:
    """Parse RTU or TCP resource syntax without guessing malformed input."""
    if not isinstance(resource_name, str):
        raise ModbusResourceError("resource name must be a string")
    if resource_name != resource_name.strip() or any(
        ch.isspace() for ch in resource_name
    ):
        raise ModbusResourceError("resource name must not contain whitespace")
    parts = resource_name.split("::")
    if not parts or parts[0] != "MODBUS":
        raise ModbusResourceError("resource name must start with 'MODBUS::'")

    if len(parts) == 3:
        serial_port, unit_token = parts[1], parts[2]
        if not (
            _COM_PORT_RE.fullmatch(serial_port) or _POSIX_PORT_RE.fullmatch(serial_port)
        ):
            raise ModbusResourceError(
                "RTU port must be COM<n> or an absolute /dev/... path"
            )
        if serial_port.startswith("/dev/"):
            device_segments = serial_port.removeprefix("/dev/").split("/")
            if any(segment in {"", ".", ".."} for segment in device_segments):
                raise ModbusResourceError(
                    "RTU /dev path must not contain empty or dot segments"
                )
        unit_id = _decimal(unit_token, "unit id", 1, 247)
        return ModbusResource(
            transport="rtu",
            unit_id=unit_id,
            serial_port=serial_port,
        )

    if len(parts) == 4:
        host, port_token, unit_token = parts[1], parts[2], parts[3]
        if not host or not _valid_host(host):
            raise ModbusResourceError("TCP host must be a valid IP address or hostname")
        tcp_port = _decimal(port_token, "TCP port", 1, 65535)
        unit_id = _decimal(unit_token, "unit id", 1, 247)
        return ModbusResource(
            transport="tcp",
            unit_id=unit_id,
            host=host,
            tcp_port=tcp_port,
        )

    raise ModbusResourceError(
        "resource must be MODBUS::<serial-port>::<unit-id> or "
        "MODBUS::<host>::<tcp-port>::<unit-id>"
    )


__all__ = ["ModbusResource", "ModbusResourceError", "parse_resource_name"]
