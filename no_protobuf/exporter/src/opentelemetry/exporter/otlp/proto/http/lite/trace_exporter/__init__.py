# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import gzip
import logging
import random
import threading
import zlib
from collections.abc import Sequence
from io import BytesIO
from os import environ
from time import time

import requests
from requests.exceptions import ConnectionError

from opentelemetry.exporter.otlp.proto.http.lite import (
    Compression,
    _OTLP_HTTP_HEADERS,
)
from opentelemetry.sdk.environment_variables import (
    OTEL_EXPORTER_OTLP_CERTIFICATE,
    OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE,
    OTEL_EXPORTER_OTLP_CLIENT_KEY,
    OTEL_EXPORTER_OTLP_COMPRESSION,
    OTEL_EXPORTER_OTLP_ENDPOINT,
    OTEL_EXPORTER_OTLP_HEADERS,
    OTEL_EXPORTER_OTLP_TIMEOUT,
    OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE,
    OTEL_EXPORTER_OTLP_TRACES_CLIENT_CERTIFICATE,
    OTEL_EXPORTER_OTLP_TRACES_CLIENT_KEY,
    OTEL_EXPORTER_OTLP_TRACES_COMPRESSION,
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
    OTEL_EXPORTER_OTLP_TRACES_HEADERS,
    OTEL_EXPORTER_OTLP_TRACES_TIMEOUT,
)
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.util.re import parse_env_headers

from ._encoder import encode_spans_bytes

_logger = logging.getLogger(__name__)

DEFAULT_COMPRESSION = Compression.NoCompression
DEFAULT_ENDPOINT = "http://localhost:4318/"
DEFAULT_TRACES_EXPORT_PATH = "v1/traces"
DEFAULT_TIMEOUT = 10  # seconds
_MAX_RETRIES = 6


def _is_retryable(resp: requests.Response) -> bool:
    return resp.status_code == 408 or 500 <= resp.status_code <= 599


def _compression_from_env() -> Compression:
    value = (
        environ.get(
            OTEL_EXPORTER_OTLP_TRACES_COMPRESSION,
            environ.get(OTEL_EXPORTER_OTLP_COMPRESSION, "none"),
        )
        .lower()
        .strip()
    )
    return Compression(value)


def _append_trace_path(endpoint: str) -> str:
    if endpoint.endswith("/"):
        return endpoint + DEFAULT_TRACES_EXPORT_PATH
    return endpoint + f"/{DEFAULT_TRACES_EXPORT_PATH}"


