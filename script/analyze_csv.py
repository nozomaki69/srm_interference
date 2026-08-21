#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import csv
import json
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

# .pos から抽出した座標を永続化しておくCSV。
# 一度参照した .pos ファイルはここに保存してから削除するので、
# .pos が無くなった後の再実行でもここから読み込める。
POSITIONS_CSV = os.path.join(PLOT_BASE_DIR, "positions.csv")

NUM_DEVICE = 30
PAN1_DEVS = list(range(3, 3 + NUM_DEVICE))          # 3..12
PAN2_DEVS = list(range(3 + NUM_DEVICE, 3 + 2 * NUM_DEVICE))  # 13..22
RSSI_START_IDX = 10 + 8 * NUM_DEVICE                # 90

FONT_SIZE = 45

# チャネル番号 -> 帯域(kbps)
CHANNEL_KBPS = {0: 50, 1: 100, 2: 200, 3: 50, 4: 100, 5: 200}

# チャネル番号 -> 中心周波数(MHz)。generate_config.py の CHANNELS と同じ値。
# 0,1,2 は base_freq_mhz、3,4,5 は base_freq_mhz-1 なので、同じ周波数同士の
# 組み合わせだけが干渉する（generate_config.py の interference_flag 判定と同一基準）。
CHANNEL_FREQ_MHZ = {0: 920, 1: 920, 2: 920, 3: 921, 4: 921, 5: 921}

# --- RSSIビン設定 -----------------------------------------------------
# RSSIビンの幅(dBm)。★ここを変更するだけで、以下の解析すべてのビン幅が
# 一括で変わる★:
#   - plot_delta_per_analysis              (ΔPERの箱ひげ図)
#   - plot_variance_distribution_boxplot   (ΔPER分散の箱ひげ図)
#   - compute_seed_max_variance / VARIANCE_RSSI_BINS (干渉検知に使うRSSIビン)
# 例: 10 -> 5 に変更すると、10dBm刻みだったビンがすべて5dBm刻みになる。
RSSI_BIN_SIZE_DBM = 5

# plot_delta_per_analysis で使うRSSI範囲(dBm)。上限・下限のレンジ自体は
# 固定のまま、RSSI_BIN_SIZE_DBM に応じてビンの本数だけが自動で変わる。
RSSI_BOX_UPPER_DBM = -50
RSSI_BOX_LOWER_DBM = -110

# plot_variance_distribution_boxplot / 干渉検知(VARIANCE_RSSI_BINS)で使うRSSI範囲(dBm)。
RSSI_VAR_UPPER_DBM = 0
RSSI_VAR_LOWER_DBM = -120


# ============================================================
# ユーティリティ
# ============================================================
def make_rssi_bins(upper, lower, bin_size):
    """
    upper(dBm) から lower(dBm) まで bin_size(dBm) 刻みのビン境界配列を作る共通ヘルパー。
    RSSI_BIN_SIZE_DBM を変更するだけで、これを呼んでいる箇所すべてのビン幅が
    一括で変わるようにするためにこの関数を経由させている。
    upper > lower を想定（例: upper=-50, lower=-110, bin_size=10）。
    """
    # stop は「lower を確実に含み、その1つ下の境界は含まない」ように
    # bin_size の半分だけ余分に伸ばしておく（丸め誤差対策）。
    return np.arange(upper, lower - bin_size / 2, -bin_size)


def get_interf_label(pan1_ch, pan2_ch):
    """
    (PAN1_CH, PAN2_CH) から 'interf' / 'no_interf' を判定する。
    generate_config.py の `CHANNELS[bw0]["freq_mhz"] == CHANNELS[bw1]["freq_mhz"]`
    と全く同じ基準（周波数が一致していれば干渉あり）で判定するため、
    .config/.pos/.trace/.stat ファイル名のプレフィックス (interf_ / no_interf_)
    と必ず一致する。
    """
    return "interf" if CHANNEL_FREQ_MHZ[pan1_ch] == CHANNEL_FREQ_MHZ[pan2_ch] else "no_interf"


def get_bandwidth_label(pan1_ch, pan2_ch):
    """(PAN1_CH, PAN2_CH) から '50vs100' のような帯域ラベルを作る"""
    k1, k2 = sorted((CHANNEL_KBPS[pan1_ch], CHANNEL_KBPS[pan2_ch]))
    return f"{k1}vs{k2}"


