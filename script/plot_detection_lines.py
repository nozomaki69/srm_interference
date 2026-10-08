#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干渉検知性能を「相手PAN負荷 100%」の断面で折れ線にする。

ヒートマップ (plots/heatmaps{,_conv}/) は自PAN負荷 x 相手PAN負荷の 5x5 格子で、
1枚25セル x 12枚ある。一番見たい「相手が最大負荷のとき、自分の負荷を上げると
検知性能がどう落ちるか」を読むには各枚から1行ずつ抜き出して並べ直す必要がある。
さらに create_heatmap.py は軸を pan1/pan2 に固定しているので (create_heatmap.py:88-89)、
PAN2 の図では自分と相手が入れ替わったままラベルも無い。

ここでは相手負荷 = 100% の1行だけを切り出し、自分 / 相手を明示的に読み替えて
折れ線にする。設計と図の読み方は docs/README.md を参照。

  横軸: 自PAN負荷 20-100%
  縦軸: --metric で切り替え。f1 (既定) / auc。軸と参照線は METRIC_SPEC で指標ごと
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
# (スロット 1/2 は以前 CV 分布図でも同じ出典で使っていた。それを3色に延長した。)
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
# なるため。コメント・argparse ヘルプ・コンソール出力は日本語のままでよい。
#
# 軸ラベルとタイトルは入れない (横軸 = 自PAN負荷 [%]、縦軸 = 指標)。
# 図のキャプションで説明する前提。

# 指標ごとの軸と参照線。y 軸を固定するのは、図をまたいで比較できることが
# この図の目的だから (自動スケールにすると枚ごとに縮尺が変わって比較できない)。
#
#   f1  : 実測レンジは td 0.717-0.945 / conv 0.813-1.000 (分散統計量, 10/2 時点)。
#         参照線 2/3 は全 Seed を「干渉あり」と判定したときの退化した F1
#         (precision 0.5, recall 1.0)。これ以下は検知できていないのと同じ。
#   auc : 参照線 0.5 はランダム判定。下限を 0.5 に置いて床を見せる。
#         実データを見てから詰めてよい。
METRIC_SPEC = {
    "f1":  {"label": "F1 score", "ylim": (0.65, 1.0),
            "ref": 2.0 / 3.0, "ref_label": "all-positive F1"},
    "auc": {"label": "AUC", "ylim": (0.50, 1.0),
            "ref": 0.5, "ref_label": "chance"},
}

# 未知の指標でも落とさず描く。縮尺の根拠も参照線の意味も決められないので、
# 自動スケールにして参照線は引かない。
DEFAULT_SPEC = {"label": None, "ylim": None, "ref": None, "ref_label": None}


def metric_spec(metric):
    spec = dict(DEFAULT_SPEC, **METRIC_SPEC.get(metric, {}))
    if spec["label"] is None:
        spec["label"] = metric
    return spec


GRID_KW = dict(color="0.85", linestyle="--", linewidth=0.8)

# --- 論文向けの体裁 -----------------------------------------------------
# タイトルと軸ラベルは入れない (図のキャプションで説明する前提)。そのぶん
# 目盛りの数字・目盛り線・凡例を大きくして、縮小しても読めるようにする。
# plot_roc.py もここから import して同じ体裁にする。
TICK_LABELSIZE = 20     # 目盛りの数字
TICK_LENGTH = 10        # 目盛り線の長さ
TICK_WIDTH = 2.0        # 目盛り線の太さ
LEGEND_FONTSIZE = 18
ANNOT_FONTSIZE = 15     # 参照線の注記、線の直接ラベル


def style_axes(ax):
    """グリッド・枠線・目盛りをまとめて整える。"""
    ax.grid(True, **GRID_KW)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("0.4")
        ax.spines[side].set_linewidth(TICK_WIDTH)
    ax.tick_params(axis="both", which="major", labelsize=TICK_LABELSIZE,
                   length=TICK_LENGTH, width=TICK_WIDTH)


def input_csv_path(mode):
    """mode -> 結果 CSV。suffix の付け方は create_heatmap.py:30-36 と同じ規則。"""
    suffix = "" if mode == "td" else "_conv"
    return os.path.join(PLOT_BASE_DIR, f"interference_detection_results{suffix}.csv")


