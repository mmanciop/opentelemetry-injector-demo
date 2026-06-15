"""
OTLP/HTTP lite exporter — no google.protobuf dependency.

This package exports traces to an OTLP collector over HTTP by serialising
spans directly to protobuf binary format using a bundled pure-Python encoder
(see ``_encoding/``), without requiring ``google.protobuf`` or any generated
``_pb2`` stubs.

Configuration environment variables (same as the standard OTLP/HTTP exporter):

- ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT``  (default: http://localhost:4318/v1/traces)
- ``OTEL_EXPORTER_OTLP_ENDPOINT``
- ``OTEL_EXPORTER_OTLP_TRACES_HEADERS``
- ``OTEL_EXPORTER_OTLP_HEADERS``
- ``OTEL_EXPORTER_OTLP_TRACES_TIMEOUT``   (default: 10 s)
- ``OTEL_EXPORTER_OTLP_TIMEOUT``
- ``OTEL_EXPORTER_OTLP_TRACES_COMPRESSION``  (none | gzip | deflate)
- ``OTEL_EXPORTER_OTLP_COMPRESSION``
- ``OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE``
- ``OTEL_EXPORTER_OTLP_CERTIFICATE``
- ``OTEL_EXPORTER_OTLP_TRACES_CLIENT_CERTIFICATE``
- ``OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE``
- ``OTEL_EXPORTER_OTLP_TRACES_CLIENT_KEY``
- ``OTEL_EXPORTER_OTLP_CLIENT_KEY``
"""

import enum

_VERSION = "1.43.0.dev"

_OTLP_HTTP_HEADERS = {
    "Content-Type": "application/x-protobuf",
    "User-Agent": "OTel-OTLP-Exporter-Python/" + _VERSION,
}


class Compression(enum.Enum):
    NoCompression = "none"
    Deflate = "deflate"
    Gzip = "gzip"
