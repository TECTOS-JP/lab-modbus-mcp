# lab-modbus-mcp

Modbus RTU / TCP instrument backend package for
[lab-executor-mcp](https://github.com/TECTOS-JP/lab-executor-mcp).

## Status

MB-1 provides the package skeleton, strict wire-command grammar, resource-name
parser, in-memory `MockModbusBackend`, backend entry point, and an importable
`ModbusBackend` skeleton. Real RTU/TCP transport is intentionally not included;
it is scheduled for MB-2. The skeleton validates its input and then raises
`ModbusTransportUnavailable` without importing pymodbus or touching a bus.

## Wire commands

The existing instrument-definition `scpi` field carries a formatted Modbus wire
command. lab-executor remains protocol-independent and continues to enforce
parameter ranges and capabilities before calling the backend.

```text
RH <addr> <type> [s<scale>]
RI <addr> <type> [s<scale>]
RC <addr>
RD <addr>
WH <addr> <type> [s<scale>] <value>
WC <addr> <0|1>
```

Register types are `u16`, `s16`, `u32`, `s32`, `float32be`, and `float32le`.
Ambiguous `float32` is rejected. `u32` and `s32` use high-word-first Modbus
order. For float32, `be` and `le` describe word order; bytes inside each
16-bit register retain Modbus big-endian order.

On read, scale is `raw * scale`. On write it is
`round(value / scale)` using Python's ties-to-even `round`; the default scale is
1.0. Unknown tokens, extra arguments, missing values, non-finite numbers, and
out-of-range addresses fail closed.

## Resource names

```text
MODBUS::COM3::1
MODBUS::/dev/ttyUSB0::1
MODBUS::192.168.0.10::502::1
```

The first two forms are RTU; the third is TCP. Unit IDs are restricted to
1–247. TCP ports are 1–65535. The entry point owns only the `MODBUS::` prefix.

## Mock backend

Raw 16-bit register maps can be injected for low-level codec tests. Logical
initial values can inject type and scale together by using read commands as
keys:

```python
from lab_modbus_mcp import MockModbusBackend

backend = MockModbusBackend(
    initial_values={
        "RH 0 u16 s0.1": 25.0,
        "RI 10 s16": -4,
        "RC 20": True,
    }
)
```

The mock has no separate raw-write or register-write helper. Its Protocol
`write()` accepts only `WH` and `WC`. Production use must invoke it through
declared `type: write` instrument commands so lab-executor performs its existing
range and capability gates; the backend Protocol itself is not a replacement
for that safety boundary.

For the BEF conformance kit only, the mock recognizes exact `*IDN?` and `CONF`
probes as side-effect-free operations. Pass `allow_conformance_probes=False` to
disable them. The normal wire parser and real backend skeleton reject both.

## Entry point

Installing the package registers:

```toml
[project.entry-points."lab_executor.backends"]
modbus = "lab_modbus_mcp.discovery:make_backend"
```

`make_backend(config)` accepts only an optional `resources: list[str]` value and
returns `BackendRegistration(prefixes=("MODBUS::",))`. Unknown configuration
keys are rejected.

## Development

```console
python -m pytest -q
python -m build
```

## License

MIT
