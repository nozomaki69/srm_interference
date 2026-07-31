#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import re
import collections
import numpy as np
import scipy.stats as stats
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
from collections import defaultdict
from sklearn.kernel_ridge import KernelRidge
from sklearn.metrics import roc_curve, auc
from statsmodels.nonparametric.smoothers_lowess import lowess
from concurrent.futures import ProcessPoolExecutor

# --- Configuration ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATS_DIR = os.path.join(SCRIPT_DIR, "..")  # commandline/
PLOT_OUTPUT_DIR = os.path.join(STATS_DIR, "plots")

# Regular expression to parse parameters from filenames
#interf_coord_dist_([\d.]+)m_off_load([\d.]+)_seed(\d+)
#interf_coord_dist_{DISTANCES_M}m_off_load_pan1_{OFFERED_LOAD_PAN1}_pan2_{OFFERED_LOAD_PAN2}_seed{seed}
#off_load_pan1_([\d.]+)_pan2_([\d.]+)_seed(\d+)
FILENAME_STAT = re.compile(r"coord_dist_([\d.]+)m_off_load_pan1_([\d.]+)_pan2_([\d.]+)_seed(\d+)\.stat")
FILENAME_TRACE = re.compile(r"coord_dist_([\d.]+)m_off_load_pan1_([\d.]+)_pan2_([\d.]+)_seed(\d+)\.trace")
FILENAME_POS = re.compile(r"coord_dist_([\d.]+)m_off_load_pan1_([\d.]+)_pan2_([\d.]+)_seed(\d+)\.pos")

# 新しいリスト定義
FILE_PREFIXES = ["interf", "no_interf"]
# --- Main Logic ---

pan1_offload_min = 0.1
pan1_offload_max = 1.1
pan2_offload_min = 0.1
pan2_offload_max = 0.3
NUM_COORD = 2
NUM_DEV_GROUP = 10 # 各グループのデバイス数
C1_DEV_RANGE = range(NUM_COORD + 1, NUM_COORD + NUM_DEV_GROUP + 1)  # 3 ~ 14
C2_DEV_RANGE = range(NUM_COORD + NUM_DEV_GROUP + 1, NUM_COORD + (2 * NUM_DEV_GROUP) + 1) # 15 ~ 26
FONT_SIZE = 45
PATTERN =2
MAX_WORKERS=32