def own_other(row):
    """結果CSVの1行を「自分 / 相手」に読み替える。plot_roc.py と共有する。

    検知を行っている側 (pan 列) が「自分」。bandwidth "AvsB" は PAN1=A kbps /
    PAN2=B kbps と読んでよい ――ラベルを作る get_bandwidth_label() はソートする
    が、TARGET_BANDWIDTH_PATTERNS が常に kbps(PAN1) <= kbps(PAN2) を満たすので
    そのソートは恒等写像になる。導出根拠は docs/README.md の「折れ線グラフ」節。

    この断面に入らない行 (相手負荷が OTHER_LOAD_PERCENT でない、対称ペアの
    PAN2 側) は None を返す。対称ペアで PAN1 だけを採るのは、非対称ペアは
    片方の PAN しか該当しないので、全系列を 1 PAN 分 (100+100 Seed) に揃えて
    ノイズ水準を均一にするため。

    規則を2箇所に書くと片方だけ直して静かにずれるので、ここを唯一の定義元にする。
    """
    a, b = (int(x) for x in row["bandwidth"].split("vs"))
    pan = row["pan"]
    if pan == "PAN1":
        own_bw, other_bw = a, b
        own_load, other_load = int(row["pan1_offload"]), int(row["pan2_offload"])
    else:
        own_bw, other_bw = b, a
        own_load, other_load = int(row["pan2_offload"]), int(row["pan1_offload"])

    if other_load != OTHER_LOAD_PERCENT:
        return None
    if a == b and pan != "PAN1":
        return None
    return {"own_bw": own_bw, "other_bw": other_bw, "own_load": own_load}


def load_series(csv_file, metric):
    """CSV を読み、{(own_bw, other_bw): {own_load: value}} を返す。

    自分 / 相手の読み替えと断面の絞り込みは own_other() が担当する。
    """
    with open(csv_file, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"{csv_file}: データ行がありません")
    if metric not in rows[0]:
        raise KeyError(
            f"{csv_file} に列 '{metric}' がありません。\n"
            f"  利用できる列: {', '.join(rows[0].keys())}\n"
            f"  auc が無い場合は CSV が古いので、./script/sbatch_reanalyze.sh で\n"
            f"  解析をやり直してください。"
        )

    series = defaultdict(dict)
    for r in rows:
        own = own_other(r)
        if own is None:
            continue
        series[(own["own_bw"], own["other_bw"])][own["own_load"]] = float(r[metric])
    return series


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
                            xytext=(6, 0), textcoords="offset points",
                            color=COLOR[other_bw], fontsize=ANNOT_FONTSIZE,
                            va="center", fontweight="bold")

    spec = metric_spec(metric)
    if spec["ref"] is not None:
        ax.axhline(spec["ref"], color="0.6", linewidth=1.0, linestyle="-",
                   zorder=0)
        # 無印の水平線だと何の線か分からないので必ず注記する
        ax.annotate(spec["ref_label"], xy=(max(loads), spec["ref"]),
                    xytext=(0, 4), textcoords="offset points",
                    color="0.45", fontsize=ANNOT_FONTSIZE, ha="right", va="bottom")
    ax.set_xticks(loads)
    ax.set_xlim(min(loads) - 5, max(loads) + 12)
    if spec["ylim"] is not None:
        ax.set_ylim(*spec["ylim"])
    style_axes(ax)


def plot_single(data, own_bw, modes, metric, out_dir, tag, fmt):
    """自帯域1つ分の図を1枚描く。"""
    direct = len(modes) == 1
    fig, ax = plt.subplots(figsize=(7.2, 5.8))
    _draw_panel(ax, data, own_bw, modes, metric, direct)
    ax.legend(loc="lower left", frameon=True, fontsize=LEGEND_FONTSIZE)
    path = os.path.join(out_dir, f"{metric}_own{own_bw}_{tag}.{fmt}")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_3panel(data, modes, metric, out_dir, tag, fmt):
    """自帯域3つを横並びのサブプロットにした1枚。"""
    direct = len(modes) == 1
    fig, axes = plt.subplots(1, 3, figsize=(19.0, 5.8), sharey=True)
    for ax, own_bw in zip(axes, BANDWIDTHS):
        _draw_panel(ax, data, own_bw, modes, metric, direct)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="center left", bbox_to_anchor=(1.0, 0.5),
               frameon=True, fontsize=LEGEND_FONTSIZE)
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
