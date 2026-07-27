#!/bin/bash

# スクリプトがあるディレクトリ（scriptフォルダ）を取得
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)

# トレースファイルがあるディレクトリ（1つ上の階層）を取得
TRACE_DIR=$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)

# デバイス数
NUM_DEVICE=10

# 出力するCSVのファイルパス
OUTPUT_CSV="$TRACE_DIR/plots/simulation_results.csv"

echo "========================================"
echo "Starting aggregation..."
echo "Trace Directory: $TRACE_DIR"
echo "Number of Devices per PAN: $NUM_DEVICE"
echo "Output CSV: $OUTPUT_CSV"
echo "========================================"

# Pythonスクリプトを直接実行
python3 "$SCRIPT_DIR/aggregate_results.py" "$TRACE_DIR" "$NUM_DEVICE" "$OUTPUT_CSV"

echo "Aggregation completed successfully!"