#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干渉検知性能を「相手PAN負荷 100%」の断面で折れ線にする。

ヒートマップ (plots/heatmaps{,_conv}/) は自PAN負荷 x 相手PAN負荷の 5x5 格子で、
1枚25セル x 12枚ある。一番見たい「相手が最大負荷のとき、自分の負荷を上げると
検知性能がどう落ちるか」を読むには各枚から1行ずつ抜き出して並べ直す必要がある。
さらに create_heatmap.py は軸を pan1/pan2 に固定しているので (create_heatmap.py:88-89)、
PAN2 の図では自分と相手が入れ替わったままラベルも無い。

ここでは相手負荷 = 100% の1行だけを切り出し、自分 / 相手を明示的に読み替えて
折れ線にする。設計と図の読み方は docs/detection_line_plots.md を参照。

  横軸: 自PAN負荷 20-100%
  縦軸: F1 (--metric で CSV の他の列にも切り替え可。将来 auc 列が入ったら --metric auc)
  色  : 相手の帯域 (50 / 100 / 200 kbps)
  線種: 測定モード (conv = 実線 / td = 点線)
"""

import os
import sys
import csv
import argparse
import datetime
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# 負荷グリッド・帯域・CSV パスは生成側/解析側から import する。
# create_heatmap.py:14-18 と analyze_csv.py:45-50 に「定数をハードコードせず
# 生成側から取れ」という規則があり、破ったときの不具合が記録されている。
import analyze_csv as A  # noqa: E402
from interference_2pan_config import OFFERED_LOAD_PERCENTS  # noqa: E402

PLOT_BASE_DIR = A.PLOT_BASE_DIR
DEFAULT_OUT_DIR = os.path.join(PLOT_BASE_DIR, "detection_lines")

# 相手PAN の負荷をこの値に固定した断面を描く
OTHER_LOAD_PERCENT = 100

# 自分 / 相手として取り得る帯域 (kbps)。CHANNEL_KBPS の値域と一致させる。
BANDWIDTHS = sorted(set(A.CHANNEL_KBPS.values()))   # [50, 100, 200]

# --- 配色 -------------------------------------------------------------
# dataviz のカテゴリカル枠スロット 1-3。この3スロットは全ペア (all-pairs) で
# light/dark 両モードのゲートを通ることが配色定義側に明記されている
# (最悪ペアで CVD dE 9.2 light / 9.4 dark、通常視 dE 24.0 light / 20.9 dark)。
# plot_cv_distribution.py:36-40 がスロット 1/2 を同じ出典で使っており、その延長。
#
# ただしスロット3の aqua は light 面でコントラスト 3:1 を下回るため relief rule
# (見えるラベルか表を添える) が要る。線3本の図では右端に直接ラベルを置き、
# 6本の図では必ず <metric>_plotted_values.csv を出すことで対応している。
COLOR = {50: "#2a78d6", 100: "#eb6834", 200: "#1baf7a"}
# 色に頼らず識別できるようにするための冗長符号化
MARKER = {50: "o", 100: "s", 200: "^"}

# 測定モード -> 線種。conv が主役なので実線。
LINESTYLE = {"conv": "-", "td": ":"}
MODE_LABEL = {"conv": "conv", "td": "td"}
MODES = ("conv", "td")

# 図中のテキストは英語にする。計算機 (Linux) に日本語フォントが無いと豆腐文字に
# なるため (plot_cv_distribution.py:42-43 と同じ規則)。
XLABEL = "Own PAN offered load [%]"
METRIC_LABEL = {"f1": "F1 score", "auc": "AUC"}

# 図をまたいで比較できるように y 軸は固定する。実測レンジは
# td 0.717-0.945 / conv 0.813-1.000 (分散統計量, 10/2 時点)。
YLIM = (0.65, 1.0)

# 全 Seed を「干渉あり」と判定したときの退化した F1 (precision 0.5, recall 1.0)。
# これ以下は検知できていないのと同じ、という下限。
DEGENERATE_F1 = 2.0 / 3.0

GRID_KW = dict(color="0.85", linestyle="--", linewidth=0.8)


def input_csv_path(mode):
    """mode -> 結果 CSV。suffix の付け方は create_heatmap.py:30-36 と同じ規則。"""
    suffix = "" if mode == "td" else "_conv"
    return os.path.join(PLOT_BASE_DIR, f"interference_detection_results{suffix}.csv")


def load_series(csv_file, metric):
    """CSV を読み、{(own_bw, other_bw): {own_load: value}} を返す。

    own / other の導出根拠は docs/detection_line_plots.md §2。
    bandwidth "AvsB" は PAN1=A kbps / PAN2=B kbps と読んでよい
    (get_bandwidth_label() のソートが TARGET_BANDWIDTH_PATTERNS 上では恒等のため)。
    """
    with open(csv_file, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"{csv_file}: データ行がありません")
    if metric not in rows[0]:
        raise KeyError(
            f"{csv_file} に列 '{metric}' がありません。\n"
            f"  利用できる列: {', '.join(rows[0].keys())}\n"
            f"  auc を使いたい場合は docs/detection_line_plots.md §7 の手順で\n"
            f"  analyze_csv.py に auc 列を追加し、計算機で再解析してください。"
        )

    series = defaultdict(dict)
    for r in rows:
        a, b = (int(x) for x in r["bandwidth"].split("vs"))
        pan = r["pan"]
        # 検知を行っている側 (pan 列) が「自分」。
        # 並び順は plot_cv_distribution.py:103-104 の慣例に合わせる。
        if pan == "PAN1":
            own_bw, other_bw = a, b
            own_load, other_load = int(r["pan1_offload"]), int(r["pan2_offload"])
        else:
            own_bw, other_bw = b, a
            own_load, other_load = int(r["pan2_offload"]), int(r["pan1_offload"])

        if other_load != OTHER_LOAD_PERCENT:
            continue
        # 対称ペアは PAN1/PAN2 の両方が該当してしまう。非対称ペアは片方しか無いので、
        # 全線を 1 PAN 分 (100+100 Seed) に揃えるため PAN1 だけを採る。
        if a == b and pan != "PAN1":
            continue

        series[(own_bw, other_bw)][own_load] = float(r[metric])
    return series


def _style_axes(ax):
    ax.grid(True, **GRID_KW)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("0.4")


def _draw_panel(ax, data, own_bw, modes, metric, direct_labels):
    """1つの軸に、ある自帯域についての線を引く。

    data: {mode: {(own_bw, other_bw): {own_load: value}}}
    modes: 描くモードのタプル。1つなら単独図、2つなら比較図。
    direct_labels: 右端に相手帯域のラベルを直接置くか (線が3本のときだけ真)。
    """
    loads = sorted(OFFERED_LOAD_PERCENTS)
    for other_bw in BANDWIDTHS:
        for mode in modes:
            pts = data[mode].get((own_bw, other_bw))
            if not pts:
                continue
            xs = [l for l in loads if l in pts]
            ys = [pts[l] for l in xs]
            label = (f"{other_bw} kbps" if len(modes) == 1
                     else f"{other_bw} kbps ({MODE_LABEL[mode]})")
            ax.plot(xs, ys,
                    color=COLOR[other_bw], linestyle=LINESTYLE[mode],
                    marker=MARKER[other_bw], markersize=6, linewidth=2.0,
                    label=label)
            if direct_labels and xs:
                # relief rule 対応。凡例と重複するが、色が薄いスロットでも
                # どの線がどれか図だけで分かるようにする。
                ax.annotate(f"{other_bw}k", xy=(xs[-1], ys[-1]),
                            xytext=(5, 0), textcoords="offset points",
                            color=COLOR[other_bw], fontsize=9,
                            va="center", fontweight="bold")

    ax.axhline(DEGENERATE_F1, color="0.6", linewidth=1.0, linestyle="-",
               zorder=0)
    # 無印の水平線だと何の線か分からないので必ず注記する
    ax.annotate("all-positive F1", xy=(max(loads), DEGENERATE_F1),
                xytext=(0, 3), textcoords="offset points",
                color="0.45", fontsize=8, ha="right", va="bottom")
    ax.set_xticks(loads)
    ax.set_xlim(min(loads) - 5, max(loads) + 12)
    ax.set_ylim(*YLIM)
    ax.set_xlabel(XLABEL, fontsize=10)
    ax.set_title(f"Own PAN: {own_bw} kbps", fontsize=12)
    _style_axes(ax)


def plot_single(data, own_bw, modes, metric, out_dir, tag, fmt):
    """自帯域1つ分の図を1枚描く。"""
    direct = len(modes) == 1
    fig, ax = plt.subplots(figsize=(5.4, 4.4))
    _draw_panel(ax, data, own_bw, modes, metric, direct)
    ax.set_ylabel(METRIC_LABEL.get(metric, metric), fontsize=10)
    ax.legend(title=f"Other PAN ({OTHER_LOAD_PERCENT}% load)",
              loc="lower left", frameon=True, fontsize=9, title_fontsize=9)
    path = os.path.join(out_dir, f"{metric}_own{own_bw}_{tag}.{fmt}")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_3panel(data, modes, metric, out_dir, tag, fmt):
    """自帯域3つを横並びのサブプロットにした1枚。"""
    direct = len(modes) == 1
    fig, axes = plt.subplots(1, 3, figsize=(14.0, 4.4), sharey=True)
    for ax, own_bw in zip(axes, BANDWIDTHS):
        _draw_panel(ax, data, own_bw, modes, metric, direct)
    axes[0].set_ylabel(METRIC_LABEL.get(metric, metric), fontsize=10)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, title=f"Other PAN ({OTHER_LOAD_PERCENT}% load)",
               loc="center left", bbox_to_anchor=(1.0, 0.5),
               frameon=True, fontsize=9, title_fontsize=9)
    fig.tight_layout()
    path = os.path.join(out_dir, f"{metric}_3panel_{tag}.{fmt}")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def dump_values(data, metric, out_dir):
    """描画に使った値を CSV に出す。数値確認用と relief rule への対応を兼ねる。"""
    path = os.path.join(out_dir, f"{metric}_plotted_values.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mode", "own_bw_kbps", "other_bw_kbps",
                    "other_load_percent", "own_load_percent", metric])
        for mode in MODES:
            for own_bw in BANDWIDTHS:
                for other_bw in BANDWIDTHS:
                    pts = data[mode].get((own_bw, other_bw), {})
                    for load in sorted(pts):
                        w.writerow([mode, own_bw, other_bw,
                                    OTHER_LOAD_PERCENT, load,
                                    f"{pts[load]:.6g}"])
    return path


def main():
    p = argparse.ArgumentParser(
        description="相手PAN負荷100%の断面で検知性能を折れ線にする")
    p.add_argument("--metric", default="f1",
                   help="縦軸に使う CSV の列名 (既定: f1)。auc 列が入れば auc も可")
    p.add_argument("--td-csv", default=None, help="td の結果 CSV")
    p.add_argument("--conv-csv", default=None, help="conv の結果 CSV")
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    p.add_argument("--format", default="pdf", choices=("pdf", "png"),
                   help="出力形式 (既定: pdf)。目視確認には png")
    args = p.parse_args()

    paths = {"td": args.td_csv or input_csv_path("td"),
             "conv": args.conv_csv or input_csv_path("conv")}

    data = {}
    for mode in MODES:
        path = paths[mode]
        if not os.path.isfile(path):
            raise FileNotFoundError(f"CSV file not found: {path}")
        mtime = datetime.datetime.fromtimestamp(
            os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
        # 解析コードより CSV が古いことがあるので更新時刻を必ず出す
        print(f"--- {mode:>4}: {path} (更新 {mtime}) ---")
        data[mode] = load_series(path, args.metric)

    # 期待する系列数の確認。欠けたまま静かに描くと図が嘘になる。
    expected = len(BANDWIDTHS) ** 2
    for mode in MODES:
        got = len(data[mode])
        n_pts = {k: len(v) for k, v in data[mode].items()}
        print(f"    {mode}: 系列 {got}/{expected}, "
              f"1系列あたりの点数 {sorted(set(n_pts.values()))}")
        if got != expected:
            missing = [k for k in ((o, t) for o in BANDWIDTHS for t in BANDWIDTHS)
                       if k not in data[mode]]
            print(f"    Warning: 欠けている (own, other) = {missing}")

    os.makedirs(args.out_dir, exist_ok=True)
    fmt = args.format
    written = []
    for tag, modes in (("conv", ("conv",)), ("td", ("td",)), ("compare", MODES)):
        for own_bw in BANDWIDTHS:
            written.append(plot_single(data, own_bw, modes, args.metric,
                                       args.out_dir, tag, fmt))
        written.append(plot_3panel(data, modes, args.metric,
                                   args.out_dir, tag, fmt))
    written.append(dump_values(data, args.metric, args.out_dir))

    print(f"\n--- {args.out_dir} に {len(written)} ファイル出力 ---")
    for path in written:
        print(f"    {os.path.basename(path)}")


if __name__ == "__main__":
    main()
