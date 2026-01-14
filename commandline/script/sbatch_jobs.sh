#!/bin/bash

CMD_DIR=/home/arimoto/opt/scensim_env/scenargie_simulator/2.2/scenarios_linux/srm_interference/commandline
SCRIPT_DIR="$CMD_DIR/script"

cd "$CMD_DIR" || exit 1

for config in *.config; do
  [ -e "$config" ] || continue
  sbatch "$SCRIPT_DIR/run_one_sim.slurm" "$config"
  echo "submitted: $config"
done

echo "全てのジョブを投入しました"
