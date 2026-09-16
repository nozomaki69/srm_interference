# -*- coding: utf-8 -*-

import os
import sys
import random
import math
import argparse
import itertools
import numpy as np
from jinja2 import Environment, FileSystemLoader, StrictUndefined

# --- パラメータ定義 ---

base_freq_mhz = 920  #920MHz
FRAME_SIZE = 250
# CBRアプリのパケット到着間隔分布。"Constant"(従来のCBR、一定間隔)または
# "Poisson"(平均間隔driot-cbr-traffic-ppsから決まる指数分布、ポアソン到着過程)
TRAFFIC_DISTRIBUTION = "Poisson"

# 送信開始時刻のジッタ[秒]。
# ポアソン到着では最初の間隔も指数分布なので開始位相は自然にばらけるため不要。
# むしろジッタを入れると送信窓がその分短くなり、offered load が目減りして
# 負荷換算がずれる(ジッタ20秒なら送信窓100秒に対し平均90秒になる)。
# 一定間隔(CBR)では全ノードの同時送信を避けるためにジッタが必要。
COORD_START_JITTER_SEC = 0.0 if TRAFFIC_DISTRIBUTION == "Poisson" else 1.0
DEVICE_START_JITTER_SEC = 0.0 if TRAFFIC_DISTRIBUTION == "Poisson" else 20.0
CHANNELS = [
    #IEEE 802.15.4(2024), pp.719
    #チャネル幅は伝送速度の2倍 (100kHz@50kbps / 200kHz@100kbps / 400kHz@200kbps)。
    #この値は TEMPLATE.config.j2 の driot-symbol-rate-map のキーと一致していなければならず、
    #一致しないと driot_phy.cpp の UpdateParametersRelatedToChannelBandwidth() が abort する。
    #Operating mode #1
    {
        "id": 0,
        "freq_mhz": base_freq_mhz,
        "width_mhz": 100e3 / 1e6, #0.1
        "rx_sensitivity_dbm": -97.0,
        "bitrate_kbps": 50,
    },
    #Operating mode #2
    {
        "id": 1,
        "freq_mhz": base_freq_mhz,
        "width_mhz": 200e3 / 1e6, #0.2
        "rx_sensitivity_dbm": -93.989700,
        "bitrate_kbps": 100,
    },
    #Operating mode #3
    {
        "id": 2,
        "freq_mhz": base_freq_mhz,
        "width_mhz": 400e3 / 1e6, #0.4
        "rx_sensitivity_dbm": -90.979400,
        "bitrate_kbps": 200,
    },
    {
        "id": 3,
        "freq_mhz": base_freq_mhz +1,
        "width_mhz": 100e3 / 1e6, #0.1
        "rx_sensitivity_dbm": -97.0,
        "bitrate_kbps": 50,
    },
    #Operating mode #2
    {
        "id": 4,
        "freq_mhz": base_freq_mhz +1,
        "width_mhz": 200e3 / 1e6, #0.2
        "rx_sensitivity_dbm": -93.989700,
        "bitrate_kbps": 100,
    },
    #Operating mode #3
    {
        "id": 5,
        "freq_mhz": base_freq_mhz +1,
        "width_mhz": 400e3 / 1e6, #0.4
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
    3: 1.4414098800604656,
    4: 1.212076401054132,
    5: 1.0192307006600434,
}

TARGET_BANDWIDTH_PATTERNS = [[0, 0], [0, 1], [0, 2], [1, 1], [1, 2], [2, 2], [0, 3], [0, 4], [0, 5], [1, 4], [1, 5], [2, 5]]
#TARGET_BANDWIDTH_PATTERNS = [[0, 2], [3, 2]]

NUM_DEVICE = 30
DEVICE_ID_1 = list(range(3, NUM_DEVICE + 3))
DEVICE_ID_2= list(range(NUM_DEVICE + 3, NUM_DEVICE + NUM_DEVICE + 3))
SIMULATION_SEEDS = 100
# --- シミュレーションの時間軸 ---
#   0 .. MEASURE_START_SEC        : 送信前(ウォームアップ)
#   MEASURE_START_SEC .. MEASURE_END_SEC : アプリがパケットを生成する窓
#   MEASURE_END_SEC .. SIM_DURATION_SEC  : ドレイン。生成は止まるが、キューに残った
#                                          フレームのCSMA・再送を最後までやりきらせる
#
# ドレインが無いと、送信窓の終端近くで生成されたパケットが Deq されないまま
# シミュレーション終了で消え、提供負荷も配送率も負荷依存で目減りする。
# 一方でドレインを長く取りすぎると、その間チャネルは空いていくので高負荷時の
# PER を過小評価する。送信窓の20%を目安とする。
MEASURE_START_SEC = 20.0
MEASURE_DURATION_SEC = 100.0
MEASURE_END_SEC = MEASURE_START_SEC + MEASURE_DURATION_SEC
DRAIN_DURATION_SEC = 20.0
SIM_DURATION_SEC = MEASURE_END_SEC + DRAIN_DURATION_SEC
MY_TRACE_TAGS = ['Mac'] #MY_TRACE_TAGS = ['Application']

# --- DrIot MAC/PHY のタイミングパラメータ ---
# ここが offered_load の換算式と TEMPLATE.config.j2 の両方の唯一の定義元。
# テンプレートには context 経由で差し込むので、片方だけ変えて式がずれることはない。
RX_TX_TURNAROUND_SEC = 0.001    # driot-rx-tx-turnaround-time
AIFS_SEC = 0.001                # driot-aifs-time (データ送信後、ACKが返るまでの間隔)
CCA_PERIODS = 8                 # driot-cca-periods       [シンボル]
SIFS_PERIODS = 12               # driot-sifs-periods      [シンボル]
LIFS_PERIODS = 40               # driot-lifs-periods      [シンボル]
MAX_SIFS_FRAME_SIZE_BYTES = 18  # driot-max-sifs-frame-size-bytes (これ以下ならSIFS、超ならLIFS)
MIN_BACKOFF_EXPONENT = 3        # driot-min-backoff-exponent
MAX_BACKOFF_EXPONENT = 5        # driot-max-backoff-exponent
MAX_CSMA_BACKOFFS = 4           # driot-max-csma-backoffs
MAX_FRAME_RETRIES = 3           # driot-max-frame-retries
FSK_PREAMBLE_REPETITION = 4     # driot-fsk-preamble-repetion-number

# --- フレーム長 (source/driot のPHY/MAC実装から導出) ---
# SUN2FSKは1シンボル=1ビットなので、シンボルレート = 伝送速度。
# フレーム送信時間は (SHR + PHR + バイト数*8) * シンボル長
# (driot_phy.cpp の CalculateFrameTransmitDuration)。FCSは加算されない。
SHR_SYMBOLS = 8 * FSK_PREAMBLE_REPETITION + 16  # プリアンブル8bit * 繰り返し数 + SFD 16bit
PHR_SYMBOLS = 16        # SUN2FSKのPHYヘッダ
ACK_PSDU_BYTES = 3      # ImmAckFrame: FrameControl 2B + SequenceNumber 1B
APPS_PER_PAN = NUM_DEVICE * 2   # コーディネータの下り30 + デバイスの上り30

DATA_FRAME_SYMBOLS = SHR_SYMBOLS + PHR_SYMBOLS + FRAME_SIZE * 8
ACK_FRAME_SYMBOLS = SHR_SYMBOLS + PHR_SYMBOLS + ACK_PSDU_BYTES * 8

# 平均バックオフ時間をサイクルに含めるか。
# 含める場合、offered_load は「1フローの衝突なしサービス時間に対する提供レートの比」になる。
# CSMAでは他ノードのバックオフ中に別ノードが送信できるためPAN全体の集約容量は 1/cycle より
# 高く、この定義は集約占有率をやや過大評価する。それでも含めているのは、バックオフが
# 伝送速度にほとんど依存しない固定時間(turnaround 1ms が支配的)であり、これを外すと
# 伝送速度間の正規化が再び崩れるため。
INCLUDE_MEAN_BACKOFF = True


def _symbol_sec(bitrate_kbps):
    """1シンボルの長さ[秒]。SUN2FSKは1シンボル=1ビットなのでシンボルレート = 伝送速度。"""
    return 1.0 / (bitrate_kbps * 1e3)


def _ceil_to_symbol(seconds, symbol_sec):
    """driot_phy.cpp の CalculateTimeOffsetToSymbolPeriods 相当 (シンボル境界へ切上げ)。"""
    return math.ceil(seconds / symbol_sec) * symbol_sec


def exchange_cycle_sec(bitrate_kbps):
    """データ1フレーム + ACK を1回やり取りするのに要する、衝突なしの所要時間[秒]。

    driot_phy.cpp:
        GetRxTxTurnaroundTime()          = turnaround をシンボル境界へ切上げ
        GetCcaDuration()                 = CCA_PERIODS * symbol
        GetAUnitBackoffDuration()        = turnaround + CCA
        GetLongInterframeSpaceDuration() = max(LIFS_PERIODS * symbol, turnaround)
    driot_mac.cpp:
        StartOrContinueIfsOrRandomAccess()  : IFS待ちの後 backoffPeriods*unit + CCA
        ProcessBackoffTimerEvent()          : CCAがクリアなら turnaround 後に送信開始
        CompleteCommandOrDataTransmission() : GetAckWaitDuration() = AIFS + ACK送信時間

    turnaround と AIFS は絶対秒(1ms)で指定されており伝送速度に依存しないため、
    DATA+ACK の送信時間だけで換算すると 200kbps 側だけ相対的に重いオーバヘッドを
    無視することになり、伝送速度間の比較が不公平になる。
    """
    sym = _symbol_sec(bitrate_kbps)
    turnaround = _ceil_to_symbol(RX_TX_TURNAROUND_SEC, sym)
    aifs = _ceil_to_symbol(AIFS_SEC, sym)
    cca = CCA_PERIODS * sym

    # データフレーム(250B)は MAX_SIFS_FRAME_SIZE_BYTES を超えるので LIFS 側
    assert FRAME_SIZE > MAX_SIFS_FRAME_SIZE_BYTES
    ifs = max(LIFS_PERIODS * sym, turnaround)

    unit_backoff = turnaround + cca
    mean_backoff = 0.0
    if INCLUDE_MEAN_BACKOFF:
        # 初回の backoffPeriods は U{0, 2^minBE - 1} なので平均 (2^minBE - 1)/2 単位
        mean_backoff = ((2 ** MIN_BACKOFF_EXPONENT - 1) / 2.0) * unit_backoff

    return (ifs + mean_backoff + cca + turnaround
            + DATA_FRAME_SYMBOLS * sym + aifs + ACK_FRAME_SYMBOLS * sym)


def offered_load_pps(bitrate_kbps, offered_load_percent):
    """PAN全体の提供負荷が飽和容量の offered_load_percent % になる、1アプリあたりの送信レート[pps]。

    飽和容量 = 1 / exchange_cycle_sec(bitrate) [交換/秒] で、PAN内の APPS_PER_PAN 個の
    アプリでこれを分け合う。再送は含まない(再送率は結果であって入力ではないため)。
    """
    return (offered_load_percent * 0.01) / (exchange_cycle_sec(bitrate_kbps) * APPS_PER_PAN)


# --- スクリプト設定 ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(SCRIPT_DIR, "../template/")  # commandline/template/
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..")  # commandline/

# テンプレートファイル名
CONFIG_TEMPLATE = "TEMPLATE.config.j2"
POS_TEMPLATE = "TEMPLATE.pos.j2"
STAT_TEMPLATE = "TEMPLATE.statconfig.j2"

# offered_load は「衝突なし飽和容量に対する提供負荷の比[%]」を表す (offered_load_pps で換算)
# 100% は提供レートが飽和容量ちょうどになる点なので、上端では待ち行列が発散し、
# 送信窓の終端までに送りきれないパケットが残る(これは飽和領域として意図した挙動)。
OFFERED_LOAD_PERCENTS = list(range(10, 101, 10))   # 10,20,...,100 [% of saturation]

# --- 全パラメータの組み合わせを事前に確定させておく ---
# 元の入れ子ループと同じ順序 (bandwidth_pattern -> offered_load_pan2 -> offered_load_pan1 -> seed)
# で並べることで、"全体の何番目から何個" というバッチ指定が可能になる。
ALL_COMBOS = list(itertools.product(
    TARGET_BANDWIDTH_PATTERNS,
    OFFERED_LOAD_PERCENTS,
    OFFERED_LOAD_PERCENTS,
    range(SIMULATION_SEEDS),
))


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


def generate_batch(combos):
    """
    combos: [(bandwidth_pattern, offered_load_pan2, offered_load_pan1, seed), ...]
    のリストを受け取り、実際に .config / .pos / .statconfig を生成する。
    """
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

    total_files = 0

    for bandwidth_pattern, offered_load_pan2, offered_load_pan1, seed in combos:
        interference_flag = 0
        pan1_bandwidth = CHANNELS[bandwidth_pattern[0]]["freq_mhz"]
        pan2_bandwidth = CHANNELS[bandwidth_pattern[1]]["freq_mhz"]

        if pan1_bandwidth == pan2_bandwidth:
            interference_flag = 1

        np.random.seed(seed)

        #エンドデバイスの分布範囲
        # それぞれの通信範囲を計算
        range1 = int(round(MAXIMUM_COMMUNICATION_RANGE[bandwidth_pattern[0]], 1) * 1000)
        range2 = int(round(MAXIMUM_COMMUNICATION_RANGE[bandwidth_pattern[1]], 1) * 1000)

        DISTANCES_M = max(range1, range2) + 100
        x1, y1 = generate_uniform_circle_coords(0, 0, range1, NUM_DEVICE)
        x2, y2 = generate_uniform_circle_coords(DISTANCES_M, 0, range2, NUM_DEVICE)

        if interference_flag == 1:
            prefix = f"interf_dist_{DISTANCES_M}m_channel_{bandwidth_pattern[0]}_vs_{bandwidth_pattern[1]}_pan1_{offered_load_pan1}_pan2_{offered_load_pan2}_seed{seed}"
        else:
            prefix = f"no_interf_dist_{DISTANCES_M}m_channel_{bandwidth_pattern[0]}_vs_{bandwidth_pattern[1]}_pan1_{offered_load_pan1}_pan2_{offered_load_pan2}_seed{seed}"

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
                    "pps": offered_load_pps(CHANNELS[bandwidth_pattern[0]]["bitrate_kbps"], offered_load_pan1),
                    "start": MEASURE_START_SEC,
                    "end": MEASURE_END_SEC,
                    "jitter": COORD_START_JITTER_SEC,
                    "payload_size": FRAME_SIZE - 15,  # MACヘッダを引いたサイズ
                    "is_ack_required": True,
                    "distribution": TRAFFIC_DISTRIBUTION,
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
                    "pps": offered_load_pps(CHANNELS[bandwidth_pattern[1]]["bitrate_kbps"], offered_load_pan2),
                    "start": MEASURE_START_SEC,
                    "end": MEASURE_END_SEC,
                    "jitter": COORD_START_JITTER_SEC,
                    "payload_size": FRAME_SIZE - 15,  # MACヘッダを引いたサイズ
                    "is_ack_required": True,
                    "distribution": TRAFFIC_DISTRIBUTION,
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
                    "pps": offered_load_pps(CHANNELS[bandwidth_pattern[0]]["bitrate_kbps"], offered_load_pan1),
                    "start": MEASURE_START_SEC,
                    "end": MEASURE_END_SEC,
                    "jitter": DEVICE_START_JITTER_SEC,
                    "payload_size": FRAME_SIZE - 15,  # MACヘッダを引いたサイズ
                    "is_ack_required": True,
                    "distribution": TRAFFIC_DISTRIBUTION,
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
                    "pps": offered_load_pps(CHANNELS[bandwidth_pattern[1]]["bitrate_kbps"], offered_load_pan2),
                    "start": MEASURE_START_SEC,
                    "end": MEASURE_END_SEC,
                    "jitter": DEVICE_START_JITTER_SEC,
                    "payload_size": FRAME_SIZE - 15,  # MACヘッダを引いたサイズ
                    "is_ack_required": True,
                    "distribution": TRAFFIC_DISTRIBUTION,
                }],
                "preamble_power": CHANNELS[bandwidth_pattern[1]]["rx_sensitivity_dbm"],
                "ed_threshold_dbm": ED_THRESHOLDS[bandwidth_pattern[1]],
            }
            all_nodes.append(device_node_2)

        # テンプレートに渡すメインのコンテキスト
        context = {
            "label": prefix,
            "config_filename_prefix": prefix,
            "seed": seed,
            # simulation-time はドレインを含めた全体。トラフィック終了(MEASURE_END_SEC)と
            # 同じにすると、終端付近のパケットが送信されないまま打ち切られる。
            "sim_time": SIM_DURATION_SEC,
            "mobility_seed": seed,
            "band_name": "DrIotTestBand",
            # 統計窓は送信開始からシミュレーション終了まで(ドレイン中の送達も数える)。
            # simulation-time を超える終端を指定すると統計が無意味になるので揃えておく。
            "measure_start": MEASURE_START_SEC,
            "measure_end": SIM_DURATION_SEC,
            "is_6lowpan_enabled": False,
            "advertising_channel_number": 0,
            "nodes": all_nodes,
            "tx_power": 13.010299956639813, # dBm
            "trace_tags": MY_TRACE_TAGS,
            "cca_mode": "ED_ONLY",
            "channels": CHANNELS,

            # MAC/PHYのタイミング。offered_load_pps() の換算式と同じ定数を使う
            # (テンプレート側に直値を書くと式とずれるため、必ずここから差し込む)
            "rx_tx_turnaround_sec": RX_TX_TURNAROUND_SEC,
            "aifs_sec": AIFS_SEC,
            "cca_periods": CCA_PERIODS,
            "sifs_periods": SIFS_PERIODS,
            "lifs_periods": LIFS_PERIODS,
            "max_sifs_frame_size_bytes": MAX_SIFS_FRAME_SIZE_BYTES,
            "min_backoff_exponent": MIN_BACKOFF_EXPONENT,
            "max_backoff_exponent": MAX_BACKOFF_EXPONENT,
            "max_csma_backoffs": MAX_CSMA_BACKOFFS,
            "max_frame_retries": MAX_FRAME_RETRIES,
            "fsk_preamble_repetition": FSK_PREAMBLE_REPETITION,
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

    return len(combos), total_files


def main():
    parser = argparse.ArgumentParser(description="シミュレーション用 .config/.pos/.statconfig をバッチ生成する")
    parser.add_argument("--start", type=int, default=0, help="全組み合わせの中の開始インデックス(0始まり)")
    parser.add_argument("--count", type=int, default=None, help="生成する組み合わせ数(省略時は start 以降の残り全部)")
    parser.add_argument("--print-total", action="store_true", help="全組み合わせ数だけを標準出力して終了する")
    args = parser.parse_args()

    if args.print_total:
        print(len(ALL_COMBOS))
        return

    start = args.start
    count = args.count if args.count is not None else (len(ALL_COMBOS) - start)
    batch = ALL_COMBOS[start:start + count]

    if not batch:
        print(f"生成対象がありません (start={start}, total={len(ALL_COMBOS)})。", file=sys.stderr)
        return

    num_combos, total_files = generate_batch(batch)
    print(f"Generated {num_combos} combinations ({total_files} files) for range [{start}, {start + num_combos})")


if __name__ == "__main__":
    main()
