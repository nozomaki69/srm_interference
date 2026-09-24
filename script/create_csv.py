import os
import sys
import glob
import re
import csv

# driot-max-frame-retries と同じ値でなければならない。
# 唯一の定義元は script/interference_2pan_config.py の MAX_FRAME_RETRIES で、そこから
# TEMPLATE.config.j2 に差し込まれる。ここはトレースを読み返す側の写しなので、
# 生成側を変えたらここも合わせること。
#
# MAC は ACKタイムアウトのたびに retryTxCount を1つ進め (driot_mac.cpp:1196)、
# retryTxCount > maxFrameRetries になった時点で諦める (driot_mac.cpp:1198)。
# つまり Ev= Tx-DATA の Retry= は 0..MAX_FRAME_RETRIES を取り、最大
# MAX_FRAME_RETRIES+1 回送信される。Retry= MAX_FRAME_RETRIES の送信が失敗した
# フレームだけが「再送上限に達して落ちたフレーム」である。
MAX_FRAME_RETRIES = 3

def parse_trace_file(filepath, num_device):
    # デバイスIDの割り当て定義
    pan1_devices = list(range(3, 3 + num_device))
    pan2_devices = list(range(3 + num_device, 3 + 2 * num_device))
    all_devices = pan1_devices + pan2_devices
    # 所属PANの判定を毎行 list で線形探索しないように set にしておく
    pan1_device_set = set(pan1_devices)
    pan2_device_set = set(pan2_devices)

    # 集計用変数の初期化
    c_deq_pkt_num = {1: 0, 2: 0} # PC1, PC2がdequeueした合計数
    c_deq_pkt_num_to_dev = {dev: 0 for dev in all_devices} # ★NEW: PCが各デバイス宛てにdequeueした数
    d_deq_pkt_num = {dev: 0 for dev in all_devices} # 各デバイスがdequeueした数

    c_rx_pkt_num_total = {1: 0, 2: 0} # PC1, PC2が受信した合計フレーム数
    c_rx_pkt_num = {dev: 0 for dev in all_devices} # PCが各デバイスから受信した数
    c_rssi_sum = {dev: 0.0 for dev in all_devices} # RSSI合計

    d_rx_pkt_num = {dev: 0 for dev in all_devices} # デバイスがPCから受信した数

    # dequeueしたが最後までACKが返らなかったフレーム数 (旧PERの分子)
    c_noack_to_dev = {dev: 0 for dev in all_devices} # PC -> 各デバイス (下りリンク)
    d_noack = {dev: 0 for dev in all_devices}        # 各デバイス -> PC (上りリンク)

    # ★NEW: MACの再送カウンタ相当の内訳。キーは常に「対向デバイスのID」で、
    # 方向 (dl = PC->デバイス / ul = デバイス->PC) ごとに別の dict に入れる。
    #   macTxSuccessCount      : 再送なし (1回目の送信) でACKが返った
    #   macRetryCount          : 1回の再送でACKが返った
    #   macMultipleRetryCount  : 2回以上の再送でACKが返った
    #   macTxFailCount         : 再送上限に達してもACKが返らなかった
    #   macCsmaFailCount       : 再送上限に達する前に落ちた
    #
    # macCsmaFailCount を4変数から分けているのは、CSMAバックオフ上限超過による破棄
    # (driot_mac.cpp:841-862 の ProcessCcaFailure) が retryTxCount を進めないまま
    # (インクリメントは :844 でコメントアウトされている) 即座にフレームを捨てるため。
    # これは「再送上限に達してACKが返ってこなかった」には当たらないので、PERの分母
    # (4変数の和) からも外す。
    counters = {
        kind + "_" + name: {dev: 0 for dev in all_devices}
        for kind in ("dl", "ul")
        for name in ("tx_success", "retry", "multi_retry", "tx_fail", "csma_fail")
    }

    # pending[node] = [seq, kind, dev, max_retry]  kind は "ul" / "dl"
    # max_retry はそのフレームについて観測した Ev= Tx-DATA の Retry= の最大値。
    # None はまだ一度も電波に出ていないことを意味する。
    #
    # DrIotMac は outputBuffer を1つしか持たない stop-and-wait なので、1ノードに
    # つきACK待ちのデータフレームは常に高々1つ。したがって次の DataFrameDequeued
    # が来た時点で、直前のフレームの成否が確定する (ACKを受けていなければ、MACが
    # 再送上限またはCSMAバックオフ上限まで粘った末に諦めたということ)。
    #
    # driot 側は Ev= Drop / Ev= AckTimeout のASCII出力をコメントアウトしている
    # (driot_mac.cpp:2622, 2665) ため、失敗そのものは trace に出ない。一方で
    # Ev= Tx-DATA (driot_mac.cpp:2492-2499) は送信試行ごとに出ていて Retry= を
    # 持っているので、「何回目の送信で決着したか」はそこから復元できる。
    # 再送では DataFrameDequeued は出し直されない (driot_mac.cpp:1633 のガードで
    # 早期 return する) ので、1フレーム = 1回の DataFrameDequeued + N回の Tx-DATA。
    pending = {}
    unresolved = {"pan1_ul": 0, "pan1_dl": 0, "pan2_ul": 0, "pan2_dl": 0}
    ack_seq_mismatch = 0
    tx_data_seq_mismatch = 0
    ack_without_tx_data = 0

    def resolve_as_failure(entry, at_eof=False):
        """ACKが返らないまま確定したフレームを数える。

        at_eof=True はシミュレーション終了時点でまだACK待ちだったフレームで、
        成否が確定していないので no-ACK の分子にも4変数にも入れず診断値として数える。
        """
        _seq, kind, dev, max_retry = entry
        if at_eof:
            pan = "pan1" if dev in pan1_device_set else "pan2"
            unresolved[pan + "_" + kind] += 1
            return

        if kind == "ul":
            d_noack[dev] += 1
        else:
            c_noack_to_dev[dev] += 1

        # 最後の送信が Retry= MAX_FRAME_RETRIES なら再送上限まで粘って落ちたフレーム。
        # それ以外 (Tx-DATA が1行も無い場合を含む) はCSMAでチャネルを取れずに落ちた。
        if max_retry is not None and max_retry >= MAX_FRAME_RETRIES:
            counters[kind + "_tx_fail"][dev] += 1
        else:
            counters[kind + "_csma_fail"][dev] += 1

    def resolve_as_success(entry):
        """ACKが返って送達が確定したフレームを、再送回数で3種に振り分ける。"""
        nonlocal ack_without_tx_data
        _seq, kind, dev, max_retry = entry
        if max_retry is None:
            # Tx-DATA を1行も見ていないのにACKが返るのは原理的に起きない。
            # 落としてしまうと分母がずれるので再送なし扱いにし、診断値を進める。
            ack_without_tx_data += 1
            max_retry = 0

        if max_retry == 0:
            counters[kind + "_tx_success"][dev] += 1
        elif max_retry == 1:
            counters[kind + "_retry"][dev] += 1
        else:
            counters[kind + "_multi_retry"][dev] += 1

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
    #
    # DrIotMac のモデル名とイベント名は driot 側で固定文字列なので、部分一致ではなく
    # 完全一致で分岐する。行数の大半を占める ABackoffStart / ACcaStart などは
    # parts[5] と parts[9] の2回の比較だけで抜けられる。
    with open(filepath, 'r') as f:
        for line in f:
            parts = line.split()
            if len(parts) < 10 or parts[5] != "DrIotMac":
                continue

            node_id = int(parts[3])
            ev = parts[9]

            if ev == "DataFrameDequeued":
                # 直前のフレームがまだ pending なら、ACKが返らないまま諦められた
                prev = pending.pop(node_id, None)
                if prev is not None:
                    resolve_as_failure(prev)

                try:
                    seq_num = int(parts[17])
                except (IndexError, ValueError):
                    seq_num = None

                if node_id in c_deq_pkt_num:
                    # --- Coordinator (ID: 1 or 2) がdequeueした数 (全体 & 各デバイス宛て) ---
                    c_deq_pkt_num[node_id] += 1
                    try:
                        # parts[15] に宛先デバイスIDが入っていることを利用
                        dest_dev = int(parts[15])
                    except (IndexError, ValueError):
                        continue
                    if dest_dev in c_deq_pkt_num_to_dev:
                        c_deq_pkt_num_to_dev[dest_dev] += 1
                        # 分子の行き先は分母と同じ条件で確定させる。こうしておくと
                        # 構造的に no-ACK 数 <= dequeue 数 が保証され、PERが1を超えない。
                        if seq_num is not None:
                            pending[node_id] = [seq_num, "dl", dest_dev, None]
                elif node_id in d_deq_pkt_num:
                    # --- Device (ID: 3 ~) がdequeueした数 ---
                    d_deq_pkt_num[node_id] += 1
                    if seq_num is not None:
                        pending[node_id] = [seq_num, "ul", node_id, None]

            elif ev == "Tx-DATA":
                # driot_mac.cpp:2492-2499:
                #   PktId= <id> Retry= <n> Seq= <seq> DestN= <id>
                # 送信試行ごとに1行出る。Retry= は outputBuffer.retryTxCount そのもので、
                # 初回送信が0、ACKタイムアウトのたびに1つ増える。
                entry = pending.get(node_id)
                if entry is None:
                    continue
                try:
                    retry = int(parts[13])
                    tx_seq = int(parts[15])
                except (IndexError, ValueError):
                    continue
                if tx_seq != entry[0]:
                    # pending と違うフレームの送信。データを取り違えないよう
                    # pending には触れず、診断カウンタだけ進める。
                    tx_data_seq_mismatch += 1
                    continue
                if entry[3] is None or retry > entry[3]:
                    entry[3] = retry

            elif ev == "RxFrame":
                if len(parts) < 16:
                    continue
                frame_type = parts[15]

                if frame_type == "ACK":
                    # driot_mac.cpp:1245-1247 より、ACKの RxFrame 行は MAC が
                    # 自分の outputBuffer のフレームに対するACKとして受理した
                    # ときにしか出力されない (一致しないACKは何も出力せずに捨てる)。
                    # したがって seq が一致すればそのフレームは送達成功。
                    #
                    # 一致しない場合は、データフレームを諦めた直後に送った
                    # コマンドフレーム宛てのACKなどなので、pending は消さずに
                    # 診断カウンタだけ進める。ここで消すと本物の失敗が成功に化ける。
                    entry = pending.get(node_id)
                    if entry is None:
                        continue
                    try:
                        acked_seq = int(parts[17])
                    except (IndexError, ValueError):
                        continue
                    if acked_seq == entry[0]:
                        del pending[node_id]
                        resolve_as_success(entry)
                    else:
                        ack_seq_mismatch += 1
                    continue

                if frame_type != "Data":
                    continue
                if node_id in c_deq_pkt_num:
                    # PCが受信したデータフレーム数とRSSI
                    try:
                        src_dev = int(parts[11].split('_')[0])
                    except ValueError:
                        continue
                    if src_dev in c_rx_pkt_num:
                        c_rx_pkt_num[src_dev] += 1
                        c_rssi_sum[src_dev] += float(parts[19])
                        if src_dev in pan1_device_set:
                            c_rx_pkt_num_total[1] += 1
                        elif src_dev in pan2_device_set:
                            c_rx_pkt_num_total[2] += 1
                elif node_id in d_rx_pkt_num:
                    # DeviceがPCから受信したデータフレーム数
                    d_rx_pkt_num[node_id] += 1

    # シミュレーション終了時点でまだACK待ちだったフレーム (ノードあたり高々1通)。
    # 成否が確定していないので分子には入れず、診断値としてだけ残す。
    for entry in pending.values():
        resolve_as_failure(entry, at_eof=True)

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

    # No-ACK Stats (旧PERの分子)。列は既存のRSSIブロックの後ろに足す。
    row.extend([c_noack_to_dev[dev] for dev in pan1_devices])
    row.extend([d_noack[dev] for dev in pan1_devices])
    row.extend([c_noack_to_dev[dev] for dev in pan2_devices])
    row.extend([d_noack[dev] for dev in pan2_devices])

    # 健全性チェック用の診断値 (いずれも通常は0になるはず)
    row.append(unresolved["pan1_ul"])
    row.append(unresolved["pan1_dl"])
    row.append(unresolved["pan2_ul"])
    row.append(unresolved["pan2_dl"])
    row.append(ack_seq_mismatch)

    # ★NEW: MAC再送カウンタの内訳。既存列の添字を動かさないよう末尾に足す。
    # 並び順は generate_header() の MAC_COUNTER_NAMES / 二重ループと厳密に一致させること。
    for devs in (pan1_devices, pan2_devices):
        for kind in ("dl", "ul"):
            for name in MAC_COUNTER_NAMES:
                row.extend([counters[kind + "_" + name][dev] for dev in devs])

    # ★NEW: 再送カウンタ側の診断値
    row.append(tx_data_seq_mismatch)
    row.append(ack_without_tx_data)

    return row

