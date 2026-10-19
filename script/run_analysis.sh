#!/bin/bash

# plots/simulation_results.csv から、干渉判定3手法の検知結果CSV -> 折れ線グラフ を作る。
#
# sbatch_jobs.sh の最後と sbatch_reanalyze.sh の両方がこれを呼ぶ。
# 手順を2箇所に書くと片方だけ直して静かにずれるので、唯一の定義元にする。
#
# 測定モードは simultaneous 固定 (analyze_csv.py の「測定モード」節を参照)。
#
# 出力:
#   plots/interference_detection_results_simultaneous.csv   検知結果 (900行)
#   plots/detection_scores_simultaneous.csv                 Seed ごとの干渉指標
#   plots/detection_lines/                                  折れ線 16枚 + 描画値CSV

set -uo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
CMD_DIR=$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)

INPUT_CSV="$CMD_DIR/plots/simulation_results.csv"

if [ ! -f "$INPUT_CSV" ]; then
    echo "エラー: 入力CSVがありません: $INPUT_CSV" >&2
    exit 1
fi

cd "$CMD_DIR" || exit 1

# 両方の測定モードを解析する (single-query = simultaneous / multi-query = sequential)。
# 同じ simulation_results.csv の別の列を読むだけ (docs/save_features.md)。
for MODE in simultaneous sequential; do
    echo "--- 解析 (3手法, $MODE) ---"
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
echo "  plots/interference_detection_results{_simultaneous,}.csv   検知結果"
echo "  plots/detection_scores{_simultaneous,}.csv                 Seed ごとの指標"
echo "  (図の一覧は上の plot_figures.sh の出力を参照)"
echo "========================================"
