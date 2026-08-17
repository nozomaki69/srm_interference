#!/bin/bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
CMD_DIR=$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)

NUM_DEVICE=30
OUTPUT_CSV="$CMD_DIR/plots/simulation_results.csv"

# 1バッチあたりの生成・シミュレーション・集計件数
BATCH_SIZE=2000

# .trace ファイルの解析を何並列のSLURMジョブに分割するか
PARSE_PARALLEL=50

# configファイル生成スクリプト (ファイル名が違う場合はここを変更してください)
GEN_CONFIG_SCRIPT="$SCRIPT_DIR/interference_2pan_config.py"

# 全バッチ終了後に実行する解析スクリプト
ANALYZE_SCRIPT="$SCRIPT_DIR/analyze_csv.py"
# analyze_csv.py が出力した interference_detection_results.csv からヒートマップを作るスクリプト
HEATMAP_SCRIPT="$SCRIPT_DIR/create_heatmap.py"

cd "$CMD_DIR" || exit

# plots / manifest / ログ用ディレクトリを作成
mkdir -p "$CMD_DIR/plots"
MANIFEST_DIR="$CMD_DIR/plots/manifests"
LOG_DIR="$CMD_DIR/plots/logs"
mkdir -p "$MANIFEST_DIR" "$LOG_DIR"

if [ -f "$OUTPUT_CSV" ]; then
    echo "古いCSVファイルが見つかりました。削除してリセットします: $OUTPUT_CSV"
    rm -f "$OUTPUT_CSV"
fi

# 前回実行時の残留ファイルをクリーンアップ
# 注意: .pos はバッチ完了時には消さず、解析スクリプト(analyze_csv.py等)が
# 全バッチ終了後に参照した時点で削除する運用のため、この起動時クリーンアップで
# まとめて消える。まだ解析していない前回分の .pos が残っている場合は、
# run_simulations.sh を再実行する前に解析スクリプトを実行しておくこと。
shopt -s nullglob
STALE_FILES=( *.config *.pos *.statconfig *.trace *.stat )
shopt -u nullglob
if [ "${#STALE_FILES[@]}" -gt 0 ]; then
    echo "警告: 前回実行時の残留ファイルが ${#STALE_FILES[@]} 件見つかりました。削除してクリーンな状態から開始します。"
    rm -f "${STALE_FILES[@]}"
fi

# 全体のシミュレーション組み合わせ数を取得
TOTAL_COMBOS=$(python3 "$GEN_CONFIG_SCRIPT" --print-total)

if [ -z "$TOTAL_COMBOS" ] || [ "$TOTAL_COMBOS" -eq 0 ]; then
    echo "警告: 生成対象のシミュレーション組み合わせが見つかりません。"
    exit 0
fi

echo "========================================"
echo "シミュレーションバッチ処理を開始します"
echo "対象ディレクトリ: $CMD_DIR"
echo "総組み合わせ数: $TOTAL_COMBOS"
echo "バッチサイズ: $BATCH_SIZE 件ごとに 生成 → 実行 → 集計 → 削除"
echo "解析並列数: $PARSE_PARALLEL"
echo "========================================"

CURSOR=0

