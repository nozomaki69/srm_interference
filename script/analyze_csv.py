#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import csv
import argparse
from collections import defaultdict

import numpy as np
import scipy.stats as stats

# ============================================================
# 設定
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(SCRIPT_DIR, "..", "plots", "simulation_results.csv")
PLOT_BASE_DIR = os.path.join(SCRIPT_DIR, "..", "plots")

NUM_DEVICE = 30
PAN1_DEVS = list(range(3, 3 + NUM_DEVICE))                   # NUM_DEVICE=30 なら 3..32
PAN2_DEVS = list(range(3 + NUM_DEVICE, 3 + 2 * NUM_DEVICE))  # NUM_DEVICE=30 なら 33..62

# チャネル番号 -> 帯域(kbps)
CHANNEL_KBPS = {0: 50, 1: 100, 2: 200, 3: 50, 4: 100, 5: 200}

# チャネル番号 -> 中心周波数(MHz)。generate_config.py の CHANNELS と同じ値。
# 0,1,2 は base_freq_mhz、3,4,5 は base_freq_mhz+1 なので、同じ周波数同士の
# 組み合わせだけが干渉する（generate_config.py の interference_flag 判定と同一基準）。
CHANNEL_FREQ_MHZ = {0: 920, 1: 920, 2: 920, 3: 921, 4: 921, 5: 921}

# チャネル番号 -> 受信感度(dBm)。RSSIビンの起点に使う。
# CHANNEL_KBPS / CHANNEL_FREQ_MHZ はローカルに複製しているが、こちらは生成側から
# import して唯一の定義元に揃える。create_heatmap.py が OFFERED_LOAD_PERCENTS で
# 同じことをしており、そこのコメントどおり直値を書くと生成側を変えたときに
# 片方だけ取り残されて静かに壊れる。
sys.path.insert(0, SCRIPT_DIR)
from interference_2pan_config import CHANNELS as _CHANNELS  # noqa: E402

RX_SENSITIVITY_DBM = {c["id"]: c["rx_sensitivity_dbm"] for c in _CHANNELS}

# --- RSSIビン設定 -----------------------------------------------------
# RSSIビンの幅(dBm)。★ここを変更するだけで、以下の解析すべてのビン幅が
# 一括で変わる★:
#   - select_bins                 (干渉検知に使うRSSIビン)
#   - compute_seed_max_variance   (Seedごとの干渉指標)
RSSI_BIN_SIZE_DBM = 10

# ビンの起点を受信感度から何dBm上に置くか。
#
# ★このブランチの方針: 起点をチャネル固有の固定値にする★
#   起点 = RX_SENSITIVITY_DBM[ch] + RSSI_BIN_ANCHOR_OFFSET_DBM
#
# 以前はそのSeedの実測RSSIの最小値 + 5dBm を起点にしていた(統計量A')。
# 基準が「実測最小値」というデータ依存の量だったため、負荷や帯域でRSSI分布が
# 少しずれるだけでビン境界と端末の切れ方が変わり、「同じリングの端末どうしを
# 比べる」という指標の前提がぶれていた。受信感度はチャネルごとの固定値なので、
# 起点をここに置けばビン境界がSeedにも負荷にも依存しなくなる。
#
# 最弱端を落とす理由自体はA'と同じで、セル端は PER が 0.5 付近になり
# 二項ノイズ p(1-p)/n が最大になるため、干渉が無くても端末間のばらつきが
# 大きく出て誤検知の床を決めてしまうからである。落とす幅がトレードオフになる:
# 広く落とすとノイズの床は下がるが、ビンに残る端末数 m が減って検出力も下がる。
#
# 同じ伝搬モデル (RSSI(r) = -58.16 - 40log10(r/154), 面積一様配置30台) での概算:
#
#   起点             除外   残り   最大ビンのm   検出力(Δ=2*S0, α=0.05)
#   受信感度+10(ED)  約20台  約10台     6.9          0.650
#   受信感度+5       約12台  約18台    12.2          0.834
#   受信感度+3       約 8台  約22台    15.4          0.895   <- 現在の設定
#
# EDしきい値を起点にする案は、除外が大きすぎて検出力が落ちるため採らない。
#
# この値はビン幅とあわせて感度解析で振る対象なので、直値をコードに埋めないこと。
RSSI_BIN_ANCHOR_OFFSET_DBM = 3.0

