# lab-modbus-mcp

Modbus RTU / TCP instrument backend package for
[lab-executor-mcp](https://github.com/TECTOS-JP/lab-executor-mcp).

## Status

MB-2 provides asynchronous Modbus TCP and RTU transport through pymodbus 3.x,
in addition to the strict MB-1 grammar, codecs, resource parser, and in-memory
mock. Connections are opened lazily and reused until communication fails or
`close()` is called.

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

## Development

```console
python -m pytest -q
python -m build
```

## License

MIT
