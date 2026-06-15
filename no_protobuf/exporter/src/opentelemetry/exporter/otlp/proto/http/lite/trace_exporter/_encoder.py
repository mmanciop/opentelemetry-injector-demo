"""Pure-Python OTLP binary encoder for trace spans.

Produces the same wire bytes as the google.protobuf-based encoder in
opentelemetry-exporter-otlp-proto-common, but without depending on
google.protobuf or the generated _pb2 stubs.

The output is a serialized ExportTraceServiceRequest message, suitable for
POSTing to an OTLP/HTTP endpoint with Content-Type: application/x-protobuf.

Field number reference (from opentelemetry/proto/):

    ExportTraceServiceRequest  resource_spans=1
    ResourceSpans              resource=1  scope_spans=2  schema_url=3
    ScopeSpans                 scope=1  spans=2  schema_url=3
    Span                       trace_id=1 span_id=2 trace_state=3
                               parent_span_id=4 flags=16 name=5 kind=6
                               start_time_unix_nano=7 end_time_unix_nano=8
                               attributes=9 dropped_attributes_count=10
                               events=11 dropped_events_count=12
                               links=13 dropped_links_count=14 status=15
    Span.Event                 time_unix_nano=1 name=2 attributes=3
                               dropped_attributes_count=4
    Span.Link                  trace_id=1 span_id=2 trace_state=3
                               attributes=4 dropped_attributes_count=5 flags=6
    Status                     message=2 code=3
    Resource                   attributes=1 dropped_attributes_count=2
    InstrumentationScope       name=1 version=2 attributes=3
                               dropped_attributes_count=4
    KeyValue                   key=1 value=2
    AnyValue (oneof)           string_value=1 bool_value=2 int_value=3
                               double_value=4 array_value=5 kvlist_value=6
                               bytes_value=7
    ArrayValue                 values=1
    KeyValueList               values=1
"""

from __future__ import annotations

import logging
import struct
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import Link, SpanContext, SpanKind, Status

from .._encoding.scalars import encode_fixed32, encode_int
from .._encoding.tag import encode_tag
from .._encoding.varint import encode_varint

_logger = logging.getLogger(__name__)

# Wire types used in the OTLP trace proto.
_WT_VARINT = 0   # int32, int64, uint32, uint64, bool, enum
_WT_64BIT  = 1   # double, fixed64, sfixed64
_WT_LEN    = 2   # string, bytes, embedded messages
_WT_32BIT  = 5   # float, fixed32, sfixed32

# SpanFlags bit-field values (from opentelemetry/proto/trace/v1/trace.proto).
_HAS_IS_REMOTE = 256   # SPAN_FLAGS_CONTEXT_HAS_IS_REMOTE_MASK
_IS_REMOTE     = 512   # SPAN_FLAGS_CONTEXT_IS_REMOTE_MASK

# Mapping from SDK SpanKind to proto SpanKind integer.
_SPAN_KIND = {
    SpanKind.INTERNAL: 1,
    SpanKind.SERVER:   2,
    SpanKind.CLIENT:   3,
    SpanKind.PRODUCER: 4,
    SpanKind.CONSUMER: 5,
}


# ---------------------------------------------------------------------------
# Low-level field builders
# ---------------------------------------------------------------------------

def _msg(field_number: int, content: bytes) -> bytes:
    """Write a length-delimited field (tag + varint length + content)."""
    return encode_tag(field_number, _WT_LEN) + encode_varint(len(content)) + content


def _str(field_number: int, value: str) -> bytes:
    """Write a string field; omit if empty (proto3 default)."""
    if not value:
        return b""
    utf8 = value.encode("utf-8")
    return encode_tag(field_number, _WT_LEN) + encode_varint(len(utf8)) + utf8


def _byt(field_number: int, value: bytes) -> bytes:
    """Write a bytes field; omit if empty (proto3 default)."""
    if not value:
        return b""
    return encode_tag(field_number, _WT_LEN) + encode_varint(len(value)) + value


def _u64(field_number: int, value: int) -> bytes:
    """Write a uint64/varint field; omit if zero (proto3 default)."""
    if value == 0:
        return b""
    return encode_tag(field_number, _WT_VARINT) + encode_varint(value)


def _fix32(field_number: int, value: int) -> bytes:
    """Write a fixed32 field; omit if zero (proto3 default)."""
    if value == 0:
        return b""
    return encode_tag(field_number, _WT_32BIT) + encode_fixed32(value)


def _fix64(field_number: int, value: int) -> bytes:
    """Write a fixed64 field (8 bytes little-endian uint64); omit if zero."""
    if value == 0:
        return b""
    return encode_tag(field_number, _WT_64BIT) + struct.pack("<Q", value)


# ---------------------------------------------------------------------------
# AnyValue — protobuf oneof; always write the chosen field even at default
# ---------------------------------------------------------------------------

