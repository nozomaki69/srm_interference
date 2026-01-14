#!/bin/bash
#SBATCH -J sim_test
#SBATCH -t 01:00:00
#SBATCH -c 1
#SBATCH --mem=2G

# ====== 引数チェック ======
if [ $# -ne 1 ]; then
  echo "Usage: sbatch run_one_sim.slurm <config file>"
  exit 1
fi

CONFIG=$1

# ====== ディレクトリ設定 ======
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
CMD_DIR=$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)
cd "$CMD_DIR" || exit

# ====== 実行 ======
echo "対象ディレクトリ: $CMD_DIR"
echo "Running simulation with config: $CONFIG"
./sim "$CONFIG"
