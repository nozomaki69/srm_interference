#!/bin/bash

# set -e は使わない (失敗箇所を自前で判定して、何が落ちたかを出してから止めたいため)。
# set -u は未定義変数の取り違えを、pipefail はパイプ途中の失敗の見逃しを防ぐ。
set -uo pipefail

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
# このスクリプトを再実行する前に analyze_csv.py を実行しておくこと。
#
# glob 展開 + rm ではなく find -delete を使う理由: .pos はスイープ中ずっと
# 溜まり続けて最大12万件になるため、`rm -f *.pos` だと引数リストが ARG_MAX
# (約2MB) を超えて "Argument list too long" で失敗する。しかも従来はその失敗を
# チェックしていなかったので、前回の残骸を抱えたまま次のスイープが走っていた。
STALE_COUNT=$(find "$CMD_DIR" -maxdepth 1 -type f \
    \( -name '*.config' -o -name '*.pos' -o -name '*.statconfig' \
       -o -name '*.trace' -o -name '*.stat' -o -name '*.done' \) | wc -l)
if [ "$STALE_COUNT" -gt 0 ]; then
    echo "警告: 前回実行時の残留ファイルが ${STALE_COUNT} 件見つかりました。削除してクリーンな状態から開始します。"
    if ! find "$CMD_DIR" -maxdepth 1 -type f \
        \( -name '*.config' -o -name '*.pos' -o -name '*.statconfig' \
           -o -name '*.trace' -o -name '*.stat' -o -name '*.done' \) -delete; then
        echo "エラー: 残留ファイルの削除に失敗しました。手動で掃除してから再実行してください。"
        exit 1
    fi
fi

