#!/bin/bash
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1

# 引数として渡された .config ファイルのパスを受け取る
CONFIG_FILE=$1

# シミュレーションの実行
/home/arimoto/opt/scensim_env/scenargie_simulator/2.2/scenarios_linux/srm_interference/commandline "$CONFIG_FILE"