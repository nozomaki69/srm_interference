#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提案手法の RSSI ビン幅の感度分析。ビン幅を 1-20 dBm で振って AUC を出し直す。

ビン幅に依存するのは提案手法の後処理だけなので、再シミュレーションは要らない。
plots/simulation_results.csv をモードごとに1回だけ読み (load_and_aggregate。ここが重い)、
ビン幅ごとに analyze_csv.run_interference_detection(bin_size=...) を回す。
95% 信頼区間は bootstrap_auc.bootstrap_group() をそのまま使う。

ビン幅 10 dBm (既定) の AUC と信頼区間が、既存の
interference_detection_results*.csv / auc_bootstrap*.csv と一致することを毎回確かめ、
一致しなければ止まる (解析の定義がずれていないことの保証)。

出力: plots/bin_width_sensitivity/auc_binwidth_{single,multi}.csv
      plots/bin_width_sensitivity/bin_diagnostics_{single,multi}.csv
設計は docs/bin_width_sensitivity.md を参照。
"""

import os
import sys
import csv
import time
import argparse
from collections import defaultdict

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import analyze_csv as A  # noqa: E402
import bootstrap_auc as B  # noqa: E402

OUT_DIR = os.path.join(A.PLOT_BASE_DIR, "bin_width_sensitivity")
# ファイル名に入れるモードの呼び名 (plot_detection_lines.FILE_MODE_TAG と同じ)
FILE_MODE_TAG = {"simultaneous": "single", "sequential": "multi"}
DEFAULT_WIDTHS = list(range(1, 21))     # 1..20 dBm、1 dBm 刻み
REFERENCE_WIDTH = A.RSSI_BIN_SIZE_DBM   # 既存の解析で使っている幅 (10 dBm)

COND_KEYS = ("bandwidth", "distance", "pan1_offload", "pan2_offload", "pan")
FIELDS = (["bin_width_dbm"] + list(COND_KEYS)
          + ["auc", "auc_ci_low", "auc_ci_high", "n_boot",
             "n_degenerate_interf", "n_degenerate_no_interf"])
DIAG_FIELDS = ["bin_width_dbm", "pan", "channel", "kbps", "observations",
               "valid_bins_per_seed", "devices_per_bin_median", "devices_per_bin_max",
               "degenerate_seeds"]


def auc_path(mode):
    return os.path.join(OUT_DIR, f"auc_binwidth_{FILE_MODE_TAG[mode]}.csv")


def diag_path(mode):
    return os.path.join(OUT_DIR, f"bin_diagnostics_{FILE_MODE_TAG[mode]}.csv")


def parse_widths(text):
    """"1-20" や "2,5,10" -> 整数のリスト。"""
    out = []
    for part in text.split(","):
        if "-" in part:
            a, b = (int(x) for x in part.split("-"))
            out += list(range(a, b + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def group_scores(score_rows):
    """score_rows -> {group_key: {"interf": array, "no_interf": array}}。

    bootstrap_auc.load_scores() と同じ形・同じ並び (Seed 番号順)。スコアも
    CSV に書くときと同じ文字列から読むので、既存のブートストラップと同じ値になる。
    """
    raw = defaultdict(lambda: {"interf": [], "no_interf": []})
    for r in score_rows:
        key = tuple(str(r[k]) for k in B.GROUP_KEYS)
        raw[key][r["klass"]].append((int(r["seed"]), float(r["score"])))
    return {key: {k: np.array([s for _, s in sorted(v)], dtype=float)
                  for k, v in g.items()}
            for key, g in raw.items()}


def bootstrap_rows(score_rows, n_boot, seed):
    """{group_key: (auc, lo, hi)}。

    乱数の消費順を bootstrap_auc.run_mode() と同じ (全手法の group_key をソートした順) に
    するため、ビン幅に依らない dper / rssi のスコアも渡して一緒に回す。こうすると
    ビン幅 10 dBm の区間が既存の auc_bootstrap*.csv とぴったり一致し、照合に使える。
    """
    groups = group_scores(score_rows)
    rng = np.random.default_rng(seed)
    lo_q, hi_q = 100 * (1 - B.CI_LEVEL) / 2, 100 * (1 + B.CI_LEVEL) / 2
    out = {}
    for key in sorted(groups):
        g = groups[key]
        if len(g["interf"]) == 0 or len(g["no_interf"]) == 0:
            continue
        auc, boot = B.bootstrap_group(g["interf"], g["no_interf"], n_boot, rng)
        lo, hi = np.percentile(boot, [lo_q, hi_q])
        out[key] = (auc, lo, hi)
    return out


def load_reference(mode):
    """既存の解析結果 (ビン幅 10 dBm) の proposed: {cond_key: (auc, lo, hi or None)}。"""
    sfx = A.mode_suffix(mode)
    res = os.path.join(A.PLOT_BASE_DIR, f"interference_detection_results{sfx}.csv")
    boot = os.path.join(A.PLOT_BASE_DIR, f"auc_bootstrap{sfx}.csv")
    ref = {}
    if os.path.isfile(res):
        with open(res, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if r["method"] == "proposed":
                    ref[tuple(r[k] for k in COND_KEYS)] = [float(r["auc"]), None, None]
    if os.path.isfile(boot):
        with open(boot, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                key = tuple(r[k] for k in COND_KEYS)
                if r["method"] == "proposed" and key in ref:
                    ref[key][1:] = [float(r["auc_ci_low"]), float(r["auc_ci_high"])]
    return ref


def diagnostics(width):
    """直前の run_interference_detection の、(PAN, ch) ごとのビン構成。"""
    rows = []
    for key in sorted(A.ANCHOR_STATS):
        pan, ch = key
        occ = np.asarray(A.BIN_OCCUPANCY.get(key, []), dtype=float)
        # ANCHOR_STATS の観測数は load_and_aggregate() が数えた (Seed, PAN) の数
        n_obs = A.ANCHOR_STATS[key]["observations"]
        rows.append({
            "bin_width_dbm": width, "pan": pan, "channel": ch,
            "kbps": A.CHANNEL_KBPS[ch], "observations": n_obs,
            "valid_bins_per_seed": f"{len(occ) / n_obs:.4f}" if n_obs else "nan",
            "devices_per_bin_median": f"{np.median(occ):.1f}" if occ.size else "nan",
            "devices_per_bin_max": f"{occ.max():.0f}" if occ.size else "nan",
            "degenerate_seeds": A.DEGENERATE_SEEDS.get(key, 0),
        })
    return rows


def run_mode(mode, widths, n_boot, seed):
    A.set_measurement_mode(mode)
    # 診断用のグローバル集計は load のたびに足し込まれるので、モードごとに空にする
    A.ANCHOR_STATS.clear()
    print(f"=== {mode} ({FILE_MODE_TAG[mode]}-query): {A.CSV_FILE} を読み込み ===")
    t0 = time.time()
    data = A.load_and_aggregate(A.CSV_FILE)
    print(f"    {len(data)} 条件 ({time.time() - t0:.0f} s)")

    ref = load_reference(mode)
    if not ref:
        print("    (既存の検知結果CSVが無いので、10 dBm の照合は省略)")

    out_rows, diag_rows = [], []
    for w in widths:
        t0 = time.time()
        A.BIN_OCCUPANCY.clear()
        A.DEGENERATE_SEEDS.clear()
        # 3手法とも回す: dper / rssi はビン幅に依らないが、ブートストラップの乱数の
        # 消費順を既存と揃えるため (bootstrap_rows() 参照)。出力は proposed だけ。
        rows, score_rows = A.run_interference_detection(data, bin_size=w)
        diag_rows += diagnostics(w)
        ci = bootstrap_rows(score_rows, n_boot, seed)

        n_mismatch = 0
        for r in rows:
            if r["method"] != "proposed":
                continue
            cond = tuple(str(r[k]) for k in COND_KEYS)
            auc, lo, hi = ci[cond + ("proposed",)]
            if abs(round(auc, 4) - r["auc"]) > 1e-9:
                raise AssertionError(f"{cond}: ブートストラップ側と検知側の AUC が違います")
            if w == REFERENCE_WIDTH and cond in ref:
                ra, rlo, rhi = ref[cond]
                if (abs(r["auc"] - ra) > 1e-9
                        or (rlo is not None and (abs(round(lo, 4) - rlo) > 1e-9
                                                 or abs(round(hi, 4) - rhi) > 1e-9))):
                    n_mismatch += 1
            out_rows.append({"bin_width_dbm": w, **{k: r[k] for k in COND_KEYS},
                             "auc": f"{r['auc']:.4f}",
                             "auc_ci_low": f"{lo:.4f}", "auc_ci_high": f"{hi:.4f}",
                             "n_boot": n_boot,
                             "n_degenerate_interf": r["n_degenerate_interf"],
                             "n_degenerate_no_interf": r["n_degenerate_no_interf"]})
        n_degen = sum(A.DEGENERATE_SEEDS.values())
        print(f"    ビン幅 {w:>2} dBm: 縮退 Seed {n_degen:>5} 件 ({time.time() - t0:.0f} s)")
        if w == REFERENCE_WIDTH and ref:
            if n_mismatch:
                raise SystemExit(
                    f"エラー: ビン幅 {w} dBm の結果が既存の解析結果と {n_mismatch} 件"
                    "一致しません。simulation_results.csv か解析コードが既存の結果と"
                    "別物になっている可能性があります。")
            print(f"    -> ビン幅 {w} dBm は既存の解析結果 (AUC と 95% 区間) と全件一致")

    os.makedirs(OUT_DIR, exist_ok=True)
    for path, fields, rows in ((auc_path(mode), FIELDS, out_rows),
                               (diag_path(mode), DIAG_FIELDS, diag_rows)):
        with open(path, "w", encoding="utf-8", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=fields)
            wr.writeheader()
            wr.writerows(rows)
        print(f"--- {len(rows)} 行 -> {path} ---")


def main():
    p = argparse.ArgumentParser(description="提案手法の RSSI ビン幅の感度分析")
    p.add_argument("--mode", choices=A.MEASUREMENT_MODES + ("both",), default="both")
    p.add_argument("--widths", default="1-20", help="ビン幅 [dBm]。例 '1-20' / '5,10,15'")
    p.add_argument("--n-boot", type=int, default=1000, help="ブートストラップの回数")
    p.add_argument("--seed", type=int, default=0, help="乱数のシード (bootstrap_auc.py と同じ既定)")
    args = p.parse_args()

    if not os.path.isfile(A.CSV_FILE):
        raise SystemExit(f"エラー: 入力CSVがありません: {A.CSV_FILE}")
    widths = parse_widths(args.widths)
    modes = A.MEASUREMENT_MODES if args.mode == "both" else (args.mode,)
    print(f"--- ビン幅 {widths} dBm, 起点 = 受信感度 + {A.RSSI_BIN_ANCHOR_OFFSET_DBM} dBm, "
          f"ブートストラップ {args.n_boot} 回 ---")
    for mode in modes:
        run_mode(mode, widths, args.n_boot, args.seed)


if __name__ == "__main__":
    main()
