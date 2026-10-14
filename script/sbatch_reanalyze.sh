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
# 行数は 6帯域ペア x 25負荷 x 2PAN x 3手法 = 900。
# (手法を増減したらここも直すこと。手法の定義元は analyze_csv.py の
#  DETECTION_METHODS で、3 はそこから来ている)
EXPECTED_ROWS=900
EXPECTED_METHODS=3
STATUS=0
CSV="$CMD_DIR/plots/interference_detection_results_simultaneous.csv"
if [ ! -f "$CSV" ]; then
    echo "エラー: $CSV がありません" >&2
    STATUS=1
else
    ROWS=$(($(wc -l < "$CSV") - 1))
    for COL in method auc; do
        if ! head -1 "$CSV" | tr ',' '\n' | grep -qx "$COL"; then
            echo "エラー: $COL 列がありません (古い analyze_csv.py が走った可能性)" >&2
            STATUS=1
        fi
    done
    if [ "$ROWS" -ne "$EXPECTED_ROWS" ]; then
        echo "エラー: 行数が $ROWS です (期待 $EXPECTED_ROWS)" >&2
        STATUS=1
    fi
    # 列があっても手法が1つしか入っていなければ比較にならない。実際に数える。
    if [ "$STATUS" -eq 0 ]; then
        METHOD_COL=$(head -1 "$CSV" | tr ',' '\n' | grep -nx "method" | cut -d: -f1)
        NUM_METHODS=$(tail -n +2 "$CSV" | cut -d, -f"$METHOD_COL" | sort -u | wc -l | tr -d ' ')
        if [ "$NUM_METHODS" -ne "$EXPECTED_METHODS" ]; then
            echo "エラー: 手法が $NUM_METHODS 種類です (期待 $EXPECTED_METHODS)" >&2
            STATUS=1
        else
            echo "  $ROWS 行、$NUM_METHODS 手法: $(tail -n +2 "$CSV" | cut -d, -f"$METHOD_COL" | sort -u | tr '\n' ' ')"
        fi
    fi
fi

if [ "$STATUS" -ne 0 ]; then
    echo "検証に失敗しました。" >&2
    exit 1
fi

echo "========================================"
echo "再解析が完了しました"
echo "  plots/detection_lines/"
echo "========================================"
