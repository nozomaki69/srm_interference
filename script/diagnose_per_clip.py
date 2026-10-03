#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PER のクリップ（受信数 > 分母 となって 0 に潰される現象）の原因を切り分ける。

実データで 9.50% (342,042 / 3,599,932) が観測された。PER の分子を直接汚染するので、
どの条件で起きているのかを特定する。設計の意図は docs/per_measurement.md の付録を参照。

出すもの:
  1. モード別の全体クリップ率
  2. 自PAN負荷別
  3. RSSIビン別（起点からの相対位置）
  4. 方向 (UL/DL) 別
  5. macCsmaFailCount の割合（自PAN負荷別）
  6. WindowDeq_* の均衡（トラフィックが定常か）
  7. 分母に macCsmaFailCount を含めた場合のクリップ率  <- 修正案の効果を直接測る

simulation_results.csv を1回読むだけ。再解析も再シミュレーションも不要。
"""

import os
import sys
import csv
import argparse
from collections import defaultdict

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# ビンの起点・チャネル情報は analyze_csv と共有する
import analyze_csv as A  # noqa: E402

COUNTERS4 = ("macTxSuccessCount", "macRetryCount",
             "macMultipleRetryCount", "macTxFailCount")
CSMA = "macCsmaFailCount"


def _col(idx, name):
    return idx.get(name)


def analyze(csv_file, modes):
    with open(csv_file, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {n: i for i, n in enumerate(header)}
        is_float = ["RSSI" in n for n in header]

        # 集計器。キーは (mode, 区分)
        tot = defaultdict(int)       # 分母>0 だった件数
        clip = defaultdict(int)      # raw PER < 0 だった件数
        clip5 = defaultdict(int)     # 分母に csma_fail を含めた場合に負だった件数
        csma_ratio = defaultdict(list)
        window_deq = defaultdict(list)
        n_rows = 0

        win_cols = [n for n in header if n.startswith("WindowDeq_")]

        for raw in reader:
            if len(raw) != len(header):
                raise ValueError(f"{csv_file}: 列数が一致しません "
                                 f"(header {len(header)} / row {len(raw)})")
            r = [float(x) if fl else int(float(x)) for x, fl in zip(raw, is_float)]
            n_rows += 1
            for c in win_cols:
                window_deq[c].append(r[idx[c]])

            pan1_ch, pan2_ch = r[idx["PAN1_CH"]], r[idx["PAN2_CH"]]
            l1, l2 = r[idx["PAN1_Offload"]], r[idx["PAN2_Offload"]]

            for pan, ch, own, devs in (("PAN1", pan1_ch, l1, A.PAN1_DEVS),
                                       ("PAN2", pan2_ch, l2, A.PAN2_DEVS)):
                anchor = A.bin_anchor_dbm(ch)
                for dev in devs:
                    for mode in modes:
                        sfx = "" if mode == "td" else "_conv"
                        rssi = r[idx[f"{pan}_PC_RSSI_Avg_from_Dev{dev}{sfx}"]]
                        # RSSI から起点を基準にしたビン番号 (0 = 最弱の有効ビン)
                        if rssi == 0:
                            bin_i = -1          # 未受信
                        elif rssi <= anchor:
                            bin_i = -2          # 起点以下（ビンに入らない）
                        else:
                            bin_i = int((rssi - anchor) // A.RSSI_BIN_SIZE_DBM)

                        for link in ("ul", "dl"):
                            if link == "ul":
                                pre = f"{pan}_Dev{dev}_to_Co_"
                                n_rx = r[idx[f"{pan}_PC_Rx_from_Dev{dev}{sfx}"]]
                            else:
                                pre = f"{pan}_Co_to_Dev{dev}_"
                                n_rx = r[idx[f"{pan}_Dev{dev}_Rx_from_PC{sfx}"]]

                            c4 = [r[idx[pre + n + sfx]] for n in COUNTERS4]
                            denom4 = sum(c4)
                            cs = r[idx[pre + CSMA + sfx]]
                            denom5 = denom4 + cs

                            if denom4 <= 0:
                                continue
                            neg4 = n_rx > denom4
                            neg5 = (denom5 > 0) and (n_rx > denom5)

                            for key in (("all",), ("load", own), ("bin", bin_i),
                                        ("link", link)):
                                tot[(mode,) + key] += 1
                                if neg4:
                                    clip[(mode,) + key] += 1
                                if neg5:
                                    clip5[(mode,) + key] += 1

                            if denom5 > 0:
                                csma_ratio[(mode, own)].append(cs / denom5)

    return tot, clip, clip5, csma_ratio, window_deq, n_rows


def pct(num, den):
    return f"{100.0 * num / den:6.2f}%" if den else "     -"


def report(tot, clip, clip5, csma_ratio, window_deq, n_rows, modes, out_csv):
    rows = []
    print(f"\n読み込んだラン数: {n_rows}")

    print("\n=== 1. 全体のクリップ率 ===")
    print(f"{'mode':>6}{'判定数':>12}{'4カウンタ分母':>14}{'5カウンタ分母(csma込み)':>24}")
    for m in modes:
        t = tot[(m, "all")]
        print(f"{m:>6}{t:>12}{pct(clip[(m,'all')], t):>14}{pct(clip5[(m,'all')], t):>24}")
        rows.append({"mode": m, "group": "all", "key": "", "n": t,
                     "clip_denom4": clip[(m, "all")], "clip_denom5": clip5[(m, "all")]})

    for group, title in (("load", "2. 自PAN負荷別"), ("bin", "3. RSSIビン別 (0=最弱, -1=未受信, -2=起点以下)"),
                         ("link", "4. 方向別")):
        print(f"\n=== {title} ===")
        keys = sorted({k[2] for k in tot if k[0] in modes and k[1] == group},
                      key=lambda x: (isinstance(x, str), x))
        hdr = f"{'':>10}" + "".join(f"{m+' 4分母':>12}{m+' 5分母':>12}" for m in modes)
        print(hdr)
        for key in keys:
            line = f"{str(key):>10}"
            for m in modes:
                t = tot[(m, group, key)]
                line += f"{pct(clip[(m,group,key)], t):>12}{pct(clip5[(m,group,key)], t):>12}"
                rows.append({"mode": m, "group": group, "key": key, "n": t,
                             "clip_denom4": clip[(m, group, key)],
                             "clip_denom5": clip5[(m, group, key)]})
            print(line)

    print("\n=== 5. macCsmaFailCount の割合 (csma / 5カウンタ和) ===")
    print(f"{'自負荷':>8}" + "".join(f"{m+' 中央':>12}{m+' 平均':>12}" for m in modes))
    for load in sorted({k[1] for k in csma_ratio}):
        line = f"{load:>7}%"
        for m in modes:
            v = csma_ratio.get((m, load), [])
            line += (f"{np.median(v):>12.4f}{np.mean(v):>12.4f}" if v else f"{'-':>12}{'-':>12}")
        print(line)

    if window_deq:
        print("\n=== 6. 窓ごとの dequeue 数 (定常性の確認) ===")
        for c in sorted(window_deq):
            v = window_deq[c]
            print(f"  {c:>26} 中央 {int(np.median(v)):>8}  平均 {np.mean(v):>10.1f}")
        meds = [np.median(window_deq[c]) for c in sorted(window_deq)]
        if min(meds) > 0:
            print(f"  -> 最大/最小 = {max(meds)/min(meds):.3f}  (1.0 に近いほど定常)")

    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["mode", "group", "key", "n",
                                          "clip_denom4", "clip_denom5"])
        w.writeheader()
        w.writerows(rows)
    print(f"\n--- 明細を {out_csv} に出力 ---")

    print("\n=== 読み方 ===")
    print("  conv の 4分母 がほぼ 0%        -> 窓の分割が主因 (td 固有)")
    print("  conv も 9% 前後                -> csma_fail の除外が主因 (両モード共通)")
    print("  5分母 でクリップが消える       -> 分母に csma_fail を足す修正が有効")
    print("  高負荷・強RSSI に集中している   -> 想定した機序の裏付け")


def main():
    p = argparse.ArgumentParser(description="PER のクリップの原因を切り分ける")
    p.add_argument("--mode", choices=("td", "conv", "both"), default="both")
    p.add_argument("--csv", default=A.CSV_FILE)
    p.add_argument("--out", default=os.path.join(A.PLOT_BASE_DIR, "per_clip_diagnosis.csv"))
    args = p.parse_args()

    modes = ("td", "conv") if args.mode == "both" else (args.mode,)
    if not os.path.isfile(args.csv):
        raise FileNotFoundError(f"CSV file not found: {args.csv}")
    print(f"--- {args.csv} を読み込み（モード: {', '.join(modes)}）---")
    report(*analyze(args.csv, modes), modes=modes, out_csv=args.out)


if __name__ == "__main__":
    main()