# positions.csv は .pos を消したあとの再解析用キャッシュだが、analyze_csv.py は
# .pos よりこちらを優先する。生成パラメータ (NUM_DEVICE / 通信範囲 / 帯域ペア) を
# 変えてスイープし直した場合、ファイル名が同じなら古い座標が黙って使われてしまうので、
# 新しいスイープを始めるこのタイミングで破棄する。
POSITIONS_CSV="$CMD_DIR/plots/positions.csv"
if [ -f "$POSITIONS_CSV" ]; then
    echo "前回の座標キャッシュを削除します (古い座標が再利用されるのを防ぐため): $POSITIONS_CSV"
    rm -f "$POSITIONS_CSV"
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
        #
        # 投入失敗を必ず検出する: MaxSubmitJobs 超過などで sbatch が失敗すると
        # JID が空になり、依存文字列が "101,,102" のような不正な形になる。
        # すると後段の `sbatch --wait` が即座に失敗し、まだ書き込み中の .trace を
        # 解析して CSV に入れ、その直後に .trace を消してしまう。
        if ! JID=$(sbatch --parsable --partition=ubuntu \
            --output="$LOG_DIR/sim_%j.out" \
            --error="$LOG_DIR/sim_%j.err" \
            "$SCRIPT_DIR/sim_worker_slurm.sh" "$(realpath "$config")"); then
            echo "エラー: シミュレーションジョブの投入に失敗しました: $config"
            echo "       (投入済み ${#JOB_IDS[@]} 件は走り続けます。scancel で停止してください)"
            exit 1
        fi
        if ! [[ "$JID" =~ ^[0-9]+$ ]]; then
            echo "エラー: sbatch がジョブIDを返しませんでした: $config (出力: '$JID')"
            exit 1
        fi
        JOB_IDS+=("$JID")
    done

    # ジョブIDをカンマ区切りに変換 (例: 101,102,103)
    DEPENDENCIES=$(IFS=,; echo "${JOB_IDS[*]}")

    echo "${#JOB_IDS[@]} 件のシミュレーションジョブをSLURMに投入しました。完了を待機しています..."

    if ! sbatch --wait --partition=ubuntu --dependency=afterany:"${DEPENDENCIES}" \
        --job-name="wait_sim" --output=/dev/null --error=/dev/null --wrap="exit 0"; then
        echo "エラー: シミュレーション完了の待機に失敗しました (依存指定が不正か、待機ジョブが実行されませんでした)。"
        echo "       .trace がまだ書き込み中の可能性があるため、ここで中断します。"
        exit 1
    fi

    echo "バッチのシミュレーション完了。"

    # ---------- 2) 生成された .trace ファイルを並列に解析 ----------
    shopt -s nullglob
    TRACE_FILES=( *.trace )
    DONE_FILES=( *.done )
    shopt -u nullglob
    NUM_TRACES=${#TRACE_FILES[@]}
    NUM_DONE=${#DONE_FILES[@]}

    # --dependency=afterany は失敗したジョブも「完了」として扱うので、sim が落ちても
    # 待機は解ける。投入件数と完走件数を突き合わせないと、ランが欠けたり trace が
    # 途中で切れたりしても CSV の行数が静かに減るだけで気づけない。
    # .trace はシミュレータが起動直後に開くため件数だけでは足りず、
    # sim_worker_slurm.sh が正常終了時にだけ置く .done を完走の判定に使う。
    if [ "$NUM_DONE" -ne "$NUM_IN_BATCH" ] || [ "$NUM_TRACES" -ne "$NUM_IN_BATCH" ]; then
        MISSING_LOG="$LOG_DIR/missing_cursor${CURSOR}.txt"
        : > "$MISSING_LOG"
        for config in "${BATCH_FILES[@]}"; do
            base="${config%.config}"
            if [ ! -f "$base.done" ] || [ ! -f "$base.trace" ]; then
                echo "$config" >> "$MISSING_LOG"
            fi
        done
        echo "エラー: 投入 $NUM_IN_BATCH 件に対し、完走 $NUM_DONE 件 / .trace $NUM_TRACES 件しかありません。"
        echo "       失敗したランの一覧: $MISSING_LOG"
        echo "       ジョブのログ ($LOG_DIR/sim_*.err) を確認してください。"
        echo "       調査のため、このバッチの .config/.statconfig/.pos/.trace は削除せずに残します。"
        exit 1
    fi

    echo "解析対象の .trace ファイル数: $NUM_TRACES (全 $NUM_IN_BATCH 件が正常終了)"

    # PARSE_PARALLEL 個のジョブに分割するためのチャンクサイズを計算(切り上げ)
    CHUNK_SIZE=$(( (NUM_TRACES + PARSE_PARALLEL - 1) / PARSE_PARALLEL ))
    if [ "$CHUNK_SIZE" -lt 1 ]; then
        CHUNK_SIZE=1
    fi

    PARSE_JOB_IDS=()
    PARTIAL_CSVS=()
    MANIFEST_FILES=()
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
        MANIFEST_FILES+=("$MANIFEST_FILE")

        PARTIAL_CSV="$CMD_DIR/plots/partial_cursor${CURSOR}_chunk${CHUNK_IDX}.csv"
        PARTIAL_CSVS+=("$PARTIAL_CSV")

        # このチャンク専用のジョブを投入。結果はヘッダー無しの部分CSVに書き込む
        if ! PJID=$(sbatch --parsable --partition=ubuntu \
            --job-name="parse_c${CHUNK_IDX}" \
            --output="$LOG_DIR/parse_cursor${CURSOR}_chunk${CHUNK_IDX}.out" \
            --error="$LOG_DIR/parse_cursor${CURSOR}_chunk${CHUNK_IDX}.err" \
            --wrap="python3 '$SCRIPT_DIR/create_csv.py' '$CMD_DIR' '$NUM_DEVICE' '$PARTIAL_CSV' '$MANIFEST_FILE'"); then
            echo "エラー: 解析ジョブの投入に失敗しました (chunk ${CHUNK_IDX})。"
            exit 1
        fi
        if ! [[ "$PJID" =~ ^[0-9]+$ ]]; then
            echo "エラー: sbatch がジョブIDを返しませんでした (chunk ${CHUNK_IDX}, 出力: '$PJID')。"
            exit 1
        fi
        PARSE_JOB_IDS+=("$PJID")
    done

    PARSE_DEPS=$(IFS=,; echo "${PARSE_JOB_IDS[*]}")

    echo "${#PARSE_JOB_IDS[@]} 件の解析ジョブをSLURMに投入しました。完了を待機しています..."

    if ! sbatch --wait --partition=ubuntu --dependency=afterany:"${PARSE_DEPS}" \
        --job-name="wait_parse" --output=/dev/null --error=/dev/null --wrap="exit 0"; then
        echo "エラー: 解析完了の待機に失敗しました。部分CSVが未完成の可能性があるため中断します。"
        exit 1
    fi

    echo "並列解析が完了しました。結果をマージします..."

    # ---------- 3) 部分CSVをマージ ----------
    # 最終CSVがまだ存在しない場合は先にヘッダー行だけを書き込む
    if [ ! -f "$OUTPUT_CSV" ]; then
        python3 "$SCRIPT_DIR/create_csv.py" --header-only "$NUM_DEVICE" "$OUTPUT_CSV"
    fi

    # 先に全チャンクを検証してから追記する (2パス)。
    # 途中まで追記してから異常に気づくと、CSVに中途半端な行が残ったまま中断することになる。
    #
    # 存在チェックだけでは足りない: 解析ジョブが OOM や timeout で途中死しても
    # 書きかけの部分CSVは「存在する」ので、末尾が欠けた行ごとマージされてしまう。
    # manifest の行数 (担当した .trace の数) と部分CSVの行数が一致することを確認する。
    MERGE_OK=true
    for i in "${!PARTIAL_CSVS[@]}"; do
        pcsv="${PARTIAL_CSVS[$i]}"
        manifest="${MANIFEST_FILES[$i]}"
        if [ ! -f "$pcsv" ]; then
            echo "エラー: 部分CSVが見つかりません: $pcsv"
            MERGE_OK=false
            continue
        fi
        expected_rows=$(wc -l < "$manifest")
        actual_rows=$(wc -l < "$pcsv")
        if [ "$actual_rows" -ne "$expected_rows" ]; then
            echo "エラー: 部分CSVの行数が合いません: $pcsv ($actual_rows 行 / 期待 $expected_rows 行)"
            echo "       解析ジョブが途中で落ちた可能性があります: $LOG_DIR/parse_cursor${CURSOR}_*.err"
            MERGE_OK=false
        fi
    done

    if [ "$MERGE_OK" = true ]; then
        for pcsv in "${PARTIAL_CSVS[@]}"; do
            cat "$pcsv" >> "$OUTPUT_CSV"
        done

        # .pos は解析スクリプト(analyze_csv.py)が全バッチ終了後に距離計算のため
        # 参照するので、ここでは削除しない。参照された時点でそちらが削除する。
        echo "マージ成功！このバッチの .trace / .config / .stat / .statconfig / .done / 部分CSV / manifest を削除します..."
        rm -f "$CMD_DIR"/*.trace "$CMD_DIR"/*.config "$CMD_DIR"/*.stat "$CMD_DIR"/*.statconfig "$CMD_DIR"/*.done
        rm -f "${PARTIAL_CSVS[@]}"
        rm -f "$MANIFEST_DIR"/manifest_cursor${CURSOR}_*.txt
    else
        echo "エラー: 集計処理中に問題が発生しました。調査のためこのバッチのファイルは残します。"
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