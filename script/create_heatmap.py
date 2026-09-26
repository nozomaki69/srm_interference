import os
import sys
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

INPUT_CSV = os.path.join(PLOT_BASE_DIR, "interference_detection_results.csv")
OUTPUT_DIR = os.path.join(PLOT_BASE_DIR, "heatmaps")

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
            f"Please place interference_detection_results.csv in {PLOT_BASE_DIR}"
        )
    df = pd.read_csv(path)
    df = df.rename(columns=COLUMN_RENAME)
    return df

def f1_floor(n_pos, n_neg):
    """F1 の構造的な下限。

    しきい値を 0 まで下げると全 seed が陽性になるので、precision = n_pos/(n_pos+n_neg)、
    recall = 1 となり、F1 = 2*n_pos / (2*n_pos + n_neg) になる。
    n_pos = n_neg = 100 なら 0.667。これは「検知できた」のではなく
    **全部を干渉ありと答えた縮退解**なので、この値のセルは検知失敗として扱う。

    以前はカラーバーの下限を 0.5 にしていたため、この 0.667 が色付きの中間値として
    描かれ、性能を過大に見せていた。
    """
    if n_pos <= 0 or n_neg <= 0:
        return 0.0
    return 2.0 * n_pos / (2.0 * n_pos + n_neg)


def make_heatmap(df: pd.DataFrame, band_pair: str, distance, subject: str, out_dir: str, max_load: int = MAX_LOAD):
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

    f1_pivot = sub.pivot(index="pan1_load", columns="pan2_load", values="f1")
    th_pivot = sub.pivot(index="pan1_load", columns="pan2_load", values="threshold")

    rows = sorted(set(LOAD_RANGE) | set(f1_pivot.index))
    cols = sorted(set(LOAD_RANGE) | set(f1_pivot.columns))
    f1_pivot = f1_pivot.reindex(index=rows, columns=cols)
    th_pivot = th_pivot.reindex(index=rows, columns=cols)

    # Increased cell sizes to ensure text visibility
    fig_w = 1.0 * len(cols)
    fig_h = 0.9 * len(rows)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    # カラーバーの下限は F1 の構造的な下限に合わせる。データから決めるので、
    # seed 数を変えても追随する。
    floor = f1_floor(sub["n_pos"].max(), sub["n_neg"].max())

    # 下限に張り付いたセル (= 検知失敗) は色を付けず灰色で潰す。
    # 数値としては 0.667 でも中身は「全部陽性」なので、色の濃淡で他と比べさせない。
    #
    # 比較は「丸めた下限」に対して行う。analyze_csv.py が F1 を小数3桁に丸めて
    # 出力している (0.6667 -> 0.667) ため、生の下限と比べると 0.0003 だけ上回って
    # 判定から漏れる。
    values = np.ma.masked_less_equal(f1_pivot.values.astype(float), round(floor, 3))
    cmap = plt.get_cmap("YlGnBu").copy()
    cmap.set_bad(color="0.75")

    im = ax.imshow(values, cmap=cmap, vmin=floor, vmax=1, aspect="auto")

    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(cols)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(rows)
    ax.invert_yaxis() 
    
    # Removed X-axis, Y-axis, and top titles as requested

    for i, load1 in enumerate(rows):
        for j, load2 in enumerate(cols):
            f1_val = f1_pivot.iloc[i, j]
            th_val = th_pivot.iloc[i, j]
            if pd.isna(f1_val):
                continue
            # カラーバーが floor..1 になったので、文字色の判定も相対位置で決める。
            # 灰色で潰したセル (下限張り付き) は黒文字にする。
            text_color = "white" if f1_val > floor + 0.6 * (1.0 - floor) else "black"
            # Removed Japanese, changed to "Th=" to save space, increased font size
            ax.text(
                j, i, f"Tau: {th_val:.2f}\nF1: {f1_val:.2f}",
                ha="center", va="center", color=text_color, fontsize=9, fontweight="bold"
            )

    cbar = fig.colorbar(im, ax=ax)
    # Removed cbar label

    fig.tight_layout()
    os.makedirs(out_dir, exist_ok=True)
    safe_band = str(band_pair).replace("/", "-")
    
    # Changed file extension to .pdf
    fname = f"heatmap_{safe_band}_{distance}_{subject}.pdf"
    fpath = os.path.join(out_dir, fname)
    
    # Saved as PDF format
    fig.savefig(fpath, format="pdf", bbox_inches="tight")
    plt.close(fig)
    return fpath

def main():
    df = load_data(INPUT_CSV)

    combos = df[["band_pair", "distance"]].drop_duplicates()
    subjects = sorted(df["subject"].unique())

    saved = []
    for _, row in combos.iterrows():
        for subject in subjects:
            path = make_heatmap(df, row["band_pair"], row["distance"], subject, OUTPUT_DIR)
            if path:
                saved.append(path)

    print(f"Created {len(saved)} heatmaps:")
    for p in saved:
        print(" -", p)

if __name__ == "__main__":
    main()