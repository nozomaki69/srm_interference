#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import re
import collections
import numpy as np
import matplotlib.pyplot as plt
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
METRIC = ["pdr"]

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
            "distance_vs_pdr1": collections.defaultdict(list), #距離ごとのpdr
            "distance_vs_pdr2": collections.defaultdict(list),
            "distance_vs_throughput_kbps1": collections.defaultdict(list), #距離ごとのthrouput
            "distance_vs_throughput_kbps2": collections.defaultdict(list),
            "device_to_coordinator_pdr": collections.defaultdict(list), 
            "coordinator_to_device_pdr": collections.defaultdict(list), 
            "two_way_pdr": collections.defaultdict(list), 
            "end_to_end_delay" : collections.defaultdict(list),
            "device_macRetryCount": collections.defaultdict(list),
            "device_macMultipleRetryCount": collections.defaultdict(list),
            "coordinator_macRetryCount": collections.defaultdict(list),
            "coordinator_macMultipleRetryCount": collections.defaultdict(list),
            "macFcsErrorCount": collections.defaultdict(list),
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
            coordinator_to_device_pdr_list, device_to_coordinator_pdr_list, two_way_pdr_list, \
            device_macRetryCount, device_macMultipleRetryCount, coordinator_macRetryCount, coordinator_macMultipleRetryCount, \
            = node_parse_trace_file(filepath, num_device)

            results["coordinator_to_device_pdr"][dist_km].append(coordinator_to_device_pdr_list)
            results["device_to_coordinator_pdr"][dist_km].append(device_to_coordinator_pdr_list)
            results["two_way_pdr"][dist_km].append(two_way_pdr_list)
            results["device_macRetryCount"][dist_km].append(device_macRetryCount)
            results["device_macMultipleRetryCount"][dist_km].append(device_macMultipleRetryCount)
            results["coordinator_macRetryCount"][dist_km].append(coordinator_macRetryCount)
            results["coordinator_macMultipleRetryCount"][dist_km].append(coordinator_macMultipleRetryCount)

            
        #距離ごとのシミュレーション回数分の結果が出ているので、距離ごとで平均をとる
        coordinator_to_device_average_pdr_dict = calculate_node_average(
                results["coordinator_to_device_pdr"]
        )
        device_to_coordinator_average_pdr_dict = calculate_node_average(
                results["device_to_coordinator_pdr"]
        )
        two_way_average_pdr_dict = calculate_node_average(
                results["two_way_pdr"]
        )
        device_macRetryCount_dict = calculate_node_average(
                results["device_macRetryCount"]
        )
        device_macMultipleRetryCount_dict = calculate_node_average(
                results["device_macMultipleRetryCount"]
        )
        coordinator_macRetryCount_dict = calculate_node_average(
                results["coordinator_macRetryCount"]
        )
        coordinator_macMultipleRetryCount_dict = calculate_node_average(
                results["coordinator_macMultipleRetryCount"]
        )

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
            plot_positions_and_values(positions, f"{prefix_name}_{dist_km}km_coordinator_to_device_pdr_plot.png", coordinator_to_device_average_pdr_dict[dist_km], bw1_khz, bw2_khz)
            plot_positions_and_values(positions, f"{prefix_name}_{dist_km}km_device_to_coordinator_pdr_plot.png", device_to_coordinator_average_pdr_dict[dist_km], bw1_khz, bw2_khz)
            plot_positions_and_values(positions, f"{prefix_name}_{dist_km}km_two_way_pdr_plot.png", two_way_average_pdr_dict[dist_km], bw1_khz, bw2_khz)
            plot_positions_and_values(positions, f"{prefix_name}_{dist_km}km_device_macRetryCount_plot.png", device_macRetryCount_dict[dist_km], bw1_khz, bw2_khz)
            plot_positions_and_values(positions, f"{prefix_name}_{dist_km}km_device_macMultipleRetryCount_plot.png", device_macMultipleRetryCount_dict[dist_km], bw1_khz, bw2_khz)
            plot_positions_and_values(positions, f"{prefix_name}_{dist_km}km_coordinator_macRetryCount_plot.png", coordinator_macRetryCount_dict[dist_km], bw1_khz, bw2_khz)
            plot_positions_and_values(positions, f"{prefix_name}_{dist_km}km_coordinator_macMultipleRetryCount_plot.png", coordinator_macMultipleRetryCount_dict[dist_km], bw1_khz, bw2_khz)
            plot_bar_chart(coordinator_macMultipleRetryCount_dict[dist_km] + coordinator_macRetryCount_dict[dist_km], f"MultipleRetryCount{dist_km}","MultipleRetryCount", f"a_{prefix_name}_{dist_km}.png")





        #stat_fileから全体の値を得る
        for filename in stat_files:
            match = FILENAME_STAT.match(filename.replace(f"{prefix_name}_", ""))
            if not match:
                print(f"Skipping file with unexpected name format: {filename}")
                continue

            dist_km = float(match.group(1))
            bw1_khz = float(match.group(2))
            bw2_khz = float(match.group(3))
            num_device = int(match.group(4))

            filepath = os.path.join(STATS_DIR, filename)
            metrics = pdr_and_throughput_parse_stat_file(filepath, num_device)

            #距離ごとのseed値のリスト
            results["distance_vs_pdr1"][dist_km].append(metrics["distance_vs_pdr1"])
            results["distance_vs_pdr2"][dist_km].append(metrics["distance_vs_pdr2"])
            results["distance_vs_throughput_kbps1"][dist_km].append(metrics["distance_vs_throughput_kbps1"])
            results["distance_vs_throughput_kbps2"][dist_km].append(metrics["distance_vs_throughput_kbps2"])
            results["end_to_end_delay"][dist_km].append(metrics["end_to_end_delay"])

        #10kmにおけるseed値を変えた結果のリストが出力される
        #print(results["pdr1"][10.0]) 

        #距離に対する平均pdrとthroughputの辞書
        avg_pdr1_by_distance = {}
        avg_pdr2_by_distance = {}
        avg_throughput1_by_distance = {}
        avg_throughput2_by_distance = {}
        
        # 標準誤差の辞書
        se_pdr1_by_distance = {}
        se_pdr2_by_distance = {}
        se_throughput1_by_distance = {}
        se_throughput2_by_distance = {}

        # --- 平均値と標準誤差の計算 (PDR) ---
        for dist_km, pdr_list in results["distance_vs_pdr1"].items():
            if pdr_list:
                # ★バグ修正：リストをNumpy配列に変換してから処理を行う（ddof=1を正しく適用するため）
                pdr_array = np.array(pdr_list)
                avg_pdr1_by_distance[dist_km] = np.mean(pdr_array)
                # 標準誤差の計算 (SE = SD / sqrt(N))
                se_pdr1_by_distance[dist_km] = np.std(pdr_array, ddof=1) / np.sqrt(len(pdr_array))
                
        for dist_km, pdr_list in results["distance_vs_pdr2"].items():
            if pdr_list:
                pdr_array = np.array(pdr_list)
                avg_pdr2_by_distance[dist_km] = np.mean(pdr_array)
                # 標準誤差の計算
                se_pdr2_by_distance[dist_km] = np.std(pdr_array, ddof=1) / np.sqrt(len(pdr_array))

        # --- 平均値と標準誤差の計算 (Throughput) ---
        for dist_km, throughput_list in results["distance_vs_throughput_kbps1"].items():
            if throughput_list:
                # ★バグ修正：リストをNumpy配列に変換してから処理を行う
                throughput_array = np.array(throughput_list)
                avg_throughput1_by_distance[dist_km] = np.mean(throughput_array)
                # 標準誤差の計算
                se_throughput1_by_distance[dist_km] = np.std(throughput_array, ddof=1) / np.sqrt(len(throughput_array))
        
        for dist_km, throughput_list in results["distance_vs_throughput_kbps2"].items():
            if throughput_list:
                throughput_array = np.array(throughput_list)
                avg_throughput2_by_distance[dist_km] = np.mean(throughput_array)
                # 標準誤差の計算
                se_throughput2_by_distance[dist_km] = np.std(throughput_array, ddof=1) / np.sqrt(len(throughput_array))

        # Create plot directory if it doesn't exist
        os.makedirs(PLOT_OUTPUT_DIR, exist_ok=True)
        print(f"Plot output directory: {os.path.abspath(PLOT_OUTPUT_DIR)}")

        # Generate plots
        plot_metric(
            avg_pdr1_by_distance,
            se_pdr1_by_distance, 
            avg_pdr2_by_distance,
            se_pdr2_by_distance, 
            "Packet Delivery Ratio (PDR)",
            "PDR vs. Distance between Coordinators",
            os.path.join(PLOT_OUTPUT_DIR, f"{prefix_name}_pdr.png"),
            bw1_khz,
            bw2_khz
        )

        # 2. Throughput Plot
        plot_metric(
            avg_throughput1_by_distance,
            se_throughput1_by_distance, 
            avg_throughput2_by_distance,
            se_throughput2_by_distance, 
            "MAC Throughput (kbps)",
            "Throughput vs. Distance between Coordinators",
            os.path.join(PLOT_OUTPUT_DIR, f"{prefix_name}_throughput.png"),
            bw1_khz,
            bw2_khz
        )

        """
        average_end_to_end_dict = {}
        for data_km in results["end_to_end_delay"].items():
            dist_km, data = data_km
            data_for_distance = data

            # 1. NumPy配列に変換 (2次元配列になる)
            end_to_end_delay_array = np.array(data_for_distance)

            # 2. 【核心】軸 (axis=0) を指定して平均を計算
            #    axis=0 (行方向) を指定することで、同じ列 (インデックス/ノード) 同士の平均が計算される
            average_end_to_end_index = np.round(np.mean(end_to_end_delay_array, axis=0), 2)
            average_end_to_end_dict[dist_km] = average_end_to_end_index

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
            plot_positions_and_values(positions, f"{prefix_name}_{dist_km}km_node_end_to_end_delya_plot.png", average_end_to_end_dict[dist_km], bw1_khz, bw2_khz)

        """
