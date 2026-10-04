#!/bin/bash

# plots/simulation_results.csv から、td と conv の両モードについて
# 検知結果CSV -> ヒートマップ -> 折れ線グラフ を作る。
#
# sbatch_jobs.sh の最後と sbatch_reanalyze.sh の両方がこれを呼ぶ。
# 手順を2箇所に書くと片方だけ直して静かにずれるので、唯一の定義元にする。
#
# 出力:
#   plots/interference_detection_results{,_conv}.csv
#   plots/heatmaps{,_conv}/                             12枚ずつ
#   plots/detection_lines/                              f1 と auc で12枚ずつ

set -uo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
CMD_DIR=$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)

INPUT_CSV="$CMD_DIR/plots/simulation_results.csv"

if [ ! -f "$INPUT_CSV" ]; then
    echo "エラー: 入力CSVがありません: $INPUT_CSV" >&2
    exit 1
fi

cd "$CMD_DIR" || exit 1

# 検知結果CSV。測定モードごとに出力名が接尾辞で分かれる。
for MODE in td conv; do
    echo "--- 解析 (--mode $MODE) ---"
    if ! python3 "$SCRIPT_DIR/analyze_csv.py" --mode "$MODE"; then
        echo "エラー: analyze_csv.py --mode $MODE に失敗しました" >&2
        exit 1
    fi

    echo "--- ヒートマップ (--mode $MODE) ---"
    if ! python3 "$SCRIPT_DIR/create_heatmap.py" --mode "$MODE"; then
        echo "エラー: create_heatmap.py --mode $MODE に失敗しました" >&2
        exit 1
    fi
done

# 折れ線は td と conv を1枚に重ねるので、両モードのCSVが揃ってから。
for METRIC in f1 auc; do
    echo "--- 折れ線グラフ (--metric $METRIC) ---"
    if ! python3 "$SCRIPT_DIR/plot_detection_lines.py" --metric "$METRIC"; then
        echo "エラー: plot_detection_lines.py --metric $METRIC に失敗しました" >&2
        exit 1
    fi
done

echo "========================================"
echo "解析と作図が完了しました"
echo "  plots/interference_detection_results.csv       (td)"
echo "  plots/interference_detection_results_conv.csv  (conv)"
echo "  plots/heatmaps/        $(ls "$CMD_DIR/plots/heatmaps" 2>/dev/null | wc -l | tr -d ' ') 枚"
echo "  plots/heatmaps_conv/   $(ls "$CMD_DIR/plots/heatmaps_conv" 2>/dev/null | wc -l | tr -d ' ') 枚"
echo "  plots/detection_lines/ $(ls "$CMD_DIR/plots/detection_lines" 2>/dev/null | wc -l | tr -d ' ') ファイル"
echo "========================================"
