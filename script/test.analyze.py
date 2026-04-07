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
from statsmodels.nonparametric.smoothers_lowess import lowess
from concurrent.futures import ProcessPoolExecutor

# ★修正：scipyのインポートを削除
# from scipy import stats 

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
pan2_offload_max = 1.1

NUM_COORD = 2
NUM_DEV_GROUP = 12 # 各グループのデバイス数
C1_DEV_RANGE = range(NUM_COORD + 1, NUM_COORD + NUM_DEV_GROUP + 1)  # 3 ~ 14
C2_DEV_RANGE = range(NUM_COORD + NUM_DEV_GROUP + 1, NUM_COORD + (2 * NUM_DEV_GROUP) + 1) # 15 ~ 26
BW1_kHZ = 150.0
BW2_kHZ = 600.0
FONT_SIZE = 45
PATTERN =2
MAX_WORKERS=32

def main():
    ratio = {
        "pan1_ratio": {},
        "pan2_ratio": {},
        "distance_pan1"  : {},
        "distance_pan2"  : {},
    }
    for prefix_name in FILE_PREFIXES:
        print(f"\n===== Processing {prefix_name} files =====\n")

        """Main execution function."""
        print("--- Starting Result Aggregation and Plotting ---")


        for off_load_pan2 in np.round(np.arange(pan1_offload_min, pan1_offload_max, 0.1),1):
            # corr_up1_list = []
            # corr_down1_list = []
            # corr_up2_list = []
            # corr_down2_list = []
            for off_load_pan1 in np.round(np.arange(pan2_offload_min, pan2_offload_max, 0.1),1):
                print("start off_load_pan1/pan2:", off_load_pan1,"/",off_load_pan2)
                distance_to_interference_pan1 = []
                up_per_all_pan1 = []
                down_per_all_pan1 = []
                
                distance_to_interference_pan2 = []
                up_per_all_pan2 = []
                down_per_all_pan2 = []

                if not os.path.isdir(STATS_DIR):
                    print(
                        f"Error: Statistics directory not found at '{STATS_DIR}'", file=sys.stderr
                    )
                    sys.exit(1)

                base_plot_dir = "plots"
                
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
                #print(pos_files)
                print(f"Found {len(stat_files)} stat files to process.")
                print(f"Found {len(trace_files)} trace files to process.")
                print(f"Found {len(pos_files)} pos files to process.")

                # Data container for all runs
                results = run_parallel_analysis(trace_files, prefix_name, STATS_DIR, NUM_DEV_GROUP, MAX_WORKERS)

                #求めた距離ごとのノードの平均を二次元平面上にプロット
                #print(results)
                distance_to_interference_pan1, up_per_all_pan1 ,down_per_all_pan1, distance_to_interference_pan2, up_per_all_pan2, down_per_all_pan2 = run_pos_parallel(pos_files, prefix_name, results, C1_DEV_RANGE, C2_DEV_RANGE, MAX_WORKERS)

                plot_distance_vs_per(distance_to_interference_pan1, up_per_all_pan1, f"pan1_{off_load_pan1}_pan2_{off_load_pan2}_solo_pan1_up.png","blue", "UpLink",plot_dir)
                plot_distance_vs_per(distance_to_interference_pan1, down_per_all_pan1, f"pan1_{off_load_pan1}_pan2_{off_load_pan2}_solo_pan1_down.png", "red", "DownLink",plot_dir)
                plot_distance_vs_per_up_down(distance_to_interference_pan1,up_per_all_pan1,down_per_all_pan1,f"pan1_{off_load_pan1}_pan2_{off_load_pan2}_per_pan1.png",plot_dir)
                plot_distance_vs_per(distance_to_interference_pan2, up_per_all_pan2, f"pan1_{off_load_pan1}_pan2_{off_load_pan2}_solo_pan2_up.png", "blue", "UpLink",plot_dir)
                plot_distance_vs_per(distance_to_interference_pan2, down_per_all_pan2, f"pan1_{off_load_pan1}_pan2_{off_load_pan2}_solo_pan2_down.png", "red", "DownLink",plot_dir)
                plot_distance_vs_per_up_down(distance_to_interference_pan2,up_per_all_pan2,down_per_all_pan2,f"pan1_{off_load_pan1}_pan2_{off_load_pan2}__per_pan2.png",plot_dir)
                
                
                plot_distance_vs_per_errorbar(distance_to_interference_pan1, up_per_all_pan1, distance_to_interference_pan1, down_per_all_pan1, f"pan1_{off_load_pan1}_pan2_{off_load_pan2}_pan1_errorbar.png", plot_dir)
                plot_distance_vs_per_errorbar(distance_to_interference_pan2, up_per_all_pan2, distance_to_interference_pan2, down_per_all_pan2, f"pan1_{off_load_pan1}_pan2_{off_load_pan2}_pan2_errorbar.png", plot_dir)
                print(f"{prefix_name}_pan1_{off_load_pan1}_pan2_{off_load_pan2}_per.png finish")

                ratio["pan1_ratio"][f"{prefix_name}_pan1_{off_load_pan1}_pan2_{off_load_pan2}"] = np.array(down_per_all_pan1)/np.array(up_per_all_pan1)
                ratio["pan2_ratio"][f"{prefix_name}_pan1_{off_load_pan1}_pan2_{off_load_pan2}"] = np.array(down_per_all_pan2)/np.array(up_per_all_pan2)
                ratio["distance_pan1"][f"{prefix_name}_pan1_{off_load_pan1}_pan2_{off_load_pan2}"] = distance_to_interference_pan1
                ratio["distance_pan2"][f"{prefix_name}_pan1_{off_load_pan1}_pan2_{off_load_pan2}"] = distance_to_interference_pan2
    
    for off_load_pan2 in np.round(np.arange(pan1_offload_min, pan1_offload_max, 0.1),1):
        for off_load_pan1 in np.round(np.arange(pan2_offload_min, pan2_offload_max, 0.1),1):
            interf_no_interf_errorbar_ratio(ratio["distance_pan1"][f"interf_pan1_{off_load_pan1}_pan2_{off_load_pan2}"], 
                                          ratio["pan1_ratio"][f"interf_pan1_{off_load_pan1}_pan2_{off_load_pan2}"], 
                                          ratio["distance_pan1"][f"no_interf_pan1_{off_load_pan1}_pan2_{off_load_pan2}"], 
                                          ratio["pan1_ratio"][f"no_interf_pan1_{off_load_pan1}_pan2_{off_load_pan2}"], f"pan1_{off_load_pan1}_pan2_{off_load_pan2}_errorbar_ratio.png", plot_dir)
            
                # distance_to_interference_pan1 = np.asarray(distance_to_interference_pan1)
                # up_per_all_pan1 = np.asarray(up_per_all_pan1)
                # down_per_all_pan1 = np.asarray(down_per_all_pan1)
                # idx = np.argsort(distance_to_interference_pan1)
                # distance_pan1_sorted = distance_to_interference_pan1[idx]
                # up_per_pan1_sorted = up_per_all_pan1[idx]
                # down_per_pan1_sorted = down_per_all_pan1[idx]
                # plot_distance_vs_per_lowess(
                #     distance_pan1_sorted,
                #     up_per_pan1_sorted,
                #     down_per_pan1_sorted,
                #     f"pan1_{off_load_pan1}_pan2_{off_load_pan2}_lowess_pan1.png",
                #     plot_dir
                # )

                # distance_to_interference_pan2 = np.asarray(distance_to_interference_pan2)
                # up_per_all_pan2 = np.asarray(up_per_all_pan2)
                # down_per_all_pan2 = np.asarray(down_per_all_pan2)
                # idx = np.argsort(distance_to_interference_pan2)
                # distance_pan2_sorted = distance_to_interference_pan2[idx]
                # up_per_pan2_sorted = up_per_all_pan2[idx]
                # down_per_pan2_sorted = down_per_all_pan2[idx]
                # plot_distance_vs_per_lowess(
                #     distance_pan2_sorted,
                #     up_per_pan2_sorted,
                #     down_per_pan2_sorted,
                #     f"pan1_{off_load_pan1}_pan2_{off_load_pan2}_lowess_pan2.png",
                #     plot_dir
                # )








