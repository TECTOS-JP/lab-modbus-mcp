# lab-modbus-mcp

Modbus RTU / TCP instrument backend package for
[lab-executor-mcp](https://github.com/TECTOS-JP/lab-executor-mcp).

## Status

MB-3 adds a thin MCP CLI, CI and Trusted Publishing workflows, and an
experimental OMRON E5CC reference definition and ramp/hold recipe. MB-2
provides asynchronous Modbus TCP and RTU transport through pymodbus 3.x.
Connections are opened lazily and reused until communication fails or
`close()` is called.

## Three usage modes

### A: backend by itself

`ModbusBackend` implements the lab-executor `InstrumentBackend` protocol and
can be injected into another Python application. This is the low-level mode;
the caller must apply its own command allowlist and value-range policy.

```python
from lab_modbus_mcp import ModbusBackend

backend = ModbusBackend(resources=["MODBUS::COM3::1"])
value = await backend.query("MODBUS::COM3::1", "RH 8192 s16 s0.1")
backend.close()
```

### B: standalone MCP server

The CLI uses only the public BEF server contract (`compose_server` and
`run_mcp_with_control`). `--control-port 0` lets the OS choose a localhost
control port. `--dry-run` performs composition without connecting to a bus and
prints the available MCP tools.

```console
lab-modbus serve --resource MODBUS::COM3::1 --baudrate 9600 --parity E
lab-modbus serve --resource MODBUS::192.168.0.10::502::1 --dry-run
```

### C: part of an integrated lab

Installation registers the `modbus` backend entry point. lab-executor can
discover it and combine it with VISA or another backend through
`CompositeBackend`; the case-sensitive `MODBUS::` prefix selects this backend.

```yaml
# instruments/_system.yaml
backends:
  visa: {}
  modbus:
    resources:
      - "MODBUS::COM3::1"
    baudrate: 9600
    bytesize: 8
    parity: "E"
    stopbits: 1
```

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

Register types are `u16`, `s16`, `u32be`, `u32le`, `s32be`, `s32le`,
`float32be`, and `float32le`. Every 32-bit type must explicitly declare word
order; ambiguous `u32`, `s32`, and `float32` are rejected. `be` is high-word
first and `le` is low-word first. Bytes inside each 16-bit register retain
Modbus big-endian order.

On read, scale is `raw * scale` for every type. On write, integer register types
use `round(value / scale)` with Python's ties-to-even `round`, while float32
types use `value / scale` without rounding so fractional values are preserved.
The default scale is 1.0. Unknown tokens, extra arguments, missing values,
non-finite numbers, and out-of-range addresses fail closed.

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
disable them. The normal wire parser and real backend reject both.

## Transport configuration

The entry-point configuration accepts the following keys. Unknown keys are
rejected.

| key | default | meaning |
|---|---:|---|
| `resources` | `[]` | configured RTU/TCP resource names; no bus scan occurs |
| `read_retries` | `1` | retries after a read communication failure |
| `baudrate` | `9600` | RTU baud rate |
| `bytesize` | `8` | RTU data bits (5–8) |
| `parity` | `N` | RTU parity (`N`, `E`, or `O`) |
| `stopbits` | `1` | RTU stop bits (1, 1.5, or 2) |

The serial settings apply to every configured RTU port in that backend
instance. TCP resources take host and port from their resource names.

```python
registration = make_backend(
    {
        "resources": [
            "MODBUS::COM3::1",
            "MODBUS::192.168.0.10::502::2",
        ],
        "read_retries": 1,
        "baudrate": 19200,
        "bytesize": 8,
        "parity": "E",
        "stopbits": 1,
    }
)
```

Each `query()` and `write()` call enforces its `timeout_ms`. Communication
failures close the affected connection, and the next attempt reconnects.
Reads may retry according to `read_retries`. Writes are never automatically
retried, even when the outcome is unknown after a timeout; retrying could apply
the same physical action twice. A 32-bit write is always sent as one
`write_registers` request containing both words.

Transactions are serialized by physical bus: RTU uses `serial_port`, and TCP
uses `host:tcp_port`. Unit ID is intentionally not part of the lock key because
multiple units can share one serial line or gateway connection. Explicit
Modbus exception responses are reported separately from timeout, disconnect,
CRC, and framing communication failures and are not retried.

`close()` is synchronous, idempotent, and best-effort. Calling it prevents new
I/O through that backend instance.

## Entry point

Installing the package registers:

```toml
[project.entry-points."lab_executor.backends"]
modbus = "lab_modbus_mcp.discovery:make_backend"
```

`make_backend(config)` returns
`BackendRegistration(prefixes=("MODBUS::",))` and accepts only the transport
configuration listed above.

## RTU verification scope

Automated tests verify RTU client construction, configured serial parameters,
unit-ID forwarding, and serial-port lock sharing. They do not claim physical
RTU communication coverage because no serial adapter or field device is
available in CI. TCP coverage uses a real pymodbus asynchronous server over a
loopback socket and exercises protocol framing, all register types, scaling,
coils, and discrete/input reads.

## Bundled OMRON E5CC reference definition

The package contains
`builtin_instruments/omron_e5cc_2byte_01c.yaml`. It is based only on OMRON's
public **E5[]C Digital Temperature Controllers Communications Manual,
H175-E1-18**, sections 4-4-3 and 5-1:

- PV: two-byte-mode address `0x2000`
- internal SP: two-byte-mode address `0x2002`
- writable SP: two-byte-mode address `0x2103`
- RUN/STOP: operation-command address `0x0000`, values `0x0100` / `0x0101`

Source: <https://www.omron-ap.com/data_pdf/mnu/h175-e1-18_e5_c.pdf?id=3102>

No undocumented register address was guessed. The profile deliberately assumes
two-byte Modbus mode and a decimal-point setting of one (`0.1 degC`). Its
`0..400 degC` SP range is a conservative template application limit, not a
universal E5CC sensor range. Confirm the exact model supports RS-485, enable
communications writing, and verify the mode, decimal point, sensor range,
limits, wiring, and fail-safe hardware before use.

The definition declares `metadata.support_level: experimental` because it was
derived from a manual and has not been tested on hardware. Its description also
states that the register addresses require confirmation. Do not change the
support level to `verified` until identify, commands, state queries,
verification, and safe shutdown have all been checked on the target hardware.

The bundled `temperature_ramp_and_hold_reference` recipe performs incremental
SP writes, waits for stability with `wait_for_stable`, then holds. It uses
`MODBUS::COM3::1` as an explicit template resource and must be adjusted for the
real resource and thermal process. It is a reference, not a validated thermal
profile.

## Safety

- Through lab-executor, writable registers must be exposed by named instrument
  commands. The bundled E5CC definition exposes only SP and documented
  RUN/STOP operations; its variable SP argument has a mandatory range.
- The low-level backend does not turn arbitrary wire commands into a safe
  device policy. Mode A callers must enforce an equivalent allowlist and ranges.
- Writes are never automatically retried, preventing an unknown outcome from
  being applied twice.
- Every 32-bit value is transferred in one multi-register transaction.
- Bus access is serialized per serial port or TCP host/port.
- The bundled definition is hardware-unverified and marked `experimental`.

## Development

```console
python -m pytest -q
ruff check src tests
ruff format --check src tests
python -m build
python -m twine check dist/*
```

## License

MIT