# ★NEW: MAC再送カウンタの内部名 -> CSVの列名に使う変数名。
# row 構築と generate_header() でこの並びを共有する。
MAC_COUNTER_NAMES = ["tx_success", "retry", "multi_retry", "tx_fail", "csma_fail"]
MAC_COUNTER_LABELS = {
    "tx_success": "macTxSuccessCount",
    "retry": "macRetryCount",
    "multi_retry": "macMultipleRetryCount",
    "tx_fail": "macTxFailCount",
    "csma_fail": "macCsmaFailCount",
}

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

    # No-ACK (旧PERの分子)
    header.extend([f"PAN1_PC_NoAck_to_Dev{dev}" for dev in pan1_devs])
    header.extend([f"PAN1_Dev{dev}_NoAck" for dev in pan1_devs])
    header.extend([f"PAN2_PC_NoAck_to_Dev{dev}" for dev in pan2_devs])
    header.extend([f"PAN2_Dev{dev}_NoAck" for dev in pan2_devs])

    # 診断値
    header.extend([
        "PAN1_UL_Unresolved", "PAN1_DL_Unresolved",
        "PAN2_UL_Unresolved", "PAN2_DL_Unresolved",
        "AckSeqMismatch",
    ])

    # ★NEW: MAC再送カウンタの内訳 (新PERの材料)。
    # 下りリンク (PC -> デバイス) は PANn_Co_to_Dev<id>_<変数名>、
    # 上りリンク (デバイス -> PC) は PANn_Dev<id>_to_Co_<変数名>。
    for pan, devs in (("PAN1", pan1_devs), ("PAN2", pan2_devs)):
        for kind in ("dl", "ul"):
            for name in MAC_COUNTER_NAMES:
                label = MAC_COUNTER_LABELS[name]
                if kind == "dl":
                    header.extend([f"{pan}_Co_to_Dev{dev}_{label}" for dev in devs])
                else:
                    header.extend([f"{pan}_Dev{dev}_to_Co_{label}" for dev in devs])

    # ★NEW: 再送カウンタ側の診断値
    header.extend(["TxDataSeqMismatch", "AckWithoutTxData"])

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