def main():
    results = {
        "up_per_all_pan1": {},
        "down_per_all_pan1": {},
        "up_per_all_pan2": {},
        "down_per_all_pan2": {},
        "pan1_ratio": {},
        "pan2_ratio": {},
        "pan1_diff" : {},
        "pan2_diff" : {},
        "pan1_ratio" : {},
        "pan2_ratio" : {},
        "distance_pan1"  : {},
        "distance_pan2"  : {},
        "pan1_c_rssi": {},
        "pan2_c_rssi": {},
        "pan1_dispersion": {},
        "pan2_dispersion": {},
    }
    interf_scenario_num = []
    for prefix_name in FILE_PREFIXES:
        print(f"\n===== Processing {prefix_name} files =====\n")

        """Main execution function."""
        print("--- Starting Result Aggregation and Plotting ---")


        for off_load_pan2 in np.round(np.arange(pan2_offload_min, pan2_offload_max, 0.1),1):
            for off_load_pan1 in np.round(np.arange(pan1_offload_min, pan1_offload_max, 0.1),1):
                    print("start off_load_pan1/pan2:", off_load_pan1,"/",off_load_pan2)

                    if not os.path.isdir(STATS_DIR):
                        print(
                            f"Error: Statistics directory not found at '{STATS_DIR}'", file=sys.stderr
                        )
                        sys.exit(1)

                    # Find all .stat files
                    stat_files = [f for f in os.listdir(STATS_DIR)
                                    if f.endswith(".stat")
                                    and f.startswith(prefix_name)
                                    and f"pan2_{off_load_pan2}" in f
                                    and f"pan1_{off_load_pan1}" in f
                                    ]
                    trace_files = [f for f in os.listdir(STATS_DIR)
                                    if f.endswith(".trace")
                                    and f.startswith(prefix_name)
                                    and f"pan2_{off_load_pan2}" in f
                                    and f"pan1_{off_load_pan1}" in f
                                    ]
                    pos_files = [f for f in os.listdir(STATS_DIR)
                                    if f.endswith(".pos")
                                    and f.startswith(prefix_name)
                                    and f"pan2_{off_load_pan2}" in f
                                    and f"pan1_{off_load_pan1}" in f
                                    ]
                    if not (stat_files or trace_files or pos_files):
                        print("Warning: No .stat, .trace, or _seed0.pos files found. Nothing to plot.", file=sys.stderr)
                        return
                    
                    print(f"Found {len(stat_files)} stat files to process.")
                    print(f"Found {len(trace_files)} trace files to process.")
                    print(f"Found {len(pos_files)} pos files to process.")

                    # Data container for all runs
                    values= run_parallel_analysis(trace_files, prefix_name, STATS_DIR, NUM_DEV_GROUP, MAX_WORKERS)
                    interf_scenario_num.append(values["interf_flag"].values())
                    results["pan1_dispersion"]
                    #求めた距離ごとのノードの平均を二次元平面上にプロット
                    offload = f"{prefix_name}_pan1_{off_load_pan1}_pan2_{off_load_pan2}"
                    results["distance_pan1"][offload], results["up_per_all_pan1"][offload], results["down_per_all_pan1"][offload], results["pan1_c_rssi"][offload], results["distance_pan2"][offload], results["up_per_all_pan2"][offload], results["down_per_all_pan2"][offload], results["pan2_c_rssi"][offload] = run_pos_parallel(pos_files, prefix_name, values, C1_DEV_RANGE, C2_DEV_RANGE, MAX_WORKERS)
                    #print(results["pan1_c_rssi"][offload])
                    results["pan1_diff"][offload] = np.array(results["down_per_all_pan1"][offload]) - np.array(results["up_per_all_pan1"][offload])
                    results["pan2_diff"][offload] = np.array(results["down_per_all_pan2"][offload]) - np.array(results["up_per_all_pan2"][offload])
                    #print(results["pan1_c_rssi"][offload])
    for prefix_name in FILE_PREFIXES:            
        base_plot_dir = "plots"            
        
        with ProcessPoolExecutor(MAX_WORKERS) as executor:  # elgarやwagnerなら8〜16くらいがおすすめ
            for off_load_pan2 in np.round(np.arange(pan2_offload_min, pan2_offload_max, 0.1),1):
                for off_load_pan1 in np.round(np.arange(pan1_offload_min, pan1_offload_max, 0.1),1):
                    if prefix_name == "interf":
                        plot_dir = os.path.join(
                            base_plot_dir,
                            "interf",
                            f"pan1_{off_load_pan1}_pan2_{off_load_pan2}"

                        )
                    else:
                        plot_dir = os.path.join(
                            base_plot_dir,
                            "no_interf",
                            f"pan1_{off_load_pan1}_pan2_{off_load_pan2}"
                        )
                    executor.submit(generate_all_plots, results, prefix_name, off_load_pan1, off_load_pan2, plot_dir)
        
    for off_load_pan2 in np.round(np.arange(pan1_offload_min, pan1_offload_max, 0.1),1):
        for off_load_pan1 in np.round(np.arange(pan1_offload_min, pan1_offload_max, 0.1),1):
                interf_diff_errorbar(results["distance_pan1"][f"interf_pan1_{off_load_pan1}_pan2_{off_load_pan2}"], 
                                    results["pan1_diff"][f"interf_pan1_{off_load_pan1}_pan2_{off_load_pan2}"], 
                                    results["distance_pan1"][f"no_interf_pan1_{off_load_pan1}_pan2_{off_load_pan2}"], 
                                    results["pan1_diff"][f"no_interf_pan1_{off_load_pan1}_pan2_{off_load_pan2}"], 
                                    f"PAN1_{off_load_pan1}_pan2_{off_load_pan2}_errorbar_diff.pdf")     
            
    
    data = [list(d) for d in interf_scenario_num]
    print(data)
    total_scenarios = 5  # seed数
    loads = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

    # 前半10個が干渉あり、後半10個が干渉なし
    interf_data    = data[:10]   # 干渉ありシナリオ
    no_interf_data = data[10:]   # 干渉なしシナリオ

    # 閾値（何台以上で干渉ありと判定するか）
    for threshold in [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.1, 0.11, 0.12, 0.13, 0.14, 0.15, 0.16, 0.17, 0.18, 0.19, 0.20, 0.21, 0.22]:
        print(f"\n--- {threshold}devices ---")
        for i, load in enumerate(loads):
            # 干渉ありシナリオ: デバイス数>=thresholdならTP
            tp = sum(1 for v in interf_data[i] if v >= threshold)
            # 干渉なしシナリオ: デバイス数>=thresholdならFP
            fp = sum(1 for v in no_interf_data[i] if v >= threshold)
            
            fn = total_scenarios - tp
            tn = total_scenarios - fp

            precision = tp / (tp + fp) if (tp + fp) > 0 else 0
            recall    = tp / (tp + fn) if (tp + fn) > 0 else 0
            fpr       = fp / (fp + tn) if (fp + tn) > 0 else 0
            f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

            print(f"Load {int(load*100)}%: TP={tp}, FP={fp}, FN={fn}, TN={tn}, "
                f"Precision={precision:.3f}, Recall={recall:.3f}, FPR={fpr:.3f}, F1={f1:.3f}")
        