def _anyvalue_bytes(value: Any) -> bytes:
    """Return the inner bytes of an AnyValue protobuf message.

    AnyValue uses a oneof, so exactly one field is written per message.  For
    oneof fields the chosen alternative is always written, even when the value
    equals the proto3 default, so the receiver knows which variant is set.
    """
    # bool must be checked before int: bool is a subclass of int in Python.
    if isinstance(value, bool):
        v = 1 if value else 0
        return encode_tag(2, _WT_VARINT) + encode_varint(v)

    if isinstance(value, str):
        utf8 = value.encode("utf-8")
        return encode_tag(1, _WT_LEN) + encode_varint(len(utf8)) + utf8

    if isinstance(value, int):
        # int_value is int64 and can be negative; encode_int handles sign extension.
        return encode_tag(3, _WT_VARINT) + encode_int(value)

    if isinstance(value, float):
        # double_value: wire type 1, 8 bytes IEEE 754 little-endian.
        return encode_tag(4, _WT_64BIT) + struct.pack("<d", value)

    if isinstance(value, bytes):
        return encode_tag(7, _WT_LEN) + encode_varint(len(value)) + value

    if isinstance(value, Mapping):
        # kvlist_value (field 6) wraps a KeyValueList message.
        # KeyValueList.values is a repeated KeyValue at field 1.
        kv_items = b"".join(
            _msg(1, _keyvalue_bytes(str(k), v)) for k, v in value.items()
        )
        return _msg(6, kv_items)

    if isinstance(value, Sequence):
        # array_value (field 5) wraps an ArrayValue message.
        # ArrayValue.values is a repeated AnyValue at field 1.
        items = b"".join(_msg(1, _anyvalue_bytes(item)) for item in value)
        return _msg(5, items)

    raise ValueError(f"Unsupported attribute value type: {type(value)!r}")


def _keyvalue_bytes(key: str, value: Any) -> bytes:
    """Return the inner bytes of a KeyValue protobuf message."""
    key_part = _str(1, key)           # KeyValue.key  = field 1 (string)
    val_part = _msg(2, _anyvalue_bytes(value))   # KeyValue.value = field 2 (AnyValue)
    return key_part + val_part


def _attrs(field_number: int, attributes: Any) -> bytes:
    """Encode a dict of attributes as repeated KeyValue fields at field_number."""
    if not attributes:
        return b""
    parts = []
    for k, v in attributes.items():
        try:
            parts.append(_msg(field_number, _keyvalue_bytes(str(k), v)))
        except Exception:
            _logger.exception("Failed to encode attribute %r", k)
    return b"".join(parts)


# ---------------------------------------------------------------------------
# Message encoders — each returns the INNER bytes of the message
# (without the tag+length wrapper that the caller adds)
# ---------------------------------------------------------------------------

def _status_bytes(status: Status) -> bytes:
    code = status.status_code.value if status.status_code else 0
    return (
        _str(2, status.description or "")   # Status.message = field 2
        + _u64(3, code)                      # Status.code    = field 3 (enum)
    )


def _scope_bytes(scope: Any) -> bytes:
    if scope is None:
        return b""
    return (
        _str(1, scope.name or "")     # InstrumentationScope.name    = field 1
        + _str(2, scope.version or "")  # InstrumentationScope.version = field 2
        + _attrs(3, scope.attributes)   # InstrumentationScope.attributes = field 3
        # dropped_attributes_count (field 4) not tracked by SDK's InstrumentationScope
    )


def _resource_bytes(resource: Any) -> bytes:
    return _attrs(1, resource.attributes)   # Resource.attributes = field 1
    # dropped_attributes_count (field 2) not tracked by SDK's Resource


def _event_bytes(event: Any) -> bytes:
    return (
        _fix64(1, event.timestamp or 0)         # Event.time_unix_nano (fixed64) = field 1
        + _str(2, event.name)                   # Event.name                    = field 2
        + _attrs(3, event.attributes)           # Event.attributes              = field 3
        + _u64(4, event.dropped_attributes or 0)  # Event.dropped_attributes_count = field 4
    )


def _link_bytes(link: Link) -> bytes:
    ctx: SpanContext | None = link.context
    flags = _HAS_IS_REMOTE
    if ctx and ctx.is_remote:
        flags |= _IS_REMOTE

    trace_id = ctx.trace_id.to_bytes(16, "big") if ctx else b""
    span_id  = ctx.span_id.to_bytes(8, "big")  if ctx else b""

    trace_state = ""
    if ctx and ctx.trace_state:
        trace_state = ",".join(f"{k}={v}" for k, v in ctx.trace_state.items())

    return (
        _byt(1, trace_id)                          # Link.trace_id                = field 1
        + _byt(2, span_id)                         # Link.span_id                 = field 2
        + _str(3, trace_state)                     # Link.trace_state             = field 3
        + _attrs(4, link.attributes)               # Link.attributes              = field 4
        + _u64(5, link.dropped_attributes or 0)    # Link.dropped_attributes_count = field 5
        + _fix32(6, flags)                         # Link.flags                   = field 6
    )


