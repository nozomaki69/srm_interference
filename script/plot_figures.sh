#!/bin/bash

# 既存の CSV から**図だけ**を作り直す。解析 (analyze_csv.py) は走らせない。
#
# 作図の設定をいじったときに使う。解析をやり直すと 155MB の
# simulation_results.csv を再パースすることになり数分かかるが、CSV が既にあるなら
# その必要は無い。
#
# 測定モードは simultaneous (single-query) と sequential (multi-query) の2つ。
# 検知結果CSVがあるモードだけ描き、無いモードは飛ばして注記を出す
# (sequential の CSV は計算機での再解析で作られる。docs/save_features.md)。
#
# 入力 (analyze_csv.py が作る):
#   plots/interference_detection_results{_simultaneous,}.csv   検知結果
#   plots/detection_scores{_simultaneous,}.csv                 Seed ごとのスコア
#
# 出力 (モードごと):
#   plots/auc_bootstrap*.csv                 AUC の 95% 信頼区間 (1000回)
#   plots/detection_lines{,_sequential}/     3手法の折れ線 (16枚 + 3x3 グリッド) x 相手負荷5通り + 描画値 CSV
#                                            名前は auc_{single,multi}_<中身>_<形>_other<相手負荷3桁>.pdf
#   plots/heatmaps_auc{_simultaneous,}/      手法ごとのヒートマップ 12枚 x 3
#   plots/roc/{simultaneous,sequential}/     ROC 曲線 27枚
#   plots/score_histograms{,_sequential}/    スコア分布 9枚
#   plots/detection_lines_mode_compare/      モード比較の 3x3 グリッド (手法ごと) x 相手負荷5通り (両モードあるとき)
#
# 解析からやり直したいときは ./script/sbatch_reanalyze.sh (こちらも最後にこれを呼ぶ)。

set -uo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
CMD_DIR=$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)
PLOTS="$CMD_DIR/plots"

cd "$CMD_DIR" || exit 1

run() {
    echo "--- $* ---"
    if ! python3 "$@"; then
        echo "エラー: 失敗しました: $*" >&2
        exit 1
    fi
}

# モード -> 検知結果CSV の接尾辞 (analyze_csv.mode_suffix() と同じ規則)
suffix() { if [ "$1" = "sequential" ]; then echo ""; else echo "_simultaneous"; fi; }

MODES_DONE=()
for MODE in simultaneous sequential; do
    if [ -f "$PLOTS/interference_detection_results$(suffix "$MODE").csv" ]; then
        MODES_DONE+=("$MODE")
    else
        echo "    ($MODE の検知結果CSVが無いので、$MODE の図は飛ばします。"
        echo "     計算機で ./script/sbatch_reanalyze.sh を回すと作られます)"
    fi
done
if [ ${#MODES_DONE[@]} -eq 0 ]; then
    echo "エラー: 検知結果CSVがありません。先に ./script/sbatch_reanalyze.sh で解析を回してください。" >&2
    exit 1
fi

# 信頼区間は折れ線が髭として読むので、折れ線より先に回す
# (スコアCSVが無いモードは自分で飛ばす)
run "$SCRIPT_DIR/bootstrap_auc.py"

for MODE in "${MODES_DONE[@]}"; do
    # 折れ線は3手法を1枚に重ねるので、手法を跨いで1回で済む
    run "$SCRIPT_DIR/plot_detection_lines.py" --mode "$MODE"
    # スコア分布は AUC の照合に折れ線の描画値を読むので、折れ線の後に回す
    run "$SCRIPT_DIR/plot_score_histograms.py" --mode "$MODE"
    run "$SCRIPT_DIR/create_heatmap.py" --mode "$MODE"
    run "$SCRIPT_DIR/plot_roc.py" --mode "$MODE"
done

# モード比較は両モードがそろったときだけ
if [ ${#MODES_DONE[@]} -eq 2 ]; then
    run "$SCRIPT_DIR/plot_detection_lines.py" --mode compare
fi

count() { find "$1" -type f 2>/dev/null | wc -l | tr -d ' '; }

echo "========================================"
echo "作図が完了しました (モード: ${MODES_DONE[*]})"
for D in detection_lines detection_lines_sequential detection_lines_mode_compare \
         heatmaps_auc_simultaneous heatmaps_auc roc score_histograms score_histograms_sequential; do
    if [ -d "$PLOTS/$D" ]; then
        printf "  plots/%-30s %s ファイル\n" "$D/" "$(count "$PLOTS/$D")"
    fi
done
echo "========================================"
