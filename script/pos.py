#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

# --- Configuration ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CMD_DIR = os.path.join(SCRIPT_DIR, "..")
POS_DIR = CMD_DIR
OUTPUT_DIR = os.path.join(CMD_DIR, "plots", "position_plots")

NUM_DEVICE = 50  # 1PANあたりのデバイス数 (interference_2pan_config.py の NUM_DEVICE と同じ)

# interference_2pan_config.py の MAXIMUM_COMMUNICATION_RANGE と同じ値 (km)
MAXIMUM_COMMUNICATION_RANGE_KM = {
    0: 1.4,
    1: 1.2,
    2: 1.0,
    3: 1.4,
    4: 1.2,
    5: 1.0,
}

# interference_2pan_config.py の CHANNELS と同じ値 (帯域ラベル表示・ディレクトリ分け用)
CHANNEL_KBPS = {0: 50, 1: 100, 2: 200, 3: 50, 4: 100, 5: 200}

# offered_load は座標に影響しないので、個別プロットはこの組み合わせだけに絞る
REPRESENTATIVE_PAN1_OFFLOAD = 10
REPRESENTATIVE_PAN2_OFFLOAD = 10

FILENAME_RE = re.compile(
    r"(interf|no_interf)_dist_(\d+)m_channel_(\d+)_vs_(\d+)"
    r"_pan1_(\d+)_pan2_(\d+)_seed(\d+)\.pos$"
)


def parse_filename(filename):
    """.pos ファイル名からパラメータを抽出する。マッチしなければ None。"""
    m = FILENAME_RE.match(filename)
    if not m:
        return None
    interf_label, distance, pan1_ch, pan2_ch, pan1_offload, pan2_offload, seed = m.groups()
    return {
        "interf_label": interf_label,
        "distance": int(distance),
        "pan1_ch": int(pan1_ch),
        "pan2_ch": int(pan2_ch),
        "pan1_offload": int(pan1_offload),
        "pan2_offload": int(pan2_offload),
        "seed": int(seed),
    }


def bandwidth_label(pan1_ch, pan2_ch):
    """(pan1_ch, pan2_ch) から '50vs100' のような帯域ラベルを作る (analyze_csv.py と同じ基準)"""
    k1, k2 = sorted((CHANNEL_KBPS[pan1_ch], CHANNEL_KBPS[pan2_ch]))
    return f"{k1}vs{k2}"


def parse_pos_file(filepath):
    """各ファイルの座標を読み込む(km単位)"""
    positions = {}
    with open(filepath, "r") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 4 and parts[1] == "0":
                try:
                    node_id = int(parts[0])
                    x = float(parts[2]) / 1000.0  # m -> km
                    y = float(parts[3]) / 1000.0  # m -> km
                    positions[node_id] = (x, y)
                except ValueError:
                    continue
    return positions


def plot_positions(positions, meta, out_dir):
    """個別seedのプロット(デバイス配置 + PANカバレッジ円)"""
    pan1_radius = MAXIMUM_COMMUNICATION_RANGE_KM[meta["pan1_ch"]]
    pan2_radius = MAXIMUM_COMMUNICATION_RANGE_KM[meta["pan2_ch"]]

    fig, ax = plt.subplots(figsize=(10, 10))

    coord1 = positions.get(1)
    coord2 = positions.get(2)

    if coord1:
        ax.plot(coord1[0], coord1[1], 'sb', markersize=10,
                 label=f"PAN1 Coordinator (ch{meta['pan1_ch']})")
        ax.add_patch(Circle(coord1, pan1_radius, color='blue', alpha=0.05, fill=True))

    if coord2:
        ax.plot(coord2[0], coord2[1], 'sr', markersize=10,
                 label=f"PAN2 Coordinator (ch{meta['pan2_ch']})")
        ax.add_patch(Circle(coord2, pan2_radius, color='red', alpha=0.05, fill=True))

    for node_id, (x, y) in positions.items():
        if node_id <= 2:
            continue
        color = 'blue' if 3 <= node_id < NUM_DEVICE + 3 else 'red'
        ax.plot(x, y, 'o', color=color, markersize=8, alpha=0.4, linestyle='')

    ax.set_aspect('equal', adjustable='box')
    plt.xlabel("x [km]", fontsize=25)
    plt.ylabel("y [km]", fontsize=25)
    plt.xticks(fontsize=25)
    plt.yticks(fontsize=25)
    plt.xlim(-2, 3.5)
    plt.ylim(-1.5, 1.5)
    leg = plt.legend(loc="lower right", fontsize=16)
    leg.get_frame().set_linewidth(1.8)
    plt.tick_params(axis="both", width=3.0, which="major", length=20)
    plt.tight_layout()

    os.makedirs(out_dir, exist_ok=True)
    fname = f"{meta['interf_label']}_ch{meta['pan1_ch']}vs{meta['pan2_ch']}_seed{meta['seed']}.pdf"
    plt.savefig(os.path.join(out_dir, fname), bbox_inches='tight', pad_inches=0.05)
    plt.close()


