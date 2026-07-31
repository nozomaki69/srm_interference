#!/bin/bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
CMD_DIR=$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)

NUM_DEVICE=50
OUTPUT_CSV="$CMD_DIR/plots/simulation_results.csv"

# 何ファイルごとに集計と削除を行うか
BATCH_SIZE=1000

# .trace ファイルの解析を何並列のSLURMジョブに分割するか
PARSE_PARALLEL=50

cd "$CMD_DIR" || exit

# 既存の .config ファイルを配列として取得
shopt -s nullglob
CONFIG_FILES=( *.config )
shopt -u nullglob

TOTAL_FILES=${#CONFIG_FILES[@]}

if [ "$TOTAL_FILES" -eq 0 ]; then
  echo "警告: 実行対象の .config ファイルが '$CMD_DIR' 内に見つかりません。"
  exit 0
fi

# plots / manifest / ログ用ディレクトリを作成
mkdir -p "$CMD_DIR/plots"
MANIFEST_DIR="$CMD_DIR/plots/manifests"
LOG_DIR="$CMD_DIR/plots/logs"
mkdir -p "$MANIFEST_DIR" "$LOG_DIR"

if [ -f "$OUTPUT_CSV" ]; then
    echo "古いCSVファイルが見つかりました。削除してリセットします: $OUTPUT_CSV"
    rm -f "$OUTPUT_CSV"
fi

echo "========================================"
echo "シミュレーションバッチ処理を開始します"
echo "対象ディレクトリ: $CMD_DIR"
echo "総ファイル数: $TOTAL_FILES"
echo "バッチサイズ: $BATCH_SIZE ファイルごとに集計"
echo "解析並列数: $PARSE_PARALLEL"
echo "========================================"


for (( i=0; i<$TOTAL_FILES; i+=$BATCH_SIZE )); do

    BATCH_FILES=("${CONFIG_FILES[@]:$i:$BATCH_SIZE}")
    NUM_IN_BATCH=${#BATCH_FILES[@]}

    echo "--------------------------------------------------"
    echo "バッチ実行開始: $((i+1)) 〜 $((i+NUM_IN_BATCH)) / $TOTAL_FILES"

    # ---------- 1) シミュレーションをSLURMに並列投入 ----------
    JOB_IDS=()
    for config in "${BATCH_FILES[@]}"; do
        # sbatchで1つずつ投入し、--parsable でジョブIDを取得
        JID=$(sbatch --parsable --partition=ubuntu "$SCRIPT_DIR/sim_worker_slurm.sh" "$(realpath "$config")")
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
        MANIFEST_FILE="$MANIFEST_DIR/manifest_batch${i}_chunk${CHUNK_IDX}.txt"
        : > "$MANIFEST_FILE"
        for tf in "${CHUNK_FILES[@]}"; do
            realpath "$tf" >> "$MANIFEST_FILE"
        done

        PARTIAL_CSV="$CMD_DIR/plots/partial_batch${i}_chunk${CHUNK_IDX}.csv"
        PARTIAL_CSVS+=("$PARTIAL_CSV")

        # このチャンク専用のジョブを投入。結果はヘッダー無しの部分CSVに書き込む
        PJID=$(sbatch --parsable --partition=ubuntu \
            --job-name="parse_c${CHUNK_IDX}" \
            --output="$LOG_DIR/parse_batch${i}_chunk${CHUNK_IDX}.out" \
            --error="$LOG_DIR/parse_batch${i}_chunk${CHUNK_IDX}.err" \
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
        echo "マージ成功！処理済みの .trace / 部分CSV / manifest を削除します..."
        rm -f "$CMD_DIR"/*.trace
        rm -f "${PARTIAL_CSVS[@]}"
        rm -f "$MANIFEST_DIR"/manifest_batch${i}_*.txt
    else
        echo "エラー: 集計処理中に問題が発生しました。"
        exit 1
    fi

done

echo "========================================"
echo "すべてのシミュレーションと集計が完了しました！"