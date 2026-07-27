#!/bin/bash
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1

# 引数として渡された .config ファイルのパスを受け取る
CONFIG_FILE=$1

# シミュレーションの実行
/opt/scenargie_simulator/source/driot/sim "$CONFIG_FILE"