def plot_distance_vs_per_lowess(
    distance,
    up_per,
    down_per,
    filename,
    plot_dir,
    frac=0.2,
    point_size=50,
    alpha=0.2,
):
    """
    距離 vs PER の散布図と LOWESS 曲線（uplink / downlink）を描画する

    Parameters
    ----------
    distance : array-like
        距離データ（x軸）
    up_per : array-like
        uplink PER
    down_per : array-like
        downlink PER
    filename : str
        出力ファイル名
    frac : float
        LOWESS の平滑化パラメータ
    point_size : int
        散布図の点サイズ
    alpha : float
        散布図の透過率
    """
    


    # LOWESS
    lowess_ul = lowess(up_per, distance, frac=frac, return_sorted=True)
    lowess_dl = lowess(down_per, distance, frac=frac, return_sorted=True)

    plt.figure(figsize=(13, 10))

    # Scatter
    plt.scatter(distance, up_per,
                s=point_size, alpha=alpha, color="blue", label="Uplink")
    plt.scatter(distance, down_per,
                s=point_size, alpha=alpha, color="red", label="Downlink")

    # LOWESS lines
    plt.plot(lowess_ul[:, 0], lowess_ul[:, 1],
             color="blue", linewidth=2, label="Uplink (LOWESS)")
    plt.plot(lowess_dl[:, 0], lowess_dl[:, 1],
             color="red", linewidth=2, label="Downlink (LOWESS)")

    #plt.xlabel("d [m]", fontsize=FONT_SIZE + 20)
    #plt.ylabel("PER",fontsize=FONT_SIZE+20)
    plt.ylim(0.0, 1.0)
    plt.xticks(fontsize=FONT_SIZE)
    plt.yticks(fontsize=FONT_SIZE)
    leg = plt.legend(fontsize=FONT_SIZE)
    leg.get_frame().set_linewidth(1.8)
    plt.tight_layout()
    plt.gca().spines['right'].set_visible(False)
    plt.gca().spines['top'].set_visible(False)
    plt.gca().spines['bottom'].set_linewidth(3.0)
    plt.gca().spines['left'].set_linewidth(3.0)
    plt.tick_params(axis="both", width=3.0, which="major", length=20)
    plt.gca().xaxis.set_major_formatter(
    mtick.StrMethodFormatter('{x:,.0f}')
    )
    plt.gca().xaxis.set_major_locator(
    mtick.MultipleLocator(400)
    )

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
    up_data_pdr_list, down_data_pdr_list = node_parse_trace_file(filepath, NUM_DEV_GROUP)
    
    # seed値と一緒に結果を返す
    return {
        "seed": seed,
        "up": up_data_pdr_list,
        "down": down_data_pdr_list
    }

