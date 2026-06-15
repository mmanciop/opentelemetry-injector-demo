"""Encoders for protobuf scalar field types.

This module contains one encoding function for each protobuf scalar type.
The functions are grouped by wire type, because the wire type determines the
byte layout on the wire — not the logical .proto type name.

Wire type 0 — Varint
    Encodes as one or more bytes with a continuation bit in the MSB of each
    byte. The number of output bytes grows with the magnitude of the value.

        bool    — varint 0 or 1 only.
        int32   — varint; negative values always cost 10 bytes.
        int64   — identical wire encoding to int32.
        sint32  — varint with ZigZag pre-encoding; negative values stay small.
        sint64  — varint with ZigZag pre-encoding; 64-bit domain.
        uint32  — plain varint; valid range [0, 2^32 - 1].
        uint64  — plain varint; valid range [0, 2^64 - 1].

Wire type 5 — 32-bit fixed-width
    Always exactly 4 bytes, stored in little-endian byte order.

        float    — IEEE 754 single-precision (32-bit).
        fixed32  — unsigned 32-bit integer.
        sfixed32 — signed 32-bit integer (two's complement).

Wire type 1 — 64-bit fixed-width
    Always exactly 8 bytes, stored in little-endian byte order.

        double   — IEEE 754 double-precision (64-bit).
        fixed64  — unsigned 64-bit integer.
        sfixed64 — signed 64-bit integer (two's complement).

Wire type 2 — Length-delimited
    A varint giving the byte length of the payload, followed immediately by
    that many payload bytes.

        string — UTF-8 encoded text; length prefix counts UTF-8 bytes.
        bytes  — arbitrary binary data; length prefix counts raw bytes.

Reference:
    https://protobuf.dev/programming-guides/encoding/
"""

import struct

from .varint import encode_varint


# ── Wire type 0 — Varint ──────────────────────────────────────────────────────


def encode_uint32(value: int) -> bytes:
    """Encode an unsigned 32-bit integer as a protobuf uint32 field value.

    Valid range: [0, 2^32 - 1]. Plain varint; no transformation applied.
    """
    return encode_varint(value)


def encode_uint64(value: int) -> bytes:
    """Encode an unsigned 64-bit integer as a protobuf uint64 field value.

    Valid range: [0, 2^64 - 1]. Plain varint; no transformation applied.
    """
    return encode_varint(value)


def encode_bool(value: bool) -> bytes:
    """Encode a Python bool as a protobuf bool field value (varint 0 or 1)."""
    return encode_varint(1 if value else 0)


def encode_int(value: int) -> bytes:
    """Encode a signed integer as a protobuf varint for int32 and int64 fields.

    Non-negative values pass straight through to encode_varint.

    Negative values are sign-extended to 64 bits via a 64-bit mask and then
    treated as an unsigned integer. This always produces exactly 10 bytes for
    any negative input, regardless of magnitude.
    """
    if value >= 0:
        return encode_varint(value)
    # Sign-extend to 64-bit two's complement, then encode as unsigned varint.
    unsigned = value & 0xFFFFFFFFFFFFFFFF
    return encode_varint(unsigned)


def encode_sint32(value: int) -> bytes:
    """Encode a signed 32-bit integer using ZigZag encoding for sint32 fields.

    ZigZag maps signed integers to non-negative integers so that small absolute
    values produce small varints: zigzag32(n) = (n << 1) ^ (n >> 31).
    """
    zigzag_value = (value << 1) ^ (value >> 31)
    zigzag_value &= 0xFFFFFFFF
    return encode_varint(zigzag_value)


def encode_sint64(value: int) -> bytes:
    """Encode a signed 64-bit integer using ZigZag encoding for sint64 fields.

    The 64-bit variant of ZigZag: zigzag64(n) = (n << 1) ^ (n >> 63).
    """
    zigzag_value = (value << 1) ^ (value >> 63)
    zigzag_value &= 0xFFFFFFFFFFFFFFFF
    return encode_varint(zigzag_value)


# ── Wire type 5 — 32-bit fixed-width ─────────────────────────────────────────


def encode_float(value: float) -> bytes:
    """Encode a float as a 4-byte IEEE 754 single-precision little-endian value."""
    return struct.pack("<f", value)


def encode_fixed32(value: int) -> bytes:
    """Encode an unsigned integer as a 4-byte little-endian fixed32 value."""
    return struct.pack("<I", value)


def encode_sfixed32(value: int) -> bytes:
    """Encode a signed integer as a 4-byte little-endian two's complement value."""
    return struct.pack("<i", value)


# ── Wire type 1 — 64-bit fixed-width ─────────────────────────────────────────


def encode_double(value: float) -> bytes:
    """Encode a float as an 8-byte IEEE 754 double-precision little-endian value."""
    return struct.pack("<d", value)


def encode_fixed64(value: int) -> bytes:
    """Encode an unsigned integer as an 8-byte little-endian fixed64 value."""
    return struct.pack("<Q", value)


def encode_sfixed64(value: int) -> bytes:
    """Encode a signed integer as an 8-byte little-endian two's complement value."""
    return struct.pack("<q", value)


# ── Wire type 2 — Length-delimited ───────────────────────────────────────────


def encode_string(value: str) -> bytes:
    """Encode a Python str as a protobuf string field value.

    Produces varint(len(utf8_bytes)) + utf8_bytes. The length counts bytes,
    not characters.
    """
    utf8_bytes = value.encode("utf-8")
    length_prefix = encode_varint(len(utf8_bytes))
    return length_prefix + utf8_bytes


def encode_bytes(value: bytes) -> bytes:
    """Encode a Python bytes object as a protobuf bytes field value.

    Produces varint(len(value)) + value.
    """
    length_prefix = encode_varint(len(value))
    return length_prefix + value