def generate_all_plots(results, prefix_name, off_load_pan1, off_load_pan2, plot_dir):
    # この関数の中に、実行したいプロット処理をすべて詰め込む
    offload = f"{prefix_name}_pan1_{off_load_pan1}_pan2_{off_load_pan2}"
    
    plot_delta_per_analysis(results["pan1_diff"][offload], results["pan1_c_rssi"][offload], f"pan1_box_{offload}.pdf", plot_dir)
    plot_delta_per_analysis(results["pan2_diff"][offload], results["pan2_c_rssi"][offload], f"pan2_box_{offload}.pdf", plot_dir)
    plot_variance_distribution_boxplot(results["pan1_diff"][offload], results["pan1_c_rssi"][offload], f"pan1_s_{offload}.pdf", plot_dir)
    plot_variance_distribution_boxplot(results["pan2_diff"][offload], results["pan2_c_rssi"][offload], f"pan2_s_{offload}.pdf", plot_dir)

    # 2. エラーバー付きのプロット
    plot_distance_vs_per_errorbar(results["distance_pan1"][offload], results["up_per_all_pan1"][offload], 
                                  results["distance_pan1"][offload], results["down_per_all_pan1"][offload], 
                                  f"pan1_errorbar_{offload}.pdf", plot_dir)
    
    plot_distance_vs_per_errorbar(results["distance_pan2"][offload], results["up_per_all_pan2"][offload], 
                                  results["distance_pan2"][offload], results["down_per_all_pan2"][offload], 
                                  f"pan2_errorbar_{offload}.pdf", plot_dir)

