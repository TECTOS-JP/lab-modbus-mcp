# Changelog

## Unreleased

### Added

- MB-1 package skeleton for `lab-modbus-mcp` 0.1.0.
- Strict parsers for `MODBUS::` RTU/TCP resources and RH/RI/RC/RD/WH/WC wire
  commands.
- Register codecs for u16/s16 and explicit big-/little-word-order 32-bit integer
  and float types, plus deterministic type-specific scale handling.
- In-memory `MockModbusBackend` with injectable register/bit maps and logical
  initial values.
- Importable, unconnected `ModbusBackend` skeleton for the MB-2 transport seam.
- `lab_executor.backends` entry-point registration with `MODBUS::` ownership.
- BEF backend-conformance, fail-closed grammar, round-trip, word-order,
  resource-parser, discovery, and packaging tests.

### Fixed

- Preserve fractional float32 values during scaled writes; only integer
  registers apply ties-to-even rounding.
- Require explicit word order for 32-bit integers (`u32be/le`, `s32be/le`) and
  reject ambiguous bare `u32` / `s32` tokens.
- Add root `conftest.py` so local source imports work without installing this
  project; metadata-dependent entry-point tests skip clearly when uninstalled.
