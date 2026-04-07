#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simulation Position Plotting Script
This script reads .pos files, plots node positions, and saves the plots.
"""

import os
import re
import sys
import matplotlib.pyplot as plt
import numpy as np
import matplotlib.ticker as ticker
from matplotlib.ticker import MultipleLocator

# --- Configuration ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 修正: プロットの出力先をスクリプトの1つ上の階層に設定
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..")

# .posファイルはOUTPUT_DIRと同じ階層にあると仮定
POS_DIR = OUTPUT_DIR
num_device = 12

# Regular expression to parse parameters from filenames
# Matches: driot_dist_{distance}m_bw_{bw1}and{bw2}khz_num_device{num_device}_seed{seed}.pos
FILENAME_RE = re.compile(
    r"interf_coord_dist_([\d.]+)m_off_load([\d.]+)_seed(\d+)\.pos"
)

def parse_pos_file(filepath):
    """Parses a single .pos file to extract node positions."""
    positions = {}
    with open(filepath, "r") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 4:
                node_id = int(parts[0])
                # 1行目の座標のみを抽出
                if parts[1] == "0":
                    x = float(parts[2]) / 1000.0  # meters to kilometers
                    y = float(parts[3]) / 1000.0  # meters to kilometers
                    positions[node_id] = (x, y)
    return positions

def plot_positions(positions, filename):
    """
    Plots node positions with different markers for coordinators and devices.
    """
    match = FILENAME_RE.match(filename)
    if not match:
        print(f"Skipping file with unexpected name format: {filename}")
        return

    dist_m = float(match.group(1))
    seed = int(match.group(3))

    plt.figure(figsize=(10, 8))

    # Plot coordinators as squares
    coord1_pos = positions.get(1)
    coord2_pos = positions.get(2)
    if coord1_pos:
        plt.plot(coord1_pos[0], coord1_pos[1], marker='s', markersize=10, color='b', label=f"Coordinator(PAN1)", linestyle='')
    if coord2_pos:
        plt.plot(coord2_pos[0], coord2_pos[1], marker='s', markersize=10, color='r', label=f"Coordinator(PAN2)", linestyle='')

    # Plot devices as circles
    device_group1_ids = range(3, num_device + 3)
    device_group2_ids = range(num_device + 3, 2 * num_device + 3)

    # Plot Group 1 devices (belonging to Coordinator 1)
    for node_id in device_group1_ids:
        pos = positions.get(node_id)
        if pos:
            label = f"Device(PAN1)" if node_id == 3 else None
            plt.plot(pos[0], pos[1], marker='o', markersize=10, color='b', label=label, alpha=0.6)
            # plt.text(
            # pos[0], pos[1], 
            # f'{node_id}', 
            # fontsize=15, 
            # # 決定したアライメントを適用
            # #verticalalignment= "bottom", 
            # #horizontalalignment= 'right'
            # )

    # Plot Group 2 devices (belonging to Coordinator 2)
    for node_id in device_group2_ids:
        pos = positions.get(node_id)
        if pos:
            label = f"Device(PAN2)" if node_id == num_device + 3 else None
            plt.plot(pos[0], pos[1], marker='o', markersize=10, color='r', label=label, alpha=0.6)
            # plt.text(
            # pos[0], pos[1], 
            # f'{node_id}', 
            # fontsize=15, 
            # # 決定したアライメントを適用
            # #verticalalignment= "bottom", 
            # #horizontalalignment= 'right'
            # )
        
    #plt.grid(True, which='major', linestyle='--', linewidth=0.8, color='gray', alpha=0.7)
    plt.xlabel("X (km)", fontsize=20)
    plt.ylabel("Y (km)", fontsize=20)
    #plt.title(f"Node Positions for Dist={dist_m}m, BWs={bw1_khz} & {bw2_khz}kHz", fontsize=20)
    plt.tick_params(axis='both', labelsize=18)
    #plt.axis('equal')
    plt.xlim(-0.60, 1.56)
    plt.ylim(-0.84, 0.84)
    xmin, xmax = -0.60, 1.56
    ymin, ymax = -0.84, 0.84
    # 240 m = 0.24 km
    xticks = np.arange(xmin, xmax + 0.24, 0.24)
    yticks = np.arange(ymin, ymax + 0.24, 0.24)
    ax = plt.gca()
    ax.set_xticks(xticks)
    ax.set_yticks(yticks)

    ax.grid(True, axis='x', linewidth=0.8)
    ax.grid(True, axis='y', linewidth=0.8)

    plt.grid(True)
    plt.tight_layout()
    
    plt.legend(fontsize=10)
    output_filename = os.path.join(OUTPUT_DIR, filename.replace('.pos', f"_seed{seed}.png"))
    plt.savefig(output_filename)
    plt.close()
    print(f"Plot saved to: {output_filename}")


def main():
    """Main execution function to find and process all .pos files."""
    print("--- Starting Position Plotting ---")

    if not os.path.isdir(POS_DIR):
        print(f"Error: Position directory not found at '{POS_DIR}'", file=sys.stderr)
        sys.exit(1)

    pos_files = [f for f in os.listdir(POS_DIR) if f.endswith(".pos")]
    if not pos_files:
        print("Warning: No .pos files found. Nothing to plot.", file=sys.stderr)
        return

    print(f"Found {len(pos_files)} position files to process.")
    # plotsディレクトリを作成しないように、os.makedirsを削除
    
    for pos_file in pos_files:
        match = FILENAME_RE.match(pos_file)
        if not match:
            print(f"Skipping file with unexpected name format: {pos_file}"); continue
        
        seed = int(match.group(3))
        if seed == 0:
            filepath = os.path.join(POS_DIR, pos_file)
            positions = parse_pos_file(filepath)
            if positions:
                plot_positions(positions, pos_file)
        else:
            print(f"Skipping file: {pos_file} (seed != 0)")

    print("\n--- Script finished successfully. ---")


if __name__ == "__main__":
    main()