def plot_variance_distribution_boxplot(delta_per, rssi_list, filename, plot_dir):
    # 1. 1次元配列に平坦化
    rssi_list = np.array(rssi_list).flatten()
    delta_per = np.array(delta_per).flatten()
    
    num_seeds = len(rssi_list) // NUM_DEV_GROUP
    
    # RSSIの境界設定
    bins = np.arange(0, -121, -10)
    
    # 各RSSIビンごとに、各seedの分散値を格納するリストのリスト
    # 例: variances_per_bin[0] = [seed0の0~-10の分散, seed1の0~-10の分散, ...]
    variances_per_bin = [[] for _ in range(len(bins) - 1)]
    bin_labels = [f"[{bins[i]}, {bins[i+1]})" for i in range(len(bins) - 1)]
    
    # 2. Seedごとにループを回して分散を計算
    for s in range(num_seeds):
        start_idx = s * NUM_DEV_GROUP
        end_idx = (s + 1) * NUM_DEV_GROUP
        
        rssi_seed = rssi_list[start_idx:end_idx]
        delta_seed = delta_per[start_idx:end_idx]
        
        # 0(無効データ)を除外
        valid = rssi_seed != 0
        r_v = rssi_seed[valid]
        d_v = delta_seed[valid]
        
        for b in range(len(bins) - 1):
            upper = bins[b]
            lower = bins[b+1]
            
            # このseed内で、このRSSI区間に属するデータを抽出
            mask = (r_v > lower) & (r_v <= upper)
            bin_values = d_v[mask]
            
            # データが一定数（例えば2個以上）ある場合のみ分散を計算
            if len(bin_values) > 1:
                var_val = np.var(bin_values)
                variances_per_bin[b].append(var_val)

    # --- グラフ描画 ---
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.tick_params(axis="both", labelsize=FONT_SIZE-20, width=3.0, which="major", length=20)
    # データが存在する（1つ以上のseedで分散が計算できた）ビンのみ抽出
    plot_data = []
    plot_labels = []
    for data, label in zip(variances_per_bin, bin_labels):
        if len(data) > 0:
            plot_data.append(data)
            plot_labels.append(label)
            
    if plot_data:
        plt.boxplot(plot_data, labels=plot_labels)
    
    # y軸は分散なので 0 以上。範囲はデータの最大値に合わせるか、固定する
    plt.ylim(0, 0.4) # 分散の最大値に合わせて調整してください
    plt.grid(True, axis='y', linestyle='--', alpha=0.7)
    # --- 保存処理 ---
    os.makedirs(plot_dir, exist_ok=True)
    output_path = os.path.join(plot_dir, filename)
    plt.savefig(output_path, bbox_inches='tight', pad_inches=0.05)
    plt.close()

def plot_delta_per_analysis(delta_per, rssi_list, filename, plot_dir):
    
    # 2. RSSIが0のデータを除外
    rssi_list = np.array(rssi_list).flatten()
    delta_per = np.array(delta_per).flatten()
    valid_mask = rssi_list != 0
    delta_per_filtered = delta_per[valid_mask]
    rssi_filtered = rssi_list[valid_mask]
    # print(delta_per_filtered)
    # print(rssi_filtered)
    # 3. 0から-120まで10dBm刻みの境界
    bins = np.arange(-50, -111, -10)
    bin_data_list = []
    labels = []
    
    for i in range(len(bins) - 1):
        upper = bins[i]
        lower = bins[i+1]
        in_bin_mask = (rssi_filtered > lower) & (rssi_filtered <= upper)
        bin_data = delta_per_filtered[in_bin_mask]
        
        # グラフのX軸ラベル（例: -100 to -90）
        # ※ 数値を見やすくするため、小さい順（lower to upper）にしています
        label = f"[{upper}, {lower})"
        labels.append(label)
        
        if len(bin_data) > 0:
            bin_data_list.append(bin_data)
        else:
            bin_data_list.append([])

    # --- グラフ描画 ---
    fig, ax = plt.subplots(figsize=(10, 10))
    
    # データが存在する区間のみプロット対象にする
    plot_indices = [i for i, d in enumerate(bin_data_list) if len(d) > 0]
    # フォントサイズの一括設定
    ax.tick_params(axis="both", labelsize=FONT_SIZE-20, width=3.0, which="major", length=20)


    # 軸のフォーマット（ax.gca()を使わずに直接 ax を指定）
    ax.xaxis.set_major_formatter(mtick.StrMethodFormatter('{x:,.0f}'))
    ax.xaxis.set_major_locator(mtick.MultipleLocator(1000))
    if plot_indices:
        plt.boxplot([bin_data_list[i] for i in plot_indices], 
                    labels=[labels[i] for i in plot_indices])
    plt.ylim(-1.0, 1.0)
    # グラフの体裁を整える
    plt.grid(True, axis='y', linestyle='--', alpha=0.7)
    # plt.xticks(rotation=30) # ラベルの重なり防止

    # --- 保存処理 ---
    os.makedirs(plot_dir, exist_ok=True)
    output_path = os.path.join(plot_dir, filename)
    plt.savefig(output_path, bbox_inches='tight', pad_inches=0.05)
    plt.close()

