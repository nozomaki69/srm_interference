#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RSSIビン幅の感度分析。幅を 1〜20 dBm で振り、提案手法の AUC を比べる。

simulation_results.csv を1回だけ読み (ここが重い)、幅ごとに
analyze_csv.run_interference_detection(data, methods=("proposed",), bin_size=w)
を呼ぶ。dper / rssi はビンを使わず幅に依存しないので、1回だけ計算して
比較用の水平線にする。

再シミュレーションは不要 (ビン幅は解析でしか使わない)。設計は docs/bin_width.md。

出力 (plots/bin_width_sensitivity/):
  auc_by_bin_width.csv          幅 x 条件 x 手法の AUC
  auc_vs_bin_width.pdf          全条件の平均 AUC vs 幅
  auc_vs_bin_width_by_load.pdf  相手負荷100%断面、自帯域ごと・自負荷ごと
  degenerate_vs_bin_width.pdf   有効なビンが作れなかった Seed の割合 vs 幅
"""

import os
import sys
import csv
import argparse
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import analyze_csv as A  # noqa: E402
import plot_detection_lines as L  # noqa: E402
from interference_2pan_config import OFFERED_LOAD_PERCENTS  # noqa: E402

DEFAULT_OUT_DIR = os.path.join(A.PLOT_BASE_DIR, "bin_width_sensitivity")
CSV_NAME = "auc_by_bin_width.csv"

BIN_WIDTHS = list(range(1, 21))   # [dBm]
CURRENT_WIDTH = A.RSSI_BIN_SIZE_DBM

FIELDS = ["bin_width", "bandwidth", "pan1_offload", "pan2_offload", "pan", "method",
          "auc", "n_interf_seeds", "n_no_interf_seeds",
          "n_degenerate_interf", "n_degenerate_no_interf"]

# 自PAN負荷ごとの色 (薄い -> 濃い)
LOAD_CMAP = plt.get_cmap("viridis")


# ------------------------------------------------------------
# 計算
# ------------------------------------------------------------
def compute_rows(csv_file):
    print(f"--- Loading {csv_file} ---")
    data = A.load_and_aggregate(csv_file)
    print(f"--- Loaded {len(data)} conditions ---")
    # 入力が icc の全ランぶん揃っているかを見るための内訳。
    # condition_key = (pan1_ch, pan2_ch, distance, pan1_offload, pan2_offload)
    pairs = sorted({(k[0], k[1]) for k in data})
    loads = sorted({k[3] for k in data} | {k[4] for k in data})
    print(f"    チャネルの組 ({len(pairs)}): {pairs}")
    print(f"    負荷 [%]: {loads}")

    rows = []
    # 幅に依存しない手法は1回だけ (bin_width は空欄)
    base, _ = A.run_interference_detection(
        data, methods=tuple(m for m in A.DETECTION_METHODS if m != "proposed"))
    for r in base:
        rows.append({**r, "bin_width": ""})

    for w in BIN_WIDTHS:
        res, _ = A.run_interference_detection(data, methods=("proposed",), bin_size=w)
        for r in res:
            rows.append({**r, "bin_width": w})
        mean = np.mean([r["auc"] for r in res]) if res else float("nan")
        print(f"    bin width {w:>2} dBm: {len(res)} 条件, 平均 AUC {mean:.4f}")
    if not any(r["method"] == "proposed" for r in rows):
        # 干渉あり (同一周波数) と干渉なし (別周波数) の組が1つも揃わないと
        # AUC が1つも出ない。入力が icc の完全な結果でないときに起きる。
        raise SystemExit(
            "エラー: 干渉あり/なしの対になる条件が1つもありません。\n"
            "       simulation_results.csv が icc の 30,000 ランぶん揃っていない"
            "可能性があります (上のチャネルの組と負荷を確認してください)。\n"
            "       icc は 12 組 (干渉あり ch0-2 同士の6組 + 干渉なし ch3-5 を含む6組)、"
            "負荷 [20, 40, 60, 80, 100] が揃っているはずです。")
    return rows


def save_rows(rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def load_rows(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["bin_width"] = int(r["bin_width"]) if r["bin_width"] else ""
        r["auc"] = float(r["auc"])
        for k in ("n_interf_seeds", "n_no_interf_seeds",
                  "n_degenerate_interf", "n_degenerate_no_interf"):
            r[k] = int(r[k])
    return rows


# ------------------------------------------------------------
# 集計
# ------------------------------------------------------------
def summarize(rows):
    """全条件の平均 AUC (proposed は幅ごと) と縮退割合を返す。"""
    prop = defaultdict(list)
    degen = defaultdict(lambda: [0, 0])
    base = defaultdict(list)
    for r in rows:
        if r["method"] == "proposed":
            prop[r["bin_width"]].append(r["auc"])
            d = degen[r["bin_width"]]
            d[0] += r["n_degenerate_interf"] + r["n_degenerate_no_interf"]
            d[1] += r["n_interf_seeds"] + r["n_no_interf_seeds"]
        else:
            base[r["method"]].append(r["auc"])
    widths = sorted(prop)
    mean_auc = {w: float(np.mean(prop[w])) for w in widths}
    degen_ratio = {w: degen[w][0] / degen[w][1] if degen[w][1] else float("nan")
                   for w in widths}
    base_mean = {m: float(np.mean(v)) for m, v in base.items()}
    # 同じ平均値なら狭い方 (max は最初に見つかったものを返し、widths は昇順)
    best = max(widths, key=lambda w: mean_auc[w])
    return widths, mean_auc, degen_ratio, base_mean, best


def section_by_load(rows):
    """相手負荷100%の断面で {own_bw: {own_load: {width: [auc...]}}} を返す。

    相手帯域3つぶんの AUC をまとめる (平均は描画側で取る)。
    """
    out = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for r in rows:
        if r["method"] != "proposed":
            continue
        own = L.own_other({k: str(v) for k, v in r.items()})
        if own is None:
            continue
        out[own["own_bw"]][own["own_load"]][r["bin_width"]].append(r["auc"])
    return out


# ------------------------------------------------------------
# 作図
# ------------------------------------------------------------
def _width_axis(ax):
    ax.set_xticks([1, 5, 10, 15, 20])
    ax.set_xlim(0.5, 20.5)
    ax.set_xlabel("RSSI bin width [dB]", fontsize=L.TICK_LABELSIZE)


def plot_mean(widths, mean_auc, base_mean, best, out_dir, fmt):
    fig, ax = plt.subplots(figsize=(8.0, 5.8))
    ax.axvline(CURRENT_WIDTH, color="0.6", linewidth=1.2, linestyle="-", zorder=0,
               label=f"Current setting ({CURRENT_WIDTH} dB)")
    ax.plot(widths, [mean_auc[w] for w in widths], color="#d62728", marker="o",
            markersize=6, linewidth=2.0, label=A.METHOD_LABEL["proposed"])
    for m in ("dper", "rssi"):
        if m in base_mean:
            ax.axhline(base_mean[m], color="0.35", linestyle=L.LINESTYLE[m],
                       linewidth=2.0, label=A.METHOD_LABEL[m])
    ax.plot([best], [mean_auc[best]], marker="*", markersize=20, color="#d62728",
            markeredgecolor="k", linestyle="", zorder=5,
            label=f"Best ({best} dB, AUC {mean_auc[best]:.3f})")
    L.style_axes(ax)
    _width_axis(ax)
    ax.set_ylabel("Mean AUC (all conditions)", fontsize=L.TICK_LABELSIZE)
    # 枠の外 (右横) に置く。枠内だと線に重なるため
    ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=L.LEGEND_FONTSIZE,
              frameon=True)
    path = os.path.join(out_dir, f"auc_vs_bin_width.{fmt}")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_by_load(section, out_dir, fmt):
    loads = sorted(OFFERED_LOAD_PERCENTS)
    fig, axes = plt.subplots(1, len(L.BANDWIDTHS), figsize=(19.0, 5.8), sharey=True)
    for ax, own_bw in zip(axes, L.BANDWIDTHS):
        ax.axvline(CURRENT_WIDTH, color="0.6", linewidth=1.2, zorder=0)
        for i, load in enumerate(loads):
            per_w = section.get(own_bw, {}).get(load, {})
            ws = sorted(per_w)
            if not ws:
                continue
            ys = [float(np.mean(per_w[w])) for w in ws]
            color = LOAD_CMAP(i / max(len(loads) - 1, 1) * 0.9)
            ax.plot(ws, ys, color=color, marker="o", markersize=4, linewidth=2.0,
                    label=f"Own load {load}%")
            b = ws[int(np.argmax(ys))]
            ax.plot([b], [max(ys)], marker="*", markersize=14, color=color,
                    markeredgecolor="k", linestyle="")
        L.style_axes(ax)
        _width_axis(ax)
        ax.set_title(f"Own {own_bw} kbps", fontsize=L.TICK_LABELSIZE)
    axes[0].set_ylabel("AUC (other load 100%)", fontsize=L.TICK_LABELSIZE)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="center left", bbox_to_anchor=(1.0, 0.5),
               fontsize=L.LEGEND_FONTSIZE, frameon=True)
    fig.tight_layout()
    path = os.path.join(out_dir, f"auc_vs_bin_width_by_load.{fmt}")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_degenerate(widths, degen_ratio, out_dir, fmt):
    fig, ax = plt.subplots(figsize=(8.0, 5.8))
    ax.axvline(CURRENT_WIDTH, color="0.6", linewidth=1.2, zorder=0)
    ax.plot(widths, [100.0 * degen_ratio[w] for w in widths], color="0.25",
            marker="o", markersize=6, linewidth=2.0)
    L.style_axes(ax)
    _width_axis(ax)
    ax.set_ylabel("Seeds without a valid bin [%]", fontsize=L.TICK_LABELSIZE)
    ax.set_ylim(bottom=0)
    path = os.path.join(out_dir, f"degenerate_vs_bin_width.{fmt}")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def main():
    p = argparse.ArgumentParser(description="RSSIビン幅 1〜20 dBm の感度分析")
    p.add_argument("--csv", default=A.CSV_FILE, help="simulation_results.csv")
    p.add_argument("--from-csv", action="store_true",
                   help=f"再計算せず、出力先の {CSV_NAME} から図だけ作り直す")
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    p.add_argument("--format", default="pdf", choices=("pdf", "png"))
    args = p.parse_args()

    out_csv = os.path.join(args.out_dir, CSV_NAME)
    if args.from_csv:
        rows = load_rows(out_csv)
    else:
        if not os.path.isfile(args.csv):
            raise FileNotFoundError(f"CSV file not found: {args.csv}")
        rows = compute_rows(args.csv)
        save_rows(rows, out_csv)
        print(f"--- Saved {len(rows)} rows to {out_csv} ---")

    widths, mean_auc, degen_ratio, base_mean, best = summarize(rows)
    print("--- 全条件の平均 AUC ---")
    for w in widths:
        mark = "  <- best" if w == best else ("  (現在の設定)" if w == CURRENT_WIDTH else "")
        print(f"    {w:>2} dB: {mean_auc[w]:.4f}  縮退 {100 * degen_ratio[w]:5.2f}%{mark}")
    for m, v in base_mean.items():
        print(f"    {m}: {v:.4f} (幅に依存しない)")

    os.makedirs(args.out_dir, exist_ok=True)
    written = [
        plot_mean(widths, mean_auc, base_mean, best, args.out_dir, args.format),
        plot_by_load(section_by_load(rows), args.out_dir, args.format),
        plot_degenerate(widths, degen_ratio, args.out_dir, args.format),
    ]
    print(f"--- {os.path.normpath(args.out_dir)} に出力 ---")
    for w in written:
        print(f"    {os.path.basename(w)}")


if __name__ == "__main__":
    main()
