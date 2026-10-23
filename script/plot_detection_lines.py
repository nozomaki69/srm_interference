#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干渉判定3手法の AUC を「相手PAN負荷 100%」の断面で折れ線にする。

このブランチ (icc) の図はこれ1種類だけ。提案手法 (RSSIビン内ΔPER分散) が
2つのベースライン (ΔPERのみ / RSSIのみ) に対してどれだけ分離できているかを、
閾値の選び方に依らない AUC で比べる。手法の定義は analyze_csv.py の
DETECTION_METHODS / METHOD_LABEL が唯一の定義元。

断面を相手負荷 100% に固定するのは、一番見たいのが「相手が最大負荷のとき、
自分の負荷を上げると検知性能がどう落ちるか」だから。設計と図の読み方は
docs/README.md を参照。

  横軸: 自PAN負荷 20-100%
  縦軸: AUC (下限 0.5 がランダム判定の水準)
  色  : 相手の帯域 (50 / 100 / 200 kbps)
  線種: 判定手法 (proposed 実線 / dper 長い破線 / rssi 丸い点の列)
  点  : 白抜き。3手法の図の凡例は 3x3 の行列 (行 = 手法、列 = 相手帯域)

測定モードは --mode で選ぶ (既定 simultaneous = single-query)。測定モードと手法を
1枚に同時に振ると線種が2つの軸に取られて図が読めなくなるので、3手法の図は
モードごとに出力先を分ける。モードどうしの比較は --mode compare で、手法ごとに
3x3 グリッドを1枚ずつ描く (行 = 自帯域、列 = 相手帯域、各パネル single 赤 / multi 紫の2本)。

AUC のブートストラップ 95% 信頼区間 (bootstrap_auc.py の出力) があれば、各点に
線と同じ色の髭を付ける。docs/save_features.md 参照。
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
DEFAULT_OUT_DIR = os.path.join(PLOT_BASE_DIR, "detection_lines")
# モードごとの既定の出力先。simultaneous は従来と同じ場所。
OUT_DIR_BY_MODE = {
    "simultaneous": DEFAULT_OUT_DIR,
    "sequential": os.path.join(PLOT_BASE_DIR, "detection_lines_sequential"),
    "compare": os.path.join(PLOT_BASE_DIR, "detection_lines_mode_compare"),
}

MODES = A.MEASUREMENT_MODES                         # ("simultaneous", "sequential")
# 凡例に出す名前 (論文での呼び方。save ブランチと同じ)
MODE_LABEL = {"simultaneous": "single-query", "sequential": "multi-query"}
# モード比較図 (手法ごとの 3x3 グリッド) での色とマーカー。1パネルは2本だけなので
# 線は両方実線にし、色 (single 赤 / multi 紫) とマーカー (○ / □) で分ける。
MODE_COLOR = {"simultaneous": "#d62839", "sequential": "#7b2cbf"}   # 赤 / 紫
MODE_MARKER = {"simultaneous": "o", "sequential": "s"}

# 信頼区間の髭 (エラーバー) の体裁
CI_CAPSIZE = 4        # 髭の端の横棒の長さ [pt]
CI_LINEWIDTH = 1.2
# 髭を描くときに系列ごとに横へずらす (dodge) 間隔 [負荷 %]。
# 以前は 1.2 で、同じ負荷の点と髭が真上に重ならないようにしていたが、点が本来の
# 負荷の位置から外れて見えるので 0 (ずらさない) にしている。docs/line_plot_style.md 参照。
# 戻すときはここだけを 1.2 にする (系列は最大9本なので両端でも ±4.8%)。
CI_DODGE = 0.0

# 縦軸に使う列。このブランチは AUC だけを見る (F1 は出さない)。
METRIC = "auc"

# 相手PAN の負荷を1つに固定した断面を描く。折れ線は OTHER_LOADS の全部について描く。
# OTHER_LOAD_PERCENT は own_other() の既定値で、相手負荷を指定しない呼び出し
# (plot_score_histograms.py / plot_roc.py。どちらも相手負荷 100% の断面) が使う。
OTHER_LOAD_PERCENT = 100
OTHER_LOADS = sorted(OFFERED_LOAD_PERCENTS)

# ファイル名に入れるモードの呼び名 (図を plots/ の外に持ち出しても区別できるように)
FILE_MODE_TAG = {"simultaneous": "single", "sequential": "multi"}
# 3手法を重ねた図の「中身」の呼び名
ALL_METHODS_TAG = "3methods"


