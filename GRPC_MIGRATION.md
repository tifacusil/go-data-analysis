# early-warning-service — gRPC Migration

## Background

`data-analysis-service` has been rebuilt as `py-data-analysis`. The new version exposes two transports:

- **HTTP** on port 8080 — for frontend calls only, proxied through Nginx
- **gRPC** on port 50051 — for server-to-server calls within `landslide-net`

`early-warning-service` currently calls data-analysis over HTTP to enrich periodic reports (`_enrich_report` in `app.py:246`). That call must be migrated to gRPC because HTTP is no longer the intended server-to-server interface — it exists exclusively for the frontend. Using it from a backend service bypasses the contract system (CDCT) and couples two internal services through the public-facing transport.

---

## What needs to change

### Dependencies

Two new libraries are needed: `grpcio` (the gRPC runtime) and `grpcio-tools` (to generate Python stubs from the proto file). A third, `pybreaker`, is needed for the circuit breaker (explained below).

### Proto stubs

gRPC communication is contract-first. The contract lives in `py-data-analysis/proto/analysis.proto`. The developer must copy that file into `early-warning-service` and generate Python stubs from it. These stubs are what the code actually imports to make gRPC calls — they replace the role that a `requests.post` URL played before.

The proto file is the single source of truth shared between provider (`py-data-analysis`) and consumer (`early-warning-service`). If the data-analysis team changes the proto, early-warning must regenerate its stubs.

### Configuration

`DATA_ANALYSIS_URL` must be replaced with a gRPC host and port (`DATA_ANALYSIS_GRPC_HOST`, `DATA_ANALYSIS_GRPC_PORT`). The timeout config can stay as-is. The `go-tesis-infra` env example for `early-warning` must be updated accordingly so the service knows where to find data-analysis on `landslide-net`.

### `_enrich_report` rewrite (`app.py:246–262`)

The function currently sends `{project_id, period, window_start, window_end}` to an HTTP endpoint. That payload must change because data-analysis does not accept metadata — it only accepts raw sensor readings: a list of float values and a matching list of ISO-8601 timestamps.

The function must:
1. Fetch the actual sensor readings for the given project and time window (see open question below)
2. Open a gRPC channel to `data-analysis-1:50051`
3. Call the appropriate RPC (most likely `Predict` for report enrichment)
4. Map the response back to the dict that gets stored as `report["data_analysis"]`

### Circuit Breaker

A circuit breaker must wrap the gRPC call. The reason: report generation is a scheduled background task. If data-analysis is slow or down, without a circuit breaker every report attempt will hang until timeout, blocking the scheduler thread and eventually degrading the whole service. With a circuit breaker, after a few consecutive failures the breaker opens and `_enrich_report` returns `None` immediately — report generation continues without the analysis enrichment, which is the correct graceful degradation behavior.

---

## Open question — must be resolved before implementation

The current `_enrich_report` only passes metadata to data-analysis. The new gRPC call requires actual sensor readings. The developer must implement a function that fetches those readings for a given project and time window before making the gRPC call.

**Where does this data come from?** This is not clear from the current codebase. The most likely sources are:

- **data-management service** — holds sensor readings per project and exposes an HTTP API; this is the most architecturally correct source
- **MySQL (`mysql-early-warning`)** — if alert records stored there include the raw deformation values
- **Redis** — only stores recent readings per sensor, not historical windows; probably not suitable for report-period queries

This must be clarified with the team before implementation can begin. The answer determines what additional client code (HTTP call to data-management, or a MySQL query) is needed inside `_enrich_report`.
