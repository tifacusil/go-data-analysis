# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Generate protobuf stubs inside the build stage
COPY proto/ proto/
COPY scripts/gen_proto.sh scripts/gen_proto.sh
RUN chmod +x scripts/gen_proto.sh && \
    PYTHONPATH=/install/lib/python3.12/site-packages bash scripts/gen_proto.sh

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /install /usr/local
COPY --from=builder /build/app/generated/ app/generated/

COPY app/   app/
COPY services/ services/
COPY main.py .

ENV ANALYSIS__HTTP_PORT=8080 \
    ANALYSIS__GRPC_PORT=50051 \
    ANALYSIS__HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080 50051

HEALTHCHECK --interval=10s --timeout=2s --start-period=15s --retries=3 \
  CMD wget -qO- http://localhost:8080/health || exit 1

CMD ["python", "main.py"]