# --- 2. メインの処理部分 ---
def run_parallel_analysis(trace_files, prefix_name, STATS_DIR, NUM_DEV_GROUP, MAX_WORKERS):
    results = {
        "up_data_pdr_list": {},
        "down_data_pdr_list": {}
    }

    print(f"Starting analysis with 10 cores for {len(trace_files)} files...")

    # ProcessPoolExecutorで10並列実行
    with ProcessPoolExecutor(MAX_WORKERS) as executor:
        # 実行準備：関数に渡す引数をリスト化
        futures = [
            executor.submit(process_single_trace, f, prefix_name, STATS_DIR, NUM_DEV_GROUP) 
            for f in trace_files
        ]
        print(futures)
        # 終わったものから結果を回収
        for future in futures:
            res = future.result()
            if res:
                seed = res["seed"]
                results["up_data_pdr_list"][seed] = res["up"]
                results["down_data_pdr_list"][seed] = res["down"]

    return results

def process_single_pos(filename, prefix_name, results, C1_DEV_RANGE, C2_DEV_RANGE):
    match = FILENAME_POS.match(filename.replace(f"{prefix_name}_", ""))
    if not match:
        return None

    seed = int(match.group(4))
    positions = parse_pos_file(filename) # ファイル読み込み
    
    # このファイル（seed）での計算結果を一時的に保存するリスト
    tmp_res = {
        "dist1": [], "up1": [], "down1": [],
        "dist2": [], "up2": [], "down2": []
    }

    # PAN1の計算
    for device_id in C1_DEV_RANGE:
        d = np.sqrt((positions[device_id][0] - positions[2][0])**2 + (positions[device_id][1] - positions[2][1])**2)
        tmp_res["dist1"].append(d)
        tmp_res["up1"].append(results["up_data_pdr_list"][seed][device_id])
        tmp_res["down1"].append(results["down_data_pdr_list"][seed][device_id])

    # PAN2の計算
    for device_id in C2_DEV_RANGE:
        d = np.sqrt((positions[device_id][0] - positions[1][0])**2 + (positions[device_id][1] - positions[1][1])**2)
        tmp_res["dist2"].append(d)
        tmp_res["up2"].append(results["up_data_pdr_list"][seed][device_id])
        tmp_res["down2"].append(results["down_data_pdr_list"][seed][device_id])

    return tmp_res

