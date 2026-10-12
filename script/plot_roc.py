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
  1枚に 5本 (自PAN負荷 20-100%)、凡例に AUC を併記

--layout で1枚の粒度を選ぶ:
  single (既定) 1条件1枚  roc_own{A}_other{B}_{mode}  3x3x2 = 18枚
  panel         相手帯域3つを横並び roc_own{A}_{mode}  3x2   =  6枚
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
# 指定配色。カラーユニバーサルデザイン推奨配色セットのアクセントカラー。
# 自PAN負荷の昇順に割り当てる。
#
# 全ペアの OKLab dE は最小 19.6 (緑 vs 空色) で、通常視の床 15 を超える。
# ここまでに試した配色の中では最も分離が良い:
#   単一色相 blue の濃淡 5.0 / 寒色->暖色の5色相 7.1 / 青->紫 10.7
#   / Okabe-Ito から5色 16.4 / これ 19.6
#
# 注意: 空色 #4DC4FF は白地コントラストが 1.97:1 で 3:1 を下回る。線幅を
# 2.8 に取ってあるので線としては見えるが、細くすると薄れる。
LOAD_COLORS = [
    "#FF4B00",   # 20%   赤      白地コントラスト 3.36:1
    "#005AFF",   # 40%   青      5.38:1
    "#03AF7A",   # 60%   緑      2.83:1
    "#4DC4FF",   # 80%   空色    1.97:1
    "#990099",   # 100%  紫      7.46:1
]

# 細いと色が判別しにくいので、既定より太くする
LINEWIDTH = 2.8

GRID_KW = L.GRID_KW
# 体裁は折れ線側と共有する (plot_detection_lines が定義元)
LEGEND_FONTSIZE = L.LEGEND_FONTSIZE

# 軸ラベルとタイトルは入れない (横軸 = FPR、縦軸 = TPR)。
# 図のキャプションで説明する前提。


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
                linewidth=LINEWIDTH,
                label=f"{load}%  (AUC {auc_of(fpr, tpr):.3f})")
        n_drawn += 1

    # ランダム判定の基準線
    ax.plot([0, 1], [0, 1], color="0.6", linestyle="--", linewidth=1.0, zorder=0)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal")
    L.style_axes(ax)
    # データが無いパネルに空の凡例枠だけ出ると紛らわしい
    if n_drawn:
        ax.legend(loc="lower right", frameon=True, fontsize=LEGEND_FONTSIZE)
    else:
        ax.text(0.5, 0.5, "no data", transform=ax.transAxes, ha="center",
                va="center", color="0.55", fontsize=L.ANNOT_FONTSIZE)


def plot_single(scores, own_bw, other_bw, mode, out_dir, fmt):
    """1条件 (自帯域 x 相手帯域 x モード) を1枚に描く。

    _draw_panel() が1パネル分を完結して描くので、呼び出し方を変えるだけ。
    どの条件かはファイル名 roc_own{A}_other{B}_{mode} で区別する
    (図中にタイトルは入れない)
    """
    fig, ax = plt.subplots(figsize=(6.6, 6.6))
    _draw_panel(ax, scores, own_bw, other_bw)
    fig.tight_layout()
    path = os.path.join(out_dir, f"roc_own{own_bw}_other{other_bw}_{mode}.{fmt}")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_one(scores, own_bw, mode, out_dir, fmt):
    """相手帯域 3 つを横並びにした1枚 (--layout panel)。"""
    # パネルは左から相手帯域 50 / 100 / 200 kbps の順 (タイトルは入れない)
    fig, axes = plt.subplots(1, 3, figsize=(19.0, 6.6))
    for ax, other_bw in zip(axes, BANDWIDTHS):
        _draw_panel(ax, scores, own_bw, other_bw)
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
    p.add_argument("--layout", default="single", choices=("single", "panel"),
                   help="single: 1条件1枚 (既定、18枚) / "
                        "panel: 相手帯域3つを横並びにした1枚 (6枚)")
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
            if args.layout == "single":
                for other_bw in BANDWIDTHS:
                    written.append(plot_single(scores, own_bw, other_bw, mode,
                                               args.out_dir, args.format))
            else:
                written.append(plot_one(scores, own_bw, mode, args.out_dir, args.format))

    print(f"\n--- {args.out_dir} に {len(written)} ファイル出力 ---")
    for path in written:
        print(f"    {os.path.basename(path)}")


if __name__ == "__main__":
    main()