def pos_filename(pan1_ch, pan2_ch, distance, pan1_offload, pan2_offload, seed):
    """
    .pos ファイル名を組み立てる。
    generate_config.py は干渉の有無で "interf_" / "no_interf_" のどちらかの
    プレフィックスでファイルを生成しているため、ここでも同じ判定を使う
    （以前は "interf_" 固定になっており、no_interf の組み合わせで
    ファイルが見つからないバグがあった）。
    """
    prefix = get_interf_label(pan1_ch, pan2_ch)  # 'interf' or 'no_interf'
    return (
        f"{prefix}_dist_{distance}m_channel_{pan1_ch}_vs_{pan2_ch}"
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
# 座標の永続化 (positions.csv)
# ============================================================
def load_saved_positions(path):
    """
    既に positions.csv に保存済みの座標をすべて読み込む。
    .pos ファイルが既に削除されていても、ここに載っていればそのまま使える。
    戻り値: { pos_filename: {node_id: (x, y), ...}, ... }
    """
    saved = {}
    if not os.path.isfile(path):
        return saved

    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        for row in reader:
            if len(row) < 2:
                continue
            fname, positions_json = row[0], row[1]
            try:
                raw = json.loads(positions_json)
                saved[fname] = {int(k): tuple(v) for k, v in raw.items()}
            except (ValueError, json.JSONDecodeError):
                # 壊れた行はスキップ（該当ファイルは再度 .pos が必要になるが、
                # .pos 側が既に削除済みの場合は Warning: pos file not found として扱われる）
                continue
    return saved


def append_position_to_csv(path, fname, positions, write_header):
    """positions.csv に1件(1 .posファイル分)を追記する。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["fname", "positions_json"])
        positions_json = json.dumps({str(k): list(v) for k, v in positions.items()})
        writer.writerow([fname, positions_json])


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

    各 .pos ファイルは、最初に参照(読み込み)された時点で座標を positions.csv に
    保存してからディスクから削除する。座標が既に positions.csv に保存済みの
    場合は、.pos ファイルの有無に関わらずそちらを使う(再実行時に .pos が
    無くても解析できる)。
    """
    data = defaultdict(make_empty_condition_data)
    pos_cache = {}  # このプロセス内で同じ .pos を何度も読まないようにするキャッシュ
    deleted_pos_count = 0
    missing_pos_count = 0
    reused_from_csv_count = 0

    # 既に保存済みの座標を先に読み込んでおく
    saved_positions = load_saved_positions(POSITIONS_CSV)
    positions_csv_exists = os.path.isfile(POSITIONS_CSV)

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

            # --- 座標を取得（seed ごとに個別の .pos / positions.csv の1行に対応） ---
            fname = pos_filename(pan1_ch, pan2_ch, distance, pan1_offload, pan2_offload, seed)
            if fname not in pos_cache:
                if fname in saved_positions:
                    # positions.csv に既に保存済み -> .pos を読まずにそちらを使う
                    pos_cache[fname] = saved_positions[fname]
                    reused_from_csv_count += 1
                    # 万一 .pos がまだ残っていたら(前回の削除失敗など)ついでに消しておく
                    fpath = os.path.join(stats_dir, fname)
                    if os.path.isfile(fpath):
                        try:
                            os.remove(fpath)
                        except OSError:
                            pass
                else:
                    fpath = os.path.join(stats_dir, fname)
                    if os.path.isfile(fpath):
                        positions = parse_pos_file(fpath)
                        pos_cache[fname] = positions
                        # 削除する前に座標を positions.csv に保存する
                        append_position_to_csv(
                            POSITIONS_CSV, fname, positions,
                            write_header=not positions_csv_exists,
                        )
                        positions_csv_exists = True
                        try:
                            os.remove(fpath)
                            deleted_pos_count += 1
                        except OSError as e:
                            print(f"Warning: failed to delete pos file {fpath}: {e}")
                    else:
                        print(f"Warning: pos file not found (and not in positions.csv either): {fpath}")
                        pos_cache[fname] = None
                        missing_pos_count += 1
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

    print(
        f"--- positions: newly saved & .pos deleted: {deleted_pos_count}, "
        f"reused from positions.csv: {reused_from_csv_count}, missing: {missing_pos_count} ---"
    )
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

    bins = make_rssi_bins(RSSI_BOX_UPPER_DBM, RSSI_BOX_LOWER_DBM, RSSI_BIN_SIZE_DBM)
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
        ax.boxplot([bin_data_list[i] for i in plot_indices])
        ax.set_xticks(range(1, len(plot_indices) + 1))
        ax.set_xticklabels([labels[i] for i in plot_indices])
    plt.ylim(-1.0, 1.0)
    plt.grid(True, axis='y', linestyle='--', alpha=0.7)

    os.makedirs(plot_dir, exist_ok=True)
    plt.savefig(os.path.join(plot_dir, filename), bbox_inches='tight', pad_inches=0.05)
    plt.close()


def plot_variance_distribution_boxplot(delta_per, rssi_list, filename, plot_dir):
    rssi_list = np.array(rssi_list, dtype=float).flatten()
    delta_per = np.array(delta_per, dtype=float).flatten()

    num_seeds = len(rssi_list) // NUM_DEVICE
    bins = make_rssi_bins(RSSI_VAR_UPPER_DBM, RSSI_VAR_LOWER_DBM, RSSI_BIN_SIZE_DBM)

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
        ax.boxplot(plot_data)
        ax.set_xticks(range(1, len(plot_labels) + 1))
        ax.set_xticklabels(plot_labels)

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
# 干渉検知（帯域幅ペアごとに interf/no_interf を比較）
# ============================================================
# ΔPER(DL-UL)の分散を見る際のRSSIビン境界（plot_variance_distribution_boxplotと同じ）
VARIANCE_RSSI_BINS = make_rssi_bins(RSSI_VAR_UPPER_DBM, RSSI_VAR_LOWER_DBM, RSSI_BIN_SIZE_DBM)

# 分散のしきい値の探索範囲。ΔPERは[-1, 1]なので分散の理論上限は1だが、
# 実データではもっと小さい値になるはず。0〜1を0.001刻みで細かく探索する。
VARIANCE_THRESHOLDS = np.round(np.arange(0.0, 1.001, 0.001), 4)


def compute_seed_max_variance(delta_per, rssi_list, num_devices):
    """
    delta_per, rssi_list: Seedごとに num_devices 個ずつ連続して並んだ1次元配列。
    各SeedについてRSSIを RSSI_BIN_SIZE_DBM 幅のビンに分け、ビンごとのΔPER分散を計算し、
    そのSeed内での最大分散値を「干渉指標」として返す。

    戻り値: 各Seedの最大分散値のリスト（長さ = num_seeds）。
    有効なビン（データ点2個以上）が1つも無いSeedは 0.0 とする。
    """
    rssi_list = np.asarray(rssi_list, dtype=float)
    delta_per = np.asarray(delta_per, dtype=float)
    num_seeds = len(rssi_list) // num_devices

    seed_max_variances = []
    for s in range(num_seeds):
        start = s * num_devices
        end = (s + 1) * num_devices
        rssi_seed = rssi_list[start:end]
        delta_seed = delta_per[start:end]

        valid = rssi_seed != 0
        r_v = rssi_seed[valid]
        d_v = delta_seed[valid]

        max_var = 0.0
        for b in range(len(VARIANCE_RSSI_BINS) - 1):
            upper, lower = VARIANCE_RSSI_BINS[b], VARIANCE_RSSI_BINS[b + 1]
            mask = (r_v > lower) & (r_v <= upper)
            bin_values = d_v[mask]
            if len(bin_values) > 1:
                var_val = np.var(bin_values)
                if var_val > max_var:
                    max_var = var_val

        seed_max_variances.append(max_var)

    return seed_max_variances


def evaluate_interference_detection(interf_values, no_interf_values):
    """
    interf_values / no_interf_values: 干渉あり/なしシナリオでの、各Seedの
    干渉指標（compute_seed_max_variance の出力）。
    分散のしきい値を振り、F1が最大となるしきい値と、その時の
    TP/FP/FN/TN・Precision/Recall/FPR/F1 を返す。
    """
    n_pos = len(interf_values)
    n_neg = len(no_interf_values)

    best = None
    for th in VARIANCE_THRESHOLDS:
        tp = sum(1 for v in interf_values if v >= th)
        fp = sum(1 for v in no_interf_values if v >= th)
        fn = n_pos - tp
        tn = n_neg - fp

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        if best is None or f1 > best["f1"]:
            best = {
                "threshold": th, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                "precision": precision, "recall": recall, "fpr": fpr, "f1": f1,
            }

    best["n_interf_seeds"] = n_pos
    best["n_no_interf_seeds"] = n_neg
    return best


def run_interference_detection(data):
    """
    帯域幅の組み合わせ（例: 50vs50）ごとに、干渉あり/なしシナリオの
    ΔPER分散（RSSIビンごとの最大値, Seed単位）を比較し、干渉検知の
    最適しきい値とその性能指標を求める。PAN1・PAN2それぞれについて行う。
    """
    # (bandwidth_label, distance, pan1_offload, pan2_offload) -> {'interf': key, 'no_interf': key}
    groups = defaultdict(dict)
    for condition_key in data.keys():
        pan1_ch, pan2_ch, distance, pan1_offload, pan2_offload = condition_key
        bw_label = get_bandwidth_label(pan1_ch, pan2_ch)
        interf_label = get_interf_label(pan1_ch, pan2_ch)
        group_key = (bw_label, distance, pan1_offload, pan2_offload)
        groups[group_key][interf_label] = condition_key

    rows = []
    for (bw_label, distance, pan1_offload, pan2_offload), pair in sorted(groups.items()):
        if "interf" not in pair or "no_interf" not in pair:
            # 対になるシナリオ（干渉あり/なし両方）が揃っていない場合はスキップ
            continue

        interf_entry = data[pair["interf"]]
        no_interf_entry = data[pair["no_interf"]]

        for pan_name, dl_key, ul_key, rssi_key in [
            ("PAN1", "pan1_dl", "pan1_ul", "pan1_rssi"),
            ("PAN2", "pan2_dl", "pan2_ul", "pan2_rssi"),
        ]:
            interf_delta = np.array(interf_entry[dl_key]) - np.array(interf_entry[ul_key])
            no_interf_delta = np.array(no_interf_entry[dl_key]) - np.array(no_interf_entry[ul_key])

            interf_values = compute_seed_max_variance(interf_delta, interf_entry[rssi_key], NUM_DEVICE)
            no_interf_values = compute_seed_max_variance(no_interf_delta, no_interf_entry[rssi_key], NUM_DEVICE)

            if len(interf_values) == 0 or len(no_interf_values) == 0:
                print(f"Warning: no seed data for {bw_label} {distance}m pan1_{pan1_offload}_pan2_{pan2_offload} ({pan_name}) - skipping")
                continue

            result = evaluate_interference_detection(interf_values, no_interf_values)

            rows.append({
                "bandwidth": bw_label,
                "distance": distance,
                "pan1_offload": pan1_offload,
                "pan2_offload": pan2_offload,
                "pan": pan_name,
                "best_threshold": result["threshold"],
                "TP": result["tp"],
                "FP": result["fp"],
                "FN": result["fn"],
                "TN": result["tn"],
                "precision": round(result["precision"], 3),
                "recall": round(result["recall"], 3),
                "fpr": round(result["fpr"], 3),
                "f1": round(result["f1"], 3),
                "n_interf_seeds": result["n_interf_seeds"],
                "n_no_interf_seeds": result["n_no_interf_seeds"],
            })

    return rows


def save_interference_detection_csv(rows, output_path):
    fieldnames = [
        "bandwidth", "distance", "pan1_offload", "pan2_offload", "pan",
        "best_threshold", "TP", "FP", "FN", "TN",
        "precision", "recall", "fpr", "f1",
        "n_interf_seeds", "n_no_interf_seeds",
    ]
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


# ============================================================
# メイン処理
# ============================================================
def main():
    if not os.path.isfile(CSV_FILE):
        raise FileNotFoundError(f"CSV file not found: {CSV_FILE}")

    print(f"--- Loading {CSV_FILE} ---")
    data = load_and_aggregate(CSV_FILE, STATS_DIR)
    print(f"--- Loaded {len(data)} conditions ---")

    # --- 干渉検知（帯域幅ペアごとに interf/no_interf を比較, プロットはしない） ---
    print("--- Running interference detection analysis ---")
    interference_rows = run_interference_detection(data)
    interference_csv_path = os.path.join(PLOT_BASE_DIR, "interference_detection_results.csv")
    save_interference_detection_csv(interference_rows, interference_csv_path)
    print(f"--- Saved {len(interference_rows)} rows to {interference_csv_path} ---")

    for condition_key, entry in data.items():
        pan1_ch, pan2_ch, distance, pan1_offload, pan2_offload = condition_key

        interf_label = get_interf_label(pan1_ch, pan2_ch)
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
