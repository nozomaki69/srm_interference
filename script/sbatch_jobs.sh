#!/bin/bash
#SBATCH -o /home/arimoto/opt/scensim_env/scenargie_simulator/2.2/scenarios_linux/srm_interference/commandline/logs/%x_%j.out
#SBATCH -e /home/arimoto/opt/scensim_env/scenargie_simulator/2.2/scenarios_linux/srm_interference/commandline/logs/%x_%j.err

CMD_DIR=/home/arimoto/opt/scensim_env/scenargie_simulator/2.2/scenarios_linux/srm_interference/commandline
SCRIPT_DIR="$CMD_DIR/script"
CONFIG_DIR="$CMD_DIR"   # ← config があるディレクトリに応じて変更

cd "$CONFIG_DIR" || {
  echo "ERROR: cd failed: $CONFIG_DIR"
  exit 1
}
JOB_NAME="sim_arimoto"
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

for config in "${configs[@]}"; do
  echo "Submitting: $config"
<<<<<<< HEAD
  sbatch --partition="ubuntu" --job-name="$JOB_NAME" "$SCRIPT_DIR/run_one_sim.slurm.sh" "$(realpath "$config")"
=======
  sbatch --partition=ubuntu --job-name="$JOB_NAME" "$SCRIPT_DIR/run_one_sim.slurm.sh" "$(realpath "$config")"
>>>>>>> 3df9b3284d3397f013c998960b60a8fa03560384
  count=$((count + 1))
done

echo "----------------------------------------"
echo "Total submitted jobs: $count"
echo "全てのシミュレーションのジョブを投入しました"
