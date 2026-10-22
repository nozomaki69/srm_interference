#!/bin/bash

# 提案手法の RSSI ビン幅の感度分析 (1-20 dBm) を SLURM で回し、完了を待って検証する。
# 再シミュレーションは不要 (plots/simulation_results.csv さえあればよい)。
#
# 中身: bin_width_sensitivity.py (解析) -> plot_bin_width_sensitivity.py (作図)。
# 出力は plots/bin_width_sensitivity/ だけで、既存の解析結果・図には触らない。
# 設計は docs/bin_width_sensitivity.md を参照。
#
# 引数はそのまま bin_width_sensitivity.py に渡る (例: --widths 5,10,15)。

set -uo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
CMD_DIR=$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)

INPUT_CSV="$CMD_DIR/plots/simulation_results.csv"
OUT_DIR="$CMD_DIR/plots/bin_width_sensitivity"
LOG_DIR="$CMD_DIR/plots/logs"

# 投入前に手元で止める。SLURM ジョブが起動してから落ちると原因が分かりにくい。
if [ ! -f "$INPUT_CSV" ]; then
    echo "エラー: 入力CSVがありません: $INPUT_CSV" >&2
    echo "       先に ./script/sbatch_jobs.sh を完走させてください。" >&2
    exit 1
fi

mkdir -p "$LOG_DIR"
cd "$CMD_DIR" || exit 1

# 引数を SLURM の --wrap に安全に渡す
ARGS=$(printf ' %q' "$@")

echo "--- 入力: $INPUT_CSV ($(du -h "$INPUT_CSV" | cut -f1)) ---"
echo "--- SLURM に投入して完了を待ちます (ログ: $LOG_DIR/binwidth_<jobid>.{out,err}) ---"

# --wait で完了までブロックする。解析はシングルスレッドなので -c 1。
if ! sbatch --wait --partition=ubuntu -c 1 \
    --job-name="binwidth" \
    --output="$LOG_DIR/binwidth_%j.out" \
    --error="$LOG_DIR/binwidth_%j.err" \
    --wrap="python3 '$SCRIPT_DIR/bin_width_sensitivity.py'$ARGS && python3 '$SCRIPT_DIR/plot_bin_width_sensitivity.py'"; then
    echo "エラー: 感度分析ジョブが失敗しました。" >&2
    ls -t "$LOG_DIR"/binwidth_*.err 2>/dev/null | head -1 | while read -r f; do
        echo "--- $(basename "$f") の末尾 ---" >&2
        tail -20 "$f" >&2
    done
    exit 1
fi

# --- 結果の検証 ---------------------------------------------------------
# 行数 = ビン幅の数 x 300 (6帯域ペア x 25負荷 x 2PAN)。ビン幅の数は CSV から数える。
STATUS=0
for TAG in single multi; do
    CSV="$OUT_DIR/auc_binwidth_${TAG}.csv"
    if [ ! -f "$CSV" ]; then
        echo "エラー: $(basename "$CSV") がありません" >&2
        STATUS=1
        continue
    fi
    ROWS=$(($(wc -l < "$CSV") - 1))
    N_WIDTHS=$(tail -n +2 "$CSV" | cut -d, -f1 | sort -u | wc -l | tr -d ' ')
    EXPECTED=$((N_WIDTHS * 300))
    if [ "$ROWS" -ne "$EXPECTED" ]; then
        echo "エラー: $(basename "$CSV") の行数が $ROWS です (期待 $EXPECTED = $N_WIDTHS 幅 x 300)" >&2
        STATUS=1
    else
        echo "  $(basename "$CSV"): $ROWS 行 ($N_WIDTHS 幅)"
    fi
done

if [ "$STATUS" -ne 0 ]; then
    echo "検証に失敗しました。" >&2
    exit 1
fi

echo "========================================"
echo "ビン幅の感度分析が完了しました: plots/bin_width_sensitivity/"
echo "  (ビン幅 10 dBm が既存の解析結果と一致することはジョブ内で確認済み。ログ参照)"
echo "  結果を共有するには:"
echo "    git add plots/bin_width_sensitivity && git commit -m '...' && git push"
echo "========================================"