# --- 測定モード -------------------------------------------------------
# create_csv.py は1つのトレースから2通りの測定結果を出している:
#   td   : 各メトリックを自分の 200s 窓で測る (標準に忠実な時間分割測定)。既存の列名
#   conv : 全メトリックを W0 の 200s で同時に測る (従来方式の対照)。列名 + "_conv"
# どちらを解析するかで参照する列の接尾辞と出力ファイル名が変わる。
MEASUREMENT_MODE = "td"
COLUMN_SUFFIX = ""


def set_measurement_mode(mode):
    """"td" か "conv" を指定して、参照する列と出力名を切り替える。"""
    global MEASUREMENT_MODE, COLUMN_SUFFIX
    if mode not in ("td", "conv"):
        raise ValueError(f"unknown measurement mode: {mode}")
    MEASUREMENT_MODE = mode
    COLUMN_SUFFIX = "" if mode == "td" else "_conv"


def bin_anchor_dbm(channel):
    """チャネル番号 -> RSSIビンの起点(dBm)。この値以下の端末はビンに入らない。"""
    return RX_SENSITIVITY_DBM[channel] + RSSI_BIN_ANCHOR_OFFSET_DBM


# --- ビン構成の診断 ---------------------------------------------------
# 起点を固定値に変えた影響(端末が何台残るか)は伝搬モデルからの概算しかできて
# いないので、実行のたびに実測値を出して1回で決着させる。
# キーは (PAN名, チャネル番号)。
ANCHOR_STATS = defaultdict(lambda: {"observations": 0, "devices": 0, "above": 0})
BIN_OCCUPANCY = defaultdict(list)     # -> 有効ビンに入った端末数のリスト
DEGENERATE_SEEDS = defaultdict(int)   # -> 有効ビンが1つも無かったSeed数


def _update_anchor_stats(pan, channel, rssi_values):
    """1観測(1 Seed の 1 PAN)分の「起点を超えた端末数」を数える。"""
    anchor = bin_anchor_dbm(channel)
    st = ANCHOR_STATS[(pan, channel)]
    st["observations"] += 1
    for v in rssi_values:
        if v == 0:
            continue
        st["devices"] += 1
        if v > anchor:
            st["above"] += 1


def print_bin_diagnostics():
    """ビン構成の実測値を出す。

    起点を固定値に変えると「何台が起点より上に残るか」で検出力が決まるが、
    その見積もりは伝搬モデルからの概算しかできていない。実行のたびにここで
    実測値を出し、概算(30台中18台が残り、最大ビンの端末数が約12)と突き合わせる。
    """
    if not ANCHOR_STATS:
        return
    print()
    print("=== RSSIビンの構成 (起点 = 受信感度 + "
          f"{RSSI_BIN_ANCHOR_OFFSET_DBM:.1f} dBm, ビン幅 {RSSI_BIN_SIZE_DBM} dBm) ===")
    print(f"{'PAN':>5}{'ch':>4}{'kbps':>6}{'起点':>9}{'観測数':>8}"
          f"{'受信端末/観測':>14}{'起点超え/観測':>14}{'割合':>8}")
    for (pan, ch) in sorted(ANCHOR_STATS):
        st = ANCHOR_STATS[(pan, ch)]
        n_obs = max(st["observations"], 1)
        ratio = st["above"] / st["devices"] if st["devices"] else float("nan")
        print(f"{pan:>5}{ch:>4}{CHANNEL_KBPS[ch]:>6}{bin_anchor_dbm(ch):>9.2f}"
              f"{st['observations']:>8}{st['devices'] / n_obs:>14.1f}"
              f"{st['above'] / n_obs:>14.1f}{ratio * 100:>7.1f}%")

    if BIN_OCCUPANCY:
        print()
        print(f"{'PAN':>5}{'ch':>4}{'有効ビン/Seed':>14}{'ビン内端末数(中央)':>20}"
              f"{'最大':>6}{'有効ビン0のSeed':>16}")
        for key in sorted(BIN_OCCUPANCY):
            pan, ch = key
            occ = np.asarray(BIN_OCCUPANCY[key], dtype=float)
            n_seed = ANCHOR_STATS[key]["observations"]
            per_seed = len(occ) / n_seed if n_seed else float("nan")
            print(f"{pan:>5}{ch:>4}{per_seed:>14.2f}{np.median(occ):>20.1f}"
                  f"{occ.max():>6.0f}{DEGENERATE_SEEDS.get(key, 0):>16}")

    total_degen = sum(DEGENERATE_SEEDS.values())
    if total_degen > 0:
        print()
        print(f"警告: 有効ビンが1つも作れなかった観測が {total_degen} 件あります。"
              " これらの干渉指標は 0.0 に縮退しており、検知に寄与しません。")
        print("      起点が高すぎる可能性があります"
              " (RSSI_BIN_ANCHOR_OFFSET_DBM を下げるか、ビン幅を広げてください)。")


