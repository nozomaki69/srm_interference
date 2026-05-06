#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle

# --- Configuration ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..")
POS_DIR = OUTPUT_DIR
num_device = 50 # 1PANあたりのデバイス数（合計120台ならここを調整）

FILENAME_RE = re.compile(
    r"interf_coord_dist_1500m_off_load_pan1_0.1_pan2_([\d.]+)_seed(\d+).pos"
)

def parse_pos_file(filepath):
    """各ファイルの座標を読み込む"""
    positions = {}
    with open(filepath, "r") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 4:
                node_id = int(parts[0])
                if parts[1] == "0":
                    x = float(parts[2]) / 1000.0  # m to km
                    y = float(parts[3]) / 1000.0  # m to km
                    positions[node_id] = (x, y)
    return positions

def plot_positions(positions, filename):
    """個別seedのプロット"""
    match = FILENAME_RE.match(filename)
    if not match: return
    seed = int(match.group(2))

    fig, ax = plt.subplots(figsize=(10, 10))

    coord1 = positions.get(1)
    coord2 = positions.get(2)

    # PAN1範囲 (1.4km)
    if coord1:
        ax.plot(coord1[0], coord1[1], 'sb', markersize=10, label="PAN1 Coordinator")
        ax.add_patch(Circle((coord1[0], coord1[1]), 1.4, color='blue', alpha=0.05, fill=True))

    # PAN2範囲 (1.0km)
    if coord2:
        ax.plot(coord2[0], coord2[1], 'sr', markersize=10, label="PAN2 Coordinator")
        ax.add_patch(Circle((coord2[0], coord2[1]), 1.0, color='red', alpha=0.05, fill=True))

    # デバイスプロット
    for node_id, (x, y) in positions.items():
        if node_id <= 2: continue
        color = 'blue' if 3 <= node_id < num_device + 3 else 'red'
        ax.plot(x, y, 'o', color=color, markersize=8, alpha=0.4, linestyle='')

    ax.set_aspect('equal', adjustable='box')
    plt.xlabel("x [km]", fontsize=25)
    plt.ylabel("y [km]", fontsize=25)
    plt.xticks(fontsize= 25)
    plt.yticks(fontsize= 25)
    leg = plt.legend(loc="lower right", fontsize=20)
    leg.get_frame().set_linewidth(1.8)
    plt.tick_params(axis="both",width=3.0, which="major", length=20)
    
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, filename.replace('.pos', f"_seed{seed}.pdf")), bbox_inches='tight', pad_inches=0.05)

    plt.close()

def plot_centroids(stats):
    """全seedの重心をプロット（視認性向上版）"""
    fig, ax = plt.subplots(figsize=(10, 10))
    
    for node_id, data in stats.items():
        mean_x = data['sum_x'] / data['count']
        mean_y = data['sum_y'] / data['count']

        if node_id == 1:
            # コーディネータはデバイスプロットと同様に青い四角
            ax.plot(mean_x, mean_y, marker='s', markersize=12, color='b', label="Coord1 Mean", linestyle='')
            # 範囲を分かりやすくするため薄い塗りつぶしも追加
            ax.add_patch(Circle((mean_x, mean_y), 1.4, color='blue', alpha=0.03, fill=True))
        elif node_id == 2:
            # コーディネータはデバイスプロットと同様に赤い四角
            ax.plot(mean_x, mean_y, marker='s', markersize=12, color='r', label="Coord2 Mean", linestyle='')
            ax.add_patch(Circle((mean_x, mean_y), 1.0, color='red', alpha=0.03, fill=True))
        else:
            # デバイスの重心を「ばつ印」でプロット
            # サイズを大きく(10)、線を太く(mew=3)して、デバイスプロットに近い存在感にする
            color = 'blue' if 3 <= node_id < num_device + 3 else 'red'
            ax.plot(mean_x, mean_y, marker='x', markersize=10, color=color, mew=3, linestyle='')

    # 軸の設定
    ax.set_aspect('equal', adjustable='box')
    plt.title("Device Centroids across All Seeds", fontsize=20)
    plt.xlabel("x [m]", fontsize=20)
    plt.ylabel("y [km]", fontsize=20)
    
    # 軸の範囲が自動で小さくなりすぎる場合は、ここで余裕を持たせる設定も可能
    # ax.autoscale(enable=True, tight=False)

    plt.tick_params(axis='both', labelsize=18)
    #plt.grid(True, linestyle=':', alpha=0.6)
    
    output_path = os.path.join(OUTPUT_DIR, "all_seeds_centroids.pdf")
    plt.savefig(output_path)
    plt.close()
    print(f"Centroid plot (enhanced visibility) saved to: {output_path}")

def main():
    print("--- Starting Position Plotting ---")
    pos_files = [f for f in os.listdir(POS_DIR) if f.endswith(".pos")]
    
    # 重心計算用の集計辞書
    # {node_id: {'sum_x': 0.0, 'sum_y': 0.0, 'count': 0}}
    stats = {}

    for pos_file in pos_files:
        match = FILENAME_RE.match(pos_file)
        if not match: continue
        
        filepath = os.path.join(POS_DIR, pos_file)
        positions = parse_pos_file(filepath)
        
        if positions:
            # 1. 個別プロット
            plot_positions(positions, pos_file)
            
            # 2. 重心データの集計（読み込みながら加算）
            for node_id, (x, y) in positions.items():
                if node_id not in stats:
                    stats[node_id] = {'sum_x': 0.0, 'sum_y': 0.0, 'count': 0}
                stats[node_id]['sum_x'] += x
                stats[node_id]['sum_y'] += y
                stats[node_id]['count'] += 1

    # 全ファイルの読み込みが終わったら重心を描画
    if stats:
        plot_centroids(stats)

    print("--- Script finished successfully. ---")

if __name__ == "__main__":
    main()