def run_pos_parallel(pos_files, prefix_name, results, C1_DEV_RANGE, C2_DEV_RANGE, MAX_WORKERS):
    # 最終的な格納先
    distance_to_interference_pan1 = []
    up_per_all_pan1 = []
    down_per_all_pan1 = []
    distance_to_interference_pan2 = []
    up_per_all_pan2 = []
    down_per_all_pan2 = []
    with ProcessPoolExecutor(MAX_WORKERS) as executor:
        # 10並列で実行
        futures = [
            executor.submit(process_single_pos, f, prefix_name, results, C1_DEV_RANGE, C2_DEV_RANGE)
            for f in pos_files
        ]

        for future in futures:
            res = future.result()
            if res:
                # 各プロセスの結果をメインのリストに結合（extend）
                distance_to_interference_pan1.extend(res["dist1"])
                up_per_all_pan1.extend(res["up1"])
                down_per_all_pan1.extend(res["down1"])
                distance_to_interference_pan2.extend(res["dist2"])
                up_per_all_pan2.extend(res["up2"])
                down_per_all_pan2.extend(res["down2"])

    return (distance_to_interference_pan1, up_per_all_pan1, down_per_all_pan1,
            distance_to_interference_pan2, up_per_all_pan2, down_per_all_pan2)

def plot_distance_vs_per_up_down(distance, up_per, down_per, filename, plot_dir):
    plt.figure(figsize=(13, 10))
    plt.scatter(distance, up_per, color='blue', marker='o', s=50, label='UpLink')
    plt.scatter(distance, down_per, color='red', marker='o', s=50, label='DownLink')

    #plt.xlabel("d [m]",fontsize=65)
    #plt.ylabel("PER",fontsize=65)
    #plt.title(filename)

    plt.ylim(0.0, 1.0)
    plt.xticks(fontsize=FONT_SIZE)
    plt.yticks(fontsize=FONT_SIZE)
    leg = plt.legend(fontsize=FONT_SIZE)
    leg.get_frame().set_linewidth(1.8)

    plt.tight_layout()
    plt.gca().spines['right'].set_visible(False)
    plt.gca().spines['top'].set_visible(False)
    plt.gca().spines['bottom'].set_linewidth(3.0)
    plt.gca().spines['left'].set_linewidth(3.0)
    plt.tick_params(axis="both",width=3.0, which="major", length=20)
    plt.gca().xaxis.set_major_formatter(
    mtick.StrMethodFormatter('{x:,.0f}')
    )
    plt.gca().xaxis.set_major_locator(
    mtick.MultipleLocator(400)
    )

    os.makedirs(plot_dir, exist_ok=True)
    output_path = os.path.join(plot_dir, filename)
    plt.savefig(output_path, bbox_inches='tight', pad_inches=0.05)
    plt.close()


