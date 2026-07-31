import os
import sys
import glob
import re
import csv

def parse_trace_file(filepath, num_device):
    # デバイスIDの割り当て定義
    pan1_devices = list(range(3, 3 + num_device))
    pan2_devices = list(range(3 + num_device, 3 + 2 * num_device))
    all_devices = pan1_devices + pan2_devices

    # 集計用変数の初期化
    c_deq_pkt_num = {1: 0, 2: 0} # PC1, PC2がdequeueした合計数
    c_deq_pkt_num_to_dev = {dev: 0 for dev in all_devices} # ★NEW: PCが各デバイス宛てにdequeueした数
    d_deq_pkt_num = {dev: 0 for dev in all_devices} # 各デバイスがdequeueした数

    c_rx_pkt_num_total = {1: 0, 2: 0} # PC1, PC2が受信した合計フレーム数
    c_rx_pkt_num = {dev: 0 for dev in all_devices} # PCが各デバイスから受信した数
    c_rssi_sum = {dev: 0.0 for dev in all_devices} # RSSI合計

    d_rx_pkt_num = {dev: 0 for dev in all_devices} # デバイスがPCから受信した数

    # ファイル名からメタデータを抽出
    filename = os.path.basename(filepath)
    match = re.search(r'dist_(\d+)m_channel_(\d+)_vs_(\d+)_pan1_(\d+)_pan2_(\d+)_seed(\d+)', filename)
    if not match:
        return None # 形式が違うファイルはスキップ

    distance = int(match.group(1))
    pan1_ch = int(match.group(2))
    pan2_ch = int(match.group(3))
    pan1_offload = int(match.group(4))
    pan2_offload = int(match.group(5))
    seed = int(match.group(6))

    # トレースファイルの解析
    with open(filepath, 'r') as f:
        for line in f:
            parts = line.split()
            if not parts: continue

            # --- Coordinator (ID: 1 or 2) ---
            if "DrIotMac" in parts[5] and parts[3] in ["1", "2"]:
                pc_id = int(parts[3])

                # PCがdequeueした数（全体 ＆ 各デバイス宛て）
                if "DataFrameDequeued" in parts[9]:
                    c_deq_pkt_num[pc_id] += 1
                    try:
                        # parts[15] に宛先デバイスIDが入っていることを利用
                        dest_dev = int(parts[15])
                        if dest_dev in c_deq_pkt_num_to_dev:
                            c_deq_pkt_num_to_dev[dest_dev] += 1
                    except (IndexError, ValueError):
                        pass

                # PCが受信したフレーム数とRSSI
                if "RxFrame" in parts[9] and "Data" in parts[15]:
                    pkt_id = parts[11]
                    try:
                        src_dev = int(pkt_id.split('_')[0])
                        if src_dev in c_rx_pkt_num:
                            c_rx_pkt_num[src_dev] += 1
                            c_rssi_sum[src_dev] += float(parts[19])
                            if src_dev in pan1_devices:
                                c_rx_pkt_num_total[1] += 1
                            elif src_dev in pan2_devices:
                                c_rx_pkt_num_total[2] += 1
                    except ValueError:
                        pass

            # --- Device (ID: 3 ~) ---
            if "DrIotMac" in parts[5] and parts[3] not in ["1", "2"]:
                dev_id = int(parts[3])

                # Deviceがdequeueした数
                if "DataFrameDequeued" in parts[9]:
                    d_deq_pkt_num[dev_id] += 1

                # Deviceが受信したフレーム数
                if "RxFrame" in parts[9] and "Data" in parts[15]:
                    d_rx_pkt_num[dev_id] += 1

    # 各デバイスからのRSSI平均を計算
    c_rssi_avg = {}
    for dev in all_devices:
        if c_rx_pkt_num[dev] > 0:
            c_rssi_avg[dev] = c_rssi_sum[dev] / c_rx_pkt_num[dev]
        else:
            c_rssi_avg[dev] = 0.0 # 受信0の場合は0とする

    # --- CSVの行データを構築 ---
    row = [pan1_ch, pan2_ch, distance, pan1_offload, pan2_offload, seed]

    # PAN1 Deq Stats
    row.append(c_deq_pkt_num[1])
    row.extend([c_deq_pkt_num_to_dev[dev] for dev in pan1_devices]) # ★NEW
    row.extend([d_deq_pkt_num[dev] for dev in pan1_devices])

    # PAN2 Deq Stats
    row.append(c_deq_pkt_num[2])
    row.extend([c_deq_pkt_num_to_dev[dev] for dev in pan2_devices]) # ★NEW
    row.extend([d_deq_pkt_num[dev] for dev in pan2_devices])

    # PAN1 Rx Stats
    row.append(c_rx_pkt_num_total[1])
    row.extend([c_rx_pkt_num[dev] for dev in pan1_devices])

    # PAN2 Rx Stats
    row.append(c_rx_pkt_num_total[2])
    row.extend([c_rx_pkt_num[dev] for dev in pan2_devices])

    # Device Rx Stats
    row.extend([d_rx_pkt_num[dev] for dev in pan1_devices])
    row.extend([d_rx_pkt_num[dev] for dev in pan2_devices])

    # RSSI Stats
    row.extend([round(c_rssi_avg[dev], 4) for dev in pan1_devices])
    row.extend([round(c_rssi_avg[dev], 4) for dev in pan2_devices])

    return row

