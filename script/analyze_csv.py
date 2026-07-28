#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
simulation_results.csv を読み込み、PAN1_CH / PAN2_CH / Distance / PAN1_Offload /
PAN2_Offload の組み合わせ（条件）ごとに Seed をまたいで集計し、
PER (Packet Error Rate) と RSSI、距離（.pos ファイルから算出）に関する
統計プロットを出力する。

出力先: plots/{帯域の組み合わせ}/{距離}m/{interf|no_interf}/
"""

import os
import re
import csv
from collections import defaultdict

import numpy as np
import pandas as pd
import scipy.stats as stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick

# ============================================================
# 設定
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATS_DIR = os.path.join(SCRIPT_DIR, "..")                         # .pos ファイルの場所
CSV_FILE = os.path.join(SCRIPT_DIR, "..", "plots", "simulation_results.csv")
PLOT_BASE_DIR = os.path.join(SCRIPT_DIR, "..", "plots")

NUM_DEVICE = 50
PAN1_DEVS = list(range(3, 3 + NUM_DEVICE))          # 3..12
PAN2_DEVS = list(range(3 + NUM_DEVICE, 3 + 2 * NUM_DEVICE))  # 13..22
RSSI_START_IDX = 10 + 8 * NUM_DEVICE                # 90

FONT_SIZE = 45

# チャネル番号 -> 帯域(kbps)
CHANNEL_KBPS = {0: 50, 1: 100, 2: 200, 3: 50, 4: 100, 5: 200}

# 干渉あり / なし の (PAN1_CH, PAN2_CH) 組み合わせ（順不同。内部でソートして照合する）
INTERF_PAIRS = {(0, 0), (0, 1), (0, 2), (1, 1), (1, 2), (2, 2)}
NO_INTERF_PAIRS = {(0, 3), (0, 4), (0, 5), (1, 4), (1, 5), (2, 5)}


# ============================================================
# ユーティリティ
# ============================================================
def get_interf_label(pan1_ch, pan2_ch):
    """(PAN1_CH, PAN2_CH) から 'interf' / 'no_interf' / None を判定する"""
    key = tuple(sorted((pan1_ch, pan2_ch)))
    if key in INTERF_PAIRS:
        return "interf"
    if key in NO_INTERF_PAIRS:
        return "no_interf"
    return None


def get_bandwidth_label(pan1_ch, pan2_ch):
    """(PAN1_CH, PAN2_CH) から '50vs100' のような帯域ラベルを作る"""
    k1, k2 = sorted((CHANNEL_KBPS[pan1_ch], CHANNEL_KBPS[pan2_ch]))
    return f"{k1}vs{k2}"


def pos_filename(pan1_ch, pan2_ch, distance, pan1_offload, pan2_offload, seed):
    return (
        f"interf_dist_{distance}m_channel_{pan1_ch}_vs_{pan2_ch}"
        f"_pan1_{pan1_offload}_pan2_{pan2_offload}_seed{seed}.pos"
    )


def parse_pos_file(filepath):
    """.pos ファイルを解析し、ノードの初期座標（メートル単位）を抽出する。"""
    positions = {}
    with open(filepath, "r") as f:
        for line in f:
            parts = line.split()
            # 1行目 (時間 = 0) の座標のみを抽出
            if len(parts) > 4 and parts[1] == "0":
                try:
                    node_id = int(parts[0])
                    x_m = float(parts[2])
                    y_m = float(parts[3])
                    positions[node_id] = (x_m, y_m)
                except ValueError:
                    continue
    return positions


# ============================================================
# CSV 読み込み & 集計
# ============================================================
def make_empty_condition_data():
    return {
        "pan1_ul": [], "pan1_dl": [], "pan1_rssi": [], "pan1_dist": [],
        "pan2_ul": [], "pan2_dl": [], "pan2_rssi": [], "pan2_dist": [],
    }


def load_and_aggregate(csv_file, stats_dir):
    """
    CSV を読み込み、(PAN1_CH, PAN2_CH, Distance, PAN1_Offload, PAN2_Offload) を
    条件キーとして、全 Seed x 全デバイス分の UL/DL PER・RSSI・(.pos から算出した)
    距離を1つの配列に蓄積する。
    """
    data = defaultdict(make_empty_condition_data)
    pos_cache = {}  # 同じ .pos ファイルを何度も読まないようにキャッシュ

    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {name: i for i, name in enumerate(header)}

        for row in reader:
            int_parts = [int(float(x)) for x in row[:RSSI_START_IDX]]
            float_parts = [float(x) for x in row[RSSI_START_IDX:]]
            r = int_parts + float_parts

            pan1_ch = r[idx["PAN1_CH"]]
            pan2_ch = r[idx["PAN2_CH"]]
            distance = r[idx["Distance"]]
            pan1_offload = r[idx["PAN1_Offload"]]
            pan2_offload = r[idx["PAN2_Offload"]]
            seed = r[idx["Seed"]]

            condition_key = (pan1_ch, pan2_ch, distance, pan1_offload, pan2_offload)

            # --- .pos ファイルから座標を取得（seed ごとに個別ファイル） ---
            fname = pos_filename(pan1_ch, pan2_ch, distance, pan1_offload, pan2_offload, seed)
            if fname not in pos_cache:
                fpath = os.path.join(stats_dir, fname)
                if os.path.isfile(fpath):
                    pos_cache[fname] = parse_pos_file(fpath)
                else:
                    print(f"Warning: pos file not found: {fpath}")
                    pos_cache[fname] = None
            positions = pos_cache[fname]

            entry = data[condition_key]

            # --- PAN1（座標基準ノードは id=2） ---
            for dev in PAN1_DEVS:
                dev_deq = r[idx[f"PAN1_Dev{dev}_Deq"]]
                pc_rx = r[idx[f"PAN1_PC_Rx_from_Dev{dev}"]]
                ul_per = 1.0 - (pc_rx / dev_deq) if dev_deq > 0 else 0.0

                pc_deq = r[idx[f"PAN1_PC_Deq_to_Dev{dev}"]]
                dev_rx = r[idx[f"PAN1_Dev{dev}_Rx_from_PC"]]
                dl_per = 1.0 - (dev_rx / pc_deq) if pc_deq > 0 else 0.0

                rssi = r[idx[f"PAN1_PC_RSSI_Avg_from_Dev{dev}"]]

                entry["pan1_ul"].append(ul_per)
                entry["pan1_dl"].append(dl_per)
                entry["pan1_rssi"].append(rssi)
                entry["pan1_dist"].append(_calc_distance(positions, dev, 2))

            # --- PAN2（座標基準ノードは id=1） ---
            for dev in PAN2_DEVS:
                dev_deq = r[idx[f"PAN2_Dev{dev}_Deq"]]
                pc_rx = r[idx[f"PAN2_PC_Rx_from_Dev{dev}"]]
                ul_per = 1.0 - (pc_rx / dev_deq) if dev_deq > 0 else 0.0

                pc_deq = r[idx[f"PAN2_PC_Deq_to_Dev{dev}"]]
                dev_rx = r[idx[f"PAN2_Dev{dev}_Rx_from_PC"]]
                dl_per = 1.0 - (dev_rx / pc_deq) if pc_deq > 0 else 0.0

                rssi = r[idx[f"PAN2_PC_RSSI_Avg_from_Dev{dev}"]]

                entry["pan2_ul"].append(ul_per)
                entry["pan2_dl"].append(dl_per)
                entry["pan2_rssi"].append(rssi)
                entry["pan2_dist"].append(_calc_distance(positions, dev, 1))

    return data


def _calc_distance(positions, dev_id, ref_id):
    """positions が無い、あるいは該当ノードが無い場合は NaN を返す。"""
    if positions is None or dev_id not in positions or ref_id not in positions:
        return np.nan
    dx = positions[dev_id][0] - positions[ref_id][0]
    dy = positions[dev_id][1] - positions[ref_id][1]
    return float(np.sqrt(dx ** 2 + dy ** 2))


# ============================================================
# プロット関数（旧コードから移植）
# ============================================================
def plot_delta_per_analysis(delta_per, rssi_list, filename, plot_dir):
    rssi_list = np.array(rssi_list, dtype=float).flatten()
    delta_per = np.array(delta_per, dtype=float).flatten()
    valid_mask = rssi_list != 0
    delta_per_filtered = delta_per[valid_mask]
    rssi_filtered = rssi_list[valid_mask]

    bins = np.arange(-50, -111, -10)
    bin_data_list = []
    labels = []

    for i in range(len(bins) - 1):
        upper = bins[i]
        lower = bins[i + 1]
        in_bin_mask = (rssi_filtered > lower) & (rssi_filtered <= upper)
        bin_data = delta_per_filtered[in_bin_mask]
        labels.append(f"[{upper}, {lower})")
        bin_data_list.append(bin_data if len(bin_data) > 0 else [])

    fig, ax = plt.subplots(figsize=(10, 10))
    plot_indices = [i for i, d in enumerate(bin_data_list) if len(d) > 0]
    ax.tick_params(axis="both", labelsize=FONT_SIZE - 20, width=3.0, which="major", length=20)
    ax.xaxis.set_major_formatter(mtick.StrMethodFormatter('{x:,.0f}'))
    ax.xaxis.set_major_locator(mtick.MultipleLocator(1000))

    if plot_indices:
        plt.boxplot([bin_data_list[i] for i in plot_indices],
                     labels=[labels[i] for i in plot_indices])
    plt.ylim(-1.0, 1.0)
    plt.grid(True, axis='y', linestyle='--', alpha=0.7)

    os.makedirs(plot_dir, exist_ok=True)
    plt.savefig(os.path.join(plot_dir, filename), bbox_inches='tight', pad_inches=0.05)
    plt.close()


def plot_variance_distribution_boxplot(delta_per, rssi_list, filename, plot_dir):
    rssi_list = np.array(rssi_list, dtype=float).flatten()
    delta_per = np.array(delta_per, dtype=float).flatten()

    num_seeds = len(rssi_list) // NUM_DEVICE
    bins = np.arange(0, -121, -10)

    variances_per_bin = [[] for _ in range(len(bins) - 1)]
    bin_labels = [f"[{bins[i]}, {bins[i + 1]})" for i in range(len(bins) - 1)]

    for s in range(num_seeds):
        start_idx = s * NUM_DEVICE
        end_idx = (s + 1) * NUM_DEVICE

        rssi_seed = rssi_list[start_idx:end_idx]
        delta_seed = delta_per[start_idx:end_idx]

        valid = rssi_seed != 0
        r_v = rssi_seed[valid]
        d_v = delta_seed[valid]

        for b in range(len(bins) - 1):
            upper = bins[b]
            lower = bins[b + 1]
            mask = (r_v > lower) & (r_v <= upper)
            bin_values = d_v[mask]
            if len(bin_values) > 1:
                variances_per_bin[b].append(np.var(bin_values))

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.tick_params(axis="both", labelsize=FONT_SIZE - 20, width=3.0, which="major", length=20)

    plot_data = []
    plot_labels = []
    for d, label in zip(variances_per_bin, bin_labels):
        if len(d) > 0:
            plot_data.append(d)
            plot_labels.append(label)

    if plot_data:
        plt.boxplot(plot_data, labels=plot_labels)

    plt.ylim(0, 0.4)
    plt.grid(True, axis='y', linestyle='--', alpha=0.7)

    os.makedirs(plot_dir, exist_ok=True)
    plt.savefig(os.path.join(plot_dir, filename), bbox_inches='tight', pad_inches=0.05)
    plt.close()


def add_errorbar_plot(distance, per, color, label, ax):
    distance = np.asarray(distance, dtype=float)
    per = np.asarray(per, dtype=float)

    # 座標が取得できなかった (NaN) サンプルは除外する
    valid = ~np.isnan(distance)
    distance = distance[valid]
    per = per[valid]
    if len(distance) == 0:
        return

    bin_size = 100
    bins = np.arange(50, np.nanmax(distance) + bin_size, bin_size)

    df = pd.DataFrame({'dist': distance, 'per': per})
    df['bin'] = pd.cut(df['dist'], bins=bins, labels=bins[:-1] + bin_size / 2)

    stats_df = df.groupby('bin', observed=False)['per'].agg(['mean', 'count', 'std']).dropna()

    ci95_hi = []
    for i in range(len(stats_df)):
        m, n, s = stats_df.iloc[i][['mean', 'count', 'std']]
        if n > 1:
            interval = stats.t.ppf(0.975, n - 1) * (s / np.sqrt(n))
            ci95_hi.append(interval)
        else:
            ci95_hi.append(0)

    ax.errorbar(
        stats_df.index.astype(float),
        stats_df['mean'],
        yerr=ci95_hi,
        fmt='o',
        color=color,
        label=label,
        capsize=8,
        capthick=3,
        elinewidth=3,
        markersize=12,
    )


def plot_distance_vs_per_errorbar(dist_up, per_up, dist_down, per_down, filename, plot_dir):
    fig, ax = plt.subplots(figsize=(13, 10))

    if len(dist_up) > 0:
        add_errorbar_plot(dist_up, per_up, 'blue', 'UpLink', ax)
    if len(dist_down) > 0:
        add_errorbar_plot(dist_down, per_down, 'red', 'DownLink', ax)

    ax.set_ylim(0.0, 1.0)
    ax.tick_params(axis="both", labelsize=FONT_SIZE, width=3.0, which="major", length=20)

    leg = ax.legend(fontsize=FONT_SIZE)
    leg.get_frame().set_linewidth(1.8)

    ax.xaxis.set_major_formatter(mtick.StrMethodFormatter('{x:,.0f}'))
    ax.xaxis.set_major_locator(mtick.MultipleLocator(1000))
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    fig.tight_layout()
    os.makedirs(plot_dir, exist_ok=True)
    plt.savefig(os.path.join(plot_dir, filename), bbox_inches='tight', pad_inches=0.05)
    plt.close()


# ============================================================
# メイン処理
# ============================================================
def main():
    if not os.path.isfile(CSV_FILE):
        raise FileNotFoundError(f"CSV file not found: {CSV_FILE}")

    print(f"--- Loading {CSV_FILE} ---")
    data = load_and_aggregate(CSV_FILE, STATS_DIR)
    print(f"--- Loaded {len(data)} conditions ---")

    for condition_key, entry in data.items():
        pan1_ch, pan2_ch, distance, pan1_offload, pan2_offload = condition_key

        interf_label = get_interf_label(pan1_ch, pan2_ch)
        if interf_label is None:
            print(f"Warning: unknown channel pair ({pan1_ch}, {pan2_ch}) - skipping")
            continue
        bw_label = get_bandwidth_label(pan1_ch, pan2_ch)

        plot_dir = os.path.join(PLOT_BASE_DIR, bw_label, f"{distance}m", interf_label)
        suffix = f"pan1_{pan1_offload}_pan2_{pan2_offload}"

        print(f"Plotting: {plot_dir} / {suffix}")

        # --- PAN1 ---
        pan1_diff = np.array(entry["pan1_dl"]) - np.array(entry["pan1_ul"])
        plot_delta_per_analysis(pan1_diff, entry["pan1_rssi"], f"pan1_box_{suffix}.pdf", plot_dir)
        plot_variance_distribution_boxplot(pan1_diff, entry["pan1_rssi"], f"pan1_s_{suffix}.pdf", plot_dir)
        plot_distance_vs_per_errorbar(
            entry["pan1_dist"], entry["pan1_ul"],
            entry["pan1_dist"], entry["pan1_dl"],
            f"pan1_errorbar_{suffix}.pdf", plot_dir,
        )

        # --- PAN2 ---
        pan2_diff = np.array(entry["pan2_dl"]) - np.array(entry["pan2_ul"])
        plot_delta_per_analysis(pan2_diff, entry["pan2_rssi"], f"pan2_box_{suffix}.pdf", plot_dir)
        plot_variance_distribution_boxplot(pan2_diff, entry["pan2_rssi"], f"pan2_s_{suffix}.pdf", plot_dir)
        plot_distance_vs_per_errorbar(
            entry["pan2_dist"], entry["pan2_ul"],
            entry["pan2_dist"], entry["pan2_dl"],
            f"pan2_errorbar_{suffix}.pdf", plot_dir,
        )

    print("--- Done ---")


if __name__ == "__main__":
    main()