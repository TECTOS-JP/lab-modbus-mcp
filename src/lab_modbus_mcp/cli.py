"""Thin command-line wrapper around the public lab-executor server contract."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Sequence

from lab_executor.control_plane import run_mcp_with_control
from lab_executor.server import compose_server

from lab_modbus_mcp.backend import ModbusBackend


def _control_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("control port must be an integer") from exc
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("control port must be between 0 and 65535")
    return port


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lab-modbus",
        description="Run lab-modbus-mcp through the public lab-executor server API.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser(
        "serve", help="serve the Modbus backend over MCP stdio"
    )
    serve.add_argument(
        "--resource",
        action="append",
        required=True,
        help="configured MODBUS:: resource (repeat for multiple units/endpoints)",
    )
    serve.add_argument("--dry-run", action="store_true", help="compose and list tools")
    serve.add_argument("--read-retries", type=int, default=1)
    serve.add_argument("--baudrate", type=int, default=9600)
    serve.add_argument("--bytesize", type=int, default=8)
    serve.add_argument("--parity", choices=("N", "E", "O", "n", "e", "o"), default="N")
    serve.add_argument("--stopbits", type=float, choices=(1.0, 1.5, 2.0), default=1.0)
    serve.add_argument(
        "--control-port",
        type=_control_port,
        default=0,
        help="localhost control-plane port (default: 0, OS-assigned)",
    )
    return parser


async def _dry_run(mcp: object, backend: ModbusBackend) -> None:
    list_tools = getattr(mcp, "list_tools")
    tools = await list_tools()
    payload = {
        "backend_id": backend.backend_id,
        "resources": await backend.list_resources(),
        "tools": sorted(tool.name for tool in tools),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        backend = ModbusBackend(
            resources=args.resource,
            read_retries=args.read_retries,
            baudrate=args.baudrate,
            bytesize=args.bytesize,
            parity=args.parity,
            stopbits=args.stopbits,
        )
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))

    mcp, job_mgr = compose_server(backend, name="lab-modbus")
    try:
        if args.dry_run:
            asyncio.run(_dry_run(mcp, backend))
        else:
            asyncio.run(
                run_mcp_with_control(
                    mcp,
                    job_mgr,
                    args.control_port,
                    backend_id=backend.backend_id,
                )
            )
    finally:
        backend.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
