#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干渉判定3手法の ROC 曲線を描く。

save ブランチの plot_roc.py を、手法の列 (method) を持つこのブランチのスコアCSVに
合わせたもの。検知結果CSVの AUC は面積の数値でしかないので、低 FPR 側で素直に
立ち上がっているのか、高 FPR 側でようやく稼いでいるのかを曲線で見る。

断面は折れ線 (plot_detection_lines.py) と揃える:
  相手PAN負荷 = 100% に固定、1枚に5本 (自PAN負荷 20-100%)、凡例に AUC を併記
  1枚 = (自帯域, 相手帯域, 手法)。1モード 27 枚

出力: plots/roc/{simultaneous,sequential}/roc_own{A}_other{B}_{method}.pdf
設計は docs/save_features.md を参照。
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

# 自分/相手の読み替え規則と体裁は折れ線側と共有する。
import analyze_csv as A  # noqa: E402
import plot_detection_lines as L  # noqa: E402
from interference_2pan_config import OFFERED_LOAD_PERCENTS  # noqa: E402

DEFAULT_OUT_DIR = os.path.join(A.PLOT_BASE_DIR, "roc")
BANDWIDTHS = L.BANDWIDTHS
METHODS = A.DETECTION_METHODS

# 自PAN負荷の昇順に割り当てる色 (save の plot_roc.py と同じ。カラーユニバーサル
# デザイン推奨配色のアクセントカラー)。空色は白地コントラストが低いので線を太くする。
LOAD_COLORS = ["#FF4B00", "#005AFF", "#03AF7A", "#4DC4FF", "#990099"]
LINEWIDTH = 2.8


def input_csv_path(mode):
    return os.path.join(A.PLOT_BASE_DIR, f"detection_scores{A.mode_suffix(mode)}.csv")


def roc_curve(pos, neg):
    """(fpr, tpr) を返す。同値は1点にまとめる (save の plot_roc.py と同じ)。

    同じスコアを境に TP と FP が同時に増えるので、1件ずつ点を打つと階段が嘘になる。
    同値をまとめた点列の台形則面積は、順位ベースの AUC (analyze_csv._rank_auc) と一致する。
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
    idx = np.r_[np.where(np.diff(scores))[0], len(scores) - 1]
    tp = np.cumsum(labels)[idx]
    fp = np.cumsum(1.0 - labels)[idx]
    return np.r_[0.0, fp / n_neg], np.r_[0.0, tp / n_pos]


def auc_of(fpr, tpr):
    """ROC の台形則面積。"""
    return float(np.trapezoid(tpr, fpr))


def load_scores(csv_file):
    """{(method, own_bw, other_bw, own_load): {"interf": [...], "no_interf": [...]}}"""
    out = defaultdict(lambda: {"interf": [], "no_interf": []})
    with open(csv_file, "r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            own = L.own_other(r)
            if own is None:
                continue
            key = (r["method"], own["own_bw"], own["other_bw"], own["own_load"])
            out[key][r["klass"]].append(float(r["score"]))
    return out


def plot_one(scores, method, own_bw, other_bw, out_dir, fmt, mismatches):
    loads = sorted(OFFERED_LOAD_PERCENTS)
    fig, ax = plt.subplots(figsize=(6.6, 6.6))
    n_drawn = 0
    for i, load in enumerate(loads):
        cell = scores.get((method, own_bw, other_bw, load))
        if not cell or not cell["interf"] or not cell["no_interf"]:
            continue
        fpr, tpr = roc_curve(cell["interf"], cell["no_interf"])
        area = auc_of(fpr, tpr)
        # 曲線の面積が順位ベースの AUC と一致することを確かめる
        if abs(area - A._rank_auc(cell["interf"], cell["no_interf"])) > 1e-9:
            mismatches.append((method, own_bw, other_bw, load))
        ax.plot(fpr, tpr, color=LOAD_COLORS[i % len(LOAD_COLORS)], linewidth=LINEWIDTH,
                label=f"{load}%  (AUC {area:.3f})")
        n_drawn += 1

    # ランダム判定の基準線
    ax.plot([0, 1], [0, 1], color="0.6", linestyle="--", linewidth=1.0, zorder=0)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal")
    L.style_axes(ax)
    if n_drawn:
        ax.legend(loc="lower right", frameon=True, fontsize=L.LEGEND_FONTSIZE - 2)
    else:
        ax.text(0.5, 0.5, "no data", transform=ax.transAxes, ha="center",
                va="center", color="0.55")
    fig.tight_layout()
    path = os.path.join(out_dir, f"roc_own{own_bw}_other{other_bw}_{method}.{fmt}")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def main():
    p = argparse.ArgumentParser(description="干渉判定3手法の ROC 曲線を描く")
    p.add_argument("--mode", choices=A.MEASUREMENT_MODES, default="simultaneous",
                   help="simultaneous: single-query (既定) / sequential: multi-query")
    p.add_argument("--csv", default=None, help="Seed 別スコア CSV (--mode より優先)")
    p.add_argument("--out-dir", default=None,
                   help="出力先 (既定: plots/roc/<モード>/)")
    p.add_argument("--format", default="pdf", choices=("pdf", "png"))
    args = p.parse_args()

    path = args.csv or input_csv_path(args.mode)
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"スコアCSVがありません: {path}\n"
            f"  analyze_csv.py --mode {args.mode} を実行してください。")
    out_dir = args.out_dir or os.path.join(DEFAULT_OUT_DIR, args.mode)
    os.makedirs(out_dir, exist_ok=True)
    print(f"--- {args.mode}: {path} ---")
    scores = load_scores(path)

    written, mismatches = [], []
    for method in METHODS:
        for own_bw in BANDWIDTHS:
            for other_bw in BANDWIDTHS:
                written.append(plot_one(scores, method, own_bw, other_bw,
                                        out_dir, args.format, mismatches))
    if mismatches:
        print(f"    Warning: 曲線の面積と AUC が一致しない条件が {len(mismatches)} 件: "
              f"{mismatches[:5]}")
    print(f"--- {out_dir} に {len(written)} ファイル出力 ---")


if __name__ == "__main__":
    main()
