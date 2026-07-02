#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."
PROTO_SRC="$ROOT/proto"
OUT_DIR="$ROOT/app/generated"

mkdir -p "$OUT_DIR"

python -m grpc_tools.protoc \
  -I "$PROTO_SRC" \
  --python_out="$OUT_DIR" \
  --grpc_python_out="$OUT_DIR" \
  "$PROTO_SRC/analysis.proto"

python -m grpc_tools.protoc \
  -I "$PROTO_SRC" \
  --python_out="$OUT_DIR" \
  --grpc_python_out="$OUT_DIR" \
  "$PROTO_SRC/dataanalysis_v1.proto"

# readings.proto: cliente de data-management.ReadingService (reemplaza pymysql)
python -m grpc_tools.protoc \
  -I "$PROTO_SRC" \
  --python_out="$OUT_DIR" \
  --grpc_python_out="$OUT_DIR" \
  "$PROTO_SRC/readings.proto"

touch "$OUT_DIR/__init__.py"

# Fix relative imports emitted by protoc
sed -i 's/^import analysis_pb2/from app.generated import analysis_pb2/' \
  "$OUT_DIR/analysis_pb2_grpc.py"
sed -i 's/^import dataanalysis_v1_pb2/from app.generated import dataanalysis_v1_pb2/' \
  "$OUT_DIR/dataanalysis_v1_pb2_grpc.py"
sed -i 's/^import readings_pb2/from app.generated import readings_pb2/' \
  "$OUT_DIR/readings_pb2_grpc.py"

echo "Proto generated → $OUT_DIR"