def _span_bytes(sdk_span: ReadableSpan) -> bytes:
    ctx = sdk_span.get_span_context()

    trace_id = ctx.trace_id.to_bytes(16, "big")
    span_id  = ctx.span_id.to_bytes(8, "big")

    trace_state = ""
    if ctx.trace_state:
        trace_state = ",".join(f"{k}={v}" for k, v in ctx.trace_state.items())

    # parent_span_id is absent for root spans.
    parent_span_id = b""
    if sdk_span.parent:
        parent_span_id = sdk_span.parent.span_id.to_bytes(8, "big")

    # flags: bit 8 (HAS_IS_REMOTE) is always set; bit 9 (IS_REMOTE) if parent is remote.
    flags = _HAS_IS_REMOTE
    if sdk_span.parent and sdk_span.parent.is_remote:
        flags |= _IS_REMOTE

    kind = _SPAN_KIND.get(sdk_span.kind, 0)

    events_bytes = b"".join(
        _msg(11, _event_bytes(e)) for e in (sdk_span.events or [])
    )
    links_bytes = b"".join(
        _msg(13, _link_bytes(lk)) for lk in (sdk_span.links or [])
    )

    status_part = b""
    if sdk_span.status is not None:
        status_part = _msg(15, _status_bytes(sdk_span.status))

    return (
        _byt(1, trace_id)                                    # trace_id                = 1
        + _byt(2, span_id)                                   # span_id                 = 2
        + _str(3, trace_state)                               # trace_state             = 3
        + _byt(4, parent_span_id)                            # parent_span_id          = 4
        + _fix32(16, flags)                                  # flags (fixed32)         = 16
        + _str(5, sdk_span.name)                             # name                    = 5
        + _u64(6, kind)                                      # kind (enum)             = 6
        + _fix64(7, sdk_span.start_time or 0)                # start_time_unix_nano (fixed64) = 7
        + _fix64(8, sdk_span.end_time or 0)                 # end_time_unix_nano (fixed64)   = 8
        + _attrs(9, sdk_span.attributes)                     # attributes              = 9
        + _u64(10, sdk_span.dropped_attributes or 0)         # dropped_attributes_count = 10
        + events_bytes                                        # events                  = 11
        + _u64(12, sdk_span.dropped_events or 0)             # dropped_events_count    = 12
        + links_bytes                                         # links                   = 13
        + _u64(14, sdk_span.dropped_links or 0)              # dropped_links_count     = 14
        + status_part                                         # status                  = 15
    )


# ---------------------------------------------------------------------------
# Top-level encoder
# ---------------------------------------------------------------------------

def encode_spans_bytes(sdk_spans: Sequence[ReadableSpan]) -> bytes:
    """Encode a batch of ReadableSpans as a binary ExportTraceServiceRequest.

    The returned bytes can be sent directly as the body of an OTLP/HTTP POST
    to v1/traces with Content-Type: application/x-protobuf.

    The grouping logic mirrors the proto-common encoder: spans are grouped by
    Resource (ResourceSpans) and then by InstrumentationScope (ScopeSpans).
    """
    # Group spans: resource → instrumentation_scope → [span_bytes, ...]
    buckets: dict[Any, dict[Any, list[bytes]]] = defaultdict(lambda: defaultdict(list))
    for sdk_span in sdk_spans:
        buckets[sdk_span.resource][sdk_span.instrumentation_scope].append(
            _span_bytes(sdk_span)
        )

    # Build the ExportTraceServiceRequest body.
    # resource_spans is a repeated field at field 1.
    parts: list[bytes] = []
    for sdk_resource, sdk_scopes in buckets.items():
        scope_spans_parts: list[bytes] = []

        for sdk_scope, span_bytes_list in sdk_scopes.items():
            scope_inner = sdk_scope if sdk_scope else None
            scope_bytes = _scope_bytes(scope_inner) if scope_inner else b""

            ss_bytes = (
                (_msg(1, scope_bytes) if scope_bytes else b"")   # ScopeSpans.scope      = 1
                + b"".join(_msg(2, sb) for sb in span_bytes_list)  # ScopeSpans.spans    = 2
                + _str(3, getattr(sdk_scope, "schema_url", "") or "")  # ScopeSpans.schema_url = 3
            )
            scope_spans_parts.append(ss_bytes)

        rs_bytes = (
            _msg(1, _resource_bytes(sdk_resource))              # ResourceSpans.resource     = 1
            + b"".join(_msg(2, ss) for ss in scope_spans_parts) # ResourceSpans.scope_spans  = 2
            + _str(3, sdk_resource.schema_url or "")            # ResourceSpans.schema_url   = 3
        )
        parts.append(_msg(1, rs_bytes))   # ExportTraceServiceRequest.resource_spans = 1

    return b"".join(parts)