# ============================================================
# ユーティリティ
# ============================================================
def select_bins(rssi_values, anchor_dbm, bin_size=RSSI_BIN_SIZE_DBM, min_count=2):
    """
    anchor_dbm を下端として bin_size 刻みで上方向にビンを作り、
    (upper, lower) のリストを強い側から順に返す。
    ビンの内外判定は呼び出し側と揃えて lower < r <= upper。

      例) anchor が -94 dBm なら (-94, -84], (-84, -74], ... と最大RSSIを覆うまで。
          -94 dBm 以下の端末はどのビンにも入らない。

    anchor_dbm は bin_anchor_dbm(ch) が返すチャネル固有の固定値なので、
    ビン境界はSeedにも負荷にも依存しない。以前のデータ依存の起点
    (実測RSSIの最小値 + 5dBm) と違うのはこの点で、最弱端を落とす意図
    (セル端は二項ノイズが最大で誤検知の床を決める) 自体は残っている。

    干渉検知の統計量がこの関数を経由することで、「どのビンを使うか」の定義が
    1箇所に集まる。
    端末が min_count 個未満しか入らないビンは返さない(間が空くこともある)。
    """
    r = np.asarray(rssi_values, dtype=float).flatten()
    r = r[r != 0]
    if r.size == 0:
        return []

    top = float(r.max())

    bins = []
    lo = float(anchor_dbm)
    while lo < top:
        hi = lo + bin_size
        if np.count_nonzero((r > lo) & (r <= hi)) >= min_count:
            bins.append((hi, lo))
        lo = hi

    # 弱い側から作ったので、戻り値の並びを他と揃えて強い側からにする。
    bins.reverse()
    return bins


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


# ============================================================
# CSV 読み込み & 集計
# ============================================================
def make_empty_condition_data():
    """1条件 (帯域ペア・距離・負荷の組) に、全 Seed x 全デバイス分を平らに貯める。

    統計量に要るのは UL/DL の PER と RSSI だけ。ノード座標から出す距離と
    ΔPER の推定誤差分散 (二項ノイズ) も以前は貯めていたが、前者は距離-PER の
    エラーバー図、後者は変動係数ベースの判定でしか使っておらず、
    どちらもこのブランチには無いので持たない。
    """
    return {
        "pan1_ul": [], "pan1_dl": [], "pan1_rssi": [],
        "pan2_ul": [], "pan2_dl": [], "pan2_rssi": [],
    }


# ============================================================
# PER の定義（このブランチ = one_side_correct_measure）
# ============================================================
# 分母は correct_mesure と同じ「MAC再送カウンタ4種の和」のまま、
# **分子だけを受信側が実際に受信したデータフレーム数に置き換える**。
#
#   PER = 1 - (受信側が受信したデータフレーム数) / (macTxSuccessCount + macRetryCount
#                                                 + macMultipleRetryCount + macTxFailCount)
#
# correct_mesure は送信側から見た指標だった:
#
#   PER = macTxFailCount / (4カウンタの和)
#
# こちらは「再送上限まで粘ってもACKが返らなかったフレームの割合」で、送信側のACK
# 受信状況だけで決まる。対してこのブランチは受信側の受信数を直接使うので、
# 送達を受信側から片側 (one side) で測ることになる。
#
# 分母は「決着のついたフレーム数」なので、CSMAでチャネルを取れずに落ちたフレーム
# (macCsmaFailCount) と、シミュレーション終了時点でまだACK待ちだったフレーム
# (PANn_*_Unresolved) は correct_mesure と同様に外れたままになる。
#
# ★注意: この定義は構造的に PER >= 0 を保証しない★
# 分母は「フレーム数」だが、分子の受信数は create_csv.py が Ev= RxFrame を
# 1行ごとに数えたもので、**再送されたフレームの重複受信もそのまま加算される**
# (ACKだけが失われた場合、受信側は同じフレームを2回以上受け取る)。
# したがって 受信数 > 分母 となり得て、1 - 受信数/分母 が負になる。
# ここでは [0, 1] にクリップし、クリップが起きた回数を診断値として数える。
# correct_mesure のコメントが受信数ベースを採らない理由として挙げていたのが
# まさにこの重複受信の問題なので、クリップ頻度は必ず確認すること。
CLIP_STATS = {"negative": 0, "total": 0}


