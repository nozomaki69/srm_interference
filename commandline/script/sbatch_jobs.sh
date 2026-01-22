#!/bin/bash
#SBATCH -o /home/arimoto/opt/scensim_env/scenargie_simulator/2.2/scenarios_linux/srm_interference/commandline/logs/%x_%j.out
#SBATCH -e /home/arimoto/opt/scensim_env/scenargie_simulator/2.2/scenarios_linux/srm_interference/commandline/logs/%x_%j.err

CMD_DIR=/home/arimoto/opt/scensim_env/scenargie_simulator/2.2/scenarios_linux/srm_interference/commandline
SCRIPT_DIR="$CMD_DIR/script"

cd "$CMD_DIR" || exit 1

count=0

for config in *.config; do
  # *.config が1つも無いときの対策
  [ -e "$config" ] || continue

  sbatch run_one_sim.slurm "$(SCRIPT_DIR "$config")"
  echo "submitted: $config"

  count=$((count + 1))
done

echo "----------------------------------------"
echo "Total submitted jobs: $count"

echo "全てのジョブを投入しました"
