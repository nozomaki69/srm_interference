import os
import pandas as pd
import numpy as np
import matplotlib
import matplotlib.pyplot as plt

# ============ Settings ============
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 結果ファイル(interference_detection_results.csv)・出力先(heatmaps/)は
# いずれも scripts/ の1つ上の plots/ 以下にある(analyze_csv.py の PLOT_BASE_DIR と同じ場所)
PLOT_BASE_DIR = os.path.join(SCRIPT_DIR, "..", "plots")

INPUT_CSV = os.path.join(PLOT_BASE_DIR, "interference_detection_results.csv")
OUTPUT_DIR = os.path.join(PLOT_BASE_DIR, "heatmaps")

LOAD_RANGE = list(range(10, 101, 10))

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

def make_heatmap(df: pd.DataFrame, band_pair: str, distance, subject: str, out_dir: str):
    sub = df[
        (df["band_pair"] == band_pair)
        & (df["distance"] == distance)
        & (df["subject"] == subject)
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

    im = ax.imshow(f1_pivot.values, cmap="YlGnBu", vmin=0.5, vmax=1, aspect="auto")

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
            text_color = "white" if f1_val >= 0.8 else "black"
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
