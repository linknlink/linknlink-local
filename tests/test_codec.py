"""Tests for the LinknLink IR/RF wire-format codec."""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

CODEC_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "custom_components"
    / "linknlink"
    / "codec.py"
)
spec = importlib.util.spec_from_file_location("linknlink_codec", CODEC_PATH)
codec = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(codec)


def test_encode_ir_simple():
    # 560 us / 32.84 ~= 17 ticks (0x11), 1690 us ~= 51 ticks (0x33).
    blob = codec.encode_ir([560, 560, 1690])
    assert blob == bytes.fromhex("26 00 03 00 11 11 33 0d 05".replace(" ", ""))


def test_encode_rf_433():
    blob = codec.encode_rf([400, 800, 400], frequency_hz=433_920_000)
    # 400 us -> 12 ticks (0x0c), 800 us -> 24 ticks (0x18).
    assert blob == bytes.fromhex("b2 00 03 00 0c 18 0c 0d 05".replace(" ", ""))


def test_encode_rf_315():
    blob = codec.encode_rf([400], frequency_hz=315_000_000)
    assert blob[0] == codec.CODE_RF_315


def test_encode_rf_rejects_unsupported_band():
    with pytest.raises(ValueError):
        codec.encode_rf([400], frequency_hz=868_000_000)


def test_long_pulse_uses_16bit_form():
    # 10000 us / 32.84 ~= 305 ticks = 0x0131, encoded as 00 01 31.
    blob = codec.encode_ir([10_000])
    # header (4) + 3 bytes pulse + terminator (2)
    assert len(blob) == 4 + 3 + 2
    assert blob[2:4] == bytes((3, 0))  # length LE
    assert blob[4:7] == bytes((0x00, 0x01, 0x31))


def test_repeat_byte():
    blob = codec.encode_ir([560], repeat=3)
    assert blob[1] == 3


def test_round_trip_mixed_lengths():
    timings = [560, 560, 1690, 9000, 4500, 560, 1690, 560, 560, 11_000]
    blob = codec.encode_ir(timings, repeat=2)
    code_type, repeat, decoded = codec.decode(blob)
    assert code_type == codec.CODE_IR
    assert repeat == 2
    # Round-trip is lossy by one tick (rounding); check within tolerance.
    assert len(decoded) == len(timings)
    for original, got in zip(timings, decoded):
        assert abs(got - original) <= int(codec.TICK_US) + 1


def test_round_trip_rf():
    timings = [350, 1050, 350, 1050, 9500]
    blob = codec.encode_rf(timings, frequency_hz=433_920_000)
    code_type, repeat, decoded = codec.decode(blob)
    assert code_type == codec.CODE_RF_433
    assert repeat == 0
    for original, got in zip(timings, decoded):
        assert abs(got - original) <= int(codec.TICK_US) + 1


def test_negative_pulse_rejected():
    with pytest.raises(ValueError):
        codec.encode_ir([-1])


def test_zero_pulse_clamped_to_one_tick():
    blob = codec.encode_ir([1])  # well below one tick
    assert blob[4] == 1  # clamped to minimum 1 tick instead of 0