class OTLPSpanExporter(SpanExporter):
    """OTLP/HTTP span exporter that uses a bundled pure-Python protobuf encoder.

    Drop-in replacement for ``opentelemetry.exporter.otlp.proto.http.trace_exporter
    .OTLPSpanExporter`` that does not depend on ``google.protobuf``,
    ``googleapis-common-protos``, ``opentelemetry-proto``, or
    ``opentelemetry-exporter-otlp-proto-common``.

    All OTLP/HTTP environment variables and constructor parameters are supported
    with identical semantics.  The credential-provider plug-in mechanism is not
    supported (pass a custom ``session`` instead if you need custom auth).
    """

    def __init__(
        self,
        endpoint: str | None = None,
        certificate_file: str | None = None,
        client_key_file: str | None = None,
        client_certificate_file: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        compression: Compression | None = None,
        session: requests.Session | None = None,
    ):
        self._shutdown_in_progress = threading.Event()
        self._endpoint = endpoint or environ.get(
            OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
            _append_trace_path(
                environ.get(OTEL_EXPORTER_OTLP_ENDPOINT, DEFAULT_ENDPOINT)
            ),
        )
        self._certificate_file = certificate_file or environ.get(
            OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE,
            environ.get(OTEL_EXPORTER_OTLP_CERTIFICATE, True),
        )
        self._client_key_file = client_key_file or environ.get(
            OTEL_EXPORTER_OTLP_TRACES_CLIENT_KEY,
            environ.get(OTEL_EXPORTER_OTLP_CLIENT_KEY, None),
        )
        self._client_certificate_file = client_certificate_file or environ.get(
            OTEL_EXPORTER_OTLP_TRACES_CLIENT_CERTIFICATE,
            environ.get(OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE, None),
        )
        self._client_cert = (
            (self._client_certificate_file, self._client_key_file)
            if self._client_certificate_file and self._client_key_file
            else self._client_certificate_file
        )
        headers_string = environ.get(
            OTEL_EXPORTER_OTLP_TRACES_HEADERS,
            environ.get(OTEL_EXPORTER_OTLP_HEADERS, ""),
        )
        self._headers = headers or parse_env_headers(headers_string, liberal=True)
        self._timeout = timeout or float(
            environ.get(
                OTEL_EXPORTER_OTLP_TRACES_TIMEOUT,
                environ.get(OTEL_EXPORTER_OTLP_TIMEOUT, DEFAULT_TIMEOUT),
            )
        )
        self._compression = compression or _compression_from_env()
        self._session = session or requests.Session()
        self._session.headers.update(self._headers)
        self._session.headers.update(_OTLP_HTTP_HEADERS)
        # Allow callers to override the default Content-Type / User-Agent.
        self._session.headers.update(self._headers)
        if self._compression is not Compression.NoCompression:
            self._session.headers.update(
                {"Content-Encoding": self._compression.value}
            )
        self._shutdown = False

    def _send(self, data: bytes, timeout_sec: float) -> requests.Response:
        if self._compression == Compression.Gzip:
            buf = BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="w") as gz:
                gz.write(data)
            data = buf.getvalue()
        elif self._compression == Compression.Deflate:
            data = zlib.compress(data)

        try:
            return self._session.post(
                url=self._endpoint,
                data=data,
                verify=self._certificate_file,
                timeout=timeout_sec,
                cert=self._client_cert,
            )
        except ConnectionError:
            # Retry once on a keep-alive connection reset.
            return self._session.post(
                url=self._endpoint,
                data=data,
                verify=self._certificate_file,
                timeout=timeout_sec,
                cert=self._client_cert,
            )

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if self._shutdown:
            _logger.warning("Exporter already shutdown, ignoring batch")
            return SpanExportResult.FAILURE

        serialized_data = encode_spans_bytes(spans)
        deadline_sec = time() + self._timeout

        for retry_num in range(_MAX_RETRIES):
            # ±20 % jitter on exponential back-off.
            backoff_sec = 2**retry_num * random.uniform(0.8, 1.2)
            export_error: Exception | None = None
            retryable = False
            status_code = None
            reason: object = None

            try:
                resp = self._send(serialized_data, deadline_sec - time())
                if resp.ok:
                    return SpanExportResult.SUCCESS
                reason = resp.reason
                retryable = _is_retryable(resp)
                status_code = resp.status_code
            except requests.exceptions.RequestException as exc:
                export_error = exc
                reason = exc
                retryable = isinstance(exc, ConnectionError)

            if not retryable:
                _logger.error(
                    "Failed to export span batch, status: %s, reason: %s",
                    status_code,
                    reason,
                )
                return SpanExportResult.FAILURE

            if (
                retry_num + 1 == _MAX_RETRIES
                or backoff_sec > (deadline_sec - time())
                or self._shutdown
            ):
                _logger.error(
                    "Failed to export span batch due to timeout, max retries or shutdown."
                )
                return SpanExportResult.FAILURE

            _logger.warning(
                "Transient error %s while exporting spans, retrying in %.2fs.",
                reason,
                backoff_sec,
            )
            shutdown = self._shutdown_in_progress.wait(backoff_sec)
            if shutdown:
                _logger.warning("Shutdown in progress, aborting retry.")
                break

        return SpanExportResult.FAILURE

    def shutdown(self):
        if self._shutdown:
            _logger.warning("Exporter already shutdown, ignoring call")
            return
        self._shutdown = True
        self._shutdown_in_progress.set()
        self._session.close()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