while [ "$CURSOR" -lt "$TOTAL_COMBOS" ]; do

    BATCH_END=$((CURSOR + BATCH_SIZE))
    if [ "$BATCH_END" -gt "$TOTAL_COMBOS" ]; then
        BATCH_END=$TOTAL_COMBOS
    fi

    echo "--------------------------------------------------"
    echo "バッチ実行開始: $((CURSOR+1)) 〜 $BATCH_END / $TOTAL_COMBOS"

    # ---------- 0) configファイル群を生成 ----------
    echo "configファイルを生成しています..."
    if ! python3 "$GEN_CONFIG_SCRIPT" --start "$CURSOR" --count "$BATCH_SIZE"; then
        echo "エラー: configファイルの生成に失敗しました。"
        exit 1
    fi

    shopt -s nullglob
    BATCH_FILES=( *.config )
    shopt -u nullglob
    NUM_IN_BATCH=${#BATCH_FILES[@]}

    if [ "$NUM_IN_BATCH" -eq 0 ]; then
        echo "エラー: configファイルが生成されませんでした。"
        exit 1
    fi

    # ---------- 1) シミュレーションをSLURMに並列投入 ----------
    JOB_IDS=()
    for config in "${BATCH_FILES[@]}"; do
        # sbatchで1つずつ投入し、--parsable でジョブIDを取得
        # --output/--error を明示しないと slurm-<jobid>.out がCMD_DIR直下に
        # 大量に作られてしまうので、解析ジョブと同様にLOG_DIRへ逃がす
        JID=$(sbatch --parsable --partition=ubuntu \
            --output="$LOG_DIR/sim_%j.out" \
            --error="$LOG_DIR/sim_%j.err" \
            "$SCRIPT_DIR/sim_worker_slurm.sh" "$(realpath "$config")")
        JOB_IDS+=("$JID")
    done

    # ジョブIDをカンマ区切りに変換 (例: 101,102,103)
    DEPENDENCIES=$(IFS=,; echo "${JOB_IDS[*]}")

    echo "${#JOB_IDS[@]} 件のシミュレーションジョブをSLURMに投入しました。完了を待機しています..."

    sbatch --wait --partition=ubuntu --dependency=afterany:${DEPENDENCIES} \
        --job-name="wait_sim" --output=/dev/null --error=/dev/null --wrap="exit 0"

    echo "バッチのシミュレーション完了。"

    # ---------- 2) 生成された .trace ファイルを並列に解析 ----------
    shopt -s nullglob
    TRACE_FILES=( *.trace )
    shopt -u nullglob
    NUM_TRACES=${#TRACE_FILES[@]}

    if [ "$NUM_TRACES" -eq 0 ]; then
        echo "警告: .trace ファイルが見つかりません。このバッチの解析をスキップします。"
        CURSOR=$BATCH_END
        continue
    fi

    echo "解析対象の .trace ファイル数: $NUM_TRACES"

    # PARSE_PARALLEL 個のジョブに分割するためのチャンクサイズを計算(切り上げ)
    CHUNK_SIZE=$(( (NUM_TRACES + PARSE_PARALLEL - 1) / PARSE_PARALLEL ))
    if [ "$CHUNK_SIZE" -lt 1 ]; then
        CHUNK_SIZE=1
    fi

    PARSE_JOB_IDS=()
    PARTIAL_CSVS=()
    CHUNK_IDX=0

    for (( j=0; j<$NUM_TRACES; j+=$CHUNK_SIZE )); do
        CHUNK_IDX=$((CHUNK_IDX+1))
        CHUNK_FILES=("${TRACE_FILES[@]:$j:$CHUNK_SIZE}")

        # このチャンクが担当する trace ファイルの一覧(manifest)を書き出す
        MANIFEST_FILE="$MANIFEST_DIR/manifest_cursor${CURSOR}_chunk${CHUNK_IDX}.txt"
        : > "$MANIFEST_FILE"
        for tf in "${CHUNK_FILES[@]}"; do
            realpath "$tf" >> "$MANIFEST_FILE"
        done

        PARTIAL_CSV="$CMD_DIR/plots/partial_cursor${CURSOR}_chunk${CHUNK_IDX}.csv"
        PARTIAL_CSVS+=("$PARTIAL_CSV")

        # このチャンク専用のジョブを投入。結果はヘッダー無しの部分CSVに書き込む
        PJID=$(sbatch --parsable --partition=ubuntu \
            --job-name="parse_c${CHUNK_IDX}" \
            --output="$LOG_DIR/parse_cursor${CURSOR}_chunk${CHUNK_IDX}.out" \
            --error="$LOG_DIR/parse_cursor${CURSOR}_chunk${CHUNK_IDX}.err" \
            --wrap="python3 '$SCRIPT_DIR/create_csv.py' '$CMD_DIR' '$NUM_DEVICE' '$PARTIAL_CSV' '$MANIFEST_FILE'")
        PARSE_JOB_IDS+=("$PJID")
    done

    PARSE_DEPS=$(IFS=,; echo "${PARSE_JOB_IDS[*]}")

    echo "${#PARSE_JOB_IDS[@]} 件の解析ジョブをSLURMに投入しました。完了を待機しています..."

    sbatch --wait --partition=ubuntu --dependency=afterany:${PARSE_DEPS} \
        --job-name="wait_parse" --output=/dev/null --error=/dev/null --wrap="exit 0"

    echo "並列解析が完了しました。結果をマージします..."

    # ---------- 3) 部分CSVをマージ ----------
    # 最終CSVがまだ存在しない場合は先にヘッダー行だけを書き込む
    if [ ! -f "$OUTPUT_CSV" ]; then
        python3 "$SCRIPT_DIR/create_csv.py" --header-only "$NUM_DEVICE" "$OUTPUT_CSV"
    fi

    MERGE_OK=true
    for pcsv in "${PARTIAL_CSVS[@]}"; do
        if [ -f "$pcsv" ]; then
            cat "$pcsv" >> "$OUTPUT_CSV"
        else
            echo "エラー: 部分CSVが見つかりません: $pcsv"
            MERGE_OK=false
        fi
    done

    if [ "$MERGE_OK" = true ]; then
        # .pos は解析スクリプト(analyze_csv.py)が全バッチ終了後に距離計算のため
        # 参照するので、ここでは削除しない。参照された時点でそちらが削除する。
        echo "マージ成功！このバッチの .trace / .config / .stat / .statconfig / 部分CSV / manifest を削除します..."
        rm -f "$CMD_DIR"/*.trace "$CMD_DIR"/*.config "$CMD_DIR"/*.stat "$CMD_DIR"/*.statconfig
        rm -f "${PARTIAL_CSVS[@]}"
        rm -f "$MANIFEST_DIR"/manifest_cursor${CURSOR}_*.txt
    else
        echo "エラー: 集計処理中に問題が発生しました。"
        exit 1
    fi

    CURSOR=$BATCH_END

done

echo "========================================"
echo "すべてのシミュレーションと集計が完了しました！"
echo "========================================"

echo "解析スクリプトを実行します: $ANALYZE_SCRIPT"
if python3 "$ANALYZE_SCRIPT"; then
    echo "解析が完了しました。"
else
    echo "エラー: $ANALYZE_SCRIPT の実行に失敗しました。"
    exit 1
fi

echo "ヒートマップ生成スクリプトを実行します: $HEATMAP_SCRIPT"
if python3 "$HEATMAP_SCRIPT"; then
    echo "ヒートマップ生成が完了しました。"
else
    echo "エラー: $HEATMAP_SCRIPT の実行に失敗しました。"
    exit 1
fi

echo "========================================"
echo "すべての処理が完了しました！"