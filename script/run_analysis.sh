#!/bin/bash

# plots/simulation_results.csv から、sequential と simultaneous の両モードについて
# 検知結果CSV -> ヒートマップ -> 折れ線グラフ を作る。
#
# sbatch_jobs.sh の最後と sbatch_reanalyze.sh の両方がこれを呼ぶ。
# 手順を2箇所に書くと片方だけ直して静かにずれるので、唯一の定義元にする。
#
# 出力:
#   plots/interference_detection_results{,_simultaneous}.csv
#   plots/heatmaps{,_simultaneous}/ plots/heatmaps_auc{,_simultaneous}/  12枚ずつ
#   plots/detection_lines/                              f1 と auc で12枚ずつ
#   plots/detection_scores{,_simultaneous}.csv                  Seed ごとの干渉指標
#   plots/roc/                                          ROC 曲線 6枚

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
for MODE in sequential simultaneous; do
    echo "--- 解析 (--mode $MODE) ---"
    if ! python3 "$SCRIPT_DIR/analyze_csv.py" --mode "$MODE"; then
        echo "エラー: analyze_csv.py --mode $MODE に失敗しました" >&2
        exit 1
    fi

done

# 作図は plot_figures.sh が唯一の定義元。手順を2箇所に書くと片方だけ直して
# 静かにずれる (図の設定だけ変えたいときはそちらを単体で回せる)。
if ! bash "$SCRIPT_DIR/plot_figures.sh"; then
    echo "エラー: plot_figures.sh に失敗しました" >&2
    exit 1
fi

echo "========================================"
echo "解析と作図が完了しました"
echo "  plots/interference_detection_results{,_simultaneous}.csv   検知結果"
echo "  plots/detection_scores{,_simultaneous}.csv                 Seed ごとの指標"
echo "  (図の一覧は上の plot_figures.sh の出力を参照)"
echo "========================================"