def calculate_node_average(results_dict):
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

"""
def parse_trace_file(filepath, num_device):
    rssi_list = [0.0 for _ in range(3 * num_device)] 
    count_rssi_additions = [0 for _ in range(3 * num_device)] 

    with open(filepath, "r") as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            
            if "DrIotPhy" in parts[5] and "1" in parts[3] and "RxEnd" in parts[9]:
                pkt_id = parts[11]
                devicenum_ber = int(pkt_id.split('_')[0])
                rssi_list[devicenum_ber] += float(parts[13])
                count_rssi_additions[devicenum_ber] += 1
                #if devicenum_ber == 12:
                   # print(float(parts[13]))
            
            if "DrIotPhy" in parts[5] and "2" in parts[3] and "RxEnd" in parts[9]:
                pkt_id = parts[11]
                devicenum_ber = int(pkt_id.split('_')[0])
                rssi_list[devicenum_ber] += float(parts[13])
                count_rssi_additions[devicenum_ber] += 1

        for device_id in range(3 * num_device):
            rssi = rssi_list[device_id]
            num = count_rssi_additions[device_id]
            if rssi != 0 or num != 0:
                rssi_list[device_id] = round(rssi/num,1)
    
    return rssi_list
"""


def pdr_and_throughput_parse_stat_file(filepath, num_device):
    """Parses a single .stat file to extract key metrics."""
    packets_sent1 = 0
    packets_received1 = 0
    packets_sent2 = 0
    packets_received2 = 0
    bytes_received_mac1 = 0
    bytes_received_mac2 = 0
    end_to_end_delay = [0.0 for _ in range(3 * num_device)]

    sim_time = 30.0
    SENDER_ID_RANGE1 = [str(i) for i in range(3, num_device + 3)] 
    SENDER_ID_RANGE1.append("1")
    
    SENDER_ID_RANGE2 = [str(i) for i in range(num_device + 3, 2*num_device + 3)] 
    SENDER_ID_RANGE2.append("2")
    
    
    with open(filepath, "r") as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue

            # 3~12の送信デバイスの送信パケット量
            if parts[0] in SENDER_ID_RANGE1 and "DrIotMac" in parts[1] and "FramesDequeued" in parts[1]:
                packets_sent1 += int(parts[3])
            # 13~22の送信デバイスの送信パケット量
            if parts[0] in SENDER_ID_RANGE2 and "DrIotMac" in parts[1] and "FramesDequeued" in parts[1]:
                packets_sent2 += int(parts[3])
            
            # Node 1,2 is the coordinator
            if (
                parts[0] in SENDER_ID_RANGE1
                and "DrIotMac" in parts[1]
                and "Data_FramesReceived" in parts[1]
            ):
                packets_received1 += int(parts[3])
            if (
                parts[0] in SENDER_ID_RANGE1
                and "DrIotMac" in parts[1]
                and "BytesSentToUpperLayer" in parts[1]
            ):
                bytes_received_mac1 += int(parts[3])

            if (
                parts[0] in SENDER_ID_RANGE2
                and "DrIotMac" in parts[1]
                and "Data_FramesReceived" in parts[1]
            ):
                packets_received2 += int(parts[3])
            if (
                parts[0] in SENDER_ID_RANGE2
                and "DrIotMac" in parts[1]
                and "BytesSentToUpperLayer" in parts[1]
            ):
                bytes_received_mac2 += int(parts[3])

            if("DrIotMac" in parts[1] and "DataFrameEndToEndDelay" in parts[1]):
                device_num = int(parts[0])
                if("-" == parts[3]):
                    end_to_end_delay[device_num] = 0
                else:
                    end_to_end_delay[device_num] = float(parts[3])        

    pdr1 = packets_received1 / packets_sent1 if packets_sent1 > 0 else 0.0
    pdr2 = packets_received2 / packets_sent2 if packets_sent2 > 0 else 0.0

    if sim_time == 0:
        throughput_kbps1 = 0.0
        throughput_kbps2 = 0.0
        
    else:
        throughput_kbps1 = (bytes_received_mac1 * 8) / sim_time / 1000
        throughput_kbps2 = (bytes_received_mac2 * 8) / sim_time / 1000

    return {
        "distance_vs_pdr1": pdr1,
        "distance_vs_pdr2": pdr2,
        "distance_vs_throughput_kbps1": throughput_kbps1,
        "distance_vs_throughput_kbps2": throughput_kbps2,
        "end_to_end_delay": end_to_end_delay
    }

