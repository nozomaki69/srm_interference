#!/bin/bash
#SBATCH -J stats_job
#SBATCH -c 32             # 【重要】1タスクあたりのコア数（30コア使いたい場合）

python3 ./script/interference_2pan_plot_results.py