#!/bin/bash
#SBATCH ... (各種設定)

CONFIG=$1  # ここで引数を受け取っているか？
./sim "$CONFIG"