def node_parse_trace_file(filepath,num_device):
    #device → coordinator
    device_dequed_list = [0 for _ in range(3 * num_device)]
    coordinator_receive_list = [0 for _ in range(3 * num_device)]
    device_received_ack_list = [0 for _ in range(3 * num_device)]

    #coordinator → device
    coordinator_dequed_list = [0 for _ in range(3 * num_device)]
    device_receive_list = [0 for _ in range(3 * num_device)]
    coordinator_received_ack_list = [0 for _ in range(3 * num_device)]

    device_to_coordinator_pdr_list = [0.0 for _ in range(3 * num_device)]
    coordinator_to_device_pdr_list = [0.0 for _ in range(3 * num_device)]
    two_way_pdr_list = [0.0 for _ in range(3 * num_device)]

    coordinator1_destination_devicenum_ber = 0
    coordinator2_destination_devicenum_ber = 0
    device_TxsuccessCount = [0 for _ in range(3 * num_device)]
    coordinator_TxsuccessCount = [0 for _ in range(3 * num_device)]
    device_currentRetry_list = [0 for _ in range(3 * num_device)]
    coordinator_currentRetry_list = [0 for _ in range(3 * num_device)]
    coordinator_macRetryCount_list = [0 for _ in range(3 * num_device)]
    coordinator_macRetryCount_ratio = [0 for _ in range(3 * num_device)]

    device_macRetryCount_list = [0 for _ in range(3 * num_device)]
    device_macRetryCount_ratio = [0 for _ in range(3 * num_device)]


    coordinator_macMultipleRetryCount_list = [0 for _ in range(3 * num_device)]
    coordinator_macMultipleRetryCount_ratio = [0 for _ in range(3 * num_device)]

    device_macMultipleRetryCount_list = [0 for _ in range(3 * num_device)]
    device_macMultipleRetryCount_ratio = [0 for _ in range(3 * num_device)]

    macFcsErrorCount_list = [0.0 for _ in range(3 * num_device)]

    SENDER_ID_RANGE1 = [int(i) for i in range(3, num_device + 3)] 

    with open(filepath, "r") as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue

            #coordinator
            if "DrIotMac" in parts[5] and ( "1" == parts[3] or  "2" == parts[3]):
                #retryの送信する場所とその場所ごとのretry回数の記憶
                if "Tx-DATA" in parts[9]:
                    if "1" == parts[3]:
                        devicenum_ber = coordinator1_destination_devicenum_ber
                    elif "2" == parts[3]:
                        devicenum_ber = coordinator2_destination_devicenum_ber

                    num_retry =  int(parts[13])
                    coordinator_currentRetry_list[devicenum_ber] = num_retry
                
                if "DataFrameDequeued" in parts[9]:
                    devicenum_ber = int(parts[15]) #DestNodeId
                    coordinator_dequed_list[devicenum_ber] += 1
                    if "1" == parts[3]:
                        coordinator1_destination_devicenum_ber = devicenum_ber
                    elif "2" == parts[3]:
                        coordinator2_destination_devicenum_ber = devicenum_ber

                    if devicenum_ber in SENDER_ID_RANGE1:
                        coordinator_dequed_list[1] += 1
                    else:
                        coordinator_dequed_list[2] += 1

                if "RxFrame" in parts[9]:
                    pkt_id = parts[11]
                    devicenum_ber = int(pkt_id.split('_')[0])
                    #coordinatorが受信機
                    if "Data" in parts[15]:
                        coordinator_receive_list[devicenum_ber] += 1
                        if devicenum_ber in SENDER_ID_RANGE1:
                            coordinator_receive_list[1] += 1
                        else:
                            coordinator_receive_list[2] += 1

                    #coordinatorが送信機
                    if "ACK" in parts[15]:
                        coordinator_received_ack_list[devicenum_ber] += 1

                        if coordinator_currentRetry_list[devicenum_ber] == 0:
                            coordinator_TxsuccessCount[devicenum_ber] += 1
                        elif coordinator_currentRetry_list[devicenum_ber] == 1:
                            coordinator_macRetryCount_list[devicenum_ber] += 1
                        elif coordinator_currentRetry_list[devicenum_ber] > 1:
                            coordinator_macMultipleRetryCount_list[devicenum_ber] += 1

            #device
            if "DrIotMac" in parts[5] and parts[3]!= "1" and parts[3]!= "2":
                devicenum_ber = int(parts[3])
                if "Tx-DATA" in parts[9]:
                    num_retry =  int(parts[13])
                    device_currentRetry_list[devicenum_ber] = num_retry

                if "DataFrameDequeued" in parts[9] :
                    device_dequed_list[devicenum_ber] += 1
                    if devicenum_ber in SENDER_ID_RANGE1:
                        device_dequed_list[1] += 1
                    else:
                        device_dequed_list[2] += 1

                if "RxFrame" in parts[9]: 
                    if "Data" in parts[15]:
                        device_receive_list[devicenum_ber] += 1
                        if devicenum_ber in SENDER_ID_RANGE1:
                            device_receive_list[1] += 1
                        else:
                            device_receive_list[2] += 1
                    
                    if "ACK" in parts[15]:
                        device_received_ack_list[devicenum_ber] += 1

                        if device_currentRetry_list[devicenum_ber] == 0:
                            device_TxsuccessCount[devicenum_ber] += 1
                        elif device_currentRetry_list[devicenum_ber] == 1:
                            device_macRetryCount_list[devicenum_ber] += 1
                        elif device_currentRetry_list[devicenum_ber] > 1:
                            device_macMultipleRetryCount_list[devicenum_ber] += 1


        for device_id in range(3 * num_device):
            two_way_dequed = coordinator_dequed_list[device_id] + device_dequed_list[device_id] 
            two_way_received_ack = coordinator_received_ack_list[device_id] + device_received_ack_list[device_id]

            if coordinator_dequed_list[device_id] != 0  and device_dequed_list[device_id]  != 0 and \
                device_received_ack_list[device_id] != 0 and coordinator_received_ack_list[device_id] != 0:

                coordinator_to_device_pdr_list[device_id] = round(coordinator_received_ack_list[device_id]/coordinator_dequed_list[device_id],3)
                device_to_coordinator_pdr_list[device_id] = round(device_received_ack_list[device_id]/device_dequed_list[device_id],3)
                two_way_pdr_list[device_id] = round(two_way_received_ack/two_way_dequed,3)
                device_macRetryCount_ratio[device_id] = (device_macRetryCount_list[device_id]/(device_received_ack_list[device_id]))
                device_macMultipleRetryCount_ratio[device_id] = (device_macMultipleRetryCount_list[device_id]/(device_received_ack_list[device_id]))
                coordinator_macRetryCount_ratio[device_id] = (coordinator_macRetryCount_list[device_id]/(coordinator_received_ack_list[device_id]))
                coordinator_macMultipleRetryCount_ratio[device_id] = (coordinator_macMultipleRetryCount_list[device_id]/(coordinator_received_ack_list[device_id]))


        return coordinator_to_device_pdr_list, device_to_coordinator_pdr_list, two_way_pdr_list, \
        device_macRetryCount_ratio, device_macMultipleRetryCount_ratio, coordinator_macRetryCount_ratio, \
        coordinator_macMultipleRetryCount_ratio


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


