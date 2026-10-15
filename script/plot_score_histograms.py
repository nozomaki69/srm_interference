#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干渉あり / なしのスコア分布 (山) を、自PAN負荷ごとにヒストグラムで描く。

AUC は「干渉ありの山」と「干渉なしの山」の離れ具合を、閾値をずらしながら測った
ものである。その山そのものを見て、どう分離しているか (重なっているか) を確かめる。

対象は折れ線 (plot_detection_lines.py) と同じ断面: 相手PAN負荷 100% と 200%
(icc_load200。断面ごとに other100/ other200/ へ出す)、
自帯域 x 相手帯域の 9 通り、対称ペアは PAN1 側だけ。読み替え規則は
plot_detection_lines.own_other() をそのまま使う (2箇所に書くと静かにずれる)。

  1枚 = 帯域の組 (自帯域, 相手帯域) 1つ
  行  : 判定手法 (proposed / dper / rssi)
  列  : 自PAN負荷
  横軸: その手法の Seed ごとのスコア
        proposed = RSSIビン内 ΔPER 分散の最大値、dper = 全端末の ΔPER 分散、
        rssi = 全端末の平均RSSI [dBm]
  縦軸: シナリオ数 (Seed 数。干渉あり・なし各 100)
  色  : 干渉あり = 赤、干渉なし = 青

