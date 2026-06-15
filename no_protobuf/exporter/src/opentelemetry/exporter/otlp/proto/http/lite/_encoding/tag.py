"""Encoder for protobuf record tags.

Every field in a serialized protobuf message is preceded by a tag. The tag
encodes two pieces of information:

    1. The field number  — which field this is (assigned in the .proto file).
    2. The wire type    — how the following bytes should be interpreted.

The tag is itself encoded as a varint. Its value is:

    tag_integer = (field_number << 3) | wire_type

The three lowest bits carry the wire type (values 0–5); the remaining bits
carry the field number.

Wire types
----------

    Wire type 0  VARINT       — int32, int64, uint32, uint64, sint32, sint64,
                                bool, enum
    Wire type 1  64BIT        — fixed64, sfixed64, double
    Wire type 2  LEN          — string, bytes, embedded messages, packed arrays
    Wire type 3  SGROUP       — (deprecated, start group)
    Wire type 4  EGROUP       — (deprecated, end group)
    Wire type 5  32BIT        — fixed32, sfixed32, float

Tag size examples
-----------------

Field numbers 1–15 fit in a single byte for wire types 0 and 2:

    field 1,  wire_type 0: tag = (1<<3)|0  =   8  → b'\\x08'  (1 byte)
    field 2,  wire_type 0: tag = (2<<3)|0  =  16  → b'\\x10'  (1 byte)
    field 15, wire_type 0: tag = (15<<3)|0 = 120  → b'\\x78'  (1 byte)
    field 16, wire_type 0: tag = (16<<3)|0 = 128  → b'\\x80\\x01' (2 bytes)

Field number 536870911 (the maximum) with wire type 5:

    tag = (536870911<<3)|5 = 4294967293  → 5-byte varint

Reference:
    https://protobuf.dev/programming-guides/encoding/
"""

from .varint import encode_varint


def encode_tag(field_number: int, wire_type: int) -> bytes:
    """Encode a protobuf field tag as a varint.

    The tag integer is computed as ``(field_number << 3) | wire_type`` and then
    varint-encoded. This value is written to the wire immediately before the
    field's payload bytes.

    Args:
        field_number: The field number assigned in the .proto file. Valid range
            is [1, 536870911] (29-bit unsigned integer, excluding 19000–19999
            which are reserved by the protobuf implementation).
        wire_type: The wire type for the field. One of:
            0 (varint), 1 (64-bit), 2 (length-delimited), 5 (32-bit).

    Returns:
        The varint-encoded tag as a bytes object (1–5 bytes).

    Reference:
        https://protobuf.dev/programming-guides/encoding/
    """
    # Combine field_number and wire_type into a single integer.
    #
    # The three lowest bits are reserved for the wire type (values 0–5 fit
    # in 3 bits). Shifting field_number left by 3 positions makes room for
    # those wire_type bits, and OR-ing with wire_type fills them in.
    #
    # Example: field_number=1, wire_type=0
    #     (1 << 3) | 0 = 8 = 0b00001000
    #     encode_varint(8) = b'\x08'
    #
    # Example: field_number=1, wire_type=2 (length-delimited)
    #     (1 << 3) | 2 = 10 = 0b00001010
    #     encode_varint(10) = b'\x0a'
    tag = (field_number << 3) | wire_type
    return encode_varint(tag)