def plot_bar_chart(data_array, title, y_label, output_filename):
    
    # 1. データとインデックスの準備
    values = np.array(data_array)
    # 配列番号 (インデックス) を横軸にする
    indices = np.arange(len(values))
    
    # 2. 平均値の計算
    if len(values) == 0:
        print("Error: Input array is empty. Cannot generate chart.")
        return
    average_value = 0.0
    for device_id in indices:
        if device_id in C1_DEV_RANGE or device_id in C2_DEV_RANGE:
            average_value += data_array[device_id] 
    average_value = average_value / 24

    # 3. グラフの作成
    plt.figure(figsize=(12, 6))

    # 棒グラフの描画
    plt.bar(indices, values, color='skyblue', label='Individual Value')

    # 平均値を点線でプロット
    plt.axhline(
        average_value, 
        color='red', 
        linestyle='--', 
        linewidth=2, 
        label=f'Average ({average_value:.2f})'
    )

    # 4. グラフの整形
    plt.xlabel("Array Index (Array Number)")
    plt.ylabel(y_label)
    plt.title(title)
    plt.xticks(indices) # X軸の目盛りをインデックスに合わせる
    plt.grid(axis='y', linestyle=':', alpha=0.7)
    plt.legend()

    # 5. ファイル出力 (余白を詰めて保存)
    output_filename = os.path.join(PLOT_OUTPUT_DIR, output_filename)
    os.makedirs(PLOT_OUTPUT_DIR, exist_ok=True)
    
    plt.tight_layout()
    plt.savefig(output_filename, bbox_inches='tight', pad_inches=0.05)
    plt.close()
    print(f"Plot saved to: {output_filename}")



