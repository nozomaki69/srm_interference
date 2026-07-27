# -*- coding: utf-8 -*-

import os
import sys
import random
import math
import numpy as np
from jinja2 import Environment, FileSystemLoader, StrictUndefined

# --- パラメータ定義 ---

base_freq_mhz = 920  #920MHz
FRAME_SIZE = 250
CHANNELS = [
    #IEEE 802.15.4(2024), pp.719
    #非同期検波と仮定し、カーソンの定理よりチャネルの帯域幅は伝送速度の3倍
    #Operating mode #1
    {
        "id": 0,
        "freq_mhz": base_freq_mhz,
        "width_mhz": 150e3 / 1e6, #0.15
        "rx_sensitivity_dbm": -97.0,
        "bitrate_kbps": 50,
    },
    #Operating mode #2
    {
        "id": 1,
        "freq_mhz": base_freq_mhz,
        "width_mhz": 300e3 / 1e6, #0.3
        "rx_sensitivity_dbm": -93.989700,
        "bitrate_kbps": 200,
    },  
    #Operating mode #3
    {
        "id": 2,
        "freq_mhz": base_freq_mhz,
        "width_mhz": 600e3 / 1e6, #0.6
        "rx_sensitivity_dbm": -90.979400,
        "bitrate_kbps": 600,
    }, 
    {
        "id": 3,
        "freq_mhz": base_freq_mhz -1,
        "width_mhz": 150e3 / 1e6, #0.15
        "rx_sensitivity_dbm": -97.0,
        "bitrate_kbps": 50,
    },
    #Operating mode #2
    {
        "id": 4,
        "freq_mhz": base_freq_mhz -1,
        "width_mhz": 300e3 / 1e6, #0.3
        "rx_sensitivity_dbm": -93.989700,
        "bitrate_kbps": 100,
    },  
    #Operating mode #3
    {
        "id": 5,
        "freq_mhz": base_freq_mhz-1,
        "width_mhz": 600e3 / 1e6, #0.6
        "rx_sensitivity_dbm": -90.979400,
        "bitrate_kbps": 200,
    },  
]
ED_THRESHOLDS = {
    0: CHANNELS[0]["rx_sensitivity_dbm"] + 10,
    1: CHANNELS[1]["rx_sensitivity_dbm"] + 10,
    2: CHANNELS[2]["rx_sensitivity_dbm"] + 10,
    3: CHANNELS[3]["rx_sensitivity_dbm"] + 10,
    4: CHANNELS[4]["rx_sensitivity_dbm"] + 10,
    5: CHANNELS[5]["rx_sensitivity_dbm"] + 10,
}
MAXIMUM_COMMUNICATION_RANGE = {
    0: 1.4414098800604656,
    1: 1.212076401054132,
    2: 1.0192307006600434,
}

TARGET_BANDWIDTH_PATTERNS = [[0, 0], [0, 1], [0, 2], [1, 1], [1, 2], [2, 2], [0, 3], [0, 4], [0, 5], [1, 4], [1, 5], [2, 5]]
NUM_DEVICE = 10
DEVICE_ID_1 = list(range(3, NUM_DEVICE + 3))
DEVICE_ID_2= list(range(NUM_DEVICE + 3, NUM_DEVICE + NUM_DEVICE + 3))

DISTANCES_M = 1500
SIMULATION_SEEDS = 3
MEASURE_START_SEC = 20.0
MEASURE_DURATION_SEC = 100.0
MEASURE_END_SEC = MEASURE_START_SEC + MEASURE_DURATION_SEC
SIM_DURATION_SEC = MEASURE_END_SEC + MEASURE_START_SEC
MY_TRACE_TAGS = ['Mac'] #MY_TRACE_TAGS = ['Application']

# --- スクリプト設定 ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(SCRIPT_DIR, "../template/")  # commandline/template/
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..")  # commandline/

# テンプレートファイル名
CONFIG_TEMPLATE = "TEMPLATE.config.j2"
POS_TEMPLATE = "TEMPLATE.pos.j2"
STAT_TEMPLATE = "TEMPLATE.statconfig.j2"

pan1_offload_min = 0.1
pan1_offload_max = 0.3
pan2_offload_min = 0.1
pan2_offload_max = 0.3


def generate_uniform_circle_coords(center_x, center_y, radius, num_devices):
    """
    中心(x, y)から指定された半径内に一様にデバイスを配置する
    """
    # 0から1の間のランダムな値を生成
    u = np.random.rand(num_devices)
    v = np.random.rand(num_devices)
    
    # 半径方向の計算 (sqrtを使うことで中心付近の密集を防ぎ、一様に分散させる)
    r = radius * np.sqrt(u)
    # 角度方向の計算 (0 to 2π)
    theta = 2 * np.pi * v
    
    # 極座標から直交座標(x, y)に変換
    x = center_x + r * np.cos(theta)
    y = center_y + r * np.sin(theta)
    
    return x, y

