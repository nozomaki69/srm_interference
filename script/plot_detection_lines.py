#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干渉判定3手法の AUC を「相手PAN負荷 100% / 200%」の断面で折れ線にする。

このブランチ (icc) の図はこれ1種類だけ。提案手法 (RSSIビン内ΔPER分散) が
2つのベースライン (ΔPERのみ / RSSIのみ) に対してどれだけ分離できているかを、
閾値の選び方に依らない AUC で比べる。手法の定義は analyze_csv.py の
DETECTION_METHODS / METHOD_LABEL が唯一の定義元。

断面を相手負荷で固定するのは、一番見たいのが「相手が重いとき、自分の負荷を
上げると検知性能がどう落ちるか」だから。icc_load200 ブランチは負荷を 200% まで
広げたので、icc と同じ 100% の断面と、新しい最大負荷 200% の断面の2つを出す
(docs/load200.md)。設計と図の読み方は docs/README.md を参照。

  横軸: 自PAN負荷 20-200%
  縦軸: AUC (下限 0.5 がランダム判定の水準)
  色  : 相手の帯域 (50 / 100 / 200 kbps)
  線種: 判定手法 (proposed 実線 / dper 破線 / rssi 点線)

測定モードは simultaneous (メトリックの同時測定) 固定。理由は analyze_csv.py の
「測定モード」節を参照 ―― 測定モードと手法を同時に振ると線種が2つの軸に
取られて図が読めなくなる。
"""

import os
import sys
import csv
import math
import argparse
import datetime
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# 負荷グリッド・帯域・手法・CSV パスは生成側/解析側から import する。
# 定数をハードコードすると、生成側を変えたときに片方だけ取り残されて静かに壊れる。
import analyze_csv as A  # noqa: E402
from interference_2pan_config import OFFERED_LOAD_PERCENTS  # noqa: E402

PLOT_BASE_DIR = A.PLOT_BASE_DIR
# icc の 20-100% の結果 (detection_lines/) と混ざらないよう別の場所に出す。
# 断面ごとに other100/ other200/ のサブディレクトリを切る。
DEFAULT_OUT_DIR = os.path.join(PLOT_BASE_DIR, "detection_lines_more")

# 縦軸に使う列。このブランチは AUC だけを見る (F1 は出さない)。
METRIC = "auc"

# 相手PAN の負荷をこれらの値に固定した断面を、それぞれ描く。
# 100 は icc と同じ断面 (横軸を 200% まで伸ばしたものとして直接比べられる)、
# 200 は新しい最大負荷。
OTHER_LOAD_PERCENTS = (100, 200)

# 自分 / 相手として取り得る帯域 (kbps)。CHANNEL_KBPS の値域と一致させる。
BANDWIDTHS = sorted(set(A.CHANNEL_KBPS.values()))   # [50, 100, 200]

# 判定手法。並び順も表示名も analyze_csv.py が定義元。
METHODS = A.DETECTION_METHODS                       # ("proposed", "dper", "rssi")
METHOD_LABEL = A.METHOD_LABEL

# --- 配色 -------------------------------------------------------------
# dataviz のカテゴリカル枠スロット 1-3。この3スロットは全ペア (all-pairs) で
# light/dark 両モードのゲートを通ることが配色定義側に明記されている
# (最悪ペアで CVD dE 9.2 light / 9.4 dark、通常視 dE 24.0 light / 20.9 dark)。
#
# ただしスロット3の aqua は light 面でコントラスト 3:1 を下回るため relief rule
# (見えるラベルか表を添える) が要る。描画値を必ず auc_plotted_values.csv に
# 出すことで対応している。
COLOR = {50: "#2a78d6", 100: "#eb6834", 200: "#1baf7a"}
# 色に頼らず識別できるようにするための冗長符号化
MARKER = {50: "o", 100: "s", 200: "^"}

# 手法 -> 線種。提案手法を実線にして、ベースラインを破線・点線で下に敷く。
# 以前はこの軸が測定モード (simultaneous 実線 / sequential 点線) だった。
LINESTYLE = {"proposed": "-", "dper": "--", "rssi": ":"}

# 図中のテキストは英語にする。計算機 (Linux) に日本語フォントが無いと豆腐文字に
# なるため。コメント・argparse ヘルプ・コンソール出力は日本語のままでよい。
#
# 軸ラベルとタイトルは入れない (横軸 = 自PAN負荷 [%]、縦軸 = AUC)。
# 図のキャプションで説明する前提。

GRID_KW = dict(color="0.85", linestyle="--", linewidth=0.8)

# --- 論文向けの体裁 -----------------------------------------------------
# タイトルと軸ラベルは入れない (図のキャプションで説明する前提)。そのぶん
# 目盛りの数字・目盛り線・凡例を大きくして、縮小しても読めるようにする。
TICK_LABELSIZE = 20     # 目盛りの数字
TICK_LENGTH = 10        # 目盛り線の長さ
TICK_WIDTH = 2.0        # 目盛り線の太さ
LEGEND_FONTSIZE = 18


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


def input_csv_path():
    """検知結果 CSV。測定モードは simultaneous 固定なので接尾辞も固定。"""
    return os.path.join(
        PLOT_BASE_DIR, f"interference_detection_results{A.COLUMN_SUFFIX}.csv")


def own_other(row, other_load_percent):
    """結果CSVの1行を、断面 other_load_percent における「自分 / 相手」に読み替える。

    検知を行っている側 (pan 列) が「自分」。bandwidth "AvsB" は PAN1=A kbps /
    PAN2=B kbps と読んでよい ――ラベルを作る get_bandwidth_label() はソートする
    が、TARGET_BANDWIDTH_PATTERNS が常に kbps(PAN1) <= kbps(PAN2) を満たすので
    そのソートは恒等写像になる。導出根拠は docs/README.md の「折れ線グラフ」節。

    この断面に入らない行 (相手負荷が other_load_percent でない、対称ペアの
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

    if other_load != other_load_percent:
        return None
    if a == b and pan != "PAN1":
        return None
    return {"own_bw": own_bw, "other_bw": other_bw, "own_load": own_load}


def load_series(csv_file):
    """CSV を読み、断面ごとに
    {other_load: {method: {(own_bw, other_bw): {own_load: auc}}}} を返す。

    自分 / 相手の読み替えと断面の絞り込みは own_other() が担当する。
    """
    with open(csv_file, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"{csv_file}: データ行がありません")
    for col in ("method", METRIC):
        if col not in rows[0]:
            raise KeyError(
                f"{csv_file} に列 '{col}' がありません。\n"
                f"  利用できる列: {', '.join(rows[0].keys())}\n"
                f"  CSV が古いので、./script/sbatch_reanalyze.sh で\n"
                f"  解析をやり直してください。"
            )

    series = {ol: {m: defaultdict(dict) for m in METHODS}
              for ol in OTHER_LOAD_PERCENTS}
    unknown = set()
    for r in rows:
        method = r["method"]
        if method not in METHODS:
            unknown.add(method)
            continue
        for other_load in OTHER_LOAD_PERCENTS:
            own = own_other(r, other_load)
            if own is None:
                continue
            series[other_load][method][(own["own_bw"], own["other_bw"])][
                own["own_load"]] = float(r[METRIC])

    if unknown:
        # 黙って捨てると「描いたつもりの手法が図に無い」事故になる
        print(f"    Warning: 未知の手法を無視しました: {sorted(unknown)}")
    return series


def choose_ylim(sections):
    """全図で共通に使う y 軸の範囲を決める。

    sections: {other_load: data}。2つの断面をまたいで1つだけ決める
    (断面ごとに変えると、100% と 200% の図を並べたときに比較が崩れる)。

    save ブランチは AUC を (0.50, 1.0) に固定していた。0.5 がランダム判定の
    水準で、軸の下端がそのまま床を示すからである。だが**ベースラインは 0.5 を
    下回り得る** (指標が干渉の有無と逆相関する条件が実在する。docs/auc.md 参照)。
    下回った点が枠外に消えると図が嘘になるので、必要なときだけ下げる。

    枚ごとに変えてはいけない。図をまたいで比較できることがこの図の目的なので、
    全描画値の最小値から1つだけ決めて全図に同じ値を当てる。
    """
    values = [v
              for data in sections.values()
              for per_method in data.values()
              for pts in per_method.values()
              for v in pts.values()]
    if not values:
        return (0.50, 1.0)
    lo = min(values)
    if lo >= 0.5:
        return (0.50, 1.0)
    # 0.1 刻みで切り下げる。目盛りが半端な位置に来ないようにするため。
    return (math.floor(lo * 10.0) / 10.0, 1.0)


def _draw_panel(ax, data, own_bw, methods, ylim):
    """1つの軸に、ある自帯域についての線を引く。

    data: {method: {(own_bw, other_bw): {own_load: auc}}}
    methods: 描く手法のタプル。1つなら単独図、3つなら比較図。
    """
    loads = sorted(OFFERED_LOAD_PERCENTS)
    # 手法を外側で回すので、凡例は「実線 50/100/200 -> 破線 50/100/200 -> ...」の
    # 順に並ぶ。帯域を外側にすると 50実線/50破線/50点線/100実線/... と交互になって
    # 読みにくい。
    for method in methods:
        for other_bw in BANDWIDTHS:
            pts = data[method].get((own_bw, other_bw))
            if not pts:
                continue
            xs = [l for l in loads if l in pts]
            ys = [pts[l] for l in xs]
            ax.plot(xs, ys,
                    color=COLOR[other_bw], linestyle=LINESTYLE[method],
                    marker=MARKER[other_bw], markersize=6, linewidth=2.0,
                    label=f"{other_bw} kbps")

    ax.set_xticks(loads)
    ax.set_xlim(min(loads) - 5, max(loads) + 12)
    ax.set_ylim(*ylim)
    style_axes(ax)


def legend_handles(methods):
    """凡例の手。色 (帯域) と線種 (手法) を分けて並べる。

    3手法 x 3帯域を総当たりで出すと 9 項目になり、どれが色の違いでどれが線種の
    違いなのかが読み取れない。符号化の軸ごとに1ブロックずつ出せば 3+3 で済む。
    手法が1つだけの図では線種の軸が無いので、帯域のブロックだけを出す。
    """
    handles = [Line2D([], [], color=COLOR[bw], marker=MARKER[bw],
                      linestyle="-" if len(methods) == 1 else LINESTYLE[methods[0]],
                      markersize=6, linewidth=2.0, label=f"{bw} kbps")
               for bw in BANDWIDTHS]
    if len(methods) == 1:
        return handles
    # 線種の凡例は色を持たせない (色は帯域の軸なので、混ぜると意味が二重になる)
    handles += [Line2D([], [], color="0.35", linestyle=LINESTYLE[m],
                       linewidth=2.0, label=METHOD_LABEL[m])
                for m in methods]
    return handles


def plot_single(data, own_bw, methods, out_dir, tag, fmt, ylim):
    """自帯域1つ分の図を1枚描く。"""
    # 横軸の目盛りが 10 個 (20-200%) あるので icc (7.2) より横に広げる
    fig, ax = plt.subplots(figsize=(10.0, 5.8))
    _draw_panel(ax, data, own_bw, methods, ylim)
    handles = legend_handles(methods)
    ax.legend(handles=handles, loc="lower left", frameon=True,
              fontsize=LEGEND_FONTSIZE)
    path = os.path.join(out_dir, f"{METRIC}_own{own_bw}_{tag}.{fmt}")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_3panel(data, methods, out_dir, tag, fmt, ylim):
    """自帯域3つを横並びのサブプロットにした1枚。"""
    fig, axes = plt.subplots(1, 3, figsize=(27.0, 5.8), sharey=True)
    for ax, own_bw in zip(axes, BANDWIDTHS):
        _draw_panel(ax, data, own_bw, methods, ylim)
    handles = legend_handles(methods)
    fig.legend(handles=handles, loc="center left", bbox_to_anchor=(1.0, 0.5),
               frameon=True, fontsize=LEGEND_FONTSIZE)
    fig.tight_layout()
    path = os.path.join(out_dir, f"{METRIC}_3panel_{tag}.{fmt}")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def dump_values(sections, out_dir):
    """描画に使った値を CSV に出す。数値確認用と relief rule への対応を兼ねる。

    両断面を1本にまとめ、other_load_percent 列で区別する。
    """
    path = os.path.join(out_dir, f"{METRIC}_plotted_values.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["method", "own_bw_kbps", "other_bw_kbps",
                    "other_load_percent", "own_load_percent", METRIC])
        for other_load, data in sections.items():
            for method in METHODS:
                for own_bw in BANDWIDTHS:
                    for other_bw in BANDWIDTHS:
                        pts = data[method].get((own_bw, other_bw), {})
                        for load in sorted(pts):
                            w.writerow([method, own_bw, other_bw,
                                        other_load, load,
                                        f"{pts[load]:.6g}"])
    return path