# --- plot_metric (修正箇所) ---
def plot_metric(data1, se_data1, data2, se_data2, y_label, title, output_filename, bw1_khz, bw2_khz):

    plt.figure(figsize=(10, 6))

    # Channel 1 Data
    distances1 = sorted(data1.keys())
    metric_values1 = [data1[d] for d in distances1]
    se_values1 = [se_data1[d] for d in distances1]
    
    # Channel 2 Data
    distances2 = sorted(data2.keys())
    metric_values2 = [data2[d] for d in distances2]
    se_values2 = [se_data2[d] for d in distances2]
    
    # 信頼区間の乗数。Numpyのみを使用する場合、95%信頼区間の厳密な計算はできませんが、
    # 統計的なプロットとして一般的に使われる「標準誤差 (SE)」自体をエラーバーとしてプロットします。
    t_multiplier = 1.0 # SEのみを表示する場合は 1.0

    # Plotting (Channel 1)
    plt.errorbar(
        distances1, 
        metric_values1, 
        yerr=[x * t_multiplier for x in se_values1], # エラーバーの追加
        marker='o', 
        linestyle='-', 
        color='#005AFF', 
        capsize=5, # エラーバーのキャップのサイズ
        label=f'{bw1_khz} kHz coordinator'
    )
    
    # Plotting (Channel 2)
    plt.errorbar(
        distances2, 
        metric_values2, 
        yerr=[x * t_multiplier for x in se_values2], # エラーバーの追加
        marker='s', 
        linestyle='--', 
        color="#FF3300", 
        capsize=5, 
        label=f'{bw2_khz} kHz coordinator'
    )

    # Formatting
    plt.xlabel("Distance between Coordinators (km)")
    plt.ylabel(y_label)
    plt.title(title)
    #plt.grid(True, linestyle='--', alpha=0.7)
    plt.axvline(x=1.01, color='#808080', linestyle='--', label='Maximum Communication Distance (x=1.01)')
    plt.legend(title="Channel Bandwidth")

    # X軸の範囲をデータに基づいて設定する（もしデータが50kmを超えないならこのままでOK）
    plt.xlim(left=0.0, right=2.6) 
    
    if "PDR" in y_label:
        plt.ylim(0, 1.05)
    else:
        plt.ylim(bottom=0)

    plt.savefig(output_filename)
    plt.close()
    print(f"Plot saved to: {output_filename}")


if __name__ == "__main__":
    main()
