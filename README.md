# py-data-analysis

Data analysis microservice for the landslide early warning system (Bai et al. 2020).

Provides signal processing and forecasting algorithms over two transports:
- **HTTP** (port 8080) — for frontend calls, proxied through Nginx
- **gRPC** (port 50051) — for server-to-server calls within `landslide-net`

---

## Algorithms

| Endpoint | Methods / Models |
|---|---|
| Outlier detection | `3sigma`, `iqr`, `chauvenet` |
| Denoising | `wavelet` (db4 soft threshold), `emd` (ZCR-based IMF removal), `svm` (SVR trend fit) |
| Regression | `polynomial` (configurable degree), `bayesian` (BayesianRidge) |
| Prediction | `arima` (configurable order), `gm11` (Grey Model, ≥4 points) |

All results are cached in Redis by SHA-256 hash of the request body (TTL: 1 hour by default).

---

## Project structure

```
proto/              gRPC contract — single source of truth
scripts/            gen_proto.sh — generates Python stubs from the proto
app/
  config.py         All configuration via environment variables
  cache.py          Redis cache (shared by HTTP and gRPC)
  consul.py         Consul registration/deregistration
  grpc_servicer.py  gRPC handler — server-to-server transport
  http_app.py       FastAPI app — frontend HTTP transport
  generated/        Auto-generated proto stubs (gitignored)
services/           Pure business logic, no transport coupling
  outliers_service.py
  denoise_service.py
  regression_service.py
  predict_service.py
main.py             Entry point — runs gRPC and HTTP servers concurrently
tests/
  unit/             Service layer unit tests
  cdct/             Pact provider verification (consumer-driven contract tests)
```

---

## Getting started

### Prerequisites

- Python 3.12
- Running infra stack from `go-tesis-infra/local/infra/` (Redis, Consul)

### Setup

```bash
pip install -r requirements.txt
bash scripts/gen_proto.sh   # must run once before starting or testing
cp .env.example .env        # fill in real values
```

### Run locally

```bash
python main.py
```

HTTP available at `http://localhost:8080/health`.
gRPC available at `localhost:50051`.

### Run tests

```bash
python -m pytest tests/unit -v
```

For CDCT provider verification (requires a running Pact broker):

```bash
PACT_BROKER_URL=http://localhost:9292 python -m pytest tests/cdct -v
```

---

## Configuration

All configuration is via environment variables. See `.env.example` for the full list.

| Variable | Default | Description |
|---|---|---|
| `ANALYSIS__HTTP_PORT` | `8080` | HTTP server port |
| `ANALYSIS__GRPC_PORT` | `50051` | gRPC server port |
| `ANALYSIS__GRPC_MAX_WORKERS` | `10` | Thread pool size for blocking gRPC handlers |
| `ANALYSIS__ROUTE_PREFIX` | _(empty)_ | Optional URL prefix (e.g. `/analysis`) |
| `ANALYSIS__INSTANCE_ID` | `data-analysis-01` | Consul service instance ID |
| `ANALYSIS__REDIS__HOST` | `localhost` | Redis host |
| `ANALYSIS__REDIS__CACHE_TTL_SECONDS` | `3600` | Cache TTL in seconds |
| `ANALYSIS__CONSUL__HOST` | `localhost` | Consul host |

---

## HTTP API

All routes are prefixed by `ANALYSIS__ROUTE_PREFIX` (empty by default).

### `GET /health`

Returns service status, Redis connectivity, Consul registration, and optional library availability.

### `POST /outliers`

Detects anomalous values in a time series.

Request body:
```json
{ "values": [1.2, 3.4, 100.0, 2.1], "timestamps": ["2024-01-01T00:00:00Z", "..."], "method": "3sigma" }
```

### `POST /denoise`

Smooths a noisy time series.

Request body:
```json
{ "values": [...], "timestamps": [...], "method": "wavelet" }
```

### `POST /regression`

Fits a regression curve to a time series.

Request body:
```json
{ "values": [...], "timestamps": [...], "model": "polynomial", "degree": 3 }
```

### `POST /predict`

Forecasts future values.

Request body:
```json
{ "values": [...], "timestamps": [...], "model": "arima", "horizon": 30, "arima_order": [1, 1, 1] }
```

---

## gRPC API

Defined in `proto/analysis.proto`. Exposes the same four operations as the HTTP API: `DetectOutliers`, `Denoise`, `Regression`, `Predict`.

Intended consumers: backend services within `landslide-net` (e.g. `early-warning-service`). See `GRPC_MIGRATION.md` for migration guidance.

---

## Docker

The image is built in two stages. The builder stage installs dependencies and generates the proto stubs. The runtime stage copies only what is needed to keep the image lean.

```bash
docker build -t py-data-analysis .
```

The image is published to `ghcr.io/tifacusil/data-analysis:latest` by the CI pipeline on every push to `main`.

---

## CI/CD

GitHub Actions pipeline (`.github/workflows/ci.yml`) runs on every push and pull request:

1. **Lint** — flake8
2. **Unit tests** — pytest against the service layer
3. **CDCT** — Pact provider verification against published consumer contracts
4. **Build & push** — Docker image to GHCR (on `main` only)

Requires `PACT_BROKER_URL` and `PACT_BROKER_TOKEN` secrets set in the GitHub repository settings.
