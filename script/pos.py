#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ノード配置図を、帯域パターンごとに1枚ずつ描く (Seed は1つ)。

スイープの .pos はバッチ完了時に消えるので手元に残らない。そこで
interference_2pan_config.generate_batch() をそのまま呼んで一時ディレクトリに .pos を
作り、それを読む。座標の生成規則を2箇所に書くと静かにずれるため。

  自PAN = PAN1 (青)、隣接PAN = PAN2 (赤)
  コーディネータ = 四角、端末 = 丸、円 = 各PANの通信範囲

出力: plots/position_plots/{interf|no_interf}_ch{PAN1}vs{PAN2}_seed{seed}.pdf
設計は docs/README.md の「ノード配置図」節を参照。
"""

import os
import sys
import argparse
import tempfile
import contextlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle  # noqa: E402

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import interference_2pan_config as C  # noqa: E402

DEFAULT_OUT_DIR = os.path.join(SCRIPT_DIR, "..", "plots", "position_plots")

# 座標は負荷に依存しないので、実在する負荷の組を1つだけ生成する
LOAD_PERCENT = C.OFFERED_LOAD_PERCENTS[0]

OWN_COLOR = "blue"
NEIGHBOR_COLOR = "red"


def range_km(ch):
    """生成側と同じく 0.1 km に丸めた通信範囲 [km]"""
    return int(round(C.MAXIMUM_COMMUNICATION_RANGE[ch], 1) * 1000) / 1000.0


def generate_pos(pattern, seed, work_dir):
    """generate_batch() で .pos を1つ作り、そのパスを返す。"""
    C.OUTPUT_DIR = work_dir
    # generate_batch() はファイル名を1行ずつ print するので黙らせる
    with open(os.devnull, "w") as devnull, contextlib.redirect_stdout(devnull):
        C.generate_batch([(pattern, LOAD_PERCENT, LOAD_PERCENT, seed)])
    suffix = (f"_channel_{pattern[0]}_vs_{pattern[1]}"
              f"_pan1_{LOAD_PERCENT}_pan2_{LOAD_PERCENT}_seed{seed}.pos")
    hits = [f for f in os.listdir(work_dir) if f.endswith(suffix)]
    if len(hits) != 1:
        raise RuntimeError(f".pos が1つに定まりません: {hits}")
    return os.path.join(work_dir, hits[0])


def parse_pos_file(filepath):
    """時刻 0 の座標を {node_id: (x_km, y_km)} で返す。"""
    positions = {}
    with open(filepath, "r") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 4 and parts[1] == "0":
                positions[int(parts[0])] = (float(parts[2]) / 1000.0,
                                            float(parts[3]) / 1000.0)
    return positions


def plot_positions(positions, pattern, seed, interf_label, out_dir):
    pan1_ch, pan2_ch = pattern
    fig, ax = plt.subplots(figsize=(10, 10))

    own_dev = [positions[i] for i in C.DEVICE_ID_1 if i in positions]
    nb_dev = [positions[i] for i in C.DEVICE_ID_2 if i in positions]

    ax.add_patch(Circle(positions[1], range_km(pan1_ch), color=OWN_COLOR,
                        alpha=0.05, fill=True))
    ax.add_patch(Circle(positions[2], range_km(pan2_ch), color=NEIGHBOR_COLOR,
                        alpha=0.05, fill=True))

    ax.plot(*positions[1], "s", color=OWN_COLOR, markersize=12,
            label="Own-PAN Coordinator", linestyle="")
    ax.plot(*positions[2], "s", color=NEIGHBOR_COLOR, markersize=12,
            label="Neighboring-PAN Coordinator", linestyle="")
    ax.plot([p[0] for p in own_dev], [p[1] for p in own_dev], "o", color=OWN_COLOR,
            markersize=8, alpha=0.5, label="Own-PAN end device", linestyle="")
    ax.plot([p[0] for p in nb_dev], [p[1] for p in nb_dev], "o", color=NEIGHBOR_COLOR,
            markersize=8, alpha=0.5, label="Neighboring-PAN end device", linestyle="")

    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("x [km]", fontsize=25)
    ax.set_ylabel("y [km]", fontsize=25)
    ax.tick_params(axis="both", labelsize=25, width=3.0, which="major", length=20)
    ax.set_xlim(-2, 3.5)
    ax.set_ylim(-1.5, 1.5)
    # 凡例は枠の外 (上) に出す。枠内だと端末に重なって隠れるため
    leg = ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=2, fontsize=16)
    leg.get_frame().set_linewidth(1.8)
    fig.tight_layout()

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{interf_label}_ch{pan1_ch}vs{pan2_ch}_seed{seed}.pdf")
    fig.savefig(path, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    return path


def main():
    p = argparse.ArgumentParser(description="帯域パターンごとのノード配置図 (Seed 1つ)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    args = p.parse_args()

    written = []
    with tempfile.TemporaryDirectory() as work_dir:
        for pattern in C.TARGET_BANDWIDTH_PATTERNS:
            pos_file = generate_pos(pattern, args.seed, work_dir)
            interf_label = ("no_interf" if os.path.basename(pos_file).startswith("no_interf")
                            else "interf")
            positions = parse_pos_file(pos_file)
            written.append(plot_positions(positions, pattern, args.seed, interf_label,
                                          args.out_dir))

    print(f"--- {os.path.normpath(args.out_dir)} に {len(written)} ファイル出力 ---")
    for w in written:
        print(f"    {os.path.basename(w)}")


if __name__ == "__main__":
    main()