def process_single_trace(filename, prefix_name, STATS_DIR, NUM_DEV_GROUP):
    # ファイル名から情報を抽出（元のループ内の処理）
    match = FILENAME_TRACE.match(filename.replace(f"{prefix_name}_", ""))
    if not match:
        return None
    
    seed = int(match.group(4))
    filepath = os.path.join(STATS_DIR, filename)
    
    # 重い解析処理を実行
    up_data_pdr_list, down_data_pdr_list, c_rssi_ave_list, interf_flag = node_parse_trace_file(filepath, NUM_DEV_GROUP)
    
    # seed値と一緒に結果を返す
    return {
        "seed": seed,
        "up": up_data_pdr_list,
        "down": down_data_pdr_list,
        "c_rssi": c_rssi_ave_list,
        "interf_flag": interf_flag
    }

# --- 2. メインの処理部分 ---
def run_parallel_analysis(trace_files, prefix_name, STATS_DIR, NUM_DEV_GROUP, MAX_WORKERS):
    values = {
        "up_data_pdr_list": {},
        "down_data_pdr_list": {},
        "c_rssi_ave_list": {},
        "interf_flag": {}
    }

    with ProcessPoolExecutor(MAX_WORKERS) as executor:
        # 実行準備：関数に渡す引数をリスト化
        futures = [
            executor.submit(process_single_trace, f, prefix_name, STATS_DIR, NUM_DEV_GROUP) 
            for f in trace_files
        ]

        for future in futures:
            res = future.result()
            if res:
                seed = res["seed"]
                values["up_data_pdr_list"][seed] = res["up"]
                values["down_data_pdr_list"][seed] = res["down"]
                values["c_rssi_ave_list"][seed] = res["c_rssi"]
                values["interf_flag"][seed] = res["interf_flag"]
    return values

def process_single_pos(filename, prefix_name, values, C1_DEV_RANGE, C2_DEV_RANGE):
    match = FILENAME_POS.match(filename.replace(f"{prefix_name}_", ""))
    if not match:
        return None

    seed = int(match.group(4))
    positions = parse_pos_file(filename) # ファイル読み込み
    
    # このファイル（seed）での計算結果を一時的に保存するリスト
    tmp_res = {
        "dist1": [], "up1": [], "down1": [], "pan1_c_rssi": [],
        "dist2": [], "up2": [], "down2": [], "pan2_c_rssi": []
    }
    #ここでpan1とpan2を両方同じリストで管理していたものを分ける
    # PAN1の計算
    for device_id in C1_DEV_RANGE:
        d = np.sqrt((positions[device_id][0] - positions[2][0])**2 + (positions[device_id][1] - positions[2][1])**2)
        tmp_res["dist1"].append(d)
        tmp_res["up1"].append(values["up_data_pdr_list"][seed][device_id])
        tmp_res["down1"].append(values["down_data_pdr_list"][seed][device_id])
        tmp_res["pan1_c_rssi"].append(values["c_rssi_ave_list"][seed][device_id])

    # PAN2の計算
    for device_id in C2_DEV_RANGE:
        d = np.sqrt((positions[device_id][0] - positions[1][0])**2 + (positions[device_id][1] - positions[1][1])**2)
        tmp_res["dist2"].append(d)
        tmp_res["up2"].append(values["up_data_pdr_list"][seed][device_id])
        tmp_res["down2"].append(values["down_data_pdr_list"][seed][device_id])
        tmp_res["pan2_c_rssi"].append(values["c_rssi_ave_list"][seed][device_id])
    return tmp_res

