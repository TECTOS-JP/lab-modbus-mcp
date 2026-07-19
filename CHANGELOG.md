# Changelog

## Unreleased

### Added

- MB-1 package skeleton for `lab-modbus-mcp` 0.1.0.
- Strict parsers for `MODBUS::` RTU/TCP resources and RH/RI/RC/RD/WH/WC wire
  commands.
- Register codecs for u16/s16/u32/s32 and explicit float32 word order, plus
  deterministic scale handling.
- In-memory `MockModbusBackend` with injectable register/bit maps and logical
  initial values.
- Importable, unconnected `ModbusBackend` skeleton for the MB-2 transport seam.
- `lab_executor.backends` entry-point registration with `MODBUS::` ownership.
- BEF backend-conformance, fail-closed grammar, round-trip, word-order,
  resource-parser, discovery, and packaging tests.
