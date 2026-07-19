from __future__ import annotations

import asyncio
import ast
import json
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from lab_executor.backends import BackendRegistration, CompositeBackend
from lab_executor.job.manager import JobManager
from lab_executor.job.state_machine import JobStatus
from lab_executor.job.store import JobStore
from lab_executor.models.instrument_def import InstrumentDefinition
from lab_modbus_mcp.cli import main
from lab_modbus_mcp.mock_backend import MockModbusBackend


ROOT = Path(__file__).parents[1]
DEFINITION_PATH = (
    ROOT
    / "src"
    / "lab_modbus_mcp"
    / "builtin_instruments"
    / "omron_e5cc_2byte_01c.yaml"
)
RESOURCE = "MODBUS::COM3::1"


def _raw_definition() -> dict:
    return yaml.safe_load(DEFINITION_PATH.read_text(encoding="utf-8"))


def _definition() -> InstrumentDefinition:
    return InstrumentDefinition(**_raw_definition())


def test_builtin_definition_is_valid_and_truthfully_experimental():
    definition = _definition()
    assert definition.metadata.support_level == "experimental"
    assert definition.metadata.support_level != "verified"
    description = definition.metadata.description.lower()
    assert "hardware has not been verified" in description
    assert "confirm register addresses" in description


def test_builtin_definition_is_available_as_a_package_resource():
    resource = files("lab_modbus_mcp.builtin_instruments").joinpath(
        "omron_e5cc_2byte_01c.yaml"
    )
    assert resource.is_file()
    assert 'support_level: "experimental"' in resource.read_text("utf-8")


def test_builtin_definition_contains_only_documented_reference_operations():
    commands = _raw_definition()["commands"]
    assert {name: command["scpi"] for name, command in commands.items()} == {
        "read_process_value": "RH 8192 s16 s0.1",
        "read_internal_set_point": "RH 8194 s16 s0.1",
        "set_set_point": "WH 8451 s16 s0.1 {temperature_c}",
        "start_control": "WH 0 u16 256",
        "stop_control": "WH 0 u16 257",
    }


def test_every_parameter_of_every_write_command_has_a_range():
    commands = _raw_definition()["commands"]
    for name, command in commands.items():
        if command["type"] != "write":
            continue
        parameters = command.get("parameters", [])
        if not parameters:
            assert "{" not in command["scpi"], f"{name} has an undeclared argument"
        for parameter in parameters:
            assert "range" in parameter, f"{name}.{parameter['name']} lacks range"
    assert commands["set_set_point"]["parameters"][0]["range"] == [0, 400]


def test_polling_and_safe_shutdown_are_declared():
    raw = _raw_definition()
    assert raw["commands"]["read_process_value"]["polling_safe"] is True
    assert raw["commands"]["read_internal_set_point"]["polling_safe"] is True
    assert raw["safe_shutdown"] == [{"command": "stop_control"}]


@pytest.mark.asyncio
async def test_reference_ramp_recipe_completes_with_mock(tmp_path, monkeypatch):
    monkeypatch.setenv("VISA_MCP_SAFETY_MODE", "permissive")
    definition = _definition()
    backend = MockModbusBackend(
        resources=[RESOURCE],
        initial_values={
            "RH 8192 s16 s0.1": 40.0,
            "RH 8194 s16 s0.1": 20.0,
        },
    )
    session = SimpleNamespace(
        resource_name=RESOURCE,
        idn_response="<mock E5CC>",
        idn_parsed={"manufacturer": "OMRON", "model": "E5CC"},
        definition=definition,
        command_history=[],
    )
    session.record_command = session.command_history.append

    class SessionManager:
        def get_session(self, resource_name: str):
            return session if resource_name == RESOURCE else None

    store = JobStore(db_path=tmp_path / "jobs.sqlite")
    manager = JobManager(backend=backend, session_mgr=SessionManager(), store=store)
    record = await manager.start_recipe_job(
        RESOURCE,
        "temperature_ramp_and_hold_reference",
        {
            "start_c": 20,
            "target_c": 40,
            "step_c": 10,
            "ramp_points": 2,
            "step_interval_s": 0,
            "stability_tolerance_c": 0.5,
            "stability_window_s": 0.1,
            "stability_interval_s": 0.02,
            "stability_timeout_s": 1,
            "hold_s": 0,
        },
        job_timeout_s=3,
    )
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        current = manager.get(record.job_id)
        if current.status in {
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.TIMEOUT,
        }:
            break
        await asyncio.sleep(0.02)
    else:
        pytest.fail(
            f"mock ramp recipe did not reach a terminal state: {current.to_dict()}"
        )

    assert current.status is JobStatus.COMPLETED, current.to_dict()
    assert current.result and current.result["success"] is True
    assert float(await backend.query(RESOURCE, "RH 8451 s16 s0.1")) == 40.0


class OtherBackend:
    backend_id = "other"

    async def list_resources(self) -> list[str]:
        return ["OTHER::1"]

    async def query(self, resource_name: str, command: str, **_kwargs) -> str:
        return f"{resource_name}:{command}"

    async def write(self, resource_name: str, command: str, **_kwargs) -> None:
        self.last_write = (resource_name, command)

    def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_composite_backend_routes_modbus_prefix_to_mock():
    modbus = MockModbusBackend(
        resources=[RESOURCE], initial_values={"RH 8192 s16 s0.1": 25.0}
    )
    other = OtherBackend()
    composite = CompositeBackend(
        [
            BackendRegistration(backend=modbus, prefixes=("MODBUS::",)),
            BackendRegistration(backend=other, prefixes=("OTHER::",)),
        ]
    )

    assert float(await composite.query(RESOURCE, "RH 8192 s16 s0.1")) == 25.0
    assert await composite.query("OTHER::1", "PING") == "OTHER::1:PING"


def test_cli_dry_run_composes_server_and_lists_tools(capsys):
    assert main(["serve", "--resource", RESOURCE, "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["backend_id"] == "modbus"
    assert payload["resources"] == [RESOURCE]
    assert len(payload["tools"]) > 0
    assert {"execute_named_command", "start_recipe_job"} <= set(payload["tools"])


def test_cli_imports_only_public_lab_executor_contract_modules():
    tree = ast.parse((ROOT / "src" / "lab_modbus_mcp" / "cli.py").read_text("utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("lab_executor")
    }
    assert modules == {"lab_executor.control_plane", "lab_executor.server"}
