#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
干渉あり / なしで、上りリンクと下りリンクの PER の変動係数 (CV) が
実際にどのような値を取るのかを可視化する。

判定方式を決める前に、分離があるのか・どの向きに動くのか・閾値をどこに置けそうかを
データで確認するのが狙い。設計の意図は docs/cv_distribution_plots.md を参照。

統計量は analyze_cv.compute_seed_max_cv() と同じ定義:
    ビンごと cv_b = std(PER in ビンb) / mean(PER in ビンb)
    観測ごと 統計量 = max_b cv_b
--aggregate bin を指定すると max を取る前のビンごとの生の CV を描く。

simulation_results.csv から読むだけなので再シミュレーションは不要。
"""

import os
import sys
import csv
import argparse
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# ビンの切り方・PER の定義・CSV の読み込みは analyze_csv と共有する
import analyze_csv as A  # noqa: E402

# --- 配色 -------------------------------------------------------------------
# dataviz の既定カテゴリパレットの slot1 / slot2。色は干渉の有無にだけ使い、
# UL / DL はパネルで分ける。色数を2に絞ることで CVD 下の分離に余裕を持たせる。
# validate_palette.js と同じ計算で検証済み:
#   light: 通常視 ΔE 33.6 (floor 15) / CVD 最小 ΔE 24.7 (target 8) / 全チェック PASS
COLOR = {"no_interf": "#2a78d6", "interf": "#eb6834"}
# 図中のテキストは英語にする。計算機 (Linux) に日本語フォントが無いと豆腐文字に
# なるうえ、投稿先も英文のため。コンソール出力と記録は日本語のままでよい。
LABEL = {"no_interf": "No interference", "interf": "Interference"}
# 色だけに頼らないための副次エンコーディング
LINESTYLE = {"no_interf": "-", "interf": "--"}
MARKER = {"no_interf": "o", "interf": "^"}

GRID_KW = dict(color="0.85", linestyle="--", linewidth=0.8)
ORDER = ["no_interf", "interf"]


def _style_axes(ax):
    """グリッドと軸を後退させる。"""
    ax.grid(True, **GRID_KW)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("0.4")


# ============================================================
# データの収集
# ============================================================
def bin_cvs(per_list, rssi_list, num_devices, anchor_dbm):
    """Seed ごとに、そのSeedの各ビンの CV のリストを返す。"""
    per = np.asarray(per_list, dtype=float)
    rssi = np.asarray(rssi_list, dtype=float)
    for s in range(len(rssi) // num_devices):
        sl = slice(s * num_devices, (s + 1) * num_devices)
        r_v, p_v = rssi[sl], per[sl]
        valid = r_v != 0
        r_v, p_v = r_v[valid], p_v[valid]
        out = []
        for upper, lower in A.select_bins(r_v, anchor_dbm):
            vals = p_v[(r_v > lower) & (r_v <= upper)]
            if len(vals) < 2:
                continue
            mean = float(np.mean(vals))
            if mean <= 0:
                continue
            out.append(float(np.std(vals)) / mean)
        yield out


def collect(data, pans, aggregate, other_load=None, own_load=None):
    """(bandwidth, own_load, other_load, pan, label, cv_ul, cv_dl) を集める。

    aggregate="max" なら観測ごとに max_b cv_b を1点、"bin" ならビンごとに1点。
    UL と DL は同じビン構成から取るので、散布図で対にできる。

    other_load / own_load を指定するとその負荷の条件だけに絞る。相手PAN負荷が
    20〜40% の領域は oracle 閾値でも検知不能 (F1 が構造的下限に張り付く) なので、
    全負荷を混ぜると信号が薄まる。干渉が実際に効いている領域だけを見たいときは
    other_load=100 のように絞ること。
    """
    recs = []
    for ck, entry in data.items():
        pan1_ch, pan2_ch, distance, l1, l2 = ck
        label = A.get_interf_label(pan1_ch, pan2_ch)
        bw = A.get_bandwidth_label(pan1_ch, pan2_ch)
        for pan, ch, own, other in (("PAN1", pan1_ch, l1, l2),
                                    ("PAN2", pan2_ch, l2, l1)):
            if pan not in pans:
                continue
            if other_load is not None and other != other_load:
                continue
            if own_load is not None and own != own_load:
                continue
            anchor = A.bin_anchor_dbm(ch)
            p = pan.lower()
            ul_seeds = list(bin_cvs(entry[p + "_ul"], entry[p + "_rssi"],
                                    A.NUM_DEVICE, anchor))
            dl_seeds = list(bin_cvs(entry[p + "_dl"], entry[p + "_rssi"],
                                    A.NUM_DEVICE, anchor))
            for ul, dl in zip(ul_seeds, dl_seeds):
                if not ul or not dl:
                    continue
                if aggregate == "max":
                    pairs = [(max(ul), max(dl))]
                else:
                    pairs = list(zip(ul, dl))   # 同じビン同士を対にする
                for cv_ul, cv_dl in pairs:
                    recs.append((bw, own, other, pan, label, cv_ul, cv_dl))
    return recs


# ============================================================
# 図
# ============================================================
def plot_ecdf(recs, out_path, aggregate, cond="all loads"):
    """ECDF。閾値 tau で各クラスの何割が上に来るかを直接読める形。"""
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharex=True, sharey=True)
    for ax, (link, col) in zip(axes, (("Uplink (UL)", 5), ("Downlink (DL)", 6))):
        for lab in ORDER:
            v = np.sort([r[col] for r in recs if r[4] == lab])
            if not len(v):
                continue
            y = np.arange(1, len(v) + 1) / len(v)
            ax.plot(v, y, color=COLOR[lab], linestyle=LINESTYLE[lab], linewidth=2.0,
                    label=f"{LABEL[lab]} (n={len(v)})")
            ax.axvline(np.median(v), color=COLOR[lab], linewidth=1.0, alpha=0.35)
        ax.set_title(link, fontsize=12)
        ax.set_xlabel("Coefficient of variation  CV = SD / mean")
        _style_axes(ax)
    axes[0].set_ylabel("Cumulative fraction")
    axes[0].legend(loc="lower right", frameon=True, fontsize=10)
    fig.suptitle(f"ECDF of CV of PER  (aggregate={aggregate}, {cond})"
                 f"   vertical line = median", fontsize=13)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def plot_box_by_load(recs, out_path, cond="all loads"):
    """自PAN負荷ごとの箱ひげ図。負荷に対して CV がどう動くかを見る。"""
    loads = sorted(set(r[1] for r in recs))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharey=True)
    width = 0.34
    for ax, (link, col) in zip(axes, (("Uplink (UL)", 5), ("Downlink (DL)", 6))):
        for k, lab in enumerate(ORDER):
            data = [[r[col] for r in recs if r[1] == ld and r[4] == lab] for ld in loads]
            pos = np.arange(len(loads)) + (k - 0.5) * width
            bp = ax.boxplot(data, positions=pos, widths=width * 0.85, showfliers=False,
                            patch_artist=True, medianprops=dict(color="white", linewidth=1.6))
            for box in bp["boxes"]:
                box.set(facecolor=COLOR[lab], edgecolor=COLOR[lab], linewidth=0)
            for part in ("whiskers", "caps"):
                for ln in bp[part]:
                    ln.set(color=COLOR[lab], linewidth=1.2)
        ax.set_xticks(np.arange(len(loads)))
        ax.set_xticklabels([f"{l}%" for l in loads])
        ax.set_xlabel("Own PAN offered load")
        ax.set_title(link, fontsize=12)
        _style_axes(ax)
    axes[0].set_ylabel("Coefficient of variation")
    axes[0].legend(handles=[plt.Rectangle((0, 0), 1, 1, color=COLOR[l]) for l in ORDER],
                   labels=[LABEL[l] for l in ORDER], loc="upper left", fontsize=10)
    fig.suptitle(f"CV by own PAN offered load  ({cond})"
                 f"   whiskers = 1.5 IQR, outliers hidden", fontsize=13)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def plot_scatter(recs, out_path, cond="all loads"):
    """CV_ul × CV_dl。UL を対照に使えるか（比や差で分離が良くなるか）を見る。"""
    fig, ax = plt.subplots(figsize=(6.4, 6.0))
    for lab in ORDER:
        x = [r[5] for r in recs if r[4] == lab]
        y = [r[6] for r in recs if r[4] == lab]
        ax.scatter(x, y, s=14, marker=MARKER[lab], c=COLOR[lab], alpha=0.35,
                   linewidths=0, label=f"{LABEL[lab]} (n={len(x)})")
    lim = [0, max(max(r[5] for r in recs), max(r[6] for r in recs)) * 1.05]
    ax.plot(lim, lim, color="0.35", linewidth=1.2, linestyle=":", label="y = x")
    ax.set_xlim(lim); ax.set_ylim(lim); ax.set_aspect("equal")
    ax.set_xlabel("Uplink CV")
    ax.set_ylabel("Downlink CV")
    ax.set_title(f"Uplink vs downlink CV  ({cond})"
                 f"\n(above y=x: downlink is more dispersed)", fontsize=12)
    _style_axes(ax)
    # 点は alpha 0.35・小サイズなので、そのままだと凡例のマーカーが見えない。
    # 凡例だけ不透明・大きめにする。
    leg = ax.legend(loc="upper left", fontsize=10, markerscale=2.6)
    for h in leg.legend_handles:
        h.set_alpha(1.0)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def save_summary(recs, path, other_tag="all"):
    rows = []
    for lab in ORDER:
        for link, col in (("ul", 5), ("dl", 6)):
            for load in sorted(set(r[1] for r in recs)):
                v = np.array([r[col] for r in recs if r[4] == lab and r[1] == load])
                if not len(v):
                    continue
                rows.append({"label": lab, "link": link, "own_load": load,
                             "other_load": other_tag, "n": len(v),
                             "median": round(float(np.median(v)), 4),
                             "q1": round(float(np.percentile(v, 25)), 4),
                             "q3": round(float(np.percentile(v, 75)), 4),
                             "p5": round(float(np.percentile(v, 5)), 4),
                             "p95": round(float(np.percentile(v, 95)), 4)})
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return rows


def main():
    parser = argparse.ArgumentParser(
        description="干渉あり/なしで UL・DL の PER の変動係数の分布を可視化する")
    parser.add_argument("--mode", choices=("td", "conv"), default="td")
    parser.add_argument("--aggregate", choices=("max", "bin"), default="max",
                        help="max: 観測ごとの max_b cv_b (検知器が使う量) / "
                             "bin: ビンごとの生の CV")
    parser.add_argument("--pan", choices=("PAN1", "PAN2", "both"), default="both")
    # 相手PAN負荷 20〜40% は oracle 閾値でも F1 が構造的下限に張り付く検知不能領域
    # なので、全負荷を混ぜると干渉ありの分布が薄まる。干渉が効いている領域だけを
    # 見たいときは --other-load 100 のように絞る。
    parser.add_argument("--other-load", default="all",
                        help="相手PANの提供負荷で絞る (例: 100)。'all' なら絞らない")
    parser.add_argument("--own-load", default="all",
                        help="自PANの提供負荷で絞る (例: 100)。'all' なら絞らない")
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()

    other_load = None if args.other_load == "all" else int(args.other_load)
    own_load = None if args.own_load == "all" else int(args.own_load)

    # 図のタイトルと出力先のタグ。絞り込み条件ごとに図が上書きし合わないようにする。
    conds, tags = [], []
    if other_load is not None:
        conds.append(f"other PAN load = {other_load}%"); tags.append(f"_other{other_load}")
    if own_load is not None:
        conds.append(f"own PAN load = {own_load}%"); tags.append(f"_own{own_load}")
    cond = ", ".join(conds) if conds else "all loads"
    tag = "".join(tags)
    other_tag = "all" if other_load is None else str(other_load)

    A.set_measurement_mode(args.mode)
    suffix = A.COLUMN_SUFFIX
    out_dir = args.out_dir or os.path.join(A.PLOT_BASE_DIR, f"cv_distribution{suffix}{tag}")
    os.makedirs(out_dir, exist_ok=True)

    print(f"--- 測定モード: {args.mode}  集約: {args.aggregate}  対象: {args.pan}  絞り込み: {cond} ---")
    if not os.path.isfile(A.CSV_FILE):
        raise FileNotFoundError(f"CSV file not found: {A.CSV_FILE}")
    data = A.load_and_aggregate(A.CSV_FILE, A.STATS_DIR)
    print(f"--- Loaded {len(data)} conditions ---")

    pans = ("PAN1", "PAN2") if args.pan == "both" else (args.pan,)
    recs = collect(data, pans, args.aggregate, other_load, own_load)
    print(f"--- {len(recs)} 点を集計 ---")
    if not recs:
        raise SystemExit("絞り込み条件に該当する条件がありません。負荷の指定を確認してください。")

    plot_ecdf(recs, os.path.join(out_dir, "cv_ecdf.pdf"), args.aggregate, cond)
    plot_box_by_load(recs, os.path.join(out_dir, "cv_box_by_load.pdf"), cond)
    plot_scatter(recs, os.path.join(out_dir, "cv_scatter.pdf"), cond)
    rows = save_summary(recs, os.path.join(out_dir, "cv_summary.csv"), other_tag)
    print(f"--- 出力: {out_dir}/ (cv_ecdf.pdf, cv_box_by_load.pdf, cv_scatter.pdf, cv_summary.csv) ---")

    print()
    print("=== 中央値（全負荷まとめ）===")
    print(f"{'':>10}{'UL':>10}{'DL':>10}{'DL/UL':>9}")
    for lab in ORDER:
        u = np.median([r[5] for r in recs if r[4] == lab])
        d = np.median([r[6] for r in recs if r[4] == lab])
        print(f"{LABEL[lab]:>10}{u:>10.3f}{d:>10.3f}{d/u:>9.3f}")
    print()
    print("DL/UL が干渉ありで大きくなっていれば、UL を対照にした比で判定できる見込みがある。")


if __name__ == "__main__":
    main()