def fig_path(out_dir, mode_tag, content, shape, other_load, fmt):
    """auc_<モード>_<中身>_<形>_otherload<相手負荷3桁>.<fmt>。命名規則は docs/line_plot_style.md。

    相手負荷は3桁にそろえる (otherload020 ... otherload100)。そろえないと名前順で
    100 が 20 より前に並ぶ。帯域は "own100kbps" のように kbps を付けて書き
    (bw_token())、相手負荷の "otherload" と取り違えないようにする。
    """
    return os.path.join(out_dir, f"{METRIC}_{mode_tag}_{content}_{shape}_"
                                 f"{otherload_token(other_load)}.{fmt}")


def bw_token(side, bw):
    """帯域のファイル名部品: bw_token("own", 100) -> "own100kbps"。"""
    return f"{side}{bw}kbps"


def otherload_token(other_load):
    """相手負荷のファイル名部品: 60 -> "otherload060"。plot_roc.py も使う。"""
    return f"otherload{other_load:03d}"


def plotted_values_path(mode):
    """描画値 CSV のパス。plot_score_histograms.py も AUC の照合に読む。"""
    return os.path.join(OUT_DIR_BY_MODE[mode],
                        f"{METRIC}_{FILE_MODE_TAG[mode]}_plotted_values.csv")

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
#
# "--" と ":" は線幅 2.0 だと間隔が近く、縮小すると見分けにくい。そこで dper は
# 長い破線、rssi は丸い点の列 (長さほぼ0の線分を丸キャップで描く) にして、
# 線の形そのものを変える。docs/line_plot_style.md 参照。
LINESTYLE = {"proposed": "-", "dper": (0, (8, 4)), "rssi": (0, (0.1, 3.0))}
# 丸い点の列は丸キャップでないと点にならない。破線の端も丸くなるが見分けには効かない
DASH_CAPSTYLE = "round"

# 点 (マーカー) は白抜きにする。縁だけで形を読むので塗りつぶしより大きくする
MARKER_SIZE = 8
MARKER_EDGEWIDTH = 1.8
MARKER_FACE = "white"


def line_kwargs(color, linestyle, marker):
    """図中の線と凡例の見本で共通の体裁。2箇所に書くと見本と線が食い違う。"""
    return dict(color=color, linestyle=linestyle, linewidth=2.0,
                dash_capstyle=DASH_CAPSTYLE,
                marker=marker, markersize=MARKER_SIZE,
                markerfacecolor=MARKER_FACE, markeredgecolor=color,
                markeredgewidth=MARKER_EDGEWIDTH)

# 図中のテキストは英語にする。計算機 (Linux) に日本語フォントが無いと豆腐文字に
# なるため。コメント・argparse ヘルプ・コンソール出力は日本語のままでよい。
#
# 軸ラベルとタイトルは入れない (横軸 = 自PAN負荷 [%]、縦軸 = AUC)。
# 図のキャプションで説明する前提。

GRID_KW = dict(color="0.85", linestyle="--", linewidth=0.8)

# --- 論文向けの体裁 -----------------------------------------------------
# タイトルと軸ラベルは入れない (図のキャプションで説明する前提)。そのぶん
# 目盛りの数字・目盛り線・凡例を大きくして、縮小しても読めるようにする。
TICK_LABELSIZE = 26     # 目盛りの数字 (以前は 20。docs/line_plot_style.md)
TICK_LENGTH = 10        # 目盛り線の長さ
TICK_WIDTH = 2.0        # 目盛り線の太さ
LEGEND_FONTSIZE = 28    # 以前は 22


def style_axes(ax, grid_axis="both"):
    """グリッド・枠線・目盛りをまとめて整える。

    grid_axis: グリッド線を引く向き。折れ線は横線 ("y") だけ (_finish_axes)。
    plot_roc.py もこれを使うので既定は両方のまま。
    """
    ax.grid(True, axis=grid_axis, **GRID_KW)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("0.4")
        ax.spines[side].set_linewidth(TICK_WIDTH)
    ax.tick_params(axis="both", which="major", labelsize=TICK_LABELSIZE,
                   length=TICK_LENGTH, width=TICK_WIDTH)


def input_csv_path(mode="simultaneous"):
    """mode -> 検知結果 CSV。"""
    return os.path.join(
        PLOT_BASE_DIR, f"interference_detection_results{A.mode_suffix(mode)}.csv")


