"""Encoder for protobuf enum field values.

Protobuf enum fields use wire type 0 (varint) and share the exact same wire
encoding as int32. This module exists as its own file — separate from scalars.py
— because an enum is not a scalar type. Enum fields carry named constants, not
raw numeric values.

Reference:
    https://protobuf.dev/programming-guides/encoding/
"""

from .scalars import encode_int


def encode_enum(value: int) -> bytes:
    """Encode a protobuf enum value.

    Delegates to encode_int because the spec defines enum encoding as identical
    to int32: non-negative values encode as a compact varint; negative values
    (legal in proto2) encode as 10-byte sign-extended varints.
    """
    return encode_int(value)
