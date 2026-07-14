"""Encoders and decoders for LinknLink/Broadlink IR and RF wire format.

Wire format accepted by ``device.api.send_data``:

    byte 0      type: 0x26 = IR, 0xb2 = 433 MHz RF, 0xd7 = 315 MHz RF
    byte 1      repeat count (0 = send once)
    bytes 2-3   payload length, little-endian, in bytes (pulse data only)
    bytes 4..N  pulse data, each pulse in ticks of ~32.84 us
                  - value < 256: one byte
                  - value >= 256: 0x00 followed by value as 16-bit big-endian
    bytes N+1.. trailing terminator 0x0d 0x05

Microsecond <-> tick conversion uses ``round(us / 32.84)``. A tick is
269/8192 ms by Broadlink convention.
"""
from __future__ import annotations

from collections.abc import Iterable

TICK_US = 32.84

CODE_IR = 0x26
CODE_RF_433 = 0xB2
CODE_RF_315 = 0xD7

TERMINATOR = bytes((0x0D, 0x05))


def _us_to_ticks(us: float) -> int:
    if us < 0:
        raise ValueError(f"pulse duration must be non-negative, got {us}")
    ticks = int(round(us / TICK_US))
    return max(ticks, 1)


def _encode_pulses(timings: Iterable[float]) -> bytes:
    out = bytearray()
    for us in timings:
        units = _us_to_ticks(us)
        if units < 256:
            out.append(units)
        else:
            if units > 0xFFFF:
                raise ValueError(
                    f"pulse {us} us ({units} ticks) exceeds 16-bit range"
                )
            out.append(0x00)
            out.append((units >> 8) & 0xFF)
            out.append(units & 0xFF)
    return bytes(out)


def _encode(code_type: int, timings: Iterable[float], repeat: int = 0) -> bytes:
    if not 0 <= repeat <= 0xFF:
        raise ValueError(f"repeat must fit in one byte, got {repeat}")
    pulses = _encode_pulses(timings)
    length = len(pulses)
    if length > 0xFFFF:
        raise ValueError(f"pulse payload {length} bytes exceeds 16-bit length")
    header = bytes((code_type, repeat, length & 0xFF, (length >> 8) & 0xFF))
    return header + pulses + TERMINATOR


def encode_ir(timings: Iterable[float], repeat: int = 0) -> bytes:
    """Encode IR pulse timings (microseconds) for ``send_data``.

    Carrier frequency is fixed by the hardware and ignored.
    """
    return _encode(CODE_IR, timings, repeat)


def encode_rf(timings: Iterable[float], frequency_hz: int, repeat: int = 0) -> bytes:
    """Encode RF pulse timings for ``send_data``.

    Only 315 MHz and 433 MHz bands are supported by the hardware.
    """
    if 300_000_000 <= frequency_hz < 320_000_000:
        code_type = CODE_RF_315
    elif 430_000_000 <= frequency_hz < 440_000_000:
        code_type = CODE_RF_433
    else:
        raise ValueError(
            f"unsupported RF frequency {frequency_hz} Hz; "
            "hardware supports 315 MHz or 433 MHz bands"
        )
    return _encode(code_type, timings, repeat)


def decode(data: bytes) -> tuple[int, int, list[int]]:
    """Decode a wire-format blob back into (code_type, repeat, timings_us).

    Used for tests and round-trip verification.
    """
    if len(data) < 6:
        raise ValueError("blob too short")
    code_type = data[0]
    repeat = data[1]
    length = data[2] | (data[3] << 8)
    if len(data) < 4 + length + 2:
        raise ValueError("blob truncated")
    if data[4 + length:4 + length + 2] != TERMINATOR:
        raise ValueError("missing terminator")
    pulses_raw = data[4:4 + length]
    timings: list[int] = []
    i = 0
    while i < len(pulses_raw):
        b = pulses_raw[i]
        if b == 0x00:
            if i + 2 >= len(pulses_raw):
                raise ValueError("truncated 16-bit pulse")
            units = (pulses_raw[i + 1] << 8) | pulses_raw[i + 2]
            i += 3
        else:
            units = b
            i += 1
        timings.append(int(round(units * TICK_US)))
    return code_type, repeat, timings
