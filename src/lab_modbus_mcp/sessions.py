"""Bind resources to instrument definitions, only where an operator says so.

The package carries ``builtin_instruments/*.yaml``, but nothing put them in
front of the runtime: the server was composed with a backend and no sessions,
so every definition-driven tool reported a configured device as unidentified.

Unlike the other backends, the binding here **cannot be inferred**. A BLE
resource names its own profile, and a DAQ device's configured model is checked
against the hardware on first contact. A Modbus resource name is just a port
and a unit id — it says nothing about what is on the other end, and nothing in
the protocol will contradict a wrong guess. Binding the wrong definition would
point writes at register addresses that mean something else entirely on that
device, so the mapping is explicit or it does not happen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from typing import Any

import yaml
from lab_executor.models.instrument_def import InstrumentDefinition


@dataclass
class ModbusSession:
    """The session surface the runtime's tools actually use."""

    resource_name: str
    definition: InstrumentDefinition
    command_history: list[Any] = field(default_factory=list)


def available_definitions() -> list[str]:
    """Names of the bundled definitions, for error messages and discovery."""
    root = resources.files("lab_modbus_mcp.builtin_instruments")
    return sorted(
        entry.name[: -len(".yaml")]
        for entry in root.iterdir()
        if entry.name.endswith(".yaml")
    )


def load_definition(name: str) -> InstrumentDefinition | None:
    """Load one bundled definition by file name, or None if there is none."""
    if "/" in name or "\\" in name or name.startswith("."):
        return None
    source = resources.files("lab_modbus_mcp.builtin_instruments").joinpath(
        f"{name}.yaml"
    )
    if not source.is_file():
        return None
    return InstrumentDefinition(**yaml.safe_load(source.read_text(encoding="utf-8")))


def build_sessions(instruments: dict[str, str]) -> dict[str, ModbusSession]:
    """Resolve an explicit ``{resource_name: definition_name}`` mapping.

    A name with no bundled definition raises rather than being skipped: the
    operator asked for a specific instrument, and silently serving none would
    leave them thinking the binding took effect.
    """
    sessions: dict[str, ModbusSession] = {}
    for resource_name, definition_name in (instruments or {}).items():
        definition = load_definition(definition_name)
        if definition is None:
            raise ValueError(
                f"unknown instrument definition: {definition_name!r}; "
                f"available: {available_definitions()!r}"
            )
        sessions[resource_name] = ModbusSession(
            resource_name=resource_name, definition=definition
        )
    return sessions


def register_sessions(job_mgr: Any, instruments: dict[str, str]) -> list[str]:
    """Attach the resolved sessions to the running server's session facade."""
    facade = getattr(job_mgr, "session_manager", None)
    register = getattr(facade, "register_session", None)
    if register is None:
        return []
    bound: list[str] = []
    for resource_name, session in build_sessions(instruments).items():
        register(resource_name, session)
        bound.append(resource_name)
    return bound


__all__ = [
    "ModbusSession",
    "available_definitions",
    "build_sessions",
    "load_definition",
    "register_sessions",
]
