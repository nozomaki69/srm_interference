#!/bin/bash
#SBATCH -o /home/arimoto/opt/scensim_env/scenargie_simulator/2.2/scenarios_linux/srm_interference/commandline/logs/%x_%j.out
#SBATCH -e /home/arimoto/opt/scensim_env/scenargie_simulator/2.2/scenarios_linux/srm_interference/commandline/logs/%x_%j.err

CMD_DIR=/home/arimoto/opt/scensim_env/scenargie_simulator/2.2/scenarios_linux/srm_interference/commandline
SCRIPT_DIR="$CMD_DIR/script"
CONFIG_DIR="$CMD_DIR"   # ← config があるディレクトリに応じて変更

# CSVを出力するディレクトリ
PLOTS_DIR="$CMD_DIR/plots"
mkdir -p "$PLOTS_DIR"

cd "$CONFIG_DIR" || {
  echo "ERROR: cd failed: $CONFIG_DIR"
  exit 1
}

JOB_NAME="sim_arimoto"
NUM_DEVICE=10  # デバイス数

# 過去の一時CSVや最終結果が残っていればリセット
rm -f "$PLOTS_DIR"/temp_*.csv
rm -f "$PLOTS_DIR"/simulation_results.csv

# -------------------------------
# .config が存在するかチェック
# -------------------------------
shopt -s nullglob
configs=(*.config)

echo "Current directory: $(pwd)"
echo "Number of config files: ${#configs[@]}"

if [ ${#configs[@]} -eq 0 ]; then
  echo "ERROR: .config ファイルが1件も見つかりません"
  exit 1
fi

# -------------------------------
# sbatch 投入
# -------------------------------
count=0
JOB_IDS=()

for config in "${configs[@]}"; do
  echo "Submitting: $config"
  
  # ジョブごとの専用一時CSVファイル名を定義
  TEMP_CSV="$PLOTS_DIR/temp_${config}.csv"
  
  # --parsable をつけてジョブIDだけを受け取るようにし、引数にNUM_DEVICEとTEMP_CSVを追加
  JOB_ID=$(sbatch --parsable --partition=ubuntu --job-name="$JOB_NAME" "$SCRIPT_DIR/run_one_sim.slurm.sh" "$(realpath "$config")" "$NUM_DEVICE" "$TEMP_CSV")
  JOB_IDS+=("$JOB_ID")
  count=$((count + 1))
done

echo "----------------------------------------"
echo "Total submitted jobs: $count"

# -------------------------------
# 全シミュレーション完了後にマージジョブを投入
# -------------------------------
if [ ${#JOB_IDS[@]} -gt 0 ]; then
    DEPENDENCIES=$(IFS=,; echo "${JOB_IDS[*]}")
    sbatch --partition=ubuntu --job-name="merge_csv" --dependency=afterany:${DEPENDENCIES} "$SCRIPT_DIR/merge_csv.slurm.sh" "$PLOTS_DIR"
    echo "すべてのシミュレーションジョブを投入しました。全完了後に自動でCSVがマージされます。"
fi