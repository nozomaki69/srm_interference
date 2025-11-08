# -*- coding: utf-8 -*-
"""
driot_measure_communication_dist シナリオ用の設定ファイル生成スクリプト (改訂版)

機能:
- テンプレートが期待するデータ構造を生成する。
- 距離とチャネル帯域幅の全組み合わせに対応する設定ファイルを生成する。
- 生成されたファイルは、一つ上の階層のディレクトリ (commandline/) に出力される。
"""

import os
import sys
import random
import numpy as np
from jinja2 import Environment, FileSystemLoader, StrictUndefined


# --- パラメータ定義 ---

CHANNELS = {
    0:  {"ch": 0, "bandwidth": 150.0, "bitrate": 50e3,   "frame_size": 255,  "preamble_power": -97.0, "range_km": 1.4414098800604656}, #周波数920MHz
    1:  {"ch": 1, "bandwidth": 150.0, "bitrate": 50e3,   "frame_size": 255,  "preamble_power": -97.0, "range_km": 1.4414098800604656}, #周波数921MHz
    2:  {"ch": 2, "bandwidth": 600.0, "bitrate": 200e3,  "frame_size": 511,  "preamble_power": -90.97940008672037, "range_km": 1.0192307006600434},#周波数920MHz
}
TARGET_BANDWIDTH_PATTERNS = [[0, 2],[1, 2]]
NUM_DEVICE = 12
DEVICE_ID_1 = list(range(3, NUM_DEVICE + 3))
DEVICE_ID_2= list(range(NUM_DEVICE + 3, NUM_DEVICE + NUM_DEVICE + 3))

DISTANCES_KM = np.round(np.arange(0.0, 2.5, 0.1),1)
SIMULATION_SEEDS = 3
OFFERED_LOAD = 0.7
 
MEASURE_START_SEC = 10.0
MEASURE_DURATION_SEC = 30.0
MEASURE_END_SEC = MEASURE_START_SEC + MEASURE_DURATION_SEC
SIM_DURATION_SEC = MEASURE_END_SEC + MEASURE_START_SEC
MY_TRACE_TAGS = ['Application', 'Mac']
#MY_TRACE_TAGS = ['Application']


# --- スクリプト設定 ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(SCRIPT_DIR, "../template/")  # commandline/template/
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..")  # commandline/

# テンプレートファイル名
CONFIG_TEMPLATE = "TEMPLATE.config.j2"
POS_TEMPLATE = "TEMPLATE.pos.j2"
STAT_TEMPLATE = "TEMPLATE.statconfig.j2"


