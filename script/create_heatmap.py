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
# 結果ファイル(interference_detection_results.csv)・出力先(heatmaps/)は
# いずれも scripts/ の1つ上の plots/ 以下にある(analyze_csv.py の PLOT_BASE_DIR と同じ場所)
PLOT_BASE_DIR = os.path.join(SCRIPT_DIR, "..", "plots")

# 測定モードごとに入出力を分ける。analyze_csv.py の --mode と同じ規約:
#   td   : 各メトリックを自分の200s窓で測る時間分割測定 (接尾辞なし)
#   conv : 全メトリックを W0 の200sで同時に測る従来方式 (接尾辞 _conv)
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
# cell_w はセル1つの幅(インチ)。"AUC=0.503" は F1 の "F1: 0.95" より横に長く、
# 既定の 1.0 では隣のセルの文字とぶつかるので広げる。
METRIC_SPEC = {
    "f1":  {"column": "f1",  "dir": "heatmaps",     "decimals": 2,
            "show_threshold": True,  "label": "F1",
            "cell_w": 1.0, "fontsize": 9},
    "auc": {"column": "auc", "dir": "heatmaps_auc", "decimals": 3,
            "show_threshold": False, "label": "AUC",
            "cell_w": 1.35, "fontsize": 8},
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
            f"(例: python3 script/analyze_csv.py --mode conv)"
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

    # Increased cell sizes to ensure text visibility
    fig_w = spec["cell_w"] * len(cols)
    fig_h = 0.9 * len(rows)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    im = ax.imshow(val_pivot.values, cmap="YlGnBu", vmin=VMIN, vmax=VMAX, aspect="auto")

    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(cols)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(rows)
    ax.invert_yaxis()

    # 白文字に切り替える閾値。YlGnBu は正規化 0.6 あたりでようやく濃い青緑になるので、
    # そこを境にする。以前は値 0.6 (正規化 0.2 = まだ薄い黄緑) で白にしており、
    # 文字が背景に埋もれていた。
    white_text_from = VMIN + 0.6 * (VMAX - VMIN)

    for i, _ in enumerate(rows):
        for j, _ in enumerate(cols):
            val = val_pivot.iloc[i, j]
            if pd.isna(val):
                continue
            text_color = "white" if val > white_text_from else "black"
            if spec["show_threshold"]:
                text = f"Tau: {th_pivot.iloc[i, j]:.2f}\n{spec['label']}: {val:.{spec['decimals']}f}"
            else:
                text = f"{spec['label']}={val:.{spec['decimals']}f}"
            ax.text(j, i, text, ha="center", va="center",
                    color=text_color, fontsize=spec["fontsize"], fontweight="bold")

    fig.colorbar(im, ax=ax)

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
        "--mode", choices=("td", "conv"), default="td",
        help="td: 時間分割測定の結果(既定) / conv: 従来方式(W0で同時測定)の結果")
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
    suffix = "" if args.mode == "td" else "_conv"

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