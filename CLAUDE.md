# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

A collection of self-contained demos proving that OpenTelemetry auto-instrumentation can be injected into applications **without modifying application source code**. Each subdirectory is an independent experiment with its own `docker-compose.yml` and a specific injection strategy or constraint.

## Running Any Example

Each example is self-contained. From any example directory:

```bash
docker compose up
```

Generate traffic to trigger traces:

```bash
curl http://localhost:3000
```

For `rename_dependencies/`, use `--build`:

```bash
docker compose up --build
```

There are no tests, no lint commands, and no build steps outside of Docker.

## Repository Structure

Each top-level directory is one standalone example:

| Directory | Injection Mechanism | Key Constraint / Point |
|---|---|---|
| `python/` | `LD_PRELOAD` + opentelemetry-injector `.deb` | Baseline Python (Flask) example |
| `python-json-http/` | `LD_PRELOAD` + opentelemetry-injector `.deb` | Exports via OTLP/HTTP explicitly |
| `python-json-file/` | `LD_PRELOAD` + opentelemetry-injector `.deb` | Exports to `.jsonl` file; proves `google.protobuf` is NOT needed |
| `node/` | `LD_PRELOAD` + opentelemetry-injector `.deb` | Node.js baseline example |
| `no_protobuf/` | PYTHONPATH + `sitecustomize.py` | Pure-Python lite OTLP exporter; zero `google.protobuf` dependency |
| `pyproto-http/` | PYTHONPATH + `sitecustomize.py` | `opentelemetry-exporter-otlp-pyproto-http`; pure-Python protobuf, OTLP/HTTP |
| `pyproto-grpc/` | PYTHONPATH + `sitecustomize.py` | `opentelemetry-exporter-otlp-pyproto-grpc`; pure-Python protobuf, OTLP/gRPC |
| `middle_exporter/` | PYTHONPATH + `sitecustomize.py` | Sidecar process handles protobuf; app ships msgpack over TCP |
| `rename_dependencies/` | PYTHONPATH + `sitecustomize.py` | Demonstrates injected library vs app version conflict isolation |

## Injection Mechanisms

Two approaches are demonstrated:

**1. `LD_PRELOAD` (Linux shared library)**
- Uses the [opentelemetry-injector](https://github.com/open-telemetry/opentelemetry-injector) Debian package
- Injector `.so` is loaded via `LD_PRELOAD=/usr/lib/opentelemetry/libotelinject.so`
- Python agent path is configured via `PYTHON_AUTO_INSTRUMENTATION_AGENT_PATH_PREFIX`
- The agent directory must contain a `sitecustomize.py` and the OTel SDK packages

**2. PYTHONPATH + `sitecustomize.py`**
- A `prepare-python-agent` Docker service installs OTel packages into `./python-agent/`
- That directory is mounted and set on `PYTHONPATH` in the app container
- Python automatically executes `sitecustomize.py` (if present on `sys.path`) before user code — this is how instrumentation bootstraps without any app code change

## Architecture of Multi-Container Examples

Most examples follow this pattern:

```
app container  --OTLP-->  OTel Collector  --debug exporter-->  collector logs
```

The `middle_exporter/` example adds a sidecar:

```
app container  --msgpack/TCP-->  sidecar container  --OTLP/gRPC/protobuf-->  OTel Collector
```

This isolates the `google.protobuf` dependency to the sidecar, keeping the app container lean.

## Key Environment Variables

All examples are configured via environment variables in `docker-compose.yml`. No `.env` files or external config needed:

- `OTEL_SERVICE_NAME` — service name shown in traces
- `OTEL_EXPORTER_OTLP_ENDPOINT` — where to send spans (e.g., `http://collector:4318`)
- `OTEL_EXPORTER_OTLP_PROTOCOL` — `http/protobuf` or `grpc`
- `PYTHON_AUTO_INSTRUMENTATION_AGENT_PATH_PREFIX` — path prefix for the injector's Python agent (LD_PRELOAD examples)
- `PYTHONPATH` — path to injected packages (PYTHONPATH examples)