def main():
    try:
        env = Environment(
            loader=FileSystemLoader(TEMPLATE_DIR),
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=StrictUndefined,
        )
        config_template = env.get_template(CONFIG_TEMPLATE)
        pos_template = env.get_template(POS_TEMPLATE)
        stat_template = env.get_template(STAT_TEMPLATE)
    except Exception as e:
        print(
            f"Error: Failed to load template files.\n  Location: {TEMPLATE_DIR}\n  Details: {e}",
            file=sys.stderr,
        )
        sys.exit(1)
        
    """メイン処理"""
    for bandwidth_pattern in TARGET_BANDWIDTH_PATTERNS:
        interference_flag = 0
        pan1_bandwidth = CHANNELS[bandwidth_pattern[0]]["freq_mhz"]
        pan2_bandwidth = CHANNELS[bandwidth_pattern[1]]["freq_mhz"]

        if pan1_bandwidth == pan2_bandwidth:
            interference_flag = 1
        
        for offered_load_pan2 in np.arange(pan2_offload_min, pan2_offload_max, 0.1):
            OFFERED_LOAD_PAN2 = round(float(offered_load_pan2), 1)

            for offered_load_pan1 in np.arange(pan1_offload_min, pan1_offload_max, 0.1):
                    OFFERED_LOAD_PAN1 = round(float(offered_load_pan1), 1)

                    for seed in range(SIMULATION_SEEDS):
                        np.random.seed(seed)

                        #エンドデバイスの分布範囲
                        x1, y1 = generate_uniform_circle_coords(0, 0, 1400, NUM_DEVICE)
                        x2, y2 = generate_uniform_circle_coords(DISTANCES_M, 0, 1000, NUM_DEVICE)

                        total_files = 0
                        
                        if interference_flag == 1:
                            prefix = f"interf_dist_{DISTANCES_M}m_channel_{bandwidth_pattern[0]}_vs_{bandwidth_pattern[1]}_pan1_{OFFERED_LOAD_PAN1}_pan2_{OFFERED_LOAD_PAN2}_seed{seed}"
                        else:
                            prefix = f"no_interf_dist_{DISTANCES_M}m_channel_{bandwidth_pattern[0]}_vs_{bandwidth_pattern[1]}_pan1_{OFFERED_LOAD_PAN1}_pan2_{OFFERED_LOAD_PAN2}_seed{seed}"
                        
                        all_nodes = [] # 新しいノードリストを初期化

                        print(prefix)

                        # Coordinatorノードの定義
                        coordinator_node_1= {
                            "id": 1,
                            "pan_id": 0,
                            "mode": "coordinator",
                            "pos_list": [{"time": 0, "x": 0, "y": 0}],
                            "interfaces": [{"mode": "PanCoordinator", "init_ch": bandwidth_pattern[0]}],
                            "associated_device_table": DEVICE_ID_1,  # Device ID 2を静的に関連付け
                            "init_block_index": 0,
                            "init_block_count": 1,
                            "desired_channel_bandwidth": CHANNELS[bandwidth_pattern[0]]["width_mhz"]*1e3,
                            "desired_block_count": 1,
                            "cbr_applications": [],
                            "preamble_power": CHANNELS[bandwidth_pattern[0]]["rx_sensitivity_dbm"],
                            "ed_threshold_dbm": ED_THRESHOLDS[bandwidth_pattern[0]],
                        }
                        for dev_id in DEVICE_ID_1:
                            coordinator_node_1["cbr_applications"].append({
                                    "dst": dev_id,  # Coordinator 1宛て
                                    "bps": ((CHANNELS[bandwidth_pattern[0]]["bitrate_kbps"]*1e3/(NUM_DEVICE +1)) * OFFERED_LOAD_PAN1),
                                    "start": MEASURE_START_SEC,
                                    "end": MEASURE_END_SEC,
                                    "jitter": 1.0,
                                    "payload_size": FRAME_SIZE - 15,  # MACヘッダを引いたサイズ
                                    "is_ack_required": True,
                            })
                        all_nodes.append(coordinator_node_1)

                        coordinator_node_2 = {
                            "id": 2,
                            "pan_id": 1, # PAN IDを2に設定（衝突回避のため）
                            "mode": "coordinator",
                            "pos_list": [{"time": 0, "x": DISTANCES_M, "y": 0}], 
                            "interfaces": [{"mode": "PanCoordinator", "init_ch": bandwidth_pattern[1]}],
                            "associated_device_table": DEVICE_ID_2,
                            "init_block_index": 0,
                            "init_block_count": 1,
                            "desired_channel_bandwidth": CHANNELS[bandwidth_pattern[1]]["width_mhz"]*1e3,
                            "desired_block_count": 1,
                            "cbr_applications": [],
                            "preamble_power": CHANNELS[bandwidth_pattern[1]]["rx_sensitivity_dbm"],
                            "ed_threshold_dbm": ED_THRESHOLDS[bandwidth_pattern[1]],
                        }
                        for dev_id in DEVICE_ID_2:
                            coordinator_node_2["cbr_applications"].append({
                                    "dst": dev_id,  # Coordinator 1宛て
                                    "bps": ((CHANNELS[bandwidth_pattern[1]]["bitrate_kbps"]*1e3/(NUM_DEVICE +1)) * OFFERED_LOAD_PAN2),
                                    "start": MEASURE_START_SEC,
                                    "end": MEASURE_END_SEC,
                                    "jitter": 1.0,
                                    "payload_size": FRAME_SIZE - 15,  # MACヘッダを引いたサイズ
                                    "is_ack_required": True,
                            })
                        all_nodes.append(coordinator_node_2)

                        for i, dev_id in enumerate(DEVICE_ID_1):
                            device_node_1 = {
                                "id": dev_id,
                                "pan_id": 0,
                                "mode": "device",
                                "pos_list": [{"time": 0, "x": x1[i], "y": y1[i]}],
                                "interfaces": [{"mode": "Device", "init_ch": bandwidth_pattern[0]}],
                                "associated": True,  # 静的に関連付け済み
                                "cbr_applications": [{
                                    "dst": 1,  # Coordinator 1宛て
                                    "bps": ((CHANNELS[bandwidth_pattern[0]]["bitrate_kbps"]*1e3/(NUM_DEVICE +1)) * OFFERED_LOAD_PAN1),
                                    "start": MEASURE_START_SEC,
                                    "end": MEASURE_END_SEC,
                                    "jitter": 20.0,
                                    "payload_size": FRAME_SIZE - 15,  # MACヘッダを引いたサイズ
                                    "is_ack_required": True,
                                }],
                                "preamble_power": CHANNELS[bandwidth_pattern[0]]["rx_sensitivity_dbm"],
                                "ed_threshold_dbm": ED_THRESHOLDS[bandwidth_pattern[0]],
                            }
                            all_nodes.append(device_node_1)


                        for i, dev_id in enumerate(DEVICE_ID_2):
                            device_node_2 = {
                                "id": dev_id,
                                "pan_id": 1,
                                "mode": "device",
                                "pos_list": [{"time": 0, "x": x2[i], "y": y2[i]}],
                                "interfaces": [{"mode": "Device", "init_ch": bandwidth_pattern[1]}],
                                "associated": True,  # 静的に関連付け済み
                                "cbr_applications": [{
                                    "dst": 2,  # Coordinator 1宛て
                                    "bps": ((CHANNELS[bandwidth_pattern[1]]["bitrate_kbps"]*1e3/(NUM_DEVICE +1)) * OFFERED_LOAD_PAN2),
                                    "start": MEASURE_START_SEC,
                                    "end": MEASURE_END_SEC,
                                    "jitter": 20.0,
                                    "payload_size": FRAME_SIZE - 15,  # MACヘッダを引いたサイズ
                                    "is_ack_required": True,
                                }],
                                "preamble_power": CHANNELS[bandwidth_pattern[1]]["rx_sensitivity_dbm"],
                                "ed_threshold_dbm": ED_THRESHOLDS[bandwidth_pattern[1]],
                            }
                            all_nodes.append(device_node_2)


                            # テンプレートに渡すfメインのコンテキスト
                        context = {
                            "label": prefix,
                            "config_filename_prefix": prefix,
                            "seed": seed,
                            "sim_time": MEASURE_END_SEC,
                            "mobility_seed": seed,
                            "band_name": "DrIotTestBand",
                            "measure_start": MEASURE_START_SEC,
                            "measure_end": SIM_DURATION_SEC - 10.0,
                            "is_6lowpan_enabled": False,
                            "advertising_channel_number": 0,
                            "nodes": all_nodes,
                            "tx_power": 13.010299956639813, # dBm
                            "trace_tags": MY_TRACE_TAGS,
                            "cca_mode": "ED_or_CS",
                            "channels": CHANNELS,

                        }

                        # --- ファイル生成 ---
                        try:
                            # .config
                            with open(os.path.join(OUTPUT_DIR, f"{prefix}.config"), "w") as f:
                                f.write(config_template.render(context))
                            # .pos
                            with open(os.path.join(OUTPUT_DIR, f"{prefix}.pos"), "w") as f:
                                f.write(pos_template.render(context))
                            # .statconfig
                            with open(os.path.join(OUTPUT_DIR, f"{prefix}.statconfig"), "w") as f:
                                f.write(stat_template.render(context))

                            total_files += 3
                        except Exception as e:
                            print(
                                f"\nError: Problem occurred while generating files for {prefix}.",
                                file=sys.stderr,
                            )
                            print(f"  Details: {e}", file=sys.stderr)
                            sys.exit(1)


if __name__ == "__main__":
    main()