def run_pos_parallel(pos_files, prefix_name, values, C1_DEV_RANGE, C2_DEV_RANGE, MAX_WORKERS):
    # 最終的な格納先
    distance_to_interference_pan1 = []
    up_per_all_pan1 = []
    down_per_all_pan1 = []
    distance_to_interference_pan2 = []
    up_per_all_pan2 = []
    down_per_all_pan2 = []
    pan1_device_rssi = []
    pan2_device_rssi = []


    with ProcessPoolExecutor(MAX_WORKERS) as executor:
        # 10並列で実行
        futures = [
            executor.submit(process_single_pos, f, prefix_name, values, C1_DEV_RANGE, C2_DEV_RANGE)
            for f in pos_files
        ]

        for future in futures:
            res = future.result()
            if res:
                # 各プロセスの結果をメインのリストに結合（extend）
                distance_to_interference_pan1.extend(res["dist1"])
                up_per_all_pan1.extend(res["up1"])
                down_per_all_pan1.extend(res["down1"])
                pan1_device_rssi.extend(res["pan1_c_rssi"])
                distance_to_interference_pan2.extend(res["dist2"])
                up_per_all_pan2.extend(res["up2"])
                down_per_all_pan2.extend(res["down2"])
                pan2_device_rssi.extend(res["pan2_c_rssi"])

    return (distance_to_interference_pan1, up_per_all_pan1, down_per_all_pan1, pan1_device_rssi,
            distance_to_interference_pan2, up_per_all_pan2, down_per_all_pan2, pan2_device_rssi)


def parse_pos_file(filepath):
    """
    .posファイルを解析し、ノードの初期座標（メートル単位）を抽出する。
    """
    positions = {}
    with open(filepath, "r") as f:
        for line in f:
            parts = line.split()
            # 1行目 (時間 = 0) の座標のみを抽出
            if len(parts) > 4 and parts[1] == "0":
                try:
                    node_id = int(parts[0])
                    # X座標は parts[2]、Y座標は parts[3]
                    x_m = float(parts[2])
                    y_m = float(parts[3])
                    # 座標をメートル単位で保存
                    positions[node_id] = (x_m, y_m)
                except ValueError:
                    # 数値変換エラーはスキップ
                    continue
    return positions

def add_errorbar_plot(distance, per, color, label, ax):
    # 1. 100m間隔のビンを作成
    bin_size = 100
    bins = np.arange(50, max(distance) + bin_size, bin_size) #等差配列
    
    # 2. Pandasを使って区間ごとに集計，分割してラベル付をするだけ
    df = pd.DataFrame({'dist': distance, 'per': per})
    df['bin'] = pd.cut(df['dist'], bins=bins, labels=bins[:-1] + bin_size/2)#distを50間隔でわけて，それぞれlabelをつける
    
    # 区間ごとの統計量を計算 groupbyによってlabelによって分けて，aggで3つの統計値を計算して，dropnaで値のない区間を削除
    stats_df = df.groupby('bin', observed=False)['per'].agg(['mean', 'count', 'std']).dropna()
    
    # 3. 95%信頼区間の計算
    # 信頼区間の半分幅 = t * (標準偏差 / sqrt(サンプル数))
    ci95_hi = []
    for i in range(len(stats_df)):
        m, n, s = stats_df.iloc[i][['mean', 'count', 'std']]#ilocは区間指定，
        if n > 1:
            # 自由度 n-1 のt分布を使用
            interval = stats.t.ppf(0.975, n-1) * (s / np.sqrt(n))
            ci95_hi.append(interval)
        else:
            ci95_hi.append(0) # データが1つ以下の場合はエラーバーを出さない

    # 4. エラーバー付きでプロット
    ax.errorbar(
        stats_df.index.astype(float), 
        stats_df['mean'], 
        yerr=ci95_hi, 
        fmt='o', 
        color=color, 
        label=label, 
        capsize=8,            # ヒゲの横棒を大きく (5 -> 8)
        capthick=3,           # ヒゲの横棒を太く (2 -> 3)
        elinewidth=3,         # ヒゲの縦線を太く (2 -> 3)
        markersize=12,        # 平均点のサイズを大きく (デフォルトは6前後)
    )

