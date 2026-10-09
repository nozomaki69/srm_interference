import os
import sys
import argparse
import pandas as pd
import numpy as np
import matplotlib
import matplotlib.pyplot as plt

# ============ Settings ============
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, SCRIPT_DIR)

# 負荷グリッドはスイープを定義している側 (interference_2pan_config) を唯一の定義元とする。
# ここに直値を書くと、スイープの範囲を変えたときにヒートマップ側だけ取り残され、
# 範囲外のセルが黙って捨てられる (以前 LOAD_RANGE / max_load が 10..100 固定のまま
# 残っており、負荷100%超を追加しても描画されないバグがあった)。
from interference_2pan_config import OFFERED_LOAD_PERCENTS  # noqa: E402
# 目盛りの体裁は折れ線・ROC と共有する (plot_detection_lines が定義元)
from plot_detection_lines import TICK_LABELSIZE, TICK_LENGTH, TICK_WIDTH  # noqa: E402
# 結果ファイル(interference_detection_results.csv)・出力先(heatmaps/)は
# いずれも scripts/ の1つ上の plots/ 以下にある(analyze_csv.py の PLOT_BASE_DIR と同じ場所)
PLOT_BASE_DIR = os.path.join(SCRIPT_DIR, "..", "plots")

# 測定モードごとに入出力を分ける。analyze_csv.py の --mode と同じ規約:
#   sequential   : 各メトリックを自分の200s窓で順に測る (接尾辞なし)
#   simultaneous : 全メトリックを W0 の200sで同時に測る参照 (接尾辞 _simultaneous)
# 統計量は ΔPER のビン内分散ひとつ (analyze_csv.py の出力) だけ。
def input_csv_path(suffix):
    return os.path.join(PLOT_BASE_DIR,
                        f"interference_detection_results{suffix}.csv")


# 指標ごとの仕様。色の範囲は両方 0.5-1.0 で揃えてあるので、F1 版と AUC 版を
# 並べて同じ濃さ = 同じ値として読める。
#
#   f1  : 最良閾値 tau での性能。その tau もセルに出す
#   auc : 閾値に依らない分離度。**AUC に閾値という概念が無いので tau は出さない**。
#         刻みが 1e-4 (100x100 ペア) なので F1 より1桁多い3桁で出す
# cell_w はセル1つの幅(インチ)、fontsize はセル内の文字の大きさ。
# "AUC=0.503" は F1 の "F1: 0.95" より横に長いぶん広く取る。
# セルの高さ (CELL_H) より幅をかなり大きく取って横長にしてある。
METRIC_SPEC = {
    "f1":  {"column": "f1",  "dir": "heatmaps",     "decimals": 2,
            "show_threshold": True,  "label": "F1",
            "cell_w": 2.30, "fontsize": 17},
    "auc": {"column": "auc", "dir": "heatmaps_auc", "decimals": 3,
            "show_threshold": False, "label": "AUC",
            "cell_w": 2.55, "fontsize": 17},
}
VMIN, VMAX = 0.5, 1.0


def output_dir_path(suffix, metric):
    return os.path.join(PLOT_BASE_DIR, f"{METRIC_SPEC[metric]['dir']}{suffix}")

LOAD_RANGE = list(OFFERED_LOAD_PERCENTS)
MAX_LOAD = max(LOAD_RANGE)

COLUMN_RENAME = {
    "bandwidth": "band_pair",
    "pan1_offload": "pan1_load",
    "pan2_offload": "pan2_load",
    "pan": "subject",
    "best_threshold": "threshold",
    "TP": "tp",
    "FP": "fp",
    "FN": "fn",
    "TN": "tn",
    "n_interf_seeds": "n_pos",
    "n_no_interf_seeds": "n_neg",
}

def load_data(path: str) -> pd.DataFrame:
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Input CSV not found: {path}\n"
            f"先に analyze_csv.py を同じモードで実行してください "
            f"(例: python3 script/analyze_csv.py --mode simultaneous)"
        )
    df = pd.read_csv(path)
    df = df.rename(columns=COLUMN_RENAME)
    return df