def generate_header(num_device):
    pan1_devs = list(range(3, 3 + num_device))
    pan2_devs = list(range(3 + num_device, 3 + 2 * num_device))

    header = [
        "PAN1_CH", "PAN2_CH", "Distance", "PAN1_Offload", "PAN2_Offload", "Seed"
    ]

    # PAN1 Deq
    header.append("PAN1_PC_Deq_Total")
    header.extend([f"PAN1_PC_Deq_to_Dev{dev}" for dev in pan1_devs]) # ★NEW
    header.extend([f"PAN1_Dev{dev}_Deq" for dev in pan1_devs])

    # PAN2 Deq
    header.append("PAN2_PC_Deq_Total")
    header.extend([f"PAN2_PC_Deq_to_Dev{dev}" for dev in pan2_devs]) # ★NEW
    header.extend([f"PAN2_Dev{dev}_Deq" for dev in pan2_devs])

    # PAN1 Rx
    header.append("PAN1_PC_Rx_Total")
    header.extend([f"PAN1_PC_Rx_from_Dev{dev}" for dev in pan1_devs])

    # PAN2 Rx
    header.append("PAN2_PC_Rx_Total")
    header.extend([f"PAN2_PC_Rx_from_Dev{dev}" for dev in pan2_devs])

    # Device Rx
    header.extend([f"PAN1_Dev{dev}_Rx_from_PC" for dev in pan1_devs])
    header.extend([f"PAN2_Dev{dev}_Rx_from_PC" for dev in pan2_devs])

    # RSSI
    header.extend([f"PAN1_PC_RSSI_Avg_from_Dev{dev}" for dev in pan1_devs])
    header.extend([f"PAN2_PC_RSSI_Avg_from_Dev{dev}" for dev in pan2_devs])

    return header

def main():
    # --- ヘッダーだけを書き出すモード (並列マージ用) ---
    # 使い方: python3 create_csv.py --header-only <num_device> <output_csv>
    if len(sys.argv) >= 2 and sys.argv[1] == "--header-only":
        if len(sys.argv) < 4:
            print("Usage: python3 create_csv.py --header-only <num_device> <output_csv>")
            sys.exit(1)
        num_device = int(sys.argv[2])
        output_csv = sys.argv[3]
        header = generate_header(num_device)
        with open(output_csv, 'a', newline='') as f:
            csv.writer(f).writerow(header)
        print(f"Header written to {output_csv}")
        return

    if len(sys.argv) < 4:
        print("Usage: python3 create_csv.py <trace_dir> <num_device> <output_csv> [manifest_file]")
        sys.exit(1)

    trace_dir = sys.argv[1]
    num_device = int(sys.argv[2])
    output_csv = sys.argv[3]
    # manifest_file が渡された場合は、そこに列挙された .trace ファイルだけを処理する
    # (並列実行の各チャンクが自分の担当ファイルだけを処理するための引数)
    manifest_file = sys.argv[4] if len(sys.argv) > 4 else None

    if manifest_file:
        with open(manifest_file, 'r') as mf:
            trace_files = [line.strip() for line in mf if line.strip()]
        # チャンクの部分CSVにはヘッダーを書かない（後でマージ時に1回だけ書く）
        write_header = False
    else:
        trace_files = glob.glob(os.path.join(trace_dir, "*.trace"))
        write_header = not os.path.isfile(output_csv)

    if not trace_files:
        print(f"No .trace files found for {manifest_file or trace_dir}")
        sys.exit(1)

    header = generate_header(num_device)

    # CSV書き込み
    with open(output_csv, 'a', newline='') as f:
        writer = csv.writer(f)

        if write_header:
            writer.writerow(header)

        for filepath in trace_files:
            row = parse_trace_file(filepath, num_device)
            if row:
                writer.writerow(row)

    print(f"Successfully aggregated {len(trace_files)} trace files to {output_csv}")

if __name__ == "__main__":
    main()