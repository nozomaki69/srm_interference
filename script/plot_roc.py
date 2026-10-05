#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干渉検知の ROC 曲線を描く。

検知結果CSVの auc 列は面積の数値でしかないので、「低 FPR 側で素直に立ち上がって
いるのか、高 FPR 側でようやく稼いでいるのか」が分からない。閾値をどこに置くかの
議論もできない。そこで曲線そのものを描く。

入力は analyze_csv.py が出す plots/detection_scores{,_conv}.csv (Seed ごとの
干渉指標)。検知結果CSVは最良閾値1点の混同行列しか持たないので、そこからは
曲線を復元できない。

断面は折れ線グラフ (plot_detection_lines.py) と揃えてある:
  相手PAN負荷 = 100% に固定
  1枚   = 自帯域 x 測定モード            -> roc_own{50,100,200}_{conv,td}
  1枚に 3パネル (相手帯域 50/100/200 kbps)
  1パネルに 5本 (自PAN負荷 20-100%)、凡例に AUC を併記
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

# 自分/相手の読み替え規則と配色の方針は折れ線側と共有する。
# 規則を2箇所に書くと片方だけ直して静かにずれる。
import analyze_csv as A  # noqa: E402
import plot_detection_lines as L  # noqa: E402
from interference_2pan_config import OFFERED_LOAD_PERCENTS  # noqa: E402

PLOT_BASE_DIR = A.PLOT_BASE_DIR
DEFAULT_OUT_DIR = os.path.join(PLOT_BASE_DIR, "roc")

BANDWIDTHS = L.BANDWIDTHS
MODES = L.MODES

# --- 配色 -------------------------------------------------------------
# 1パネル内で変わるのは自PAN負荷で、これは順序のある量。カテゴリカル配色では
# なく単一色相の濃淡 (dataviz の sequential、blue ランプ) を薄い->濃いで当てる。
# 負荷が上がる = 検知が難しくなる方向を濃い色にしている。
#
# ランプの薄い側 (250 / 300) は白地でコントラストが 2:1 台しかなく線が見えない
# ので使わない。濃い側に寄せた 350 / 450 / 500 / 600 / 700 を使う。
LOAD_COLORS = ["#5598e7", "#2a78d6", "#256abf", "#184f95", "#0d366b"]

# 濃い側に寄せたぶん隣接する段どうしが近くなるので、マーカーで冗長符号化する。
# 階段状の曲線が潰れないよう markevery で間引く。
LOAD_MARKERS = ["o", "s", "^", "D", "v"]
MARKEVERY = 12

GRID_KW = L.GRID_KW

# 図中のテキストは英語。計算機 (Linux) に日本語フォントが無いと豆腐になるため。
XLABEL = "False positive rate"
YLABEL = "True positive rate"


def input_csv_path(mode):
    suffix = "" if mode == "td" else "_conv"
    return os.path.join(PLOT_BASE_DIR, f"detection_scores{suffix}.csv")


def roc_curve(pos, neg):
    """(fpr, tpr) を返す。sklearn には依存しない。

    スコアの降順に閾値を下げながら TPR = TP/n_pos, FPR = FP/n_neg を出す。
    **同値は1点にまとめる**。同じスコアを境に TP と FP が同時に増えるので、
    1件ずつ点を打つと「先に TP だけ増えた」ように見えて階段が嘘になる。
    同値をまとめた点列の台形則面積は、順位ベースの AUC
    (analyze_csv._rank_auc) と一致する。
    """
    pos = np.asarray(pos, dtype=float)
    neg = np.asarray(neg, dtype=float)
    n_pos, n_neg = len(pos), len(neg)
    if n_pos == 0 or n_neg == 0:
        return np.array([0.0, 1.0]), np.array([0.0, 1.0])

    scores = np.concatenate([pos, neg])
    labels = np.concatenate([np.ones(n_pos), np.zeros(n_neg)])

    order = np.argsort(-scores, kind="mergesort")
    scores, labels = scores[order], labels[order]

    # 同値の並びの「最後」の位置だけを残す
    idx = np.r_[np.where(np.diff(scores))[0], len(scores) - 1]
    tp = np.cumsum(labels)[idx]
    fp = np.cumsum(1.0 - labels)[idx]

    # (0,0) から始める。終点は必ず (1,1) になる。
    return np.r_[0.0, fp / n_neg], np.r_[0.0, tp / n_pos]