def main():
    """メイン処理"""
    for bandwidth_pattern in TARGET_BANDWIDTH_PATTERNS:
        c1_info = CHANNELS[bandwidth_pattern[0]]
        c2_info = CHANNELS[bandwidth_pattern[1]]
        if c1_info == CHANNELS[0]:
            interference = 1
        else:
            interference = 0
            
        for seed in range(SIMULATION_SEEDS):
            try:
                # undefined=StrictUndefined: 未定義変数があればエラーで停止
                # lstrip_blocks=True: タグの前の空白を削除し、不要��空行を抑制
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

            print(
                f"Starting to generate configuration files...\nOutput directory: {os.path.abspath(OUTPUT_DIR)}"
            )
            device_x = [-2, -1, -1, -1, 0, 0,  0,  0, 1, 1,  1, 2]
            device_y = [ 0,  1,  0, -1, 2, 1, -1, -2, 1, 0, -1, 0]

            #device_x = [-1, -1, -1,  0,  1, 1, 1, 0, -2,  0, 2, 0]
            #device_y = [ 1,  0, -1, -1, -1, 0, 1, 1,  0, -2, 0, 2]
            total_files = 0
            for dist_km in DISTANCES_KM: #コーディネータ間の距離
                if interference == 1:
                    prefix = f"interference_dist_{dist_km}km_bw_{c1_info['bandwidth']}and{c2_info['bandwidth']}khz_num_device{NUM_DEVICE}_seed{seed}"
                else:
                    prefix = f"non_interference_dist_{dist_km}km_bw_{c1_info['bandwidth']}and{c2_info['bandwidth']}khz_num_device{NUM_DEVICE}_seed{seed}"

                all_nodes = [] # 新しいノードリストを初期化

                # Coordinatorノードの定義
                coordinator_node_1= {
                    "id": 1,
                    "pan_id": 0,
                    "mode": "coordinator",
                    "pos_list": [{"time": 0, "x": 0, "y": 0}],
                    "interfaces": [{"mode": "PanCoordinator", "init_ch": c1_info["ch"]}],
                    "associated_device_table": DEVICE_ID_1,  # Device ID 2を静的に関連付け
                    "init_block_index": 0,
                    "init_block_count": 1,
                    "desired_channel_bandwidth": c1_info["bandwidth"],
                    "desired_block_count": 1,
                    "cbr_applications": [],
                    "preamble_power": c1_info["preamble_power"],
                }
                for dev_id in DEVICE_ID_1:
                    coordinator_node_1["cbr_applications"].append({
                            "dst": dev_id,  # Coordinator 1宛て
                            "bps": (c1_info["bitrate"]/24) * OFFERED_LOAD,
                            "start": MEASURE_START_SEC,
                            "end": MEASURE_END_SEC,
                            "jitter": 1.0,
                            "payload_size": c1_info["frame_size"] - 15,  # MACヘッダを引いたサイズ
                            "is_ack_required": True,
                    })
                all_nodes.append(coordinator_node_1)

                coordinator_node_2 = {
                    "id": 2,
                    "pan_id": 1, # PAN IDを2に設定（衝突回避のため）
                    "mode": "coordinator",
                    "pos_list": [{"time": 0, "x": dist_km * 1000, "y": 0}], 
                    "interfaces": [{"mode": "PanCoordinator", "init_ch": c2_info["ch"]}],
                    "associated_device_table": DEVICE_ID_2,
                    "init_block_index": 0,
                    "init_block_count": 1,
                    "desired_channel_bandwidth": c2_info["bandwidth"],
                    "desired_block_count": 1,
                    "cbr_applications": [],
                    "preamble_power": c2_info["preamble_power"],
                }
                for dev_id in DEVICE_ID_2:
                    coordinator_node_2["cbr_applications"].append({
                            "dst": dev_id,  # Coordinator 1宛て
                            "bps": (c2_info["bitrate"]/24) * OFFERED_LOAD,
                            "start": MEASURE_START_SEC,
                            "end": MEASURE_END_SEC,
                            "jitter": 1.0,
                            "payload_size": c2_info["frame_size"] - 15,  # MACヘッダを引いたサイズ
                            "is_ack_required": True,
                    })
                all_nodes.append(coordinator_node_2)

                for dev_id in DEVICE_ID_1: 
                    device_node_1 = {
                        "id": dev_id,
                        "pan_id": 0,
                        "mode": "device",
                        "pos_list": [{"time": 0, "x": device_x[dev_id - 3] * 300, "y": device_y[dev_id - 3] * 300}],
                        "interfaces": [{"mode": "Device", "init_ch": c1_info["ch"]}],
                        "associated": True,  # 静的に関連付け済み
                        "cbr_applications": [{
                            "dst": 1,  # Coordinator 1宛て
                            "bps": (c1_info["bitrate"]/24) * OFFERED_LOAD,
                            "start": MEASURE_START_SEC,
                            "end": MEASURE_END_SEC,
                            "jitter": 1.0,
                            "payload_size": c1_info["frame_size"] - 15,  # MACヘッダを引いたサイズ
                            "is_ack_required": True,
                        }],
                        "preamble_power": c1_info["preamble_power"],
                    }
                    all_nodes.append(device_node_1)


                for dev_id in DEVICE_ID_2: 
                    device_node_2 = {
                        "id": dev_id,
                        "pan_id": 1,
                        "mode": "device",
                        "pos_list": [{"time": 0, "x": (dist_km * 1000) + device_x[dev_id - NUM_DEVICE - 3] * 300, "y": 0 + device_y[dev_id - NUM_DEVICE - 3] * 300}],
                        "interfaces": [{"mode": "Device", "init_ch": c2_info["ch"]}],
                        "associated": True,  # 静的に関連付け済み
                        "cbr_applications": [{
                            "dst": 2,  # Coordinator 1宛て
                            "bps": (c2_info["bitrate"]/24) * OFFERED_LOAD,
                            "start": MEASURE_START_SEC,
                            "end": MEASURE_END_SEC,
                            "jitter": 1.0,
                            "payload_size": c2_info["frame_size"] - 15,  # MACヘッダを引いたサイズ
                            "is_ack_required": True,
                        }],
                        "preamble_power": c2_info["preamble_power"],
                    }
                    all_nodes.append(device_node_2)


                    # テンプレートに渡すメインのコンテキスト
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

            print(
                f"\nCompleted: Generated {len(DISTANCES_KM) * NUM_DEVICE} patterns, total {total_files} files."
            )


if __name__ == "__main__":
    main()