def _one_side_per(r, idx, pan, dev, direction):
    """受信側の受信数を分子にした PER を返す。

    direction は "ul" (デバイス -> コーディネータ) または "dl" (コーディネータ -> デバイス)。
    分母に使う再送カウンタの接頭辞と、分子に使う受信数の列名が方向で変わる。
    """
    sfx = COLUMN_SUFFIX
    if direction == "ul":
        prefix = f"{pan}_Dev{dev}_to_Co_"
        n_rx = r[idx[f"{pan}_PC_Rx_from_Dev{dev}{sfx}"]]
    else:
        prefix = f"{pan}_Co_to_Dev{dev}_"
        n_rx = r[idx[f"{pan}_Dev{dev}_Rx_from_PC{sfx}"]]

    total = (r[idx[prefix + "macTxSuccessCount" + sfx]]
             + r[idx[prefix + "macRetryCount" + sfx]]
             + r[idx[prefix + "macMultipleRetryCount" + sfx]]
             + r[idx[prefix + "macTxFailCount" + sfx]])
    if total <= 0:
        return 0.0

    per = 1.0 - (n_rx / total)
    CLIP_STATS["total"] += 1
    if per < 0.0:
        CLIP_STATS["negative"] += 1
        return 0.0
    return per if per <= 1.0 else 1.0


def load_and_aggregate(csv_file):
    """
    CSV を読み込み、(PAN1_CH, PAN2_CH, Distance, PAN1_Offload, PAN2_Offload) を
    条件キーとして、全 Seed x 全デバイス分の UL/DL PER と RSSI を
    1つの配列に蓄積する。

    .pos ファイル(ノード座標)は読まない。座標が要るのは距離-PER のエラーバー図
    だけで、このブランチはヒートマップと折れ線しか出さないため。
    """
    data = defaultdict(make_empty_condition_data)

    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {name: i for i, name in enumerate(header)}
        # float として読むのはRSSI列だけ。以前は位置 (10 + 8*NUM_DEVICE) で
        # 決め打ちしていたが、create_csv.generate_header() に列を1つ足すだけで
        # 静かに壊れるので、列名で判定する。
        is_float_col = ["RSSI" in name for name in header]

        for row in reader:
            # 長さチェックは必須。sbatch_jobs.sh は部分CSVの「行数」しか検証して
            # いないので、途中で切れた行が混ざると zip が黙って切り詰めて列がずれる。
            if len(row) != len(header):
                raise ValueError(
                    f"{csv_file}: 列数が一致しません "
                    f"(header {len(header)} 列 / row {len(row)} 列)。"
                    " 途中で落ちた解析ジョブの部分CSVが混ざっていないか確認すること。"
                )
            r = [float(x) if is_float else int(float(x))
                 for x, is_float in zip(row, is_float_col)]

            pan1_ch = r[idx["PAN1_CH"]]
            pan2_ch = r[idx["PAN2_CH"]]
            distance = r[idx["Distance"]]
            pan1_offload = r[idx["PAN1_Offload"]]
            pan2_offload = r[idx["PAN2_Offload"]]

            condition_key = (pan1_ch, pan2_ch, distance, pan1_offload, pan2_offload)

            entry = data[condition_key]

            # --- PAN1 ---
            for dev in PAN1_DEVS:
                # 上り (デバイス -> PC) と下り (PC -> デバイス) で、それぞれ
                # 受信側の受信数を分子にしたPERを出す。定義は _one_side_per() を参照。
                ul_per = _one_side_per(r, idx, "PAN1", dev, "ul")
                dl_per = _one_side_per(r, idx, "PAN1", dev, "dl")

                rssi = r[idx[f"PAN1_PC_RSSI_Avg_from_Dev{dev}{COLUMN_SUFFIX}"]]

                entry["pan1_ul"].append(ul_per)
                entry["pan1_dl"].append(dl_per)
                entry["pan1_rssi"].append(rssi)

            # この観測(1 Seed 分)のRSSIから、起点を超えた端末数を数える
            _update_anchor_stats("PAN1", pan1_ch, entry["pan1_rssi"][-NUM_DEVICE:])

            # --- PAN2 ---
            for dev in PAN2_DEVS:
                # 上り (デバイス -> PC) と下り (PC -> デバイス) で、それぞれ
                # 受信側の受信数を分子にしたPERを出す。定義は _one_side_per() を参照。
                ul_per = _one_side_per(r, idx, "PAN2", dev, "ul")
                dl_per = _one_side_per(r, idx, "PAN2", dev, "dl")

                rssi = r[idx[f"PAN2_PC_RSSI_Avg_from_Dev{dev}{COLUMN_SUFFIX}"]]

                entry["pan2_ul"].append(ul_per)
                entry["pan2_dl"].append(dl_per)
                entry["pan2_rssi"].append(rssi)

            # この観測(1 Seed 分)のRSSIから、起点を超えた端末数を数える
            _update_anchor_stats("PAN2", pan2_ch, entry["pan2_rssi"][-NUM_DEVICE:])

    # 受信数ベースのPERは重複受信で負になり得る。どれだけ起きたかを必ず出す。
    # 割合が大きいなら、この定義は「ACK損失が損失として現れない」という
    # correct_mesure のコメントが指摘していた問題に実際にぶつかっている。
    n_total = CLIP_STATS["total"]
    n_neg = CLIP_STATS["negative"]
    if n_total > 0:
        print(
            f"--- PER clip: 受信数 > 分母 となり 0 にクリップした件数 "
            f"{n_neg} / {n_total} ({100.0 * n_neg / n_total:.2f}%) ---"
        )
        if n_neg > 0:
            print(
                "    (再送フレームの重複受信によるもの。割合が大きい場合、"
                "この PER 定義は ACK 損失を損失として捉えられていない)"
            )
    return data