def plot_distance_vs_per(distance, per, filename, color, legend_name, plot_dir):
    plt.figure(figsize=(13, 10))
    plt.scatter(distance, per, color = f"{color}",marker='o', s=50,label = f"{legend_name}")
    #plt.xlabel("d [m]",fontsize=FONT_SIZE+20)
    #plt.ylabel("PER",fontsize=FONT_SIZE+20)
    #plt.title(filename)
    plt.tight_layout()
    plt.ylim(0.0, 1.0)
    plt.xticks(fontsize=FONT_SIZE)
    plt.yticks(fontsize=FONT_SIZE)
    leg = plt.legend(fontsize=FONT_SIZE)
    leg.get_frame().set_linewidth(1.8)
    plt.tick_params(axis="both",width=3.0, which="major", length=20)
    plt.gca().xaxis.set_major_formatter(
    mtick.StrMethodFormatter('{x:,.0f}')
    )
    plt.gca().xaxis.set_major_locator(
    mtick.MultipleLocator(400)
    )

    plt.gca().spines['right'].set_visible(False)
    plt.gca().spines['top'].set_visible(False)
    plt.gca().spines['bottom'].set_linewidth(3.0)
    plt.gca().spines['left'].set_linewidth(3.0)

    os.makedirs(plot_dir, exist_ok=True)
    output_path = os.path.join(plot_dir, filename)
    plt.savefig(output_path, bbox_inches='tight', pad_inches=0.05)
    plt.close()

   
def calculate_node_seed_average(results_dict):
    average_dict = {}

    # 辞書のキーと値（dist_mと生データ）をループ
    for dist_m, data_for_distance in results_dict.items():
        
        # 1. NumPy配列に変換 (2次元配列になる)
        # data_for_distance は [[pdr_n1_s1, ...], [pdr_n1_s2, ...], ...]
        pdr_array = np.array(data_for_distance)

        # 2. 軸 (axis=0, 行方向) を指定して平均を計算
        #    これにより、同じノード（列）同士の平均が計算される
        average_per_index = np.round(np.mean(pdr_array, axis=0), 2)
        
        # 3. 距離をキーとして平均配列を格納
        average_dict[dist_m] = average_per_index
        
    return average_dict

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
    # 1. 50m間隔のビンを作成
    bin_size = 50
    bins = np.arange(0, max(distance) + bin_size, bin_size) #等差配列
    
    # 2. Pandasを使って区間ごとに集計，分割してラベル付をするだけ
    df = pd.DataFrame({'dist': distance, 'per': per})
    df['bin'] = pd.cut(df['dist'], bins=bins, labels=bins[:-1] + bin_size/2)#distを50間隔でわけて，それぞれlabelをつける
    
    # 区間ごとの統計量を計算 groupbyによってlabelによって分けて，aggで3つの統計値を計算して，dropnaで値のない区間を削除
    stats_df = df.groupby('bin')['per'].agg(['mean', 'count', 'std']).dropna()
    
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
    ax.errorbar(stats_df.index.astype(float), stats_df['mean'], yerr=ci95_hi, 
                fmt='o', color=color, label=label, capsize=5, capthick=2, elinewidth=2)

def plot_distance_vs_per_errorbar(dist_up, per_up, dist_down, per_down, filename, plot_dir):
    fig, ax = plt.subplots(figsize=(13, 10))

    # それぞれ独立した関数を呼び出す
    if len(dist_up) > 0:
        add_errorbar_plot(dist_up, per_up, 'blue', 'UpLink', ax)
    
    if len(dist_down) > 0:
        add_errorbar_plot(dist_down, per_down, 'red', 'DownLink', ax)

    # グラフの装飾
    ax.set_ylim(0.0, 1.0)
    ax.legend(fontsize=20)
    ax.grid(True, linestyle='--', alpha=0.5)

    os.makedirs(plot_dir, exist_ok=True)
    output_path = os.path.join(plot_dir, filename)
    plt.savefig(output_path, bbox_inches='tight', pad_inches=0.05)
    plt.close()

