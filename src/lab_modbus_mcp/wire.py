"""Parser and register codecs for the lab-modbus wire command language."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
import struct
from typing import Literal


READ_OPS = frozenset({"RH", "RI", "RC", "RD"})
WRITE_OPS = frozenset({"WH", "WC"})
REGISTER_TYPES = frozenset(
    {
        "u16",
        "s16",
        "u32",
        "s32",
        "float32be",
        "float32le",
    }
)
INTEGER_TYPES = frozenset({"u16", "s16", "u32", "s32"})
FLOAT_TYPES = frozenset({"float32be", "float32le"})
_ADDRESS_RE = re.compile(r"[0-9]+", re.ASCII)
_NUMBER_RE = re.compile(
    r"[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?)|(?:\.[0-9]+))"
    r"(?:[eE][+-]?[0-9]+)?",
    re.ASCII,
)


class WireCommandError(ValueError):
    """The wire command is malformed, ambiguous, or out of range."""


@dataclass(frozen=True)
class WireCommand:
    opcode: Literal["RH", "RI", "RC", "RD", "WH", "WC"]
    address: int
    data_type: str | None = None
    scale: float = 1.0
    value: float | bool | None = None

    @property
    def is_read(self) -> bool:
        return self.opcode in READ_OPS

    @property
    def is_write(self) -> bool:
        return self.opcode in WRITE_OPS


def _address(token: str) -> int:
    if not _ADDRESS_RE.fullmatch(token):
        raise WireCommandError("address must be a decimal integer")
    address = int(token)
    if not 0 <= address <= 65535:
        raise WireCommandError("address must be between 0 and 65535")
    return address


def _number(token: str, label: str) -> float:
    if not _NUMBER_RE.fullmatch(token):
        raise WireCommandError(f"{label} must be a finite decimal number")
    value = float(token)
    if not math.isfinite(value):
        raise WireCommandError(f"{label} must be finite")
    return value


def _scale(token: str) -> float:
    if not token.startswith("s") or len(token) == 1:
        raise WireCommandError("scale token must have the form s<number>")
    scale = _number(token[1:], "scale")
    if scale == 0:
        raise WireCommandError("scale must not be zero")
    return scale


def _register_type(token: str) -> str:
    if token not in REGISTER_TYPES:
        raise WireCommandError(
            f"unsupported register type {token!r}; 32-bit float word order "
            "must be explicit"
        )
    return token


def _validate_register_span(address: int, data_type: str) -> None:
    if data_type not in {"u16", "s16"} and address == 65535:
        raise WireCommandError("32-bit value at address 65535 exceeds register space")


def parse_wire_command(command: str) -> WireCommand:
    """Parse exactly one command; extra or unknown tokens are rejected."""
    if not isinstance(command, str):
        raise WireCommandError("command must be a string")
    if command != command.strip() or not command:
        raise WireCommandError("command must be non-empty with no outer whitespace")
    tokens = command.split()
    opcode = tokens[0]

    if opcode in {"RC", "RD"}:
        if len(tokens) != 2:
            raise WireCommandError(f"{opcode} requires exactly an address")
        return WireCommand(opcode=opcode, address=_address(tokens[1]))

    if opcode == "WC":
        if len(tokens) != 3:
            raise WireCommandError("WC requires exactly an address and 0 or 1")
        if tokens[2] not in {"0", "1"}:
            raise WireCommandError("WC value must be exactly 0 or 1")
        return WireCommand(
            opcode="WC",
            address=_address(tokens[1]),
            value=tokens[2] == "1",
        )

    if opcode in {"RH", "RI"}:
        if len(tokens) not in {3, 4}:
            raise WireCommandError(
                f"{opcode} requires address, type, and optional scale"
            )
        address = _address(tokens[1])
        data_type = _register_type(tokens[2])
        _validate_register_span(address, data_type)
        scale = _scale(tokens[3]) if len(tokens) == 4 else 1.0
        return WireCommand(
            opcode=opcode,
            address=address,
            data_type=data_type,
            scale=scale,
        )

    if opcode == "WH":
        if len(tokens) not in {4, 5}:
            raise WireCommandError(
                "WH requires address, type, optional scale, and value"
            )
        if len(tokens) == 5:
            scale = _scale(tokens[3])
            value_token = tokens[4]
        else:
            scale = 1.0
            value_token = tokens[3]
        address = _address(tokens[1])
        data_type = _register_type(tokens[2])
        _validate_register_span(address, data_type)
        return WireCommand(
            opcode="WH",
            address=address,
            data_type=data_type,
            scale=scale,
            value=_number(value_token, "value"),
        )

    raise WireCommandError(f"unknown opcode {opcode!r}")


def register_count(data_type: str) -> int:
    _register_type(data_type)
    return 1 if data_type in {"u16", "s16"} else 2


def encode_registers(value: int | float, data_type: str) -> tuple[int, ...]:
    """Encode one raw value into unsigned 16-bit Modbus words."""
    _register_type(data_type)
    if data_type in INTEGER_TYPES:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise WireCommandError("integer register value must be numeric")
        if not math.isfinite(float(value)) or float(value) != int(value):
            raise WireCommandError("integer register value must be an integer")
        integer = int(value)
        ranges = {
            "u16": (0, 0xFFFF),
            "s16": (-(1 << 15), (1 << 15) - 1),
            "u32": (0, 0xFFFFFFFF),
            "s32": (-(1 << 31), (1 << 31) - 1),
        }
        minimum, maximum = ranges[data_type]
        if not minimum <= integer <= maximum:
            raise WireCommandError(f"value is out of range for {data_type}")
        bits = 16 if data_type in {"u16", "s16"} else 32
        unsigned = integer & ((1 << bits) - 1)
        if bits == 16:
            return (unsigned,)
        # u32/s32 use the Modbus conventional high-word-first order.
        return ((unsigned >> 16) & 0xFFFF, unsigned & 0xFFFF)

    number = float(value)
    if not math.isfinite(number):
        raise WireCommandError("float register value must be finite")
    try:
        packed = struct.pack(">f", number)
    except OverflowError as exc:
        raise WireCommandError("float register value is out of float32 range") from exc
    high, low = struct.unpack(">HH", packed)
    return (high, low) if data_type == "float32be" else (low, high)


def decode_registers(words: tuple[int, ...] | list[int], data_type: str) -> int | float:
    """Decode unsigned 16-bit words according to an explicit register type."""
    expected = register_count(data_type)
    if len(words) != expected:
        raise WireCommandError(f"{data_type} requires exactly {expected} register(s)")
    if any(
        isinstance(word, bool) or not isinstance(word, int) or not 0 <= word <= 0xFFFF
        for word in words
    ):
        raise WireCommandError("register words must be integers between 0 and 65535")

    if data_type == "u16":
        return words[0]
    if data_type == "s16":
        return words[0] - 0x10000 if words[0] & 0x8000 else words[0]

    high, low = words if data_type != "float32le" else (words[1], words[0])
    unsigned = (high << 16) | low
    if data_type == "u32":
        return unsigned
    if data_type == "s32":
        return unsigned - 0x100000000 if unsigned & 0x80000000 else unsigned
    number = struct.unpack(">f", struct.pack(">HH", high, low))[0]
    if not math.isfinite(number):
        raise WireCommandError("decoded float register value must be finite")
    return number


def encode_scaled_value(
    value: int | float, data_type: str, scale: float
) -> tuple[int, ...]:
    if not math.isfinite(scale) or scale == 0:
        raise WireCommandError("scale must be finite and non-zero")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WireCommandError("scaled value must be numeric, not bool")
    number = float(value)
    if not math.isfinite(number):
        raise WireCommandError("scaled value must be finite")
    scaled = number / scale
    if not math.isfinite(scaled):
        raise WireCommandError("scaled raw value must be finite")
    raw = round(scaled)
    return encode_registers(raw, data_type)


def decode_scaled_value(
    words: tuple[int, ...] | list[int],
    data_type: str,
    scale: float,
) -> int | float:
    if not math.isfinite(scale) or scale == 0:
        raise WireCommandError("scale must be finite and non-zero")
    value = decode_registers(words, data_type) * scale
    if not math.isfinite(value):
        raise WireCommandError("scaled decoded value must be finite")
    return value


__all__ = [
    "FLOAT_TYPES",
    "INTEGER_TYPES",
    "READ_OPS",
    "REGISTER_TYPES",
    "WRITE_OPS",
    "WireCommand",
    "WireCommandError",
    "decode_registers",
    "decode_scaled_value",
    "encode_registers",
    "encode_scaled_value",
    "parse_wire_command",
    "register_count",
]
