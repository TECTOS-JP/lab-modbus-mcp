"""lab-executor backend entry-point factory."""

from __future__ import annotations

from typing import Any

from lab_executor.backends import BackendRegistration

from lab_modbus_mcp.backend import ModbusBackend


def make_backend(config: dict[str, Any] | None = None) -> BackendRegistration:
    """Construct the unconnected MB-1 backend from strict configuration."""
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise TypeError("modbus backend config must be a mapping")
    unknown = set(config) - {"resources"}
    if unknown:
        raise ValueError(f"unknown modbus backend config keys: {sorted(unknown)!r}")
    resources = config.get("resources", [])
    if not isinstance(resources, list) or not all(
        isinstance(resource, str) for resource in resources
    ):
        raise TypeError("modbus backend resources must be list[str]")
    return BackendRegistration(
        backend=ModbusBackend(resources=resources),
        prefixes=("MODBUS::",),
    )


__all__ = ["make_backend"]