def interf_no_interf_errorbar_ratio(interf_dist_pan1, interf_pan1_per_ratio, no_interf_dist_pan1, no_interf_pan1_per_ratio, filename, plot_dir):
    fig, ax = plt.subplots(figsize=(13, 10))

    # それぞれ独立した関数を呼び出す
    if len(interf_dist_pan1) > 0:
        add_errorbar_plot(interf_dist_pan1, interf_pan1_per_ratio, 'blue', 'UpLink', ax)
    
    if len(no_interf_dist_pan1) > 0:
        add_errorbar_plot(no_interf_dist_pan1, no_interf_pan1_per_ratio, 'red', 'DownLink', ax)

    # グラフの装飾
    ax.legend(fontsize=20)
    ax.grid(True, linestyle='--', alpha=0.5)

    output_filename = os.path.join(PLOT_OUTPUT_DIR, filename)
    os.makedirs(PLOT_OUTPUT_DIR, exist_ok=True)
    
    plt.tight_layout()
    plt.savefig(output_filename, bbox_inches='tight', pad_inches=0.05)
    plt.close()
    
def node_parse_trace_file(filepath,num_device):
    #device → coordinator
    coordinator_receive_list = [0 for _ in range(3 * num_device)]
    device_dequed_list = [0 for _ in range(3 * num_device)]
    device_received_ack_list = [0 for _ in range(3 * num_device)]

    #coordinator → device
    coordinator_dequed_list = [0 for _ in range(3 * num_device)]
    device_receive_list = [0 for _ in range(3 * num_device)]

    up_data_pdr_list = [0 for _ in range(3 * num_device)]
    down_data_pdr_list = [0 for _ in range(3 * num_device)]

    SENDER_ID_RANGE1 = [int(i) for i in range(3, num_device + 3)] 

    with open(filepath, "r") as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue

            #coordinator
            if "DrIotMac" in parts[5] and ( "1" == parts[3] or  "2" == parts[3]):
                #coordinatorが送信機
                if "DataFrameDequeued" in parts[9]:
                    devicenum_ber = int(parts[15])
                    coordinator_dequed_list[devicenum_ber] += 1

                #coordinatorが受信機
                if "RxFrame" in parts[9]:
                    pkt_id = parts[11]
                    devicenum_ber = int(pkt_id.split('_')[0])
                    if "Data" in parts[15]:
                        coordinator_receive_list[devicenum_ber] += 1
                        if devicenum_ber in SENDER_ID_RANGE1:
                            coordinator_receive_list[1] += 1
                        else:
                            coordinator_receive_list[2] += 1

            #device
            if "DrIotMac" in parts[5] and parts[3]!= "1" and parts[3]!= "2":
                devicenum_ber = int(parts[3])
                # if "Tx-DATA" in parts[9]:
                #     num_retry =  int(parts[13])
                #     device_currentRetry_list[devicenum_ber] = num_retry

                if "DataFrameDequeued" in parts[9] :
                    device_dequed_list[devicenum_ber] += 1
                    if devicenum_ber in SENDER_ID_RANGE1:
                        device_dequed_list[1] += 1
                    else:
                        device_dequed_list[2] += 1

                if "RxFrame" in parts[9]: 
                    if "ACK" in parts[15]:
                        device_received_ack_list[devicenum_ber] += 1
                    
                    if "Data" in parts[15]:
                        device_receive_list[devicenum_ber] +=  1

        for device_id in range(3 * num_device):
            if device_dequed_list[device_id]  != 0 and coordinator_dequed_list[device_id] != 0:
                up_data_pdr_list[device_id] =  round((device_dequed_list[device_id] - coordinator_receive_list[device_id])/device_dequed_list[device_id],3)
                down_data_pdr_list[device_id] =  round((coordinator_dequed_list[device_id] - device_receive_list[device_id])/coordinator_dequed_list[device_id],3)
        
        return up_data_pdr_list, down_data_pdr_list


