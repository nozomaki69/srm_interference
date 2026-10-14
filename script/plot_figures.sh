#!/bin/bash

# 既存の CSV から**図だけ**を作り直す。解析 (analyze_csv.py) は走らせない。
#
# 作図の設定をいじったときに使う。解析をやり直すと 155MB の
# simulation_results.csv を再パースすることになり数分かかるが、CSV が既にあるなら
# その必要は無い。
#
# 入力 (analyze_csv.py が作る):
#   plots/interference_detection_results_simultaneous.csv   検知結果 (method / auc 列)
#
# 出力:
#   plots/detection_lines/   折れ線 16枚 (手法3 + 比較1) x (自帯域3 + 3パネル1)
#                            + auc_plotted_values.csv
#
# 解析からやり直したいときは ./script/sbatch_reanalyze.sh (こちらも最後にこれを呼ぶ)。

set -uo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
CMD_DIR=$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)
PLOTS="$CMD_DIR/plots"

INPUT="$PLOTS/interference_detection_results_simultaneous.csv"
if [ ! -f "$INPUT" ]; then
    echo "エラー: 入力CSVがありません: plots/$(basename "$INPUT")" >&2
    echo "       先に ./script/sbatch_reanalyze.sh で解析を回してください。" >&2
    exit 1
fi

cd "$CMD_DIR" || exit 1

run() {
    echo "--- $* ---"
    if ! python3 "$@"; then
        echo "エラー: 失敗しました: $*" >&2
        exit 1
    fi
}

# 折れ線は3手法を1枚に重ねるので、手法を跨いで1回で済む
run "$SCRIPT_DIR/plot_detection_lines.py"

count() { ls "$1" 2>/dev/null | wc -l | tr -d ' '; }

echo "========================================"
echo "作図が完了しました"
echo "  plots/detection_lines/     $(count "$PLOTS/detection_lines") ファイル"
echo "========================================"
