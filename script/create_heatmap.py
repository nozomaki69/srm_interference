import os
import pandas as pd
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from matplotlib import font_manager

# ============ 設定 ============
INPUT_CSV = "data.csv"      # 入力CSVのパス
OUTPUT_DIR = "heatmaps"     # 出力先ディレクトリ

# PAN1負荷・PAN2負荷として想定するレンジ(10刻み)。
# データがこの一部しか無くても、枠として全体を描画し、無い部分は空欄にする。
LOAD_RANGE = list(range(10, 101, 10))

COLUMNS = [
    "band_pair", "distance", "pan1_load", "pan2_load", "subject",
    "threshold", "tp", "fp", "fn", "tn",
    "precision", "recall", "fpr", "f1",
    "n_pos", "n_neg",
]

# 日本語フォント(環境にNoto Sans CJK JPがあれば使う。無ければ既定フォントのまま)
_jp_font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
if os.path.exists(_jp_font_path):
    font_manager.fontManager.addfont(_jp_font_path)
    matplotlib.rcParams["font.family"] = "Noto Sans CJK JP"
matplotlib.rcParams["axes.unicode_minus"] = False


def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, header=None, names=COLUMNS)
    return df


def make_heatmap(df: pd.DataFrame, band_pair: str, distance, subject: str, out_dir: str):
    sub = df[
        (df["band_pair"] == band_pair)
        & (df["distance"] == distance)
        & (df["subject"] == subject)
    ]
    if sub.empty:
        return None

    # 同じ(PAN1負荷, PAN2負荷)の組が複数行あった場合は最後の行を採用
    sub = sub.drop_duplicates(subset=["pan1_load", "pan2_load"], keep="last")

    f1_pivot = sub.pivot(index="pan1_load", columns="pan2_load", values="f1")
    th_pivot = sub.pivot(index="pan1_load", columns="pan2_load", values="threshold")

    # データに実在する負荷値も取りこぼさないよう、想定レンジと実データ値の和集合にする
    rows = sorted(set(LOAD_RANGE) | set(f1_pivot.index))
    cols = sorted(set(LOAD_RANGE) | set(f1_pivot.columns))
    f1_pivot = f1_pivot.reindex(index=rows, columns=cols)
    th_pivot = th_pivot.reindex(index=rows, columns=cols)

    fig_w = 1.2 + 0.9 * len(cols)
    fig_h = 1.0 + 0.8 * len(rows)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    im = ax.imshow(f1_pivot.values, cmap="YlGnBu", vmin=0, vmax=1, aspect="auto")

    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(cols)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(rows)
    ax.set_xlabel("PAN2 負荷 (%)")
    ax.set_ylabel("PAN1 負荷 (%)")
    ax.set_title(f"帯域幅: {band_pair} / 距離: {distance} / 測定PAN: {subject}")

    for i, load1 in enumerate(rows):
        for j, load2 in enumerate(cols):
            f1_val = f1_pivot.iloc[i, j]
            th_val = th_pivot.iloc[i, j]
            if pd.isna(f1_val):
                continue
            text_color = "white" if f1_val > 0.6 else "black"
            ax.text(
                j, i, f"閾値={th_val:.2f}\nF1={f1_val:.3f}",
                ha="center", va="center", color=text_color, fontsize=8,
            )

    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("F1 スコア")

    fig.tight_layout()
    os.makedirs(out_dir, exist_ok=True)
    safe_band = str(band_pair).replace("/", "-")
    fname = f"heatmap_{safe_band}_{distance}_{subject}.png"
    fpath = os.path.join(out_dir, fname)
    fig.savefig(fpath, dpi=150)
    plt.close(fig)
    return fpath


def main():
    df = load_data(INPUT_CSV)

    combos = df[["band_pair", "distance"]].drop_duplicates()
    subjects = sorted(df["subject"].unique())  # 例: ["PAN1", "PAN2"]

    saved = []
    for _, row in combos.iterrows():
        for subject in subjects:
            path = make_heatmap(df, row["band_pair"], row["distance"], subject, OUTPUT_DIR)
            if path:
                saved.append(path)

    print(f"{len(saved)} 枚のヒートマップを作成しました:")
    for p in saved:
        print(" -", p)


if __name__ == "__main__":
    main()
