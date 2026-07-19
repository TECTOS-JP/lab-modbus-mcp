from __future__ import annotations

import math

import pytest

from lab_modbus_mcp.wire import (
    WireCommandError,
    decode_registers,
    decode_scaled_value,
    encode_registers,
    encode_scaled_value,
    parse_wire_command,
    register_count,
)


@pytest.mark.parametrize(
    ("text", "opcode", "address", "data_type", "scale", "value"),
    [
        ("RH 0 u16", "RH", 0, "u16", 1.0, None),
        ("RI 12 s16 s0.1", "RI", 12, "s16", 0.1, None),
        ("RC 3", "RC", 3, None, 1.0, None),
        ("RD 4", "RD", 4, None, 1.0, None),
        ("WH 4 u16 25", "WH", 4, "u16", 1.0, 25.0),
        ("WH 5 s32 s0.01 -3.5", "WH", 5, "s32", 0.01, -3.5),
        ("WC 6 0", "WC", 6, None, 1.0, False),
        ("WC 6 1", "WC", 6, None, 1.0, True),
    ],
)
def test_parse_all_operations(text, opcode, address, data_type, scale, value):
    parsed = parse_wire_command(text)
    assert parsed.opcode == opcode
    assert parsed.address == address
    assert parsed.data_type == data_type
    assert parsed.scale == scale
    assert parsed.value == value


@pytest.mark.parametrize(
    "data_type",
    ["u16", "s16", "u32", "s32", "float32be", "float32le"],
)
def test_all_declared_register_types_parse(data_type):
    assert parse_wire_command(f"RH 0 {data_type}").data_type == data_type


@pytest.mark.parametrize(
    "text",
    [
        "",
        " RH 0 u16",
        "RH 0 u16 ",
        "XX 0 u16",
        "RH",
        "RH 0",
        "RH 0 u16 extra extra",
        "RH -1 u16",
        "RH 65536 u16",
        "RH 0 float32",
        "RH 65535 u32",
        "WH 65535 float32be 1",
        "RH 0 U16",
        "RH 0 u16 0.1",
        "RH 0 u16 s0",
        "RH 0 u16 snan",
        "RI 0 u16 value",
        "RC",
        "RC 0 extra",
        "WH 0 u16",
        "WH 0 u16 s0.1",
        "WH 0 u16 s0.1 1 extra",
        "WH 0 u16 nope",
        "WC 0",
        "WC 0 2",
        "WC 0 true",
        "WC 0 1 extra",
        "*IDN?",
        "CONF",
    ],
)
def test_invalid_commands_fail_closed(text):
    with pytest.raises(WireCommandError):
        parse_wire_command(text)


@pytest.mark.parametrize(
    ("value", "data_type"),
    [
        (0, "u16"),
        (65535, "u16"),
        (-32768, "s16"),
        (32767, "s16"),
        (0, "u32"),
        (0xFFFFFFFF, "u32"),
        (-(1 << 31), "s32"),
        ((1 << 31) - 1, "s32"),
        (1.25, "float32be"),
        (1.25, "float32le"),
    ],
)
def test_register_codec_round_trip(value, data_type):
    decoded = decode_registers(encode_registers(value, data_type), data_type)
    assert decoded == pytest.approx(value)


def test_32bit_integer_order_is_high_word_first():
    assert encode_registers(0x11223344, "u32") == (0x1122, 0x3344)


def test_float_word_orders_are_distinct_and_decode_equivalently():
    big = encode_registers(12.5, "float32be")
    little = encode_registers(12.5, "float32le")
    assert big == tuple(reversed(little))
    assert big != little
    assert decode_registers(big, "float32be") == pytest.approx(12.5)
    assert decode_registers(little, "float32le") == pytest.approx(12.5)


@pytest.mark.parametrize(
    ("value", "data_type"),
    [
        (-1, "u16"),
        (65536, "u16"),
        (-32769, "s16"),
        (32768, "s16"),
        (-1, "u32"),
        (1 << 32, "u32"),
        (-(1 << 31) - 1, "s32"),
        (1 << 31, "s32"),
        (1.5, "u16"),
    ],
)
def test_register_codec_rejects_out_of_range_or_fractional_integer(value, data_type):
    with pytest.raises(WireCommandError):
        encode_registers(value, data_type)


def test_scale_round_trip_and_rounding_rule():
    words = encode_scaled_value(25.0, "u16", 0.1)
    assert words == (250,)
    assert decode_scaled_value(words, "u16", 0.1) == pytest.approx(25.0)
    assert encode_scaled_value(0.25, "u16", 0.1) == (2,)


def test_codec_rejects_wrong_word_count_and_invalid_words():
    with pytest.raises(WireCommandError):
        decode_registers([1], "u32")
    with pytest.raises(WireCommandError):
        decode_registers([-1], "u16")
    with pytest.raises(WireCommandError):
        decode_registers([True], "u16")


def test_non_finite_float_encoding_rejected():
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(WireCommandError):
            encode_registers(value, "float32be")


def test_scale_overflow_is_rejected():
    with pytest.raises(WireCommandError):
        encode_scaled_value(1.0, "u16", 1e-320)
    with pytest.raises(WireCommandError):
        decode_scaled_value([0x7F7F, 0xFFFF], "float32be", 1e308)


def test_register_count_rejects_unknown_type():
    with pytest.raises(WireCommandError):
        register_count("float32")
