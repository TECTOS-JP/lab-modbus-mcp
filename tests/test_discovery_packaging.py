from __future__ import annotations

from importlib import metadata
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib

import pytest

from lab_executor.backends import BackendRegistration, discover_backends

from lab_modbus_mcp.backend import ModbusBackend
from lab_modbus_mcp.discovery import make_backend


def _installed_modbus_entry_points():
    matches = [
        ep
        for ep in metadata.entry_points(group="lab_executor.backends")
        if ep.name == "modbus"
    ]
    if not matches:
        pytest.skip(
            "lab-modbus-mcp installation metadata is required for entry-point tests"
        )
    return matches


def test_factory_returns_modbus_registration():
    registration = make_backend(
        {
            "resources": ["MODBUS::COM3::1", "MODBUS::host::502::2"],
            "read_retries": 2,
            "baudrate": 19200,
            "bytesize": 7,
            "parity": "E",
            "stopbits": 2,
        }
    )
    assert isinstance(registration, BackendRegistration)
    assert isinstance(registration.backend, ModbusBackend)
    assert registration.prefixes == ("MODBUS::",)


def test_factory_rejects_unknown_or_malformed_config():
    with pytest.raises(ValueError, match="unknown"):
        make_backend({"raw_write": True})
    with pytest.raises(TypeError):
        make_backend({"resources": "MODBUS::COM3::1"})
    with pytest.raises(TypeError):
        make_backend([])  # type: ignore[arg-type]


def test_installed_entry_point_discovers_factory():
    matches = _installed_modbus_entry_points()
    assert len(matches) == 1
    assert matches[0].load() is make_backend


def test_bef_discovery_constructs_installed_modbus_backend():
    _installed_modbus_entry_points()
    registrations = discover_backends(["modbus"])
    assert len(registrations) == 1
    assert isinstance(registrations[0].backend, ModbusBackend)
    assert registrations[0].prefixes == ("MODBUS::",)


def test_pyproject_has_frozen_packaging_metadata():
    root = Path(__file__).parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    assert project["name"] == "lab-modbus-mcp"
    assert project["version"] == "0.1.0"
    assert "lab-executor-mcp>=2.35.0,<3.0.0" in project["dependencies"]
    assert "pymodbus>=3.6,<4.0" in project["dependencies"]
    assert "pyserial>=3.5" in project["dependencies"]
    assert project["license-files"] == ["LICENSE"]
    assert set(project["urls"]) >= {"Homepage", "Repository", "Changelog", "Issues"}
    entry_points = project["entry-points"]["lab_executor.backends"]
    assert entry_points["modbus"] == "lab_modbus_mcp.discovery:make_backend"
    assert project["scripts"]["lab-modbus"] == "lab_modbus_mcp.cli:main"
    include = data["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert include and all(item.startswith("/") for item in include)
    assert "/conftest.py" in include
