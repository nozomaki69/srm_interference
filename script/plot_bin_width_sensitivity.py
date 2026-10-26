#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ビン幅の感度分析 (bin_width_sensitivity.py の出力) を図にする。

  1. 3x3 グリッド (行 = 自帯域、列 = 相手帯域)。相手負荷ごと x モードごとに1枚
       横軸: ビン幅 [dBm]、縦軸: 提案手法の AUC、線: 自PAN負荷 5本 (淡い髭 = 95% 区間)
       既存の解析で使っている 10 dBm に縦の破線
  2. 要約図。モードごとに1枚 (上段 = 45 条件の平均 AUC、下段 = 最小 AUC、列 = 相手負荷)
       提案手法をビン幅の関数として描き、ビン幅に依らない ΔPER only / RSSI only の
       同じ集計値を水平線で重ねる

断面の取り方 (自/相手の読み替え、対称ペアは PAN1 側) と体裁は plot_detection_lines.py を
import して共有する。図中のテキストは英語 (計算機に日本語フォントが無いため)。
設計は docs/bin_width_sensitivity.md を参照。
"""

import os
import sys
import csv
import math
import argparse
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import analyze_csv as A  # noqa: E402
import plot_detection_lines as PL  # noqa: E402
import bin_width_sensitivity as S  # noqa: E402

MODES = A.MEASUREMENT_MODES
BANDWIDTHS = PL.BANDWIDTHS
LOADS = sorted(PL.OFFERED_LOAD_PERCENTS)
OTHER_LOADS = PL.OTHER_LOADS

# 自PAN負荷 (順序のある量) の色。明るさが単調に変わる系列 (viridis の5点、黄色の端は避ける)
OWN_LOAD_COLOR = dict(zip(LOADS, ["#440154", "#3b528b", "#21918c", "#5ec962", "#a8b51c"]))
OWN_LOAD_MARKER = dict(zip(LOADS, ["o", "s", "^", "D", "v"]))
BAND_ALPHA = 0.12
REF_LINESTYLE = {"dper": (0, (8, 4)), "rssi": (0, (0.1, 3.0))}


def load_sweep(mode):
    """{other_load: {(own_bw, other_bw): {own_load: {width: (auc, lo, hi)}}}}。"""
    out = {L: defaultdict(lambda: defaultdict(dict)) for L in OTHER_LOADS}
    with open(S.auc_path(mode), encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            for L in OTHER_LOADS:
                own = PL.own_other(r, L)
                if own is None:
                    continue
                out[L][(own["own_bw"], own["other_bw"])][own["own_load"]][
                    int(r["bin_width_dbm"])] = (float(r["auc"]), float(r["auc_ci_low"]),
                                                float(r["auc_ci_high"]))
    return out


def choose_ylim(sweeps):
    """全図共通の y 範囲。PL.choose_ylim() と同じ方針 (0.5 を下回るときだけ 0.1 刻みで下げる)。"""
    lo = min(v[1] for sw in sweeps for per_load in sw.values() for pair in per_load.values()
             for by_w in pair.values() for v in by_w.values())
    return (0.5, 1.0) if lo >= 0.5 else (math.floor(lo * 10) / 10, 1.0)


def _finish(ax, widths, ylim):
    ax.axvline(S.REFERENCE_WIDTH, color="0.45", linestyle="--", linewidth=1.2, zorder=1)
    ax.set_xlim(min(widths) - 0.8, max(widths) + 0.8)
    ax.set_xticks([w for w in (1, 5, 10, 15, 20) if min(widths) <= w <= max(widths)])
    lo, hi = ylim
    ax.set_ylim(lo, hi + PL.YTOP_PAD)
    ax.set_yticks([round(lo + 0.1 * k, 1) for k in range(int(round((hi - lo) / 0.1)) + 1)])
    PL.style_axes(ax, grid_axis="y")


def plot_grid(sweep, widths, ylim, path):
    n = len(BANDWIDTHS)
    fig, axes = plt.subplots(n, n, figsize=(15.0, 13.0), sharex=True, sharey=True)
    for i, own_bw in enumerate(BANDWIDTHS):
        for j, other_bw in enumerate(BANDWIDTHS):
            ax = axes[i][j]
            pair = sweep.get((own_bw, other_bw), {})
            for L in LOADS:
                by_w = pair.get(L, {})
                ws = [w for w in widths if w in by_w]
                if not ws:
                    continue
                c = OWN_LOAD_COLOR[L]
                ax.fill_between(ws, [by_w[w][1] for w in ws], [by_w[w][2] for w in ws],
                                color=c, alpha=BAND_ALPHA, linewidth=0, zorder=1)
                ax.plot(ws, [by_w[w][0] for w in ws], color=c, linewidth=1.8,
                        marker=OWN_LOAD_MARKER[L], markersize=4.5,
                        markerfacecolor=PL.MARKER_FACE, markeredgecolor=c, zorder=3)
            _finish(ax, widths, ylim)
            ax.tick_params(labelleft=(j == 0), labelbottom=(i == n - 1))
    fig.tight_layout()
    handles = [Line2D([], [], color=OWN_LOAD_COLOR[L], linewidth=1.8,
                      marker=OWN_LOAD_MARKER[L], markersize=8,
                      markerfacecolor=PL.MARKER_FACE, label=f"{L}%") for L in LOADS]
    PL.thicken_legend_lines(fig.legend(handles=handles, ncol=len(handles), loc="lower center",
                                       bbox_to_anchor=(0.5, 0.99), frameon=True,
                                       fontsize=PL.LEGEND_FONTSIZE))
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def summarize(sweep, widths):
    """{"mean"/"min": {width: value}} (9ペア x 自負荷5 = 45 点の平均と最小)。"""
    out = {"mean": {}, "min": {}}
    for w in widths:
        vals = [sweep[p][L][w][0] for p in sweep for L in LOADS if w in sweep[p].get(L, {})]
        if vals:
            out["mean"][w] = sum(vals) / len(vals)
            out["min"][w] = min(vals)
    return out


def summarize_reference(mode, other_load):
    """ΔPER only / RSSI only の同じ集計 (ビン幅に依らない): {method: {"mean"/"min": v}}。"""
    data = PL.load_series(PL.input_csv_path(mode), other_load)
    out = {}
    for m in ("dper", "rssi"):
        vals = [v for pts in data[m].values() for v in pts.values()]
        out[m] = {"mean": sum(vals) / len(vals), "min": min(vals)}
    return out


def plot_summary(mode, sweeps_by_load, widths, path, value_rows):
    stats_ = ("mean", "min")
    tag = S.FILE_MODE_TAG[mode]
    fig, axes = plt.subplots(len(stats_), len(OTHER_LOADS), figsize=(22.0, 9.0),
                             sharex=True, sharey="row")
    summ = {L: summarize(sweeps_by_load[L], widths) for L in OTHER_LOADS}
    ref = {L: summarize_reference(mode, L) for L in OTHER_LOADS}
    # sharey="row" なので y 範囲は行 (統計量) ごとに1つ。パネルごとに決めると
    # 最後に描いたパネルの範囲で上書きされ、他のパネルの線が枠外に切れる
    ylims = {}
    for st in stats_:
        lo = min([v for L in OTHER_LOADS for v in summ[L][st].values()]
                 + [ref[L][m][st] for L in OTHER_LOADS for m in ref[L]])
        ylims[st] = (0.5, 1.0) if lo >= 0.5 else (math.floor(lo * 10) / 10, 1.0)
    for j, L in enumerate(OTHER_LOADS):
        for i, st in enumerate(stats_):
            ax = axes[i][j]
            ws = sorted(summ[L][st])
            ax.plot(ws, [summ[L][st][w] for w in ws], color=PL.METHOD_COLOR["proposed"],
                    linewidth=2.0, marker="o", markersize=5,
                    markerfacecolor=PL.MARKER_FACE, zorder=3)
            for m in ("dper", "rssi"):
                ax.axhline(ref[L][m][st], color=PL.METHOD_COLOR[m],
                           linestyle=REF_LINESTYLE[m], linewidth=2.0,
                           dash_capstyle=PL.DASH_CAPSTYLE, zorder=2)
            _finish(ax, widths, ylims[st])
            ax.tick_params(labelsize=16)
            # この要約図は列 = 相手負荷、行 = 統計量を見出しで示す (グリッド図と違い
            # 位置だけでは読めないため)
            if i == 0:
                ax.set_title(f"other-PAN load {L}%", fontsize=18)
            if j == 0:
                ax.set_ylabel(f"{st} AUC", fontsize=18)
            for w in ws:
                value_rows.append([tag, "summary", st, L, "", "", "", w,
                                   f"{summ[L][st][w]:.6g}", "", ""])
            for m in ref[L]:
                value_rows.append([tag, "summary_reference", st, L, "", "", m, "",
                                   f"{ref[L][m][st]:.6g}", "", ""])
    fig.tight_layout()
    handles = [Line2D([], [], color=PL.METHOD_COLOR["proposed"], linewidth=2.0, marker="o",
                      markerfacecolor=PL.MARKER_FACE, label="Proposed")]
    handles += [Line2D([], [], color=PL.METHOD_COLOR[m], linestyle=REF_LINESTYLE[m],
                       linewidth=2.0, dash_capstyle=PL.DASH_CAPSTYLE,
                       label=PL.METHOD_LABEL[m]) for m in ("dper", "rssi")]
    PL.thicken_legend_lines(fig.legend(handles=handles, ncol=3, loc="lower center",
                                       bbox_to_anchor=(0.5, 0.99), frameon=True,
                                       fontsize=PL.LEGEND_FONTSIZE))
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def main():
    p = argparse.ArgumentParser(description="ビン幅の感度分析の図")
    p.add_argument("--format", default="pdf", choices=("pdf", "png"))
    p.add_argument("--out-dir", default=S.OUT_DIR)
    args = p.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    modes = [m for m in MODES if os.path.isfile(S.auc_path(m))]
    if not modes:
        raise SystemExit(f"エラー: {S.OUT_DIR} に auc_binwidth_*.csv がありません。"
                         "先に bin_width_sensitivity.py を実行してください。")
    sweeps = {m: load_sweep(m) for m in modes}
    widths = sorted({w for sw in sweeps.values() for per_load in sw.values()
                     for pair in per_load.values() for by_w in pair.values() for w in by_w})
    ylim = choose_ylim(list(sweeps.values()))
    print(f"--- モード {modes}, ビン幅 {widths[0]}-{widths[-1]} dBm, y軸 {ylim} ---")

    written, value_rows = [], []
    for m in modes:
        tag = S.FILE_MODE_TAG[m]
        for L in OTHER_LOADS:
            written.append(plot_grid(
                sweeps[m][L], widths, ylim,
                os.path.join(args.out_dir, f"auc_{tag}_proposed_binwidth_grid_"
                                           f"{PL.otherload_token(L)}.{args.format}")))
            for (own_bw, other_bw), pair in sorted(sweeps[m][L].items()):
                for own_load in sorted(pair):
                    for w, (auc, lo, hi) in sorted(pair[own_load].items()):
                        value_rows.append([tag, "grid", "", L, own_bw, other_bw, own_load, w,
                                           f"{auc:.6g}", f"{lo:.6g}", f"{hi:.6g}"])
        written.append(plot_summary(
            m, sweeps[m], widths,
            os.path.join(args.out_dir, f"auc_{tag}_binwidth_summary.{args.format}"),
            value_rows))

    csv_path = os.path.join(args.out_dir, "auc_binwidth_plotted_values.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        # grid 行: own_bw, other_bw, own_load_or_method=自負荷。summary_reference 行: 手法名
        w.writerow(["mode", "figure", "stat", "other_load_percent", "own_bw_kbps",
                    "other_bw_kbps", "own_load_percent_or_method", "bin_width_dbm",
                    "auc", "auc_ci_low", "auc_ci_high"])
        w.writerows(value_rows)
    written.append(csv_path)
    print(f"--- {args.out_dir} に {len(written)} ファイル出力 ---")
    for path in written:
        print(f"    {os.path.basename(path)}")


if __name__ == "__main__":
    main()
