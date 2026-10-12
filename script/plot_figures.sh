#!/bin/bash

# 既存の CSV から**図だけ**を作り直す。解析 (analyze_csv.py) は走らせない。
#
# 作図の設定をいじったときに使う。解析をやり直すと 155MB の
# simulation_results.csv を再パースすることになり数分かかるが、CSV が既にあるなら
# その必要は無い。
#
# 入力 (いずれも analyze_csv.py が作る):
#   plots/interference_detection_results{,_simultaneous}.csv   検知結果 (f1 / auc 列)
#   plots/detection_scores{,_simultaneous}.csv                 Seed ごとの指標 (ROC の入力)
#
# 出力:
#   plots/heatmaps{,_simultaneous}/        F1 ヒートマップ      12枚ずつ
#   plots/heatmaps_auc{,_simultaneous}/    AUC ヒートマップ     12枚ずつ
#   plots/detection_lines/         折れ線 f1 / auc      12枚ずつ + 描画値CSV
#   plots/roc/                     ROC 曲線             18枚 (1条件1枚)
#
# 解析からやり直したいときは ./script/sbatch_reanalyze.sh (こちらも最後にこれを呼ぶ)。

set -uo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
CMD_DIR=$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)
PLOTS="$CMD_DIR/plots"

# 入力が欠けたまま走らせると、途中まで作って中途半端な状態になる。先に全部見る。
MISSING=0
for f in "interference_detection_results.csv" "interference_detection_results_simultaneous.csv" \
         "detection_scores.csv" "detection_scores_simultaneous.csv"; do
    if [ ! -f "$PLOTS/$f" ]; then
        echo "エラー: 入力CSVがありません: plots/$f" >&2
        MISSING=1
    fi
done
if [ "$MISSING" -ne 0 ]; then
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

# ヒートマップ: 測定モード x 指標
for MODE in sequential simultaneous; do
    for METRIC in f1 auc; do
        run "$SCRIPT_DIR/create_heatmap.py" --mode "$MODE" --metric "$METRIC"
    done
done

# 折れ線は sequential と simultaneous を1枚に重ねるので、モードを跨いで1回ずつ
for METRIC in f1 auc; do
    run "$SCRIPT_DIR/plot_detection_lines.py" --metric "$METRIC"
done

# ROC も両モードのスコアCSVを読む
run "$SCRIPT_DIR/plot_roc.py"

count() { ls "$1" 2>/dev/null | wc -l | tr -d ' '; }

echo "========================================"
echo "作図が完了しました"
echo "  plots/heatmaps/            $(count "$PLOTS/heatmaps") 枚   (F1, sequential)"
echo "  plots/heatmaps_simultaneous/       $(count "$PLOTS/heatmaps_simultaneous") 枚   (F1, simultaneous)"
echo "  plots/heatmaps_auc/        $(count "$PLOTS/heatmaps_auc") 枚   (AUC, sequential)"
echo "  plots/heatmaps_auc_simultaneous/   $(count "$PLOTS/heatmaps_auc_simultaneous") 枚   (AUC, simultaneous)"
echo "  plots/detection_lines/     $(count "$PLOTS/detection_lines") ファイル"
echo "  plots/roc/                 $(count "$PLOTS/roc") 枚"
echo "========================================"