def plot_positions_and_values(positions, filename, metric_values, bw1_khz, bw2_khz):
    """
    ノードの位置をプロットし、対応する値を座標の隣にオーバーレイする。
    """
    plt.figure(figsize=(10, 10))

    # X, Y座標の最大値/最小値を見つけるためのリスト
    all_x = []
    all_y = []

    for node_id, pos in positions.items():
        x_m, y_m = pos
        all_x.append(x_m)
        all_y.append(y_m)
        
        # 配列のインデックスはノードID
        value_index = node_id 
        if value_index < len(metric_values):
            value = metric_values[value_index]
        else:
            value = "N/A"

        # ----------------------------------------------------
        # 1. プロット処理
        # ----------------------------------------------------
        marker_style = 's' if node_id <= 2 else 'o'
        marker_color = 'b' if node_id == 1 or node_id in C1_DEV_RANGE else ('r' if node_id == 2 or node_id in C2_DEV_RANGE else 'k')
        
        # 座標はメートル単位だが、グラフの軸はメートル単位で描画
        plt.plot(x_m, y_m, marker=marker_style, markersize=10, color=marker_color, linestyle='', alpha=0.7)

        # ----------------------------------------------------
        # 2. 値のオーバーレイ処理
        # ----------------------------------------------------
        if node_id == 1 or node_id == 2:
            continue

        h_align = ''
        v_align = ''

        if node_id in C1_DEV_RANGE:
            # PAN 1 / Coordinator 1 グループ: 右下
            h_align = 'center'
            v_align = 'bottom'
        elif node_id in C2_DEV_RANGE:
            # PAN 2 / Coordinator 2 グループ: 左上
            h_align = 'center'
            v_align = 'top'
        else:
            # その他のノード（Node 0など）: デフォルトの右下
            h_align = 'right'
            v_align = 'bottom'


        # 値を座標の隣にテキストとして描画
        plt.text(
            x_m, y_m, 
            f'{value}', 
            fontsize=20, 
            # 決定したアライメントを適用
            verticalalignment=v_align, 
            horizontalalignment=h_align
        )

    # ----------------------------------------------------
    # 3. グラフの整形
    # ----------------------------------------------------
    
    # 軸のラベルはメートル単位
    plt.xlabel("X(m)",fontsize=20)
    plt.ylabel("Y(m)",fontsize=20)
    plt.title(f"{filename}",fontsize=20)
    plt.tick_params(axis='both', labelsize=14)
    # 軸の比率を同じにする
    plt.axis('equal') 
    #plt.grid(True, linestyle='--', alpha=0.5)

    # 凡例の設定 (コーディネータとデバイスの凡例を手動で作成)
    plt.legend(
        [plt.Line2D([0], [0], marker='s', color='b', markersize=8),
         plt.Line2D([0], [0], marker='s', color='r', markersize=8),
         plt.Line2D([0], [0], marker='o', color='b', markersize=8),
         plt.Line2D([0], [0], marker='o', color='r', markersize=8)],
        [f'Coordinator ({bw1_khz}kHz)',f'Coordinator ({bw2_khz}kHz)', f'Device ({bw1_khz}kHz)', f'Device ({bw2_khz}kHz)'],
        loc='upper right', title="Node Type",fontsize=14
    )
    
    # ファイル出力と余白の調整
    output_filename = os.path.join(PLOT_OUTPUT_DIR, filename)
    os.makedirs(PLOT_OUTPUT_DIR, exist_ok=True)
    
    plt.tight_layout()
    plt.savefig(output_filename, bbox_inches='tight', pad_inches=0.05)
    plt.close()
    print(f"Plot saved to: {output_filename}")

if __name__ == "__main__":
    main()

