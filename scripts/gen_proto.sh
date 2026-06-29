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

touch "$OUT_DIR/__init__.py"

# Fix relative imports emitted by protoc
sed -i 's/^import analysis_pb2/from app.generated import analysis_pb2/' \
  "$OUT_DIR/analysis_pb2_grpc.py"
sed -i 's/^import dataanalysis__v1__pb2/from app.generated import dataanalysis__v1__pb2/' \
  "$OUT_DIR/dataanalysis__v1__pb2_grpc.py"

echo "Proto generated → $OUT_DIR"
