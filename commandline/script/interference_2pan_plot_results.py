#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import re
import collections
import numpy as np
import matplotlib.pyplot as plt
from collections import defaultdict

# ★修正：scipyのインポートを削除
# from scipy import stats 

# --- Configuration ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATS_DIR = os.path.join(SCRIPT_DIR, "..")  # commandline/
PLOT_OUTPUT_DIR = os.path.join(STATS_DIR, "plots")

# Regular expression to parse parameters from filenames
FILENAME_STAT = re.compile(r"dist_([\d.]+)km_bw_([\d.]+?)and([\d.]+)khz_num_device(\d+)_seed(\d+)\.stat")
FILENAME_TRACE = re.compile(r"dist_([\d.]+)km_bw_([\d.]+?)and([\d.]+)khz_num_device(\d+)_seed(\d+)\.trace")
FILENAME_POS = re.compile(r"dist_([\d.]+)km_bw_([\d.]+?)and([\d.]+)khz_num_device(\d+)_seed0\.pos")

# 新しいリスト定義
FILE_PREFIXES = ["interference", "non_interference"]
# --- Main Logic ---

NUM_COORD = 2
NUM_DEV_GROUP = 12 # 各グループのデバイス数
C1_DEV_RANGE = range(NUM_COORD + 1, NUM_COORD + NUM_DEV_GROUP + 1)  # 3 ~ 14
C2_DEV_RANGE = range(NUM_COORD + NUM_DEV_GROUP + 1, NUM_COORD + (2 * NUM_DEV_GROUP) + 1) # 15 ~ 26

PATTERN =2

def main():
    for prefix_name in FILE_PREFIXES:
        print(f"\n===== Processing {prefix_name} files =====\n")
        bw1_khz = 0.0
        bw2_khz = 0.0

        """Main execution function."""
        print("--- Starting Result Aggregation and Plotting ---")

        if not os.path.isdir(STATS_DIR):
            print(
                f"Error: Statistics directory not found at '{STATS_DIR}'", file=sys.stderr
            )
            sys.exit(1)

        # Find all .stat files
        stat_files = [f for f in os.listdir(STATS_DIR) 
                               if f.endswith(".stat") and f.startswith(prefix_name)]
        trace_files = [f for f in os.listdir(STATS_DIR) 
                                if f.endswith(".trace") and f.startswith(prefix_name)]
        pos_files = [f for f in os.listdir(STATS_DIR) 
                              if f.endswith(".pos") and "_seed0" in f and f.startswith(prefix_name)]

        if not (stat_files or trace_files or pos_files):
            print("Warning: No .stat, .trace, or _seed0.pos files found. Nothing to plot.", file=sys.stderr)
            return

        print(f"Found {len(stat_files)} stat files to process.")
        print(f"Found {len(trace_files)} trace files to process.")
        print(f"Found {len(pos_files)} pos files (seed=0) to process.")

        # Data container for all runs
        results = {
            "up_data_pdr_list":collections.defaultdict(list),
            "down_data_pdr_list":collections.defaultdict(list),
        }

        #Nodeごとの統計情報をtraceファイルから取り、距離ごとにseed値全ての配列を格納
        for filename in trace_files:
            match = FILENAME_TRACE.match(filename.replace(f"{prefix_name}_", ""))
            if not match:
                print(f"Skipping file with unexpected name format: {filename}")
                continue

            dist_km = float(match.group(1))
            num_device = int(match.group(4))

            filepath = os.path.join(STATS_DIR, filename)
            up_data_pdr_list, down_data_pdr_list= node_parse_trace_file(filepath, num_device)

            results["up_data_pdr_list"][dist_km].append(up_data_pdr_list)
            results["down_data_pdr_list"][dist_km].append(down_data_pdr_list)
        #print(results["up_data_pdr_list"])    

        #距離ごとのシミュレーション回数分の結果が出ているので、距離ごとで平均をとる
        average_up_data_pdr_dict = calculate_node_seed_average(
                results["up_data_pdr_list"]
        )
        average_down_data_pdr_dict = calculate_node_seed_average(
                results["down_data_pdr_list"]
        )
        up_down_pdr_diff = defaultdict(list)
        for dist in np.round(np.arange(0.0, 2.0, 0.1),1):
            for node_id in range(30):
                diff = round(average_up_data_pdr_dict[dist][node_id] - average_down_data_pdr_dict[dist][node_id],2)
                up_down_pdr_diff[dist].append(diff)
        #print(up_down_pdr_diff)
        #print(average_up_data_pdr_dict[0.1])
    
        #求めた距離ごとのノードの平均を二次元平面上にプロット
        for filename in pos_files:
            match = FILENAME_POS.match(filename.replace(f"{prefix_name}_", ""))
            if not match:
                print(f"Skipping file with unexpected name format: {filename}")
                continue

            dist_km = float(match.group(1))
            bw1_khz = float(match.group(2))
            bw2_khz = float(match.group(3))
            num_device = int(match.group(4))

            #posファイルから場所を特定
            positions = parse_pos_file(filename)
            #plot
            plot_positions_and_values(positions, f"{prefix_name}_{dist_km}km_up_data_pdr_plot.png", average_up_data_pdr_dict[dist_km], bw1_khz, bw2_khz)
            plot_positions_and_values(positions, f"{prefix_name}_{dist_km}km_down_data_pdr_plot.png", average_down_data_pdr_dict[dist_km], bw1_khz, bw2_khz)
            plot_positions_and_values(positions, f"{prefix_name}_{dist_km}km_all_data_pdr_plot.png", up_down_pdr_diff[dist_km], bw1_khz, bw2_khz)
            