# ============================================================
# 干渉検知（帯域幅ペアごとに interf/no_interf を比較）
# ============================================================
# 干渉検知に使うRSSIビンは select_bins() が返す。起点は
# bin_anchor_dbm(ch) が返すチャネル固有の固定値なので、ビン境界は
# Seed にも負荷にも依存しない。

# 分散のしきい値の探索範囲。ΔPERは[-1, 1]なので分散の理論上限は1だが、
# 実データではもっと小さい値になるはず。0〜1を0.001刻みで細かく探索する。
VARIANCE_THRESHOLDS = np.round(np.arange(0.0, 1.001, 0.001), 4)


def compute_seed_max_variance(delta_per, rssi_list, num_devices, anchor_dbm,
                              stats_key=None):
    """
    delta_per, rssi_list: Seedごとに num_devices 個ずつ連続して並んだ1次元配列。
    各SeedについてRSSIを select_bins() が返すビンに分け、ビンごとのΔPER分散を
    計算し、そのSeed内での最大分散値を「干渉指標」として返す。
    どのビンを使うかは select_bins() が決める(起点 anchor_dbm 以下の端末は入らない)。

    stats_key を渡すと、ビン内端末数と「有効ビン0のSeed数」を診断用に集計する。

    戻り値: (各Seedの最大分散値のリスト, 有効ビンが1つも無かったSeed数)。
    有効なビン（データ点2個以上）が1つも無いSeedの指標は 0.0 とする。
    """
    rssi_list = np.asarray(rssi_list, dtype=float)
    delta_per = np.asarray(delta_per, dtype=float)
    num_seeds = len(rssi_list) // num_devices

    seed_max_variances = []
    n_degenerate = 0
    for s in range(num_seeds):
        start = s * num_devices
        end = (s + 1) * num_devices
        rssi_seed = rssi_list[start:end]
        delta_seed = delta_per[start:end]

        valid = rssi_seed != 0
        r_v = rssi_seed[valid]
        d_v = delta_seed[valid]

        max_var = 0.0
        n_used = 0
        # 起点は固定だが、上端(最大RSSI)と端末の入り方はSeedごとに違うので
        # ビンの本数と中身はSeedごとに変わる。
        for upper, lower in select_bins(r_v, anchor_dbm):
            mask = (r_v > lower) & (r_v <= upper)
            bin_values = d_v[mask]
            if len(bin_values) > 1:
                n_used += 1
                if stats_key is not None:
                    BIN_OCCUPANCY[stats_key].append(len(bin_values))
                var_val = np.var(bin_values)
                if var_val > max_var:
                    max_var = var_val

        if n_used == 0:
            n_degenerate += 1
            if stats_key is not None:
                DEGENERATE_SEEDS[stats_key] += 1

        seed_max_variances.append(max_var)

    return seed_max_variances, n_degenerate


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


