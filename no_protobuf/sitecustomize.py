"""OTel bootstrap injected via PYTHONPATH / sitecustomize.py mechanism.

Configures the OpenTelemetry SDK with the lite OTLP exporter — a pure-Python
protobuf encoder that ships NO dependency on google.protobuf.
"""

from opentelemetry import trace
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.lite.trace_exporter import OTLPSpanExporter

resource = Resource.create({"service.name": "no-protobuf-demo"})
provider = TracerProvider(resource=resource)
provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)

RequestsInstrumentor().instrument()

print("agent: lite OTLP exporter configured (no google.protobuf)", flush=True)