def calculate_node_seed_average(results_dict):
    average_dict = {}

    # 辞書のキーと値（dist_kmと生データ）をループ
    for dist_km, data_for_distance in results_dict.items():
        
        # 1. NumPy配列に変換 (2次元配列になる)
        # data_for_distance は [[pdr_n1_s1, ...], [pdr_n1_s2, ...], ...]
        pdr_array = np.array(data_for_distance)

        # 2. 軸 (axis=0, 行方向) を指定して平均を計算
        #    これにより、同じノード（列）同士の平均が計算される
        average_per_index = np.round(np.mean(pdr_array, axis=0), 2)
        
        # 3. 距離をキーとして平均配列を格納
        average_dict[dist_km] = average_per_index
        
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
                up_data_pdr_list[device_id] =  round(coordinator_receive_list[device_id]/device_dequed_list[device_id],3)
                down_data_pdr_list[device_id] =  round(device_receive_list[device_id]/coordinator_dequed_list[device_id],3)

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
        plt.plot(x_m, y_m, marker=marker_style, markersize=8, color=marker_color, linestyle='', alpha=0.7)

        # ----------------------------------------------------
        # 2. 値のオーバーレイ処理
        # ----------------------------------------------------
        
        h_align = ''
        v_align = ''

        if node_id == 1 or node_id in C1_DEV_RANGE:
            # PAN 1 / Coordinator 1 グループ: 右下
            h_align = 'right'
            v_align = 'bottom'
        elif node_id == 2 or node_id in C2_DEV_RANGE:
            # PAN 2 / Coordinator 2 グループ: 左上
            h_align = 'left'
            v_align = 'top'
        else:
            # その他のノード（Node 0など）: デフォルトの右下
            h_align = 'right'
            v_align = 'bottom'


        # 値を座標の隣にテキストとして描画
        plt.text(
            x_m, y_m, 
            f'{value}', 
            fontsize=15, 
            # 決定したアライメントを適用
            verticalalignment=v_align, 
            horizontalalignment=h_align
        )

    # ----------------------------------------------------
    # 3. グラフの整形
    # ----------------------------------------------------
    
    # 軸のラベルはメートル単位
    plt.xlabel("X-coordinate (m)")
    plt.ylabel("Y-coordinate (m)")
    plt.title(f"{filename}")
    
    # 軸の比率を同じにする
    plt.axis('equal') 
    plt.grid(True, linestyle='--', alpha=0.5)

    # 凡例の設定 (コーディネータとデバイスの凡例を手動で作成)
    plt.legend(
        [plt.Line2D([0], [0], marker='s', color='b', markersize=8),
         plt.Line2D([0], [0], marker='s', color='r', markersize=8),
         plt.Line2D([0], [0], marker='o', color='b', markersize=8),
         plt.Line2D([0], [0], marker='o', color='r', markersize=8)],
        [f'Coordinator ({bw1_khz}kHz)',f'Coordinator ({bw2_khz}kHz)', f'Device ({bw1_khz}kHz)', f'Device ({bw2_khz}kHz)'],
        loc='upper right', title="Node Type"
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