def _rank_auc(interf_values, no_interf_values):
    """順位ベースの AUC。Mann-Whitney U / (n_pos * n_neg) と同じ。

        AUC = P(指標_interf > 指標_no_interf) + 0.5 * P(同値)

    F1 が「最良の1点」での性能なのに対し、AUC は閾値の選び方に依らない分離度を
    表すので、両方を並べて見るために出す。

    閾値グリッド上の台形則にしないのは、VARIANCE_THRESHOLDS が 1.0 打ち切りの
    固定グリッドだから。指標が 1.0 を超える条件では ROC が途中で切れて AUC が
    頭打ちになる。生の値の順位なら打ち切りも刻み幅の影響も無い。

    向きは補正しない。evaluate_interference_detection() の判定が `>= th` の
    片側固定なので AUC の向きも一意に決まる。0.5 を下回ったら「指標が干渉の
    有無と逆相関している」という情報そのもので、max(auc, 1 - auc) にすると
    それが潰れる。

    rankdata は同順位に midrank を与える。有効ビンが1つも作れなかった Seed は
    compute_seed_max_variance() が max_var の初期値 0.0 をそのまま返すので
    同値が溜まり得るが、midrank によりその組は正しく 0.5 として数えられる。

    曲線そのものを見たいときは plot_roc.py。同じスコアから ROC を引くので、
    その台形則面積はここで返す値と一致する。
    """
    n_pos = len(interf_values)
    n_neg = len(no_interf_values)
    if n_pos == 0 or n_neg == 0:
        return float("nan")

    ranks = stats.rankdata(np.concatenate([interf_values, no_interf_values]))
    return (ranks[:n_pos].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


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
    # Seed ごとのスコア。ROC を引くのに要る (検知結果CSVは最良閾値1点の混同行列
    # しか持たないので、そこからは曲線を復元できない)。
    score_rows = []
    for (bw_label, distance, pan1_offload, pan2_offload), pair in sorted(groups.items()):
        if "interf" not in pair or "no_interf" not in pair:
            # 対になるシナリオ（干渉あり/なし両方）が揃っていない場合はスキップ
            continue

        interf_entry = data[pair["interf"]]
        no_interf_entry = data[pair["no_interf"]]

        # ビンの起点はチャネルの受信感度から決まる。同一帯域ペアの interf 側と
        # no_interf 側 (例 ch0 と ch3) は周波数だけが違って受信感度は同じなので、
        # 対にして比較する際にビン定義がずれることはない。念のため検査する。
        interf_ch = {"PAN1": pair["interf"][0], "PAN2": pair["interf"][1]}
        no_interf_ch = {"PAN1": pair["no_interf"][0], "PAN2": pair["no_interf"][1]}

        for pan_name, dl_key, ul_key, rssi_key in [
            ("PAN1", "pan1_dl", "pan1_ul", "pan1_rssi"),
            ("PAN2", "pan2_dl", "pan2_ul", "pan2_rssi"),
        ]:
            anchor = bin_anchor_dbm(interf_ch[pan_name])
            anchor_no_interf = bin_anchor_dbm(no_interf_ch[pan_name])
            if anchor != anchor_no_interf:
                raise ValueError(
                    f"{bw_label} {pan_name}: interf 側 (ch{interf_ch[pan_name]}) と "
                    f"no_interf 側 (ch{no_interf_ch[pan_name]}) でビンの起点が違います "
                    f"({anchor} vs {anchor_no_interf})。対比較が成立しません。"
                )

            interf_delta = np.array(interf_entry[dl_key]) - np.array(interf_entry[ul_key])
            no_interf_delta = np.array(no_interf_entry[dl_key]) - np.array(no_interf_entry[ul_key])

            interf_values, interf_degen = compute_seed_max_variance(
                interf_delta, interf_entry[rssi_key], NUM_DEVICE, anchor,
                (pan_name, interf_ch[pan_name]))
            no_interf_values, no_interf_degen = compute_seed_max_variance(
                no_interf_delta, no_interf_entry[rssi_key], NUM_DEVICE, anchor,
                (pan_name, no_interf_ch[pan_name]))

            if len(interf_values) == 0 or len(no_interf_values) == 0:
                print(f"Warning: no seed data for {bw_label} {distance}m pan1_{pan1_offload}_pan2_{pan2_offload} ({pan_name}) - skipping")
                continue

            result = evaluate_interference_detection(interf_values, no_interf_values)

            # compute_seed_max_variance は Seed 順に返すので、添字が
            # simulation_results.csv の Seed 番号と一致する。
            for klass, values in (("interf", interf_values),
                                  ("no_interf", no_interf_values)):
                for seed, score in enumerate(values):
                    score_rows.append({
                        "bandwidth": bw_label,
                        "distance": distance,
                        "pan1_offload": pan1_offload,
                        "pan2_offload": pan2_offload,
                        "pan": pan_name,
                        "klass": klass,
                        "seed": seed,
                        "score": f"{score:.9g}",
                    })

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
                # 閾値の選び方に依らない分離度。定義は _rank_auc() を参照。
                # 100x100 ペアなので刻みが 1e-4。他の指標より1桁多く残す。
                "auc": round(_rank_auc(interf_values, no_interf_values), 4),
                "n_interf_seeds": result["n_interf_seeds"],
                "n_no_interf_seeds": result["n_no_interf_seeds"],
                # 有効ビンが1つも作れず干渉指標が 0.0 に縮退したSeed数。
                # 0 でない場合、その条件の検知性能はビンの起点が高すぎることに
                # 引きずられている。
                "n_degenerate_interf": interf_degen,
                "n_degenerate_no_interf": no_interf_degen,
            })

    return rows, score_rows


