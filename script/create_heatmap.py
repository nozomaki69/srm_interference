#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干渉判定3手法の AUC を、PAN1 負荷 x PAN2 負荷の格子にヒートマップで出す。

save ブランチの create_heatmap.py の AUC 版を、手法の列 (method) を持つこのブランチの
検知結果CSVに合わせたもの。手法ごとにサブフォルダを分ける。

  縦軸: PAN1 負荷、横軸: PAN2 負荷 (自分 / 相手への読み替えはしない。save と同じ)
  セル: AUC (3桁)。色の範囲は 0.5-1.0
  1枚 = (帯域ペア, PAN)、1手法 12 枚 (6帯域ペア x 2PAN)

出力: plots/heatmaps_auc{,_simultaneous}/{method}/heatmap_{帯域ペア}_{距離}_{PAN}.pdf
設計は docs/save_features.md を参照。
"""

import os
import sys
import argparse

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# 負荷グリッドはスイープを定義している側を唯一の定義元とする。直値を書くと、
# スイープの範囲を変えたときにヒートマップだけ取り残されて範囲外のセルが黙って捨てられる。
from interference_2pan_config import OFFERED_LOAD_PERCENTS  # noqa: E402
import analyze_csv as A  # noqa: E402
# 目盛りの体裁は折れ線と共有する (plot_detection_lines が定義元)
from plot_detection_lines import TICK_LENGTH, TICK_WIDTH  # noqa: E402

LOAD_RANGE = sorted(OFFERED_LOAD_PERCENTS)
VMIN, VMAX = 0.5, 1.0
DECIMALS = 3          # 100x100 ペアなので AUC の刻みは 1e-4
CELL_SIZE = 2.10      # セル1つの幅と高さ (インチ)。値だけなので正方形。
                      # 以前は 1.70。セル内の文字を 25pt にしたら "1.000" が隣のセルに届いたので広げた
FONTSIZE = 25          # セル内の AUC (以前は 19)
# 軸とカラーバーの目盛り。折れ線と共有の TICK_LABELSIZE より一段大きくする
HEATMAP_TICK_LABELSIZE = 28
CBAR_TICK_LABELSIZE = 28

# 白文字に切り替える閾値。YlGnBu 上で白文字と黒文字の WCAG コントラストが
# 入れ替わるのが値 0.838 のところ (save の create_heatmap.py と同じ根拠)。
WHITE_TEXT_FROM = 0.84


def input_csv_path(mode):
    return os.path.join(A.PLOT_BASE_DIR,
                        f"interference_detection_results{A.mode_suffix(mode)}.csv")


def output_dir_path(mode):
    return os.path.join(A.PLOT_BASE_DIR, f"heatmaps_auc{A.mode_suffix(mode)}")


def _cell_label(val):
    """セルに書く AUC。小数3桁に丸めてから先頭の 0 を落とす (0.789 -> .789)。

    丸めて 1.000 になる値はそのまま。先に丸めないと 0.9996 が .1000 のような
    おかしな表記になりうるので、文字列にしてから判定する。
    """
    text = f"{val:.{DECIMALS}f}"
    return text[1:] if text.startswith("0.") else text


def make_heatmap(sub, out_path):
    """1枚分。sub は (帯域ペア, 距離, PAN, 手法) で絞り込んだ行。"""
    sub = sub.drop_duplicates(subset=["pan1_offload", "pan2_offload"], keep="last")
    pivot = sub.pivot(index="pan1_offload", columns="pan2_offload", values="auc")
    rows = sorted(set(LOAD_RANGE) | set(pivot.index))
    cols = sorted(set(LOAD_RANGE) | set(pivot.columns))
    pivot = pivot.reindex(index=rows, columns=cols)

    fig, ax = plt.subplots(figsize=(CELL_SIZE * len(cols), CELL_SIZE * len(rows)))
    im = ax.imshow(pivot.values, cmap="YlGnBu", vmin=VMIN, vmax=VMAX, aspect="equal")
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(cols)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(rows)
    ax.invert_yaxis()
    # 軸ラベルとタイトルは入れない (縦 = PAN1 負荷、横 = PAN2 負荷。キャプションで説明)
    ax.tick_params(axis="both", which="major", labelsize=HEATMAP_TICK_LABELSIZE,
                   length=TICK_LENGTH, width=TICK_WIDTH)

    for i in range(len(rows)):
        for j in range(len(cols)):
            val = pivot.iloc[i, j]
            if pd.isna(val):
                continue
            ax.text(j, i, _cell_label(val), ha="center", va="center",
                    color="white" if val > WHITE_TEXT_FROM else "black",
                    fontsize=FONTSIZE, fontweight="bold")

    cbar = fig.colorbar(im, ax=ax)
    cbar.ax.tick_params(labelsize=CBAR_TICK_LABELSIZE, length=TICK_LENGTH, width=TICK_WIDTH)
    fig.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, format="pdf", bbox_inches="tight")
    plt.close(fig)
    return out_path


def main():
    p = argparse.ArgumentParser(description="干渉判定3手法の AUC ヒートマップ")
    p.add_argument("--mode", choices=A.MEASUREMENT_MODES, default="simultaneous",
                   help="simultaneous: single-query (既定) / sequential: multi-query")
    p.add_argument("--input", default=None, help="検知結果 CSV (--mode より優先)")
    p.add_argument("--out-dir", default=None, help="出力先 (--mode より優先)")
    args = p.parse_args()

    input_csv = args.input or input_csv_path(args.mode)
    out_dir = args.out_dir or output_dir_path(args.mode)
    if not os.path.isfile(input_csv):
        raise FileNotFoundError(
            f"Input CSV not found: {input_csv}\n"
            f"先に analyze_csv.py --mode {args.mode} を実行してください。")
    print(f"--- 入力: {input_csv}")
    print(f"--- 出力: {out_dir}/<手法>/")

    df = pd.read_csv(input_csv)
    for col in ("method", "auc"):
        if col not in df.columns:
            raise KeyError(f"{input_csv} に列 '{col}' がありません。"
                           " ./script/sbatch_reanalyze.sh で解析をやり直してください。")

    saved = []
    keys = df[["bandwidth", "distance", "pan"]].drop_duplicates().itertuples(index=False)
    for band_pair, distance, pan in sorted(keys):
        for method in A.DETECTION_METHODS:
            sub = df[(df["bandwidth"] == band_pair) & (df["distance"] == distance)
                     & (df["pan"] == pan) & (df["method"] == method)]
            if sub.empty:
                continue
            fname = f"heatmap_{band_pair}_{distance}_{pan}.pdf"
            saved.append(make_heatmap(sub, os.path.join(out_dir, method, fname)))

    print(f"--- {len(saved)} 枚 ({len(A.DETECTION_METHODS)} 手法) ---")


if __name__ == "__main__":
    main()
