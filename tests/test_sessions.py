"""Binding resources to definitions, only where an operator says so.

The package carried an instrument definition that nothing loaded, so a
configured device was reported as unidentified by every description tool —
verified against a live server. Unlike the other backends the binding cannot be
inferred here, and these tests pin that it is never guessed.
"""

from __future__ import annotations

import pytest

from lab_modbus_mcp.cli import _parse_instruments
from lab_modbus_mcp.sessions import (
    available_definitions,
    build_sessions,
    load_definition,
    register_sessions,
)

RESOURCE = "MODBUS::COM3::1"
E5CC = "omron_e5cc_2byte_01c"


class _Facade:
    def __init__(self):
        self.sessions = {}

    def register_session(self, name, session):
        self.sessions[name] = session

    def get_session(self, name):
        return self.sessions.get(name)


class _JobMgr:
    def __init__(self):
        self.session_manager = _Facade()


def test_the_bundled_definition_loads():
    assert E5CC in available_definitions()
    definition = load_definition(E5CC)
    assert definition is not None
    assert definition.metadata.manufacturer == "OMRON"
    assert definition.commands


def test_an_explicit_mapping_resolves():
    sessions = build_sessions({RESOURCE: E5CC})
    assert set(sessions) == {RESOURCE}
    assert sessions[RESOURCE].definition.metadata.manufacturer == "OMRON"
    assert sessions[RESOURCE].command_history == []


def test_nothing_is_bound_without_an_explicit_mapping():
    """A resource name says nothing about what is on the other end.

    Binding the one bundled definition to whatever happens to be configured
    would point writes at register addresses that mean something else on a
    different device, and no Modbus response would contradict the mistake.
    """
    assert build_sessions({}) == {}
    assert register_sessions(_JobMgr(), {}) == []


def test_an_unknown_definition_name_is_refused_not_skipped():
    """Skipping would leave the operator believing the binding took effect."""
    with pytest.raises(ValueError, match="unknown instrument definition"):
        build_sessions({RESOURCE: "no_such_device"})


def test_a_definition_name_cannot_escape_the_package():
    assert load_definition("../../etc/passwd") is None
    assert load_definition(".hidden") is None


def test_register_attaches_sessions_to_the_facade():
    job_mgr = _JobMgr()
    assert register_sessions(job_mgr, {RESOURCE: E5CC}) == [RESOURCE]
    session = job_mgr.session_manager.get_session(RESOURCE)
    assert session.definition.metadata.manufacturer == "OMRON"


def test_register_is_harmless_when_the_facade_cannot_take_sessions():
    class _Bare:
        session_manager = object()

    assert register_sessions(_Bare(), {RESOURCE: E5CC}) == []


@pytest.mark.parametrize(
    "entries, expected",
    [
        ([], {}),
        ([f"{RESOURCE}={E5CC}"], {RESOURCE: E5CC}),
        (
            [f"{RESOURCE}={E5CC}", f"MODBUS::COM4::2={E5CC}"],
            {RESOURCE: E5CC, "MODBUS::COM4::2": E5CC},
        ),
    ],
)
def test_cli_pairs_are_parsed(entries, expected):
    assert _parse_instruments(entries) == expected


@pytest.mark.parametrize("entry", ["no-equals-sign", "=definition", "resource="])
def test_malformed_cli_pairs_are_refused(entry):
    with pytest.raises(ValueError, match="RESOURCE=DEFINITION"):
        _parse_instruments([entry])