def plot_centroids(stats, pan1_ch, pan2_ch, out_dir):
    """1つのチャネルペア内で、全seedの重心をプロット"""
    pan1_radius = MAXIMUM_COMMUNICATION_RANGE_KM[pan1_ch]
    pan2_radius = MAXIMUM_COMMUNICATION_RANGE_KM[pan2_ch]

    fig, ax = plt.subplots(figsize=(10, 10))

    for node_id, data in stats.items():
        mean_x = data['sum_x'] / data['count']
        mean_y = data['sum_y'] / data['count']

        if node_id == 1:
            ax.plot(mean_x, mean_y, marker='s', markersize=12, color='b', label="Coord1 Mean", linestyle='')
            ax.add_patch(Circle((mean_x, mean_y), pan1_radius, color='blue', alpha=0.03, fill=True))
        elif node_id == 2:
            ax.plot(mean_x, mean_y, marker='s', markersize=12, color='r', label="Coord2 Mean", linestyle='')
            ax.add_patch(Circle((mean_x, mean_y), pan2_radius, color='red', alpha=0.03, fill=True))
        else:
            color = 'blue' if 3 <= node_id < NUM_DEVICE + 3 else 'red'
            ax.plot(mean_x, mean_y, marker='x', markersize=10, color=color, mew=3, linestyle='')

    ax.set_aspect('equal', adjustable='box')
    plt.title(f"{CHANNEL_KBPS[pan1_ch]} vs. {CHANNEL_KBPS[pan2_ch]}", fontsize=20)
    plt.xlabel("x [km]", fontsize=20)
    plt.ylabel("y [km]", fontsize=20)
    plt.xlim(-2, 3.5)
    plt.ylim(-1.5, 1.5)
    plt.tick_params(axis='both', labelsize=18)

    os.makedirs(out_dir, exist_ok=True)
    output_path = os.path.join(out_dir, f"centroids_ch{pan1_ch}vs{pan2_ch}.pdf")
    plt.savefig(output_path, bbox_inches='tight', pad_inches=0.05)
    plt.close()
    print(f"Centroid plot saved to: {output_path}")


def main():
    print("--- Starting Position Plotting ---")
    if not os.path.isdir(POS_DIR):
        print(f"Warning: {POS_DIR} not found.")
        return

    all_files = [f for f in os.listdir(POS_DIR) if f.endswith(".pos")]
    print(f"Found {len(all_files)} .pos files in {POS_DIR}")

    # チャネルペアごとに重心集計用の辞書を分ける
    # { (pan1_ch, pan2_ch): {node_id: {'sum_x':.., 'sum_y':.., 'count':..}} }
    stats_by_channel_pair = defaultdict(dict)
    plotted = 0
    used_files = 0

    for pos_file in all_files:
        meta = parse_filename(pos_file)
        if meta is None:
            continue

        # 座標は offered_load に依存しないので、代表的な1組だけ扱う
        # (ここでフィルタしておくことで、不要な .pos の読み込み自体を避ける)
        if (meta["pan1_offload"] != REPRESENTATIVE_PAN1_OFFLOAD
                or meta["pan2_offload"] != REPRESENTATIVE_PAN2_OFFLOAD):
            continue

        filepath = os.path.join(POS_DIR, pos_file)
        positions = parse_pos_file(filepath)
        if not positions:
            continue
        used_files += 1

        # 1. 個別プロット
        bw_dir = os.path.join(
            OUTPUT_DIR,
            bandwidth_label(meta["pan1_ch"], meta["pan2_ch"]),
            f"{meta['distance']}m",
            meta["interf_label"],
        )
        plot_positions(positions, meta, bw_dir)
        plotted += 1

        # 2. 重心データの集計(チャネルペアごと)
        key = (meta["pan1_ch"], meta["pan2_ch"])
        chan_stats = stats_by_channel_pair[key]
        for node_id, (x, y) in positions.items():
            if node_id not in chan_stats:
                chan_stats[node_id] = {'sum_x': 0.0, 'sum_y': 0.0, 'count': 0}
            chan_stats[node_id]['sum_x'] += x
            chan_stats[node_id]['sum_y'] += y
            chan_stats[node_id]['count'] += 1

    print(
        f"Used {used_files} .pos files "
        f"(pan1_offload={REPRESENTATIVE_PAN1_OFFLOAD}, pan2_offload={REPRESENTATIVE_PAN2_OFFLOAD}), "
        f"Plotted {plotted} individual position plots"
    )

    # 全seedの読み込みが終わったら、チャネルペアごとに重心を描画
    for (pan1_ch, pan2_ch), chan_stats in stats_by_channel_pair.items():
        if not chan_stats:
            continue
        bw_dir = os.path.join(OUTPUT_DIR, bandwidth_label(pan1_ch, pan2_ch))
        plot_centroids(chan_stats, pan1_ch, pan2_ch, bw_dir)

    print("--- Script finished successfully. ---")


if __name__ == "__main__":
    main()