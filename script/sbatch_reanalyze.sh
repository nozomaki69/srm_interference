#!/bin/bash

# 既存の plots/simulation_results.csv に対して analyze_csv.py を td / conv の
# 両モードで回し直し、検知結果 CSV を作り直す。再シミュレーションは不要。
#
# analyze_csv.py を単体で SLURM に投げる手段が無かったので用意した。
# sbatch_analyze.sh は旧世代の interference_2pan_plot_results.py を投げる別物。
#
# 既定では --no-plots を付ける。検知結果 CSV は条件別プロットより先に書き終わって
# いて両者は独立なので、列を足しただけの再解析では 300条件 x 6枚 = 1,800枚/モードの
# 生成を丸ごと省ける。図も作り直したいときは --with-plots を渡す。
#
# 詳細は docs/detection_line_plots.md §8 を参照。

set -uo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
CMD_DIR=$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)

ANALYZE_SCRIPT="$SCRIPT_DIR/analyze_csv.py"
INPUT_CSV="$CMD_DIR/plots/simulation_results.csv"
LOG_DIR="$CMD_DIR/plots/logs"

PLOT_OPT="--no-plots"
for arg in "$@"; do
    case "$arg" in
        --with-plots) PLOT_OPT="" ;;
        -h|--help)
            echo "使い方: $0 [--with-plots]"
            echo "  既定       : 検知結果CSVだけを作り直す (--no-plots)"
            echo "  --with-plots: 条件別プロット(1,800枚/モード)も作り直す"
            exit 0
            ;;
        *)
            echo "エラー: 不明な引数: $arg" >&2
            echo "使い方: $0 [--with-plots]" >&2
            exit 1
            ;;
    esac
done

# 入力が無いまま投げると、SLURM ジョブが起動してから落ちて原因が分かりにくい。
# 手元で先に確認して止める。
if [ ! -f "$INPUT_CSV" ]; then
    echo "エラー: 入力CSVがありません: $INPUT_CSV" >&2
    echo "       スイープ (script/sbatch_jobs.sh) を先に完走させてください。" >&2
    exit 1
fi

if [ ! -f "$CMD_DIR/plots/positions.csv" ]; then
    # 座標が無くても検知結果CSVは正しく出る (run_interference_detection は
    # *_dist を使わない)。--with-plots のときだけ errorbar 図が欠ける。
    echo "注意: plots/positions.csv がありません。検知結果CSVには影響しませんが、"
    echo "      --with-plots の場合は距離-PER の errorbar 図が空になります。"
fi

mkdir -p "$LOG_DIR"
cd "$CMD_DIR" || exit 1

echo "--- 入力: $INPUT_CSV ($(du -h "$INPUT_CSV" | cut -f1)) ---"
echo "--- オプション: ${PLOT_OPT:-（プロットも生成）} ---"

# td と conv は互いに独立 (出力ファイル名が接尾辞で分かれる) なので並行して投げる。
# analyze_csv.py はシングルスレッドなので -c 1。
JIDS=()
for MODE in td conv; do
    if ! JID=$(sbatch --parsable --partition=ubuntu -c 1 \
        --job-name="reanalyze_$MODE" \
        --output="$LOG_DIR/reanalyze_${MODE}_%j.out" \
        --error="$LOG_DIR/reanalyze_${MODE}_%j.err" \
        --wrap="python3 '$ANALYZE_SCRIPT' --mode $MODE $PLOT_OPT"); then
        echo "エラー: --mode $MODE の投入に失敗しました" >&2
        exit 1
    fi
    JIDS+=("$JID")
    echo "投入: --mode $MODE  (JobID $JID)"
done

echo "----------------------------------------"
echo "2件投入しました: ${JIDS[*]}"
echo "進捗: squeue -j $(IFS=,; echo "${JIDS[*]}")"
echo "ログ: $LOG_DIR/reanalyze_*_<jobid>.out"
echo
echo "完了後に出力されるもの:"
echo "  plots/interference_detection_results.csv       (td)"
echo "  plots/interference_detection_results_conv.csv  (conv)"
echo
echo "続けて図を作る場合:"
echo "  python3 script/plot_detection_lines.py --metric auc"
echo "  python3 script/plot_detection_lines.py --metric f1"