def main():
    p = argparse.ArgumentParser(
        description="相手PAN負荷100%/200%の断面で、干渉判定3手法の AUC を折れ線にする")
    p.add_argument("--csv", default=None,
                   help=f"検知結果 CSV (既定: {input_csv_path()})")
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    p.add_argument("--format", default="pdf", choices=("pdf", "png"),
                   help="出力形式 (既定: pdf)。目視確認には png")
    args = p.parse_args()

    path = args.csv or input_csv_path()
    if not os.path.isfile(path):
        raise FileNotFoundError(f"CSV file not found: {path}")
    mtime = datetime.datetime.fromtimestamp(
        os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
    # 解析コードより CSV が古いことがあるので更新時刻を必ず出す
    print(f"--- {path} (更新 {mtime}) ---")
    sections = load_series(path)

    # 期待する系列数と点数の確認。欠けたまま静かに描くと図が嘘になる。
    expected = len(BANDWIDTHS) ** 2
    n_loads = len(OFFERED_LOAD_PERCENTS)
    for other_load, data in sections.items():
        print(f"  相手負荷 {other_load}%:")
        for method in METHODS:
            got = len(data[method])
            n_pts = {k: len(v) for k, v in data[method].items()}
            print(f"    {method:>8}: 系列 {got}/{expected}, "
                  f"1系列あたりの点数 {sorted(set(n_pts.values()))} (期待 {n_loads})")
            if got != expected:
                missing = [k for k in ((o, t) for o in BANDWIDTHS for t in BANDWIDTHS)
                           if k not in data[method]]
                print(f"    Warning: 欠けている (own, other) = {missing}")

    ylim = choose_ylim(sections)
    print(f"--- y軸: {ylim[0]:.2f} - {ylim[1]:.2f} "
          f"(全図共通。0.5 を下回る値があるときだけ下げる) ---")

    os.makedirs(args.out_dir, exist_ok=True)
    fmt = args.format
    written = []
    # 断面ごとに、手法ごとの単独図と3手法を重ねた比較図
    tags = [(m, (m,)) for m in METHODS] + [("compare", tuple(METHODS))]
    for other_load, data in sections.items():
        sub_dir = os.path.join(args.out_dir, f"other{other_load}")
        os.makedirs(sub_dir, exist_ok=True)
        for tag, methods in tags:
            for own_bw in BANDWIDTHS:
                written.append(plot_single(data, own_bw, methods,
                                           sub_dir, tag, fmt, ylim))
            written.append(plot_3panel(data, methods, sub_dir, tag, fmt, ylim))
    written.append(dump_values(sections, args.out_dir))

    print(f"\n--- {args.out_dir} に {len(written)} ファイル出力 ---")
    for path in written:
        print(f"    {os.path.relpath(path, args.out_dir)}")


if __name__ == "__main__":
    main()
