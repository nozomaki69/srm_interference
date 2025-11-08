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

# --- Configuration ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 修正: プロットの出力先をスクリプトの1つ上の階層に設定
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..")

# .posファイルはOUTPUT_DIRと同じ階層にあると仮定
POS_DIR = OUTPUT_DIR

# Regular expression to parse parameters from filenames
# Matches: driot_dist_{distance}km_bw_{bw1}and{bw2}khz_num_device{num_device}_seed{seed}.pos
FILENAME_RE = re.compile(
    r"interference_dist_([\d.]+)km_bw_([\d.]+?)and([\d.]+)khz_num_device(\d+)_seed(\d+)\.pos"
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

    dist_km = float(match.group(1))
    bw1_khz = float(match.group(2))
    bw2_khz = float(match.group(3))
    num_device = int(match.group(4))
    seed = int(match.group(5))

    plt.figure(figsize=(10, 8))

    # Plot coordinators as squares
    coord1_pos = positions.get(1)
    coord2_pos = positions.get(2)
    if coord1_pos:
        plt.plot(coord1_pos[0], coord1_pos[1], marker='s', markersize=10, color='b', label=f"Coordinator 1 ({bw1_khz} kHz)", linestyle='')
    if coord2_pos:
        plt.plot(coord2_pos[0], coord2_pos[1], marker='s', markersize=10, color='r', label=f"Coordinator 2 ({bw2_khz} kHz)", linestyle='')

    # Plot devices as circles
    device_group1_ids = range(3, num_device + 3)
    device_group2_ids = range(num_device + 3, 2 * num_device + 3)

    # Plot Group 1 devices (belonging to Coordinator 1)
    for node_id in device_group1_ids:
        pos = positions.get(node_id)
        if pos:
            label = f"Device (C1 Group)" if node_id == 3 else None
            plt.plot(pos[0], pos[1], marker='o', markersize=6, color='b', label=label, alpha=0.6)
            plt.text(
            pos[0], pos[1], 
            f'{node_id}', 
            fontsize=15, 
            # 決定したアライメントを適用
            verticalalignment= "bottom", 
            horizontalalignment= 'right'
            )

    # Plot Group 2 devices (belonging to Coordinator 2)
    for node_id in device_group2_ids:
        pos = positions.get(node_id)
        if pos:
            label = f"Device (C2 Group)" if node_id == num_device + 3 else None
            plt.plot(pos[0], pos[1], marker='o', markersize=6, color='r', label=label, alpha=0.6)
            plt.text(
            pos[0], pos[1], 
            f'{node_id}', 
            fontsize=15, 
            # 決定したアライメントを適用
            verticalalignment= "bottom", 
            horizontalalignment= 'right'
            )

    plt.xlabel("X (km)")
    plt.ylabel("Y (km)")
    plt.title(f"Node Positions for Dist={dist_km}km, BWs={bw1_khz} & {bw2_khz}kHz, Seed={seed}")
    plt.grid(True)
    plt.axis('equal')
    plt.xlim(-1.0, 3.5)
    plt.ylim(-1.5, 1.5)
    plt.legend()
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
        
        seed = int(match.group(5))
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