def auc_of(fpr, tpr):
    """ROC の台形則面積。"""
    return float(np.trapezoid(tpr, fpr))


def load_scores(csv_file):
    """{(own_bw, other_bw, own_load): {"interf": [...], "no_interf": [...]}}"""
    with open(csv_file, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"{csv_file}: データ行がありません")

    out = defaultdict(lambda: {"interf": [], "no_interf": []})
    for r in rows:
        own = L.own_other(r)
        if own is None:
            continue
        key = (own["own_bw"], own["other_bw"], own["own_load"])
        out[key][r["klass"]].append(float(r["score"]))
    return out


def _draw_panel(ax, scores, own_bw, other_bw):
    loads = sorted(OFFERED_LOAD_PERCENTS)
    n_drawn = 0
    for i, load in enumerate(loads):
        cell = scores.get((own_bw, other_bw, load))
        if not cell or not cell["interf"] or not cell["no_interf"]:
            continue
        fpr, tpr = roc_curve(cell["interf"], cell["no_interf"])
        ax.plot(fpr, tpr, color=LOAD_COLORS[i % len(LOAD_COLORS)],
                marker=LOAD_MARKERS[i % len(LOAD_MARKERS)],
                markersize=5, markevery=MARKEVERY,
                linewidth=2.0,
                label=f"{load}%  (AUC {auc_of(fpr, tpr):.3f})")
        n_drawn += 1

    # ランダム判定の基準線
    ax.plot([0, 1], [0, 1], color="0.6", linestyle="--", linewidth=1.0, zorder=0)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal")
    ax.set_xlabel(XLABEL, fontsize=10)
    ax.set_title(f"Other PAN: {other_bw} kbps", fontsize=11)
    ax.grid(True, **GRID_KW)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("0.4")
    # データが無いパネルに空の凡例枠だけ出ると紛らわしい
    if n_drawn:
        ax.legend(title="Own PAN load", loc="lower right",
                  frameon=True, fontsize=8, title_fontsize=8)
    else:
        ax.text(0.5, 0.5, "no data", transform=ax.transAxes,
                ha="center", va="center", color="0.55", fontsize=10)


def plot_one(scores, own_bw, mode, out_dir, fmt):
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.8))
    for ax, other_bw in zip(axes, BANDWIDTHS):
        _draw_panel(ax, scores, own_bw, other_bw)
    axes[0].set_ylabel(YLABEL, fontsize=10)
    fig.suptitle(f"Own PAN: {own_bw} kbps   "
                 f"(other PAN at {L.OTHER_LOAD_PERCENT}% load, {mode})",
                 fontsize=12)
    fig.tight_layout()
    path = os.path.join(out_dir, f"roc_own{own_bw}_{mode}.{fmt}")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def main():
    p = argparse.ArgumentParser(description="干渉検知の ROC 曲線を描く")
    p.add_argument("--td-csv", default=None, help="td の Seed 別スコア CSV")
    p.add_argument("--conv-csv", default=None, help="conv の Seed 別スコア CSV")
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    p.add_argument("--format", default="pdf", choices=("pdf", "png"),
                   help="出力形式 (既定: pdf)。目視確認には png")
    args = p.parse_args()

    paths = {"td": args.td_csv or input_csv_path("td"),
             "conv": args.conv_csv or input_csv_path("conv")}

    os.makedirs(args.out_dir, exist_ok=True)
    written = []
    for mode in MODES:
        path = paths[mode]
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"スコアCSVがありません: {path}\n"
                f"  analyze_csv.py --mode {mode} を実行してください "
                f"(./script/sbatch_reanalyze.sh でも作られます)。")
        print(f"--- {mode:>4}: {path} ---")
        scores = load_scores(path)

        expected = len(BANDWIDTHS) ** 2 * len(OFFERED_LOAD_PERCENTS)
        print(f"    条件 {len(scores)}/{expected}")

        for own_bw in BANDWIDTHS:
            written.append(plot_one(scores, own_bw, mode, args.out_dir, args.format))

    print(f"\n--- {args.out_dir} に {len(written)} ファイル出力 ---")
    for path in written:
        print(f"    {os.path.basename(path)}")


if __name__ == "__main__":
    main()
