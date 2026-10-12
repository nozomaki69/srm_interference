#!/bin/bash

# 既存の plots/simulation_results.csv から、解析と作図だけをやり直す。
# 再シミュレーションは不要 (simulation_results.csv さえあればよい)。
#
# 中身は run_analysis.sh と同じで、それを SLURM に投げて**完了まで待ち**、
# 結果を検証するところまでやる。投げっぱなしだと「投入できた」ことしか
# 分からず、解析が落ちていても気づけないため。

set -uo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
CMD_DIR=$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)

INPUT_CSV="$CMD_DIR/plots/simulation_results.csv"
LOG_DIR="$CMD_DIR/plots/logs"

# 投入前に手元で止める。SLURM ジョブが起動してから落ちると原因が分かりにくい。
if [ ! -f "$INPUT_CSV" ]; then
    echo "エラー: 入力CSVがありません: $INPUT_CSV" >&2
    echo "       先に ./script/sbatch_jobs.sh を完走させてください。" >&2
    exit 1
fi

mkdir -p "$LOG_DIR"
cd "$CMD_DIR" || exit 1

LOG_OUT="$LOG_DIR/reanalyze_%j.out"
echo "--- 入力: $INPUT_CSV ($(du -h "$INPUT_CSV" | cut -f1)) ---"
echo "--- SLURM に投入して完了を待ちます ---"

# --wait で完了までブロックする。analyze_csv.py はシングルスレッドなので -c 1。
if ! sbatch --wait --partition=ubuntu -c 1 \
    --job-name="reanalyze" \
    --output="$LOG_OUT" \
    --error="$LOG_DIR/reanalyze_%j.err" \
    --wrap="bash '$SCRIPT_DIR/run_analysis.sh'"; then
    echo "エラー: 解析ジョブが失敗しました。" >&2
    echo "       ログ: $LOG_DIR/reanalyze_<jobid>.{out,err}" >&2
    ls -t "$LOG_DIR"/reanalyze_*.err 2>/dev/null | head -1 | while read -r f; do
        echo "--- $(basename "$f") の末尾 ---" >&2
        tail -20 "$f" >&2
    done
    exit 1
fi

# --- 結果の検証 ---------------------------------------------------------
# ジョブが成功で終わっても、出力が期待どおりとは限らない。中身を確かめる。
# 行数は 6帯域ペア x 25負荷 x 2PAN = 300。
EXPECTED_ROWS=300
STATUS=0
for SUFFIX in "" "_simultaneous"; do
    CSV="$CMD_DIR/plots/interference_detection_results${SUFFIX}.csv"
    LABEL="${SUFFIX:-_sequential}"
    if [ ! -f "$CSV" ]; then
        echo "エラー: $CSV がありません" >&2
        STATUS=1
        continue
    fi
    ROWS=$(($(wc -l < "$CSV") - 1))
    if ! head -1 "$CSV" | tr ',' '\n' | grep -qx "auc"; then
        echo "エラー: ${LABEL}: auc 列がありません (古い analyze_csv.py が走った可能性)" >&2
        STATUS=1
    fi
    if [ "$ROWS" -ne "$EXPECTED_ROWS" ]; then
        echo "エラー: ${LABEL}: 行数が $ROWS です (期待 $EXPECTED_ROWS)" >&2
        STATUS=1
    fi
    [ "$STATUS" -eq 0 ] && echo "  ${LABEL}: $ROWS 行、auc 列あり"
done

if [ "$STATUS" -ne 0 ]; then
    echo "検証に失敗しました。" >&2
    exit 1
fi

echo "========================================"
echo "再解析が完了しました"
echo "  plots/heatmaps{,_simultaneous}/ plots/heatmaps_auc{,_simultaneous}/"
echo "  plots/detection_lines/ plots/roc/"
echo "========================================"
