#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
変動係数(CV)による干渉判定。

これまでの検知統計量は ΔPER (= PER_DL - PER_UL) の RSSIビン内分散だった。
分散は PER の絶対水準に依存するため、負荷・伝送速度・距離が変わると帰無水準が
動き、固定の閾値が条件を跨いで通用しない (icc では帯域ペアごとに最適 tau が
0.039〜0.078 とばらついていた)。

そこで変動係数 CV = 標準偏差 / 平均 を使う。平均で正規化した無次元量なので、
PER の絶対水準に依らない閾値が期待できる。

設計上の決定:
  - UL と DL は **それぞれ独立に判定** する (差分は取らない)
  - CV は **RSSIビン内** で計算する (起点・幅は analyze_csv と共有)
  - 平均 PER が MEAN_PER_FLOOR を下回るビンは、その方向については使わない
    (CV の分母が 0 に近いと発散するため)

analyze_csv.py の分散ベースの経路には手を入れていない。同じブランチで
分散版と CV 版の両方を出して比較できるようにするため。
"""

import os
import sys
import csv
import argparse
from collections import defaultdict

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# ビンの切り方・PER の定義・CSV の読み込みは analyze_csv と完全に共有する。
# ここで複製すると定義が 2 箇所に増えて必ずずれる。
import analyze_csv as A  # noqa: E402

# ビンの平均 PER がこれを下回ったら、そのビンはその方向については使わない。
# CV = SD / mean なので、平均が 0 に近いと値が発散して外れ値になる。
MEAN_PER_FLOOR = 0.01

# 診断: 平均下限で捨てたビン数 (キーは (PAN, link))
FLOOR_SKIPPED = defaultdict(int)


# ============================================================
# 統計量
# ============================================================
def compute_seed_max_cv(per_list, rssi_list, num_devices, anchor_dbm, stats_key=None):
    """各 Seed について、RSSIビン内 PER の変動係数の最大値を返す。

    per_list, rssi_list: Seed ごとに num_devices 個ずつ連続して並んだ1次元配列。
    ビンの切り方は analyze_csv.select_bins() に従う (起点 anchor_dbm 以下は入らない)。

    戻り値: (各Seedの最大CVのリスト, 有効ビン0のSeed数, 平均下限で捨てたビン数)
    有効なビンが1つも無い Seed の値は 0.0 とする。
    """
    per = np.asarray(per_list, dtype=float)
    rssi = np.asarray(rssi_list, dtype=float)
    num_seeds = len(rssi) // num_devices

    values, n_degenerate, n_floor = [], 0, 0
    for s in range(num_seeds):
        sl = slice(s * num_devices, (s + 1) * num_devices)
        r_v, p_v = rssi[sl], per[sl]
        valid = r_v != 0
        r_v, p_v = r_v[valid], p_v[valid]

        max_cv, n_used = 0.0, 0
        for upper, lower in A.select_bins(r_v, anchor_dbm):
            vals = p_v[(r_v > lower) & (r_v <= upper)]
            if len(vals) < 2:
                continue
            mean = float(np.mean(vals))
            if mean < MEAN_PER_FLOOR:
                # 平均が 0 に近いビンは CV が発散するので使わない
                n_floor += 1
                if stats_key is not None:
                    FLOOR_SKIPPED[stats_key] += 1
                continue
            # 標準偏差は現行の分散統計量 (np.var, ddof=0) と揃える
            cv = float(np.std(vals)) / mean
            n_used += 1
            if cv > max_cv:
                max_cv = cv

        if n_used == 0:
            n_degenerate += 1
        values.append(max_cv)

    return values, n_degenerate, n_floor


# ============================================================
# 閾値探索
# ============================================================
def evaluate_detection(interf_values, no_interf_values):
    """F1 が最大になる閾値と、そのときの混同行列・各指標を返す。

    閾値の候補は固定格子ではなく **観測された統計量の値そのもの** を使う。
    CV は分散と違って 1 を超え得るので、固定格子だと上限の取り方で最適解を
    逃す。観測値を候補にすれば、どの範囲でも厳密に F1 最大の閾値が求まる。
    0.0 も候補に入れる (= 全部陽性の縮退解。F1 の構造的下限を与える)。
    """
    pos = np.asarray(interf_values, dtype=float)
    neg = np.asarray(no_interf_values, dtype=float)
    n_pos, n_neg = len(pos), len(neg)

    candidates = sorted(set(pos.tolist()) | set(neg.tolist()) | {0.0})

    best = None
    for th in candidates:
        tp = int((pos >= th).sum())
        fp = int((neg >= th).sum())
        fn, tn = n_pos - tp, n_neg - fp

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        if best is None or f1 > best["f1"]:
            best = {"threshold": float(th), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                    "precision": precision, "recall": recall, "fpr": fpr, "f1": f1}

    best["n_interf_seeds"] = n_pos
    best["n_no_interf_seeds"] = n_neg
    return best


# ============================================================
# 条件ごとの判定
# ============================================================
RESULT_FIELDS = [
    "bandwidth", "distance", "pan1_offload", "pan2_offload", "pan", "link",
    "best_threshold", "TP", "FP", "FN", "TN",
    "precision", "recall", "fpr", "f1",
    "n_interf_seeds", "n_no_interf_seeds",
    "n_degenerate_interf", "n_degenerate_no_interf",
    "n_floor_skipped_interf", "n_floor_skipped_no_interf",
]


def run_cv_detection(data):
    """帯域ペアごとに interf / no_interf を対にし、UL・DL それぞれで判定する。"""
    groups = defaultdict(dict)
    for condition_key in data:
        pan1_ch, pan2_ch, distance, l1, l2 = condition_key
        groups[(A.get_bandwidth_label(pan1_ch, pan2_ch), distance, l1, l2)][
            A.get_interf_label(pan1_ch, pan2_ch)] = condition_key

    rows = []
    for (bw_label, distance, l1, l2), pair in sorted(groups.items()):
        if "interf" not in pair or "no_interf" not in pair:
            continue

        interf_entry, no_interf_entry = data[pair["interf"]], data[pair["no_interf"]]
        interf_ch = {"PAN1": pair["interf"][0], "PAN2": pair["interf"][1]}
        no_interf_ch = {"PAN1": pair["no_interf"][0], "PAN2": pair["no_interf"][1]}

        for pan in ("PAN1", "PAN2"):
            anchor = A.bin_anchor_dbm(interf_ch[pan])
            if anchor != A.bin_anchor_dbm(no_interf_ch[pan]):
                raise ValueError(
                    f"{bw_label} {pan}: interf 側と no_interf 側でビンの起点が違います。"
                    " 対比較が成立しません。")

            rssi_key = pan.lower() + "_rssi"
            for link in ("ul", "dl"):
                per_key = pan.lower() + "_" + link
                iv, i_deg, i_flo = compute_seed_max_cv(
                    interf_entry[per_key], interf_entry[rssi_key],
                    A.NUM_DEVICE, anchor, (pan, link))
                nv, n_deg, n_flo = compute_seed_max_cv(
                    no_interf_entry[per_key], no_interf_entry[rssi_key],
                    A.NUM_DEVICE, anchor, (pan, link))
                if not iv or not nv:
                    print(f"Warning: no seed data for {bw_label} {distance}m "
                          f"pan1_{l1}_pan2_{l2} ({pan}/{link}) - skipping")
                    continue

                res = evaluate_detection(iv, nv)
                rows.append({
                    "bandwidth": bw_label, "distance": distance,
                    "pan1_offload": l1, "pan2_offload": l2,
                    "pan": pan, "link": link,
                    "best_threshold": round(res["threshold"], 5),
                    "TP": res["tp"], "FP": res["fp"], "FN": res["fn"], "TN": res["tn"],
                    "precision": round(res["precision"], 3),
                    "recall": round(res["recall"], 3),
                    "fpr": round(res["fpr"], 3),
                    "f1": round(res["f1"], 3),
                    "n_interf_seeds": res["n_interf_seeds"],
                    "n_no_interf_seeds": res["n_no_interf_seeds"],
                    "n_degenerate_interf": i_deg, "n_degenerate_no_interf": n_deg,
                    "n_floor_skipped_interf": i_flo, "n_floor_skipped_no_interf": n_flo,
                })

    return rows


def save_results(rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RESULT_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def print_summary(rows):
    if not rows:
        return
    print()
    print(f"=== 結果の要約 (平均PER下限 = {MEAN_PER_FLOOR}) ===")
    print(f"{'link':>6}{'条件数':>8}{'F1中央':>9}{'F1最小':>9}{'F1最大':>9}{'閾値中央':>10}")
    for link in ("ul", "dl"):
        sub = [r for r in rows if r["link"] == link]
        if not sub:
            continue
        f1 = np.array([r["f1"] for r in sub])
        th = np.array([r["best_threshold"] for r in sub])
        print(f"{link:>6}{len(sub):>8}{np.median(f1):>9.3f}{f1.min():>9.3f}"
              f"{f1.max():>9.3f}{np.median(th):>10.4f}")

    deg = sum(r["n_degenerate_interf"] + r["n_degenerate_no_interf"] for r in rows)
    flo = sum(r["n_floor_skipped_interf"] + r["n_floor_skipped_no_interf"] for r in rows)
    print()
    print(f"有効ビン0の観測: {deg} 件 / 平均下限で捨てたビン: {flo} 件")
    if FLOOR_SKIPPED:
        print("  (PAN, link) 別:", dict(sorted(FLOOR_SKIPPED.items())))
    if flo > 0:
        print("  下限で捨てた数が多い場合は MEAN_PER_FLOOR を見直すこと。")


def main():
    # argparse の既定値で MEAN_PER_FLOOR を参照するので、global 宣言は関数の先頭に置く
    global MEAN_PER_FLOOR

    parser = argparse.ArgumentParser(
        description="変動係数(CV)による干渉判定。UL と DL をそれぞれ独立に判定する。")
    parser.add_argument(
        "--mode", choices=("td", "conv"), default="td",
        help="td: 各メトリックを自分の200s窓で測る時間分割測定(既定) / "
             "conv: 全メトリックを W0 の200sで同時に測る従来方式")
    parser.add_argument(
        "--mean-per-floor", type=float, default=MEAN_PER_FLOOR,
        help="ビンの平均PERがこれ未満なら、そのビンはその方向では使わない")
    args = parser.parse_args()

    MEAN_PER_FLOOR = args.mean_per_floor

    # 列の接尾辞 (td/conv) は analyze_csv 側の状態を切り替える。
    A.set_measurement_mode(args.mode)
    suffix = A.COLUMN_SUFFIX
    print(f"--- 測定モード: {args.mode} (列の接尾辞 '{suffix}') ---")

    if not os.path.isfile(A.CSV_FILE):
        raise FileNotFoundError(f"CSV file not found: {A.CSV_FILE}")

    print(f"--- Loading {A.CSV_FILE} ---")
    data = A.load_and_aggregate(A.CSV_FILE, A.STATS_DIR)
    print(f"--- Loaded {len(data)} conditions ---")

    rows = run_cv_detection(data)
    out = os.path.join(A.PLOT_BASE_DIR, f"cv_detection_results{suffix}.csv")
    save_results(rows, out)
    print(f"--- Saved {len(rows)} rows to {out} ---")

    A.print_bin_diagnostics()
    print_summary(rows)


if __name__ == "__main__":
    main()