def plot_distance_vs_per_errorbar(dist_up, per_up, dist_down, per_down, filename, plot_dir):
    fig, ax = plt.subplots(figsize=(13, 10))
    # それぞれ独立した関数を呼び出す
    if len(dist_up) > 0:
        add_errorbar_plot(dist_up, per_up, 'blue', 'UpLink', ax)

    if len(dist_down) > 0:
        add_errorbar_plot(dist_down, per_down, 'red', 'DownLink', ax)

    # 範囲の設定
    ax.set_ylim(0.0, 1.0)

    # フォントサイズの一括設定
    ax.tick_params(axis="both", labelsize=FONT_SIZE, width=3.0, which="major", length=20)

    # 凡例の設定
    leg = ax.legend(fontsize=FONT_SIZE)
    leg.get_frame().set_linewidth(1.8)

    # 軸のフォーマット（ax.gca()を使わずに直接 ax を指定）
    ax.xaxis.set_major_formatter(mtick.StrMethodFormatter('{x:,.0f}'))
    ax.xaxis.set_major_locator(mtick.MultipleLocator(1000))

    # 枠線の「上」と「右」を消す（さきほどのリクエストを反映）
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # 最後に tight_layout
    fig.tight_layout()

    os.makedirs(plot_dir, exist_ok=True)
    output_path = os.path.join(plot_dir, filename)
    plt.savefig(output_path, bbox_inches='tight', pad_inches=0.05)
    plt.close()

def interf_diff_errorbar(interf_dist_pan1, interf_diff, no_interf_dist_pan1, no_interf_diff, filename):
    fig, ax = plt.subplots(figsize=(13, 10))
    # それぞれ独立した関数を呼び出す
    if len(interf_dist_pan1) > 0:
        add_errorbar_plot(interf_dist_pan1, interf_diff, 'red', 'With Interference', ax)

    if len(no_interf_dist_pan1) > 0:
        add_errorbar_plot(no_interf_dist_pan1, no_interf_diff, 'blue', 'Without Interference', ax)

    # フォントサイズの一括設定
    ax.tick_params(axis="both", labelsize=FONT_SIZE, width=3.0, which="major", length=20)

    # 凡例の設定
    leg = ax.legend(fontsize=FONT_SIZE -10)
    leg.get_frame().set_linewidth(1.8)

    # 軸のフォーマット（ax.gca()を使わずに直接 ax を指定）
    ax.xaxis.set_major_formatter(mtick.StrMethodFormatter('{x:,.0f}'))
    ax.xaxis.set_major_locator(mtick.MultipleLocator(1000))

    # 枠線の「上」と「右」を消す（さきほどのリクエストを反映）
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.set_ylim(-1.0, 0.5)
    # 最後に tight_layout
    fig.tight_layout()
    output_filename = os.path.join(PLOT_OUTPUT_DIR, filename)
    os.makedirs(PLOT_OUTPUT_DIR, exist_ok=True)
    
    plt.tight_layout()
    plt.savefig(output_filename, bbox_inches='tight', pad_inches=0.05)
    plt.close()
    
