#!/bin/bash
#SBATCH -J stats_job
#SBATCH -c 32      

python3 ./script/interference_2pan_plot_results.py