def save_detection_scores_csv(rows, output_path):
    """Seed ごとの干渉指標を書き出す。ROC 曲線 (plot_roc.py) の入力。

    検知結果CSVは最良閾値1点の混同行列しか持たないので、そこからは ROC を
    復元できない。ここでスコアそのものを残しておけば、155MB の
    simulation_results.csv を再解析しなくても曲線を引き直せる。
    """
    fieldnames = ["bandwidth", "distance", "pan1_offload", "pan2_offload",
                  "pan", "klass", "seed", "score"]
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def save_interference_detection_csv(rows, output_path):
    fieldnames = [
        "bandwidth", "distance", "pan1_offload", "pan2_offload", "pan",
        "best_threshold", "TP", "FP", "FN", "TN",
        "precision", "recall", "fpr", "f1", "auc",
        "n_interf_seeds", "n_no_interf_seeds",
        "n_degenerate_interf", "n_degenerate_no_interf",
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
    parser = argparse.ArgumentParser(
        description="干渉検知の解析。検知結果CSVを出すだけで、図は作らない "
                    "(図は create_heatmap.py と plot_detection_lines.py の担当)。")
    parser.add_argument(
        "--mode", choices=("td", "conv"), default="td",
        help="td: 各メトリックを自分の200s窓で測る時間分割測定(既定) / "
             "conv: 全メトリックを W0 の200sで同時に測る従来方式")
    args = parser.parse_args()
    set_measurement_mode(args.mode)
    print(f"--- 測定モード: {MEASUREMENT_MODE} (列の接尾辞 '{COLUMN_SUFFIX}') ---")

    if not os.path.isfile(CSV_FILE):
        raise FileNotFoundError(f"CSV file not found: {CSV_FILE}")

    print(f"--- Loading {CSV_FILE} ---")
    data = load_and_aggregate(CSV_FILE)
    print(f"--- Loaded {len(data)} conditions ---")

    # --- 干渉検知（帯域幅ペアごとに interf/no_interf を比較） ---
    print("--- Running interference detection analysis ---")
    interference_rows, score_rows = run_interference_detection(data)
    interference_csv_path = os.path.join(
        PLOT_BASE_DIR, f"interference_detection_results{COLUMN_SUFFIX}.csv")
    save_interference_detection_csv(interference_rows, interference_csv_path)
    print(f"--- Saved {len(interference_rows)} rows to {interference_csv_path} ---")

    scores_csv_path = os.path.join(
        PLOT_BASE_DIR, f"detection_scores{COLUMN_SUFFIX}.csv")
    save_detection_scores_csv(score_rows, scores_csv_path)
    print(f"--- Saved {len(score_rows)} score rows to {scores_csv_path} ---")

    # ビンの起点を固定値に変えた影響(端末が何台残るか)をここで実測値として出す。
    print_bin_diagnostics()

    print("--- Done ---")


if __name__ == "__main__":
    main()