入力は analyze_csv.py が出す Seed 別スコア (detection_scores_simultaneous.csv)。
設計は docs/README.md の「スコア分布のヒストグラム」節を参照。
"""

import os
import sys
import csv
import math
import argparse
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import analyze_csv as A  # noqa: E402
import plot_detection_lines as L  # noqa: E402
from interference_2pan_config import OFFERED_LOAD_PERCENTS  # noqa: E402

# icc の 20-100% の結果 (score_histograms/) と混ざらないよう別の場所に出す。
DEFAULT_OUT_DIR = os.path.join(A.PLOT_BASE_DIR, "score_histograms_more")

METHODS = A.DETECTION_METHODS
BANDWIDTHS = L.BANDWIDTHS

# 干渉あり = 赤、干渉なし = 青 (ユーザー指定)
CLASS_STYLE = {
    "interf": {"color": "#d62728", "label": "Interference"},
    "no_interf": {"color": "#1f77b4", "label": "No interference"},
}

# 行ごとの横軸ラベル。図中のテキストは英語 (計算機に日本語フォントが無いため)。
X_LABEL = {
    "proposed": r"Max in-bin variance of $\Delta$PER",
    "dper": r"Variance of $\Delta$PER",
    "rssi": "Mean RSSI [dBm]",
}

# 両群に共通のビンの本数 (両群を合わせた範囲を等分する)
NUM_BINS = 20


def scores_csv_path():
    return os.path.join(A.PLOT_BASE_DIR, f"detection_scores{A.COLUMN_SUFFIX}.csv")


def load_scores(csv_file):
    """スコアCSVを読み、断面ごとに
    {other_load: {(own_bw, other_bw): {method: {own_load: {"interf": [...], "no_interf": [...]}}}}}
    を返す。断面の絞り込みと自分 / 相手の読み替えは own_other() に任せる。
    """
    def _per_pair():
        return {m: defaultdict(lambda: {"interf": [], "no_interf": []}) for m in METHODS}

    data = {ol: defaultdict(_per_pair) for ol in L.OTHER_LOAD_PERCENTS}
    with open(csv_file, "r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["method"] not in METHODS:
                continue
            for other_load in L.OTHER_LOAD_PERCENTS:
                own = L.own_other(r, other_load)
                if own is None:
                    continue
                data[other_load][(own["own_bw"], own["other_bw"])][r["method"]][
                    own["own_load"]][r["klass"]].append(float(r["score"]))
    return data


def load_reference_auc(path):
    """折れ線の描画値 (auc_plotted_values.csv) を読み、突き合わせ用に返す。"""
    ref = {}
    if not os.path.isfile(path):
        return ref
    with open(path, "r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            key = (int(r["other_load_percent"]), r["method"], int(r["own_bw_kbps"]),
                   int(r["other_bw_kbps"]), int(r["own_load_percent"]))
            ref[key] = float(r["auc"])
    return ref


def _draw_hist(ax, groups):
    """1パネル分。両群に共通のビンで重ねて描き、(AUC, 除外件数) を返す。"""
    finite = {k: np.asarray([v for v in vals if math.isfinite(v)], dtype=float)
              for k, vals in groups.items()}
    n_dropped = sum(len(groups[k]) - len(finite[k]) for k in groups)

    both = np.concatenate([finite["interf"], finite["no_interf"]])
    if both.size == 0:
        return float("nan"), n_dropped
    lo, hi = float(both.min()), float(both.max())
    if hi <= lo:  # 全部同じ値のときも棒が見えるように幅を持たせる
        pad = abs(lo) * 0.05 or 1e-6
        lo, hi = lo - pad, hi + pad
    edges = np.linspace(lo, hi, NUM_BINS + 1)

    # 干渉なし (青) を先に描き、干渉あり (赤) を上に重ねる
    for klass in ("no_interf", "interf"):
        st = CLASS_STYLE[klass]
        ax.hist(finite[klass], bins=edges, color=st["color"], alpha=0.45,
                edgecolor=st["color"], linewidth=0.8)

    # AUC は縮退スコアも含めた全 Seed で計算する (analyze_csv と同じ定義)
    auc = A._rank_auc(groups["interf"], groups["no_interf"])
    return auc, n_dropped


def plot_pair(other_load, own_bw, other_bw, per_method, loads, out_dir, fmt,
              ref_auc, mismatches):
    """帯域の組1つ分の 3行 x 負荷数 列の図を描く。"""
    n_rows, n_cols = len(METHODS), len(loads)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(3.3 * n_cols, 3.0 * n_rows),
                             squeeze=False)
    for i, method in enumerate(METHODS):
        for j, load in enumerate(loads):
            ax = axes[i][j]
            groups = per_method[method].get(load)
            if not groups or not groups["interf"] or not groups["no_interf"]:
                ax.text(0.5, 0.5, "no data", ha="center", va="center",
                        transform=ax.transAxes, color="0.5")
                ax.set_xticks([]); ax.set_yticks([])
                continue
            auc, n_dropped = _draw_hist(ax, groups)

            note = f"AUC {auc:.3f}"
            if n_dropped:
                note += f"\n({n_dropped} non-finite excluded)"
            ax.text(0.97, 0.95, note, ha="right", va="top", transform=ax.transAxes,
                    fontsize=10, bbox=dict(facecolor="white", edgecolor="0.8",
                                           boxstyle="round,pad=0.25", alpha=0.85))

            ref = ref_auc.get((other_load, method, own_bw, other_bw, load))
            if ref is not None and abs(ref - auc) > 1e-4:
                mismatches.append((other_load, method, own_bw, other_bw, load, auc, ref))

            ax.grid(True, color="0.88", linestyle="--", linewidth=0.6)
            ax.set_axisbelow(True)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
            ax.tick_params(labelsize=9)
            # 縦軸はシナリオ数なので整数の目盛りだけにする
            ax.yaxis.set_major_locator(MaxNLocator(integer=True))
            if i == 0:
                ax.set_title(f"Own load {load}%", fontsize=12)
            if j == 0:
                ax.set_ylabel(f"{A.METHOD_LABEL[method]}\nNumber of scenarios",
                              fontsize=11)
            ax.set_xlabel(X_LABEL[method], fontsize=9)

    handles = [Patch(facecolor=CLASS_STYLE[k]["color"], alpha=0.45,
                     edgecolor=CLASS_STYLE[k]["color"], label=CLASS_STYLE[k]["label"])
               for k in ("interf", "no_interf")]
    fig.legend(handles=handles, loc="upper center", ncol=2, frameon=False,
               fontsize=12, bbox_to_anchor=(0.5, 1.0))
    fig.suptitle(f"Own {own_bw} kbps / Other {other_bw} kbps "
                 f"(other load {other_load}%)", fontsize=13, y=1.035)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    path = os.path.join(out_dir, f"hist_own{own_bw}_other{other_bw}.{fmt}")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def main():
    p = argparse.ArgumentParser(
        description="相手PAN負荷100%/200%の断面で、干渉あり(赤)/なし(青)のスコア分布を"
                    "自PAN負荷ごとにヒストグラムにする")
    p.add_argument("--csv", default=None,
                   help=f"Seed 別スコア CSV (既定: {scores_csv_path()})")
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    p.add_argument("--format", default="pdf", choices=("pdf", "png"))
    args = p.parse_args()

    path = args.csv or scores_csv_path()
    if not os.path.isfile(path):
        raise FileNotFoundError(f"CSV file not found: {path}")
    print(f"--- {path} ---")
    data = load_scores(path)
    loads = sorted(OFFERED_LOAD_PERCENTS)

    # AUC を折れ線の描画値と突き合わせる (同じスコアから同じ定義で出しているはず)
    ref_path = os.path.join(L.DEFAULT_OUT_DIR, f"{L.METRIC}_plotted_values.csv")
    ref_auc = load_reference_auc(ref_path)

    os.makedirs(args.out_dir, exist_ok=True)
    written, mismatches = [], []
    for other_load, section in data.items():
        sub_dir = os.path.join(args.out_dir, f"other{other_load}")
        os.makedirs(sub_dir, exist_ok=True)
        for own_bw in BANDWIDTHS:
            for other_bw in BANDWIDTHS:
                per_method = section.get((own_bw, other_bw))
                if per_method is None:
                    print(f"    Warning: other{other_load} (own {own_bw}, other {other_bw})"
                          " のデータがありません")
                    continue
                written.append(plot_pair(other_load, own_bw, other_bw, per_method, loads,
                                         sub_dir, args.format, ref_auc, mismatches))

    if ref_auc:
        if mismatches:
            print(f"    Warning: 折れ線の AUC と一致しないパネルが {len(mismatches)} 件あります")
            for m in mismatches[:10]:
                print(f"      other{m[0]}% {m[1]} own{m[2]} other{m[3]} load{m[4]}: "
                      f"{m[5]:.4f} (折れ線 {m[6]:.4f})")
        else:
            print(f"--- AUC: 全パネルが折れ線の描画値 ({os.path.basename(ref_path)}) と一致 ---")
    else:
        print(f"    (突き合わせ用の {ref_path} が無いので AUC の照合は省略)")

    print(f"\n--- {args.out_dir} に {len(written)} ファイル出力 ---")
    for w in written:
        print(f"    {os.path.relpath(w, args.out_dir)}")


if __name__ == "__main__":
    main()