def ci_csv_path(mode="simultaneous"):
    """mode -> AUC のブートストラップ信頼区間 CSV (bootstrap_auc.py が作る)。"""
    return os.path.join(PLOT_BASE_DIR, f"auc_bootstrap{A.mode_suffix(mode)}.csv")


def load_ci(csv_file, other_load=OTHER_LOAD_PERCENT):
    """ブートストラップ CSV を読み、{method: {(own_bw, other_bw): {own_load: (lo, hi)}}}。

    読み替えは load_series() と同じく own_other() に任せる。
    """
    ci = {m: defaultdict(dict) for m in METHODS}
    with open(csv_file, "r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["method"] not in ci:
                continue
            own = own_other(r, other_load)
            if own is None:
                continue
            ci[r["method"]][(own["own_bw"], own["other_bw"])][own["own_load"]] = (
                float(r["auc_ci_low"]), float(r["auc_ci_high"]))
    return ci


def maybe_load_ci(mode):
    """そのモードの信頼区間 CSV があれば、相手負荷ごとに読む: {other_load: ci}。

    無ければ {other_load: None} (髭を描かない)。
    """
    path = ci_csv_path(mode)
    if not os.path.isfile(path):
        print(f"    ({os.path.basename(path)} が無いので髭は描きません。"
              "先に script/bootstrap_auc.py を実行してください)")
        return {L: None for L in OTHER_LOADS}
    print(f"--- 95% 信頼区間: {os.path.basename(path)} ---")
    return {L: load_ci(path, L) for L in OTHER_LOADS}


def _draw_series(ax, xs, ys, dx, color, linestyle, marker, label, band):
    """1本の線と、あれば髭。band: {load: (lo, hi)} か None。"""
    # 白抜きの点が髭に隠れないよう、線と点を髭より手前 (zorder 大) に描く
    ax.plot([x + dx for x in xs], ys, label=label, zorder=3,
            **line_kwargs(color, linestyle, marker))
    bx = [x for x in xs if band and x in band]
    if not bx:
        return
    by = [ys[xs.index(x)] for x in bx]
    # errorbar の yerr は点からの上下の距離で渡す
    yerr = [[max(y - band[x][0], 0.0) for x, y in zip(bx, by)],
            [max(band[x][1] - y, 0.0) for x, y in zip(bx, by)]]
    ax.errorbar([x + dx for x in bx], by, yerr=yerr, fmt="none", ecolor=color,
                elinewidth=CI_LINEWIDTH, capsize=CI_CAPSIZE, capthick=CI_LINEWIDTH,
                zorder=2)


# y 軸の上端の余白。上端をちょうど AUC = 1.0 にすると、1.0 の線と点の上半分が
# 枠で切れて見えなくなる。目盛りは 1.0 までのまま、描画範囲だけ少し上に広げる。
YTOP_PAD = 0.03
# 縦軸の目盛りの間隔。以前は 0.1 刻みで、目盛りの数字が密で小さかった
YTICK_STEP = 0.2


def _finish_axes(ax, ylim, xpad=(8, 12)):
    loads = sorted(OFFERED_LOAD_PERCENTS)
    ax.set_xticks(loads)
    ax.set_xlim(min(loads) - xpad[0], max(loads) + xpad[1])
    lo, hi = ylim
    ax.set_ylim(lo, hi + YTOP_PAD)
    # 目盛りは YTICK_STEP の倍数のうち lo..hi に入るもの。下端から数えると
    # lo = 0.5 のとき 0.5/0.7/0.9 になって 1.0 に乗らないので、倍数で取る。
    # 余白 (hi + YTOP_PAD) に 1.2 などが出ないよう hi で打ち切る
    k0 = math.ceil(lo / YTICK_STEP - 1e-9)
    k1 = math.floor(hi / YTICK_STEP + 1e-9)
    ax.set_yticks([round(k * YTICK_STEP, 1) for k in range(k0, k1 + 1)])
    # 縦のグリッド線は引かない (横軸は負荷の5点だけで、目盛りで足りる)
    style_axes(ax, grid_axis="y")


def own_other(row, other_load_wanted=OTHER_LOAD_PERCENT):
    """結果CSVの1行を「自分 / 相手」に読み替える。

    検知を行っている側 (pan 列) が「自分」。bandwidth "AvsB" は PAN1=A kbps /
    PAN2=B kbps と読んでよい ――ラベルを作る get_bandwidth_label() はソートする
    が、TARGET_BANDWIDTH_PATTERNS が常に kbps(PAN1) <= kbps(PAN2) を満たすので
    そのソートは恒等写像になる。導出根拠は docs/README.md の「折れ線グラフ」節。

    この断面に入らない行 (相手負荷が other_load_wanted でない、対称ペアの
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

    if other_load != other_load_wanted:
        return None
    if a == b and pan != "PAN1":
        return None
    return {"own_bw": own_bw, "other_bw": other_bw, "own_load": own_load}


def load_series(csv_file, other_load=OTHER_LOAD_PERCENT):
    """CSV を読み、{method: {(own_bw, other_bw): {own_load: auc}}} を返す。

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

    series = {m: defaultdict(dict) for m in METHODS}
    unknown = set()
    for r in rows:
        method = r["method"]
        if method not in series:
            unknown.add(method)
            continue
        own = own_other(r, other_load)
        if own is None:
            continue
        series[method][(own["own_bw"], own["other_bw"])][own["own_load"]] = \
            float(r[METRIC])

    if unknown:
        # 黙って捨てると「描いたつもりの手法が図に無い」事故になる
        print(f"    Warning: 未知の手法を無視しました: {sorted(unknown)}")
    return series


def choose_ylim(data, cis=()):
    """全図で共通に使う y 軸の範囲を決める。

    save ブランチは AUC を (0.50, 1.0) に固定していた。0.5 がランダム判定の
    水準で、軸の下端がそのまま床を示すからである。だが**ベースラインは 0.5 を
    下回り得る** (指標が干渉の有無と逆相関する条件が実在する。docs/auc.md 参照)。
    下回った点が枠外に消えると図が嘘になるので、必要なときだけ下げる。

    枚ごとに変えてはいけない。図をまたいで比較できることがこの図の目的なので、
    全描画値の最小値から1つだけ決めて全図に同じ値を当てる。

    cis: load_ci() の戻り値の並び (髭を描くとき)。点が枠内でも髭の下端が枠外に
    出て切れないよう、信頼区間の下限も最小値の候補に入れる。
    """
    values = [v
              for per_method in data.values()
              for pts in per_method.values()
              for v in pts.values()]
    values += [lo
               for ci in cis if ci
               for per_method in ci.values()
               for band in per_method.values()
               for lo, _hi in band.values()]
    if not values:
        return (0.50, 1.0)
    lo = min(values)
    if lo >= 0.5:
        return (0.50, 1.0)
    # 0.1 刻みで切り下げる。目盛りが半端な位置に来ないようにするため。
    return (math.floor(lo * 10.0) / 10.0, 1.0)


def _draw_panel(ax, data, own_bw, methods, ylim, ci=None):
    """1つの軸に、ある自帯域についての線を引く。

    data: {method: {(own_bw, other_bw): {own_load: auc}}}
    methods: 描く手法のタプル。1つなら単独図、3つなら比較図。
    ci: load_ci() の戻り値か None。あれば髭を付ける (横へのずらし幅は CI_DODGE)。
    """
    loads = sorted(OFFERED_LOAD_PERCENTS)
    # 後に描いた線ほど手前に来る。提案手法が一番手前になるよう、手法は逆順に描く
    # (凡例は legend_handles() が別に作るので、並び順はこの順に左右されない)。
    series = [(m, bw) for m in reversed(methods) for bw in BANDWIDTHS]
    for k, (method, other_bw) in enumerate(series):
        pts = data[method].get((own_bw, other_bw))
        if not pts:
            continue
        xs = [l for l in loads if l in pts]
        ys = [pts[l] for l in xs]
        dx = (k - (len(series) - 1) / 2.0) * CI_DODGE if ci else 0.0
        band = ci[method].get((own_bw, other_bw)) if ci else None
        _draw_series(ax, xs, ys, dx, COLOR[other_bw], LINESTYLE[method],
                     MARKER[other_bw], f"{other_bw} kbps", band)
    _finish_axes(ax, ylim)


def _sample(method, bw, label):
    """凡例の見本1つ。図中の線と同じ色・線種・白抜きマーカー。"""
    return Line2D([], [], label=label,
                  **line_kwargs(COLOR[bw], LINESTYLE[method], MARKER[bw]))


def legend_handles(methods):
    """凡例の手と、凡例の列数を返す。

    手法が1つだけの図は線種の軸が無いので、帯域3項目だけを出す (1列)。

    3手法を重ねた図は、実際に引いている 3手法 x 3帯域 = 9 本をそのまま
    3x3 の行列で出す (行 = 手法、列 = 相手帯域)。色と線種を別ブロックに分けると
    3+3 = 6 項目になり、線が6本あるように見えてしまうため。
    1列目は手法名だけの行見出し (見本を描かない)。matplotlib の凡例は列方向に
    詰めるので、[見出し3つ] -> [帯域ごとに3手法] の順に並べて ncol=4 で渡す。
    """
    if len(methods) == 1:
        return [_sample(methods[0], bw, f"{bw} kbps") for bw in BANDWIDTHS], 1
    handles = [Line2D([], [], linestyle="none", marker="none",
                      label=METHOD_LABEL[m]) for m in methods]
    handles += [_sample(m, bw, f"{bw} kbps") for bw in BANDWIDTHS for m in methods]
    return handles, 1 + len(BANDWIDTHS)


def _add_legend(target, methods, **kw):
    """legend_handles() の凡例を target (Axes か Figure) に付ける。

    行列凡例は大きく、軸の中に置くと線に重なるので軸の上側の外に置く。
    """
    handles, ncol = legend_handles(methods)
    if ncol == 1:
        return target.legend(handles=handles, frameon=True,
                             fontsize=LEGEND_FONTSIZE, **kw)
    return target.legend(handles=handles, ncol=ncol, frameon=True,
                         fontsize=LEGEND_FONTSIZE, columnspacing=1.2,
                         handlelength=2.6, loc="lower center", **kw)


def plot_single(data, own_bw, methods, path, ylim, ci=None):
    """自帯域1つ分の図を1枚描く。"""
    fig, ax = plt.subplots(figsize=(7.2, 5.8))
    _draw_panel(ax, data, own_bw, methods, ylim, ci)
    if len(methods) == 1:
        _add_legend(ax, methods, loc="lower left")
    else:
        _add_legend(ax, methods, bbox_to_anchor=(0.5, 1.02))
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_3panel(data, methods, path, ylim, ci=None):
    """自帯域3つを横並びのサブプロットにした1枚。"""
    fig, axes = plt.subplots(1, 3, figsize=(19.0, 5.8), sharey=True)
    for ax, own_bw in zip(axes, BANDWIDTHS):
        _draw_panel(ax, data, own_bw, methods, ylim, ci)
    fig.tight_layout()
    if len(methods) == 1:
        _add_legend(fig, methods, loc="center left", bbox_to_anchor=(1.0, 0.5))
    else:
        # 行列凡例は横に長いので、3パネルの上にまとめて置く
        _add_legend(fig, methods, bbox_to_anchor=(0.5, 1.0))
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


# --- 3x3 グリッド図 ---------------------------------------------------
# 帯域の組を位置 (行 = 自帯域、列 = 相手帯域) で分けるので、色は手法に回す。
# 色は帯域用と同じパレットの3スロット。線種・マーカーも手法ごとに変えて冗長にする。
METHOD_COLOR = {"proposed": "#eb6834", "dper": "#2a78d6", "rssi": "#1baf7a"}   # 橙 / 青 / 緑
METHOD_MARKER = {"proposed": "o", "dper": "s", "rssi": "^"}
# 1パネル3本なので線種で区別する必要は無く、全部実線にする (手法は色とマーカーで読む)
GRID_LINESTYLE = "-"


# gridtable 図 (各パネルの下に AUC の数値表) の体裁。docs/line_plot_style.md 参照
TABLE_FONTSIZE = 13
TABLE_HEIGHT_RATIO = 0.42   # パネルの高さに対する表の高さ
# 表の行見出しは隣のパネルの表にはみ出さないよう短くする (凡例は正式名のまま)
TABLE_ROW_LABEL = {"single-query": "single", "multi-query": "multi"}


def _draw_value_table(ax, series, row_order, xlim):
    """パネル直下の軸 ax に、そのパネルの AUC の表を描く。

    列 = 自PAN負荷 (横軸の点と中心をそろえる)、行 = 線 (row_order = 凡例の順)。
    セルは描いた点の値そのもの (AUC の点推定)。
    """
    ax.axis("off")
    loads = sorted(OFFERED_LOAD_PERCENTS)
    by_label = {label: (dict(zip(xs, ys)), color)
                for xs, ys, color, _marker, label, _band in series}
    rows = [lab for lab in row_order if lab in by_label]
    cells = [[f"{by_label[lab][0][l]:.3f}" if l in by_label[lab][0] else "-"
              for l in loads] for lab in rows]
    # 列の境界を負荷の中点に置き、列の中心を横軸の点の位置にそろえる
    step = loads[1] - loads[0]
    x0, x1 = xlim
    left = (loads[0] - step / 2 - x0) / (x1 - x0)
    width = step * len(loads) / (x1 - x0)
    tbl = ax.table(cellText=cells, rowLabels=[TABLE_ROW_LABEL.get(r, r) for r in rows], colLabels=[f"{l}%" for l in loads],
                   cellLoc="center", rowLoc="right", bbox=[left, 0.0, width, 1.0])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(TABLE_FONTSIZE)
    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor("0.75")
        cell.set_linewidth(0.6)
        if r == 0:
            cell.set_text_props(color="0.3")
        elif c == -1:
            # 行見出しは凡例と同じ色にして、線との対応を色で読めるようにする
            cell.set_text_props(color=by_label[rows[r - 1]][1], fontweight="bold")
            cell.set_edgecolor("none")


def _plot_bw_grid(series_of, handles, path, ylim, table=False):
    """行 = 自帯域、列 = 相手帯域の 3x3 を描いて保存する。

    series_of(own_bw, other_bw) は、そのパネルに描く系列
    [(xs, ys, color, marker, label, band), ...] を返す。
    3手法のグリッド図とモード比較のグリッド図で共通の枠組み。
    table=True なら各パネルの直下に AUC の数値表を付ける (gridtable 図)。
    """
    n = len(BANDWIDTHS)
    if table:
        # パネルの行と表の行を交互に積む
        fig = plt.figure(figsize=(17.0, 13.0 * (1 + TABLE_HEIGHT_RATIO)))
        gs = fig.add_gridspec(2 * n, n, height_ratios=[1.0, TABLE_HEIGHT_RATIO] * n,
                              hspace=0.12, wspace=0.42, top=0.975, bottom=0.02)
        axes = [[None] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                axes[i][j] = fig.add_subplot(
                    gs[2 * i, j], sharex=axes[0][0], sharey=axes[0][0])
    else:
        fig, axes = plt.subplots(n, n, figsize=(15.0, 13.0), sharex=True, sharey=True)
    row_order = [h.get_label() for h in handles]
    for i, own_bw in enumerate(BANDWIDTHS):
        for j, other_bw in enumerate(BANDWIDTHS):
            ax = axes[i][j]
            series = series_of(own_bw, other_bw)
            for xs, ys, color, marker, label, band in series:
                _draw_series(ax, xs, ys, 0.0, color, GRID_LINESTYLE, marker, label, band)
            _finish_axes(ax, ylim)
            # sharex/sharey でも目盛りの数字は外周のパネルにだけ出す。
            # 表付きの図は表の列見出しが負荷を示すが、横軸の数字は同じく最下段に出す
            ax.tick_params(labelleft=(j == 0), labelbottom=(i == n - 1 and not table))
            # 行・列の見出し (自帯域 / 相手帯域) は入れない。軸タイトルを入れない
            # 方針どおり、図のキャプションで説明する
            if table:
                _draw_value_table(fig.add_subplot(gs[2 * i + 1, j]), series,
                                  row_order, ax.get_xlim())
    if not table:
        fig.tight_layout()
    fig.legend(handles=handles, ncol=len(handles), loc="lower center",
               bbox_to_anchor=(0.5, 0.99), frameon=True, fontsize=LEGEND_FONTSIZE,
               handlelength=2.6)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def _points(pts):
    """{load: auc} -> 負荷順の (xs, ys)。"""
    xs = [l for l in sorted(OFFERED_LOAD_PERCENTS) if l in pts]
    return xs, [pts[l] for l in xs]


def plot_grid(data, path, ylim, ci=None, table=False):
    """行 = 自帯域、列 = 相手帯域の 3x3。1パネルに3手法の3本だけを描く。

    compare 図は1パネルに 9 本乗って読みにくいので、その代替。
    docs/line_plot_style.md の「3×3 グリッド図」参照。
    """
    def series_of(own_bw, other_bw):
        out = []
        # 後に描いた線ほど手前に来る。提案手法が一番手前になるよう逆順に描く
        for method in reversed(METHODS):
            pts = data[method].get((own_bw, other_bw))
            if not pts:
                continue
            band = ci[method].get((own_bw, other_bw)) if ci else None
            out.append((*_points(pts), METHOD_COLOR[method], METHOD_MARKER[method],
                        METHOD_LABEL[method], band))
        return out

    handles = [Line2D([], [], label=METHOD_LABEL[m],
                      **line_kwargs(METHOD_COLOR[m], GRID_LINESTYLE, METHOD_MARKER[m]))
               for m in METHODS]
    return _plot_bw_grid(series_of, handles, path, ylim, table)


def dump_values(data_by_load, ci_by_load, path):
    """描画に使った値を CSV に出す。数値確認用と relief rule への対応を兼ねる。

    相手負荷5通りぶんを1つにまとめる (other_load_percent 列で区別)。
    髭を描いたときは、信頼区間の下端・上端の列も足す。
    """
    with_ci = any(ci_by_load.values())
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["method", "own_bw_kbps", "other_bw_kbps",
                    "other_load_percent", "own_load_percent", METRIC]
                   + ([f"{METRIC}_ci_low", f"{METRIC}_ci_high"] if with_ci else []))
        for other_load in OTHER_LOADS:
            data, ci = data_by_load[other_load], ci_by_load[other_load]
            for method in METHODS:
                for own_bw in BANDWIDTHS:
                    for other_bw in BANDWIDTHS:
                        pts = data[method].get((own_bw, other_bw), {})
                        for load in sorted(pts):
                            extra = []
                            if with_ci:
                                lo, hi = (ci or {}).get(method, {}).get(
                                    (own_bw, other_bw), {}).get(
                                    load, (float("nan"), float("nan")))
                                extra = [f"{lo:.6g}", f"{hi:.6g}"]
                            w.writerow([method, own_bw, other_bw, other_load, load,
                                        f"{pts[load]:.6g}"] + extra)
    return path


# ------------------------------------------------------------
# モード比較 (single-query vs multi-query)。手法ごとに1枚
# ------------------------------------------------------------
def plot_mode_compare(data_by_mode, ci_by_mode, out_dir, fmt, ylim, other_load):
    """手法ごとに 3x3 グリッドを1枚 (計3枚)。各パネルは single / multi の2本。

    以前は1パネルに 3相手帯域 x 2モード = 6本を重ねていて見にくかったので、
    帯域の組を位置で分け、同じ条件の2モードだけを並べる。
    docs/line_plot_style.md の「モード比較図」参照。
    """
    handles = [Line2D([], [], label=MODE_LABEL[m],
                      **line_kwargs(MODE_COLOR[m], GRID_LINESTYLE, MODE_MARKER[m]))
               for m in MODES]
    written = []
    for method in METHODS:
        def series_of(own_bw, other_bw, method=method):
            out = []
            for mode in MODES:
                pts = data_by_mode[mode][method].get((own_bw, other_bw))
                if not pts:
                    continue
                ci = ci_by_mode.get(mode)
                band = ci[method].get((own_bw, other_bw)) if ci else None
                out.append((*_points(pts), MODE_COLOR[mode], MODE_MARKER[mode],
                            MODE_LABEL[mode], band))
            return out

        for shape, table in (("grid", False), ("gridtable", True)):
            written.append(_plot_bw_grid(
                series_of, handles,
                fig_path(out_dir, "modecompare", method, shape, other_load, fmt), ylim,
                table))
    return written


def load_mode(mode, csv_path=None):
    """1モード分の検知結果を相手負荷ごとに読み、系列数を確かめて返す: {other_load: data}。"""
    path = csv_path or input_csv_path(mode)
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"CSV file not found: {path}\n"
            f"  analyze_csv.py --mode {mode} を実行してください "
            f"(./script/sbatch_reanalyze.sh でも作られます)。")
    mtime = datetime.datetime.fromtimestamp(
        os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
    # 解析コードより CSV が古いことがあるので更新時刻を必ず出す
    print(f"--- {mode}: {path} (更新 {mtime}) ---")

    data_by_load = {}
    expected = len(BANDWIDTHS) ** 2
    for other_load in OTHER_LOADS:
        data = load_series(path, other_load)
        # 期待する系列数の確認。欠けたまま静かに描くと図が嘘になる。
        for method in METHODS:
            got = len(data[method])
            n_pts = sorted(set(len(v) for v in data[method].values()))
            if got != expected or n_pts != [len(OFFERED_LOAD_PERCENTS)]:
                missing = [k for k in ((o, t) for o in BANDWIDTHS for t in BANDWIDTHS)
                           if k not in data[method]]
                print(f"    Warning: 相手負荷 {other_load}% {method}: 系列 {got}/{expected}, "
                      f"点数 {n_pts}, 欠け {missing}")
        data_by_load[other_load] = data
    print(f"    相手負荷 {OTHER_LOADS} x 手法 {len(METHODS)} を読み込み")
    return data_by_load


def main():
    p = argparse.ArgumentParser(
        description="相手PAN負荷 (20-100%) ごとの断面で、干渉判定3手法の AUC を折れ線にする")
    p.add_argument("--mode", choices=MODES + ("compare",), default="simultaneous",
                   help="simultaneous: single-query の3手法 (既定) / "
                        "sequential: multi-query の3手法 / "
                        "compare: 手法ごとに single-query と multi-query を重ねる")
    p.add_argument("--csv", default=None,
                   help="検知結果 CSV (--mode が simultaneous / sequential のとき。"
                        "既定はモードに応じた plots/ 以下の CSV)")
    p.add_argument("--out-dir", default=None,
                   help="出力先 (既定はモードごとに plots/detection_lines* )")
    p.add_argument("--format", default="pdf", choices=("pdf", "png"),
                   help="出力形式 (既定: pdf)。目視確認には png")
    args = p.parse_args()

    out_dir = args.out_dir or OUT_DIR_BY_MODE[args.mode]
    os.makedirs(out_dir, exist_ok=True)
    fmt = args.format

    if args.mode == "compare":
        data_by_mode = {m: load_mode(m) for m in MODES}
        ci_by_mode = {m: maybe_load_ci(m) for m in MODES}
        # y 軸は両モード・全相手負荷で共通
        ylim = choose_ylim({f"{m}/{L}/{k}": v for m in MODES for L in OTHER_LOADS
                            for k, v in data_by_mode[m][L].items()},
                           cis=[ci_by_mode[m][L] for m in MODES for L in OTHER_LOADS])
        print(f"--- y軸: {ylim[0]:.2f} - {ylim[1]:.2f} ---")
        written = []
        for L in OTHER_LOADS:
            written += plot_mode_compare({m: data_by_mode[m][L] for m in MODES},
                                         {m: ci_by_mode[m][L] for m in MODES},
                                         out_dir, fmt, ylim, L)
    else:
        mode_tag = FILE_MODE_TAG[args.mode]
        data_by_load = load_mode(args.mode, args.csv)
        ci_by_load = maybe_load_ci(args.mode)
        # y 軸は全相手負荷で共通 (図をまたいで比べられるように)
        ylim = choose_ylim({f"{L}/{k}": v for L in OTHER_LOADS
                            for k, v in data_by_load[L].items()},
                           cis=list(ci_by_load.values()))
        print(f"--- y軸: {ylim[0]:.2f} - {ylim[1]:.2f} "
              f"(全図共通。点か髭の下端が 0.5 を下回るときだけ下げる) ---")
        written = []
        # 手法ごとの単独図と、3手法を重ねた比較図
        tags = [(m, (m,)) for m in METHODS] + [(ALL_METHODS_TAG, tuple(METHODS))]
        for L in OTHER_LOADS:
            data, ci = data_by_load[L], ci_by_load[L]
            for content, methods in tags:
                for own_bw in BANDWIDTHS:
                    written.append(plot_single(
                        data, own_bw, methods,
                        fig_path(out_dir, mode_tag, content, bw_token("own", own_bw), L, fmt),
                        ylim, ci))
                written.append(plot_3panel(
                    data, methods, fig_path(out_dir, mode_tag, content, "3panel", L, fmt),
                    ylim, ci))
            for shape, table in (("grid", False), ("gridtable", True)):
                written.append(plot_grid(
                    data, fig_path(out_dir, mode_tag, ALL_METHODS_TAG, shape, L, fmt),
                    ylim, ci, table))
        csv_path = os.path.join(out_dir, os.path.basename(plotted_values_path(args.mode)))
        written.append(dump_values(data_by_load, ci_by_load, csv_path))

    print(f"\n--- {out_dir} に {len(written)} ファイル出力 ---")
    for path in written:
        print(f"    {os.path.basename(path)}")


if __name__ == "__main__":
    main()