def node_parse_trace_file(filepath, num_device):
    size = 2 * NUM_DEV_GROUP + 3

    # device → coordinator
    c_rx_pkt_num_list     = np.zeros(size)
    d_deq_pkt_num_list    = np.zeros(size)
    d_tx_pkt_num_list = np.zeros(size)
    d_rx_ack_num_list     = np.zeros(size)

    # coordinator → device
    c_deq_pkt_num_list     = np.zeros(size)
    c_tx_pkt_num_list = np.zeros(size)
    d_rx_pkt_num_list      = np.zeros(size)

    # 統計用
    up_data_pkt_per_list      = np.zeros(size)
    down_data_pkt_per_list    = np.zeros(size)

    d_rssi_sum_list    = np.zeros(size)
    c_rssi_sum_list    = np.zeros(size)
    c_rssi_ave_list    = np.zeros(size)
    SENDER_ID_RANGE1 = [int(i) for i in range(3, num_device + 3)] 

    with open(filepath, "r") as f:
        pan1_interf_num = 0
        pan2_interf_flag = 0
        max_variance = -1.0
        max_variance_label = None
        for line in f:
            parts = line.split()

            if not parts:
                continue

            #coordinator
            if "DrIotMac" in parts[5] and ( "1" == parts[3] or  "2" == parts[3]):
                #coordinatorが送信機
                if "DataFrameDequeued" in parts[9]:
                    devicenum_ber = int(parts[15])
                    c_deq_pkt_num_list[devicenum_ber] += 1
                
                if "Tx-DATA" in parts[9]:
                    devicenum_ber = int(parts[17])
                    if "1" == parts[3]:
                        c_tx_pkt_num_list[devicenum_ber] += 1 

                    if "2" == parts[3]:
                        c_tx_pkt_num_list[devicenum_ber] += 1 

                #coordinatorが受信機
                if "RxFrame" in parts[9]:
                    pkt_id = parts[11]
                    devicenum_ber = int(pkt_id.split('_')[0])
                    if "Data" in parts[15]:
                        c_rx_pkt_num_list[devicenum_ber] += 1
                        c_rssi_sum_list[devicenum_ber] += float(parts[19])
                        if devicenum_ber in SENDER_ID_RANGE1:
                            c_rx_pkt_num_list[1] += 1
                        else:
                            c_rx_pkt_num_list[2] += 1
                

            #device
            if "DrIotMac" in parts[5] and parts[3]!= "1" and parts[3]!= "2":
                devicenum_ber = int(parts[3])

                #deviceが送信機
                if "DataFrameDequeued" in parts[9] :
                    d_deq_pkt_num_list[devicenum_ber] += 1
                    if devicenum_ber in SENDER_ID_RANGE1:
                        d_deq_pkt_num_list[1] += 1
                    else:
                        d_deq_pkt_num_list[2] += 1
                
                if "Tx-DATA" in parts[9]:
                    d_tx_pkt_num_list[devicenum_ber] += 1 
                    if devicenum_ber in SENDER_ID_RANGE1:
                        d_tx_pkt_num_list[1] += 1
                    else:
                        d_tx_pkt_num_list[2] += 1

                #deviceが受信機
                if "RxFrame" in parts[9]: 
                    if "ACK" in parts[15]:
                        d_rx_ack_num_list[devicenum_ber] += 1
                    
                    if "Data" in parts[15]:
                        d_rx_pkt_num_list[devicenum_ber] +=  1
                        d_rssi_sum_list[devicenum_ber] += float(parts[19])
        
        for device_id in range(size):
            if d_deq_pkt_num_list[device_id]  != 0 and c_deq_pkt_num_list[device_id] != 0:
                up_data_pkt_per_list[device_id] =  round((d_deq_pkt_num_list[device_id] - c_rx_pkt_num_list[device_id])/d_deq_pkt_num_list[device_id],3)
                down_data_pkt_per_list[device_id] =  round((c_deq_pkt_num_list[device_id] - d_rx_pkt_num_list[device_id])/c_deq_pkt_num_list[device_id],3)
        np.seterr(divide='ignore', invalid='ignore')
        c_rssi_ave_list = np.where(c_rx_pkt_num_list > 0, np.round(c_rssi_sum_list/c_rx_pkt_num_list, 1), 0)


    return up_data_pkt_per_list, down_data_pkt_per_list, c_rssi_ave_list, pan1_interf_num

if __name__ == "__main__":
    main()


