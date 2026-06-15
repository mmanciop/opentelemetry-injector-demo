"""Encoder for protobuf variable-length integers (varints).

Protobuf varints encode non-negative integers using a variable number of bytes.
Each byte contributes 7 bits of payload. The most significant bit (bit 7) of each
byte is a continuation flag:

    0 → this is the last byte of the varint
    1 → more bytes follow

The 7-bit payload groups are ordered little-endian: the first byte carries the
least significant 7 bits.

This encoding is identical to unsigned LEB128.

Example — encoding 300 (0b1_0010_1100):

    Split into 7-bit groups (little-endian order):
        group 0 (least significant): 0b010_1100 == 0x2C
        group 1 (most significant):  0b000_0010 == 0x02

    Group 0 is not the last byte (group 1 follows), so set continuation bit:
        0x2C | 0x80 == 0xAC

    Group 1 is the last byte, so no continuation bit:
        0x02

    Result: b'\\xac\\x02'

Reference:
    https://protobuf.dev/programming-guides/encoding/
"""


def encode_varint(value: int) -> bytes:
    """Encode a non-negative integer as a protobuf varint.

    The output length varies with the magnitude of the value:

        value in [0, 127]             → 1 byte
        value in [128, 16383]         → 2 bytes
        value in [16384, 2097151]     → 3 bytes
        value in [2097152, 268435455] → 4 bytes
        value in [268435456, 2^35-1]  → 5 bytes
        ...
        value in [2^63, 2^64-1]       → 10 bytes (maximum)

    The maximum encodable value is 2^64 - 1 (unsigned 64-bit integer),
    which encodes as exactly 10 bytes.

    Raises:
        ValueError: if value is negative.

    Reference:
        https://protobuf.dev/programming-guides/encoding/
    """
    if value < 0:
        raise ValueError(
            f"varint values must be non-negative, got {value!r}"
        )

    # Accumulate encoded bytes into a bytearray for efficient appending.
    buf = bytearray()

    while True:
        # Extract the lowest 7 bits of value as the payload for this byte.
        #
        # 0x7F is the bitmask for the 7 least significant bits (0b0111_1111).
        # The & operator isolates exactly those bits, discarding any higher bits
        # that will be handled in subsequent loop iterations.
        bits = value & 0x7F

        # Advance to the remaining bits not yet encoded.
        #
        # Shifting right by 7 discards the 7 bits we just extracted and moves
        # the next group of 7 bits into the lowest positions, ready for the
        # next iteration.
        value >>= 7

        if value == 0:
            # No more bits to encode after this byte. Append the payload bits
            # without a continuation bit (the MSB remains 0), then stop.
            buf.append(bits)
            break

        # More bytes follow. Set the continuation bit (bit 7 = MSB) in this
        # byte by OR-ing with 0x80 (0b1000_0000), then continue to the next
        # group of 7 bits.
        buf.append(bits | 0x80)

    return bytes(buf)