def make_heatmap(df: pd.DataFrame, band_pair: str, distance, subject: str, out_dir: str,
                 metric: str = "f1", max_load: int = MAX_LOAD):
    spec = METRIC_SPEC[metric]
    sub = df[
        (df["band_pair"] == band_pair)
        & (df["distance"] == distance)
        & (df["subject"] == subject)
        & (df["pan1_load"] <= max_load)
        & (df["pan2_load"] <= max_load)
    ]
    if sub.empty:
        return None

    sub = sub.drop_duplicates(subset=["pan1_load", "pan2_load"], keep="last")

    # 縦が自PAN1負荷、横がPAN2負荷。create_heatmap は pan1/pan2 をそのまま軸にする
    # (自分/相手への読み替えは折れ線側 plot_detection_lines.own_other() が行う)。
    val_pivot = sub.pivot(index="pan1_load", columns="pan2_load", values=spec["column"])
    th_pivot = (sub.pivot(index="pan1_load", columns="pan2_load", values="threshold")
                if spec["show_threshold"] else None)

    rows = sorted(set(LOAD_RANGE) | set(val_pivot.index))
    cols = sorted(set(LOAD_RANGE) | set(val_pivot.columns))
    val_pivot = val_pivot.reindex(index=rows, columns=cols)
    if th_pivot is not None:
        th_pivot = th_pivot.reindex(index=rows, columns=cols)

    # セル1つの高さ(インチ)。幅 (cell_w) をこれより大きく取ることで横長にする。
    CELL_H = 1.15
    fig_w = spec["cell_w"] * len(cols)
    fig_h = CELL_H * len(rows)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    im = ax.imshow(val_pivot.values, cmap="YlGnBu", vmin=VMIN, vmax=VMAX, aspect="auto")

    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(cols)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(rows)
    ax.invert_yaxis()
    # 目盛りは折れ線・ROC と同じ大きさに揃える (軸ラベルとタイトルは入れない)
    ax.tick_params(axis="both", which="major", labelsize=TICK_LABELSIZE,
                   length=TICK_LENGTH, width=TICK_WIDTH)

    # 白文字に切り替える閾値。YlGnBu 上で白文字と黒文字の WCAG コントラストを
    # 計算すると、入れ替わるのは値 0.838 (正規化 0.676) のところ。
    #   値 0.80 -> 白 3.30:1 / 黒 6.36:1   黒のほうが読める
    #   値 0.85 -> 白 5.14:1 / 黒 4.09:1   白のほうが読める
    # 以前は 0.80 を境にしていたため、0.80〜0.84 の帯が「白文字だが黒のほうが
    # 読みやすい」状態になっていた。切り替えを実際の交点に合わせる。
    WHITE_TEXT_FROM = 0.84

    for i, _ in enumerate(rows):
        for j, _ in enumerate(cols):
            val = val_pivot.iloc[i, j]
            if pd.isna(val):
                continue
            text_color = "white" if val > WHITE_TEXT_FROM else "black"
            if spec["show_threshold"]:
                text = f"Tau: {th_pivot.iloc[i, j]:.2f}\n{spec['label']}: {val:.{spec['decimals']}f}"
            else:
                text = f"{spec['label']}={val:.{spec['decimals']}f}"
            ax.text(j, i, text, ha="center", va="center",
                    color=text_color, fontsize=spec["fontsize"], fontweight="bold")

    cbar = fig.colorbar(im, ax=ax)
    cbar.ax.tick_params(labelsize=TICK_LABELSIZE, length=TICK_LENGTH,
                        width=TICK_WIDTH)

    fig.tight_layout()
    os.makedirs(out_dir, exist_ok=True)
    safe_band = str(band_pair).replace("/", "-")
    fname = f"heatmap_{safe_band}_{distance}_{subject}.pdf"
    fpath = os.path.join(out_dir, fname)
    fig.savefig(fpath, format="pdf", bbox_inches="tight")
    plt.close(fig)
    return fpath


def main():
    parser = argparse.ArgumentParser(
        description="干渉検知結果のヒートマップ。測定モードで入出力を切り替える。")
    parser.add_argument(
        "--mode", choices=("sequential", "simultaneous"), default="sequential",
        help="sequential: 時間分割測定の結果(既定) / "
             "simultaneous: W0で同時測定した参照の結果")
    parser.add_argument(
        "--metric", choices=tuple(METRIC_SPEC), default="f1",
        help="f1: 最良閾値での F1 と tau (既定) / auc: 閾値に依らない AUC")
    parser.add_argument(
        "--input", default=None,
        help="入力 CSV を直接指定する (--mode より優先)")
    parser.add_argument(
        "--out-dir", default=None,
        help="出力ディレクトリを直接指定する (--mode / --metric より優先)")
    args = parser.parse_args()
    suffix = "" if args.mode == "sequential" else "_simultaneous"

    input_csv = args.input or input_csv_path(suffix)
    out_dir = args.out_dir or output_dir_path(suffix, args.metric)
    print(f"--- 入力: {input_csv}")
    print(f"--- 出力: {out_dir}/")

    df = load_data(input_csv)
    column = METRIC_SPEC[args.metric]["column"]
    if column not in df.columns:
        raise KeyError(
            f"{input_csv} に列 '{column}' がありません。\n"
            f"  利用できる列: {', '.join(df.columns)}\n"
            f"  CSV が古い場合は ./script/sbatch_reanalyze.sh で解析をやり直してください。")

    combos = df[["band_pair", "distance"]].drop_duplicates()
    subjects = sorted(df["subject"].unique())

    saved = []
    for _, row in combos.iterrows():
        for subject in subjects:
            path = make_heatmap(df, row["band_pair"], row["distance"], subject,
                                out_dir, metric=args.metric)
            if path:
                saved.append(path)

    print(f"Created {len(saved)} heatmaps:")
    for p in saved:
        print(" -", p)

if __name__ == "__main__":
    main()