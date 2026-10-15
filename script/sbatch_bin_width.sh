#!/bin/bash

# RSSIビン幅の感度分析 (1〜20 dBm) を SLURM で回す。
# 再シミュレーションは不要 (既存の plots/simulation_results.csv を読むだけ)。
#
# sbatch_reanalyze.sh と同じく、投げて**完了まで待ち**、出力を検証するところまでやる。
# 出力先は plots/bin_width_sensitivity/ だけで、既存の解析結果は上書きしない。
# 設計は docs/bin_width.md。

set -uo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
CMD_DIR=$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)

INPUT_CSV="$CMD_DIR/plots/simulation_results.csv"
OUT_DIR="$CMD_DIR/plots/bin_width_sensitivity"
LOG_DIR="$CMD_DIR/plots/logs"

# 投入前に手元で止める。SLURM ジョブが起動してから落ちると原因が分かりにくい。
if [ ! -f "$INPUT_CSV" ]; then
    echo "エラー: 入力CSVがありません: $INPUT_CSV" >&2
    echo "       icc の ./script/sbatch_jobs.sh を完走させた計算機で実行してください。" >&2
    exit 1
fi

mkdir -p "$LOG_DIR"
cd "$CMD_DIR" || exit 1

echo "--- 入力: $INPUT_CSV ($(du -h "$INPUT_CSV" | cut -f1)) ---"
echo "--- SLURM に投入して完了を待ちます ---"

# 解析はシングルスレッドなので -c 1
if ! sbatch --wait --partition=ubuntu -c 1 \
    --job-name="bin_width" \
    --output="$LOG_DIR/bin_width_%j.out" \
    --error="$LOG_DIR/bin_width_%j.err" \
    --wrap="python3 '$SCRIPT_DIR/bin_width_sensitivity.py'"; then
    echo "エラー: 感度分析ジョブが失敗しました。" >&2
    echo "       ログ: $LOG_DIR/bin_width_<jobid>.{out,err}" >&2
    ls -t "$LOG_DIR"/bin_width_*.err 2>/dev/null | head -1 | while read -r f; do
        echo "--- $(basename "$f") の末尾 ---" >&2
        tail -20 "$f" >&2
    done
    exit 1
fi

# --- 結果の検証 ---------------------------------------------------------
# 行数 = 20幅 x 300条件 (proposed) + 300条件 x 2手法 (dper, rssi) = 6600。
# 300 = 6帯域ペア x 25負荷 x 2PAN。
EXPECTED_ROWS=6600
STATUS=0
CSV="$OUT_DIR/auc_by_bin_width.csv"
if [ ! -f "$CSV" ]; then
    echo "エラー: $CSV がありません" >&2
    STATUS=1
else
    ROWS=$(($(wc -l < "$CSV") - 1))
    if [ "$ROWS" -ne "$EXPECTED_ROWS" ]; then
        echo "エラー: 行数が $ROWS です (期待 $EXPECTED_ROWS)" >&2
        STATUS=1
    fi
fi
for F in auc_vs_bin_width auc_vs_bin_width_by_load degenerate_vs_bin_width; do
    if [ ! -f "$OUT_DIR/$F.pdf" ]; then
        echo "エラー: $F.pdf がありません" >&2
        STATUS=1
    fi
done

if [ "$STATUS" -ne 0 ]; then
    echo "検証に失敗しました。" >&2
    exit 1
fi

# 幅ごとの平均 AUC と最良の幅はジョブのログに出ている
LOG=$(ls -t "$LOG_DIR"/bin_width_*.out 2>/dev/null | head -1)
if [ -n "$LOG" ]; then
    sed -n '/全条件の平均 AUC/,/に出力 ---/p' "$LOG"
fi

echo "========================================"
echo "感度分析が完了しました ($ROWS 行)"
echo "  plots/bin_width_sensitivity/"
echo "========================================"
