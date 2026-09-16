# -*- coding: utf-8 -*-
"""plots/simulation_results.csv から、実際に出た負荷が offered_load と一致しているか検証する。

MAC の DataFrameDequeued は、アプリが生成したデータフレームが送信キューから取り出された
回数をそのまま数えている:

  - 6LoWPAN 無効時のデータは上限なしの std::queue (driot_mac.h:260) に積まれるので
    キュー溢れによる取りこぼしが無い
  - キューから pop されるのは1回だけで、再送は outputBuffer から行われるため
    再送で二重にカウントされない (driot_mac.cpp:1607,1619)

したがって CSV の Deq 列の合計 = アプリが生成したパケット数 であり、
追加のシミュレーションを走らせずに実負荷を検証できる。

使い方:
    python3 script/verify_offered_load.py [path/to/simulation_results.csv]
"""

import csv
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from interference_2pan_config import (  # noqa: E402
    APPS_PER_PAN,
    CHANNELS,
    MEASURE_DURATION_SEC,
    NUM_DEVICE,
    exchange_cycle_sec,
    offered_load_pps,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.join(SCRIPT_DIR, "..", "plots", "simulation_results.csv")

# 実測/期待比がこの範囲を外れたら警告する
RATIO_TOLERANCE = 0.02

# この負荷[%]を超える条件は過飽和領域。提供レートが衝突なし飽和容量を超えるので
# 待ち行列は原理的に発散し、実際に送出できる量は 100% 付近で頭打ちになる。
# つまり ratio < 1 になるのが正しい挙動なので、許容判定の対象外にして
# 情報として表示するだけにする(ここを含めると常に失敗して検証にならない)。
SATURATION_LOAD_PERCENT = 100


def device_ids(pan):
    if pan == 1:
        return range(3, 3 + NUM_DEVICE)
    return range(3 + NUM_DEVICE, 3 + 2 * NUM_DEVICE)


def deq_columns(pan):
    """PAN(1 or 2)の、アプリ生成パケット数に相当する列名を (下り, 上り) で返す。

    下り(DL)はコーディネータの PAN{n}_PC_Deq_Total (30アプリ分がこの1ノードに集中)、
    上り(UL)は各デバイスの PAN{n}_Dev{id}_Deq (1デバイス1アプリ)。

    DLとULは提供レートが同じ(各30アプリ)なので、両者がずれていたら
    コーディネータ1ノードにDL30アプリ分が集中していることによる滞留を疑う。
    """
    return ([f"PAN{pan}_PC_Deq_Total"],
            [f"PAN{pan}_Dev{d}_Deq" for d in device_ids(pan)])


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV

    if not os.path.isfile(csv_path):
        print(f"Error: CSV not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    # (channel, offered_load) -> {"dl": [...], "ul": [...]} の1ランごとの交換数
    observed = defaultdict(lambda: {"dl": [], "ul": []})

    with open(csv_path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {name: i for i, name in enumerate(header)}

        cols = {}
        for pan in (1, 2):
            dl_names, ul_names = deq_columns(pan)
            cols[pan] = ([idx[c] for c in dl_names], [idx[c] for c in ul_names])

        for row in reader:
            if not row:
                continue
            for pan in (1, 2):
                ch = int(row[idx[f"PAN{pan}_CH"]])
                load = int(row[idx[f"PAN{pan}_Offload"]])
                dl_cols, ul_cols = cols[pan]
                bucket = observed[(ch, load)]
                bucket["dl"].append(sum(int(row[i]) for i in dl_cols))
                bucket["ul"].append(sum(int(row[i]) for i in ul_cols))

    if not observed:
        print(f"Error: no rows in {csv_path}", file=sys.stderr)
        sys.exit(1)

    print(f"CSV: {csv_path}")
    print(f"traffic window: {MEASURE_DURATION_SEC} s, apps per PAN: {APPS_PER_PAN} "
          f"(DL {APPS_PER_PAN // 2} on the coordinator + UL {APPS_PER_PAN // 2} on the devices)")
    print()
    print(f"{'ch':>3} {'kbps':>5} {'load%':>6} {'runs':>5} "
          f"{'expected':>9} {'observed':>9} {'ratio':>6} {'DL':>6} {'UL':>6} "
          f"{'occup%':>7} {'per-dev':>8}")
    print("-" * 88)

    worst = 0.0
    worst_ul = 0.0
    dl_shortfall = False

    for (ch, load) in sorted(observed):
        bucket = observed[(ch, load)]
        runs = len(bucket["dl"])
        bitrate = CHANNELS[ch]["bitrate_kbps"]

        # DLとULはそれぞれ APPS_PER_PAN/2 アプリ分
        half = APPS_PER_PAN / 2.0
        expected_half = half * offered_load_pps(bitrate, load) * MEASURE_DURATION_SEC
        expected = 2.0 * expected_half

        mean_dl = sum(bucket["dl"]) / runs
        mean_ul = sum(bucket["ul"]) / runs
        mean_obs = mean_dl + mean_ul

        ratio = mean_obs / expected if expected else float("nan")
        dl_ratio = mean_dl / expected_half if expected_half else float("nan")
        ul_ratio = mean_ul / expected_half if expected_half else float("nan")

        # 実測の交換数から逆算した占有率[%]。offered_load と一致するのが正しい。
        occupancy = mean_obs * exchange_cycle_sec(bitrate) / MEASURE_DURATION_SEC * 100.0

        # 1アプリあたりの送信パケット数 (統計的な粒度の目安)
        per_device = expected / APPS_PER_PAN

        if load > SATURATION_LOAD_PERCENT:
            # 過飽和領域。ratio が 1 を下回るのが正しいので判定には使わない。
            flag = "  (oversub)"
        else:
            flag = "" if abs(ratio - 1.0) <= RATIO_TOLERANCE else "  <--"
            worst = max(worst, abs(ratio - 1.0))
            worst_ul = max(worst_ul, abs(ul_ratio - 1.0))
            if dl_ratio < 1.0 - RATIO_TOLERANCE:
                dl_shortfall = True

        print(f"{ch:>3} {bitrate:>5} {load:>6} {runs:>5} "
              f"{expected:>9.1f} {mean_obs:>9.1f} {ratio:>6.3f} "
              f"{dl_ratio:>6.3f} {ul_ratio:>6.3f} {occupancy:>7.2f} "
              f"{per_device:>8.1f}{flag}")

    print()
    print(f"worst deviation (total): {worst * 100:.2f}%  "
          f"(UL only: {worst_ul * 100:.2f}%, tolerance {RATIO_TOLERANCE * 100:.0f}%)")
    print(f"判定対象は load <= {SATURATION_LOAD_PERCENT}% の行のみ。"
          f"(oversub) の行は過飽和領域なので ratio < 1 が正常。")
    print("過飽和側は occup% 列を見る: 100 付近で頭打ちになっていれば飽和に到達している。")

    if worst > RATIO_TOLERANCE:
        print()
        print("ズレたときの切り分け:")
        if dl_shortfall and worst_ul <= RATIO_TOLERANCE:
            print("  -> DL だけが不足している。コーディネータ1ノードに下り30アプリ分が")
            print("     集中しており、CSMAで取れる送信機会が足りずキューに滞留している。")
            print("     高負荷側だけなら飽和領域として想定内。低負荷でも出るなら要調査。")
        else:
            print("  - 全負荷で一様に低い    -> 送信窓の打ち切り")
            print("     (simulation-time がトラフィック終了と同時になっていないか)")
            print("  - 高負荷側だけ低い      -> 待ち行列の滞留 (DL/UL 列で偏りを確認)")
            print("  - 伝送速度ごとにズレる  -> exchange_cycle_sec() の項の取りこぼし")
        sys.exit(1)


if __name__ == "__main__":
    main()
