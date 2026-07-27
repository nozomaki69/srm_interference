#!/bin/bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
CMD_DIR=$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)

NUM_DEVICE=10
OUTPUT_CSV="$CMD_DIR/plots/simulation_results.csv"

# 何ファイルごとに集計と削除を行うか
BATCH_SIZE=100

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

# plotsディレクトリを作成
mkdir -p "$CMD_DIR/plots"

if [ -f "$OUTPUT_CSV" ]; then
    echo "古いCSVファイルが見つかりました。削除してリセットします: $OUTPUT_CSV"
    rm -f "$OUTPUT_CSV"
fi

echo "========================================"
echo "シミュレーションバッチ処理を開始します"
echo "対象ディレクトリ: $CMD_DIR"
echo "総ファイル数: $TOTAL_FILES"
echo "バッチサイズ: $BATCH_SIZE ファイルごとに集計"
echo "========================================"


for (( i=0; i<$TOTAL_FILES; i+=$BATCH_SIZE )); do
    
    BATCH_FILES=("${CONFIG_FILES[@]:$i:$BATCH_SIZE}")
    NUM_IN_BATCH=${#BATCH_FILES[@]}
    
    echo "--------------------------------------------------"
    echo "バッチ実行開始: $((i+1)) 〜 $((i+NUM_IN_BATCH)) / $TOTAL_FILES"

    JOB_IDS=()
    for config in "${BATCH_FILES[@]}"; do
        # sbatchで1つずつ投入し、--parsable でジョブIDを取得
        JID=$(sbatch --parsable --partition=ubuntu "$SCRIPT_DIR/sim_worker_slurm.sh" "$(realpath "$config")")
        JOB_IDS+=("$JID")
    done
    
    # ジョブIDをカンマ区切りに変換 (例: 101,102,103)
    DEPENDENCIES=$(IFS=,; echo "${JOB_IDS[*]}")
    
    echo "${#JOB_IDS[@]} 件のジョブをSLURMに投入しました。完了を待機しています..."
    
    sbatch --wait --partition=ubuntu --dependency=afterany:${DEPENDENCIES} --job-name="wait_dummy" --output=/dev/null --error=/dev/null --wrap="exit 0"
    
    echo "バッチのシミュレーション完了。集計（追記）を開始します..."
    
    if python3 "$SCRIPT_DIR/create_csv.py" "$CMD_DIR" "$NUM_DEVICE" "$OUTPUT_CSV"; then
        echo "集計成功！処理済みの .trace ファイルを削除します..."
        rm -f "$CMD_DIR"/*.trace
    else
        echo "エラー: 集計処理中に問題が発生しました。"
        exit 1
    fi
    
done

echo "========================================"
echo "すべてのシミュレーションと集計が完了しました！"