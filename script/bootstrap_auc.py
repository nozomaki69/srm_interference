#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AUC のブートストラップ 95% 信頼区間を、3手法それぞれについて出す。

Seed ごとのスコア (analyze_csv.py が書く detection_scores{,_simultaneous}.csv) を、
条件ごとに干渉あり / なしの群の中で復元抽出し直して AUC を計算する。これを
既定 1000 回繰り返し、2.5% 点と 97.5% 点を 95% 信頼区間とする (パーセンタイル法)。

点推定は全 Seed から出した今の AUC のまま。ブートストラップは区間にだけ使う。
シミュレーションも再解析も要らない (スコアCSVだけで完結する)。

save ブランチの同名スクリプトを、手法の列 (method) を持つこのブランチの
スコアCSVに合わせたもの。スコアCSVがまだ無いモード (計算機で再解析する前の
sequential など) は飛ばす。

出力: plots/auc_bootstrap{,_simultaneous}.csv
設計は docs/bootstrap.md と docs/save_features.md を参照。
"""

import os
import sys
import csv
import argparse
from collections import defaultdict

import numpy as np
import scipy.stats as stats

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import analyze_csv as A  # noqa: E402

MODES = A.MEASUREMENT_MODES
GROUP_KEYS = ("bandwidth", "distance", "pan1_offload", "pan2_offload", "pan", "method")
FIELDS = list(GROUP_KEYS) + ["auc", "auc_boot_mean", "auc_ci_low", "auc_ci_high", "n_boot"]

CI_LEVEL = 0.95


def suffix(mode):
    """mode -> ファイル名の接尾辞。analyze_csv.mode_suffix() が定義元。"""
    return A.mode_suffix(mode)


def scores_path(mode):
    return os.path.join(A.PLOT_BASE_DIR, f"detection_scores{suffix(mode)}.csv")


def output_path(mode):
    return os.path.join(A.PLOT_BASE_DIR, f"auc_bootstrap{suffix(mode)}.csv")


def load_scores(path):
    """{group_key: {"interf": np.array, "no_interf": np.array}} を返す。

    Seed 番号順に並べる (復元抽出の結果を乱数のシードだけで再現できるように)。
    """
    raw = defaultdict(lambda: {"interf": [], "no_interf": []})
    with open(path, "r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            key = tuple(r[k] for k in GROUP_KEYS)
            raw[key][r["klass"]].append((int(r["seed"]), float(r["score"])))
    groups = {}
    for key, g in raw.items():
        groups[key] = {k: np.array([s for _, s in sorted(v)], dtype=float)
                       for k, v in g.items()}
    return groups


def batch_auc(pos, neg):
    """行ごとの AUC。pos: (B, n_pos)、neg: (B, n_neg)。

    analyze_csv._rank_auc() を行列にしたもの (Mann-Whitney U / (n_pos * n_neg)、
    同順位は midrank)。1000 回分をまとめて計算するために分けてある。
    """
    n_pos, n_neg = pos.shape[1], neg.shape[1]
    ranks = stats.rankdata(np.concatenate([pos, neg], axis=1), axis=1)
    return (ranks[:, :n_pos].sum(axis=1) - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def bootstrap_group(interf, no_interf, n_boot, rng):
    """1条件分。(元の AUC, ブートストラップ AUC の配列) を返す。

    干渉あり / なしをそれぞれの群の中で復元抽出する (層別。群の大きさは保つ)。
    """
    auc = A._rank_auc(interf, no_interf)
    # 行列版が元の定義と同じ値を返すことを、元データで毎回確かめる
    check = batch_auc(interf[None, :], no_interf[None, :])[0]
    if not np.isclose(check, auc, rtol=0, atol=1e-12):
        raise AssertionError(f"batch_auc と _rank_auc が一致しません: {check} vs {auc}")

    idx_pos = rng.integers(0, len(interf), size=(n_boot, len(interf)))
    idx_neg = rng.integers(0, len(no_interf), size=(n_boot, len(no_interf)))
    return auc, batch_auc(interf[idx_pos], no_interf[idx_neg])


def run_mode(mode, n_boot, seed):
    path = scores_path(mode)
    if not os.path.isfile(path):
        print(f"--- {mode}: {os.path.basename(path)} が無いので飛ばします "
              f"(analyze_csv.py --mode {mode} で作られます) ---")
        return None
    groups = load_scores(path)

    # 結果CSVの AUC (4桁に丸めてある) と突き合わせる
    results_path = os.path.join(A.PLOT_BASE_DIR,
                                f"interference_detection_results{suffix(mode)}.csv")
    ref = {}
    if os.path.isfile(results_path):
        with open(results_path, "r", encoding="utf-8", newline="") as f:
            ref = {tuple(r[k] for k in GROUP_KEYS): float(r["auc"])
                   for r in csv.DictReader(f)}

    rng = np.random.default_rng(seed)
    lo_q, hi_q = 100 * (1 - CI_LEVEL) / 2, 100 * (1 + CI_LEVEL) / 2
    rows, n_mismatch, n_outside = [], 0, 0
    # 並び順を固定してから乱数を消費する (順番が変わると結果が変わるため)
    for key in sorted(groups):
        g = groups[key]
        if len(g["interf"]) == 0 or len(g["no_interf"]) == 0:
            print(f"    Warning: {key} は片方の群が空なので飛ばします")
            continue
        auc, boot = bootstrap_group(g["interf"], g["no_interf"], n_boot, rng)
        lo, hi = np.percentile(boot, [lo_q, hi_q])
        if key in ref and abs(round(auc, 4) - ref[key]) > 1e-9:
            n_mismatch += 1
        if not (lo <= auc <= hi):
            n_outside += 1
        rows.append(dict(zip(GROUP_KEYS, key),
                         auc=f"{auc:.4f}", auc_boot_mean=f"{boot.mean():.4f}",
                         auc_ci_low=f"{lo:.4f}", auc_ci_high=f"{hi:.4f}",
                         n_boot=n_boot))

    out = output_path(mode)
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    widths = [float(r["auc_ci_high"]) - float(r["auc_ci_low"]) for r in rows]
    print(f"--- {mode}: {len(rows)} 行 (条件 x 手法) -> {out} ---")
    if ref:
        print(f"    結果CSVの AUC との不一致: {n_mismatch} 件")
    else:
        print(f"    (突き合わせ用の {results_path} が無いので照合は省略)")
    print(f"    95% 区間の幅: 中央値 {np.median(widths):.4f}, 最大 {max(widths):.4f}")
    if n_outside:
        print(f"    注意: 点推定が区間の外に出た条件が {n_outside} 件 "
              "(パーセンタイル法で分布が偏っているとき起こる)")
    if n_mismatch:
        raise SystemExit("エラー: スコアCSVから再計算した AUC が結果CSVと一致しません。"
                         "スコアCSVと結果CSVが別の解析から来ている可能性があります。")
    return out


def main():
    p = argparse.ArgumentParser(
        description="Seed 別スコアから AUC のブートストラップ 95% 信頼区間を出す")
    p.add_argument("--n-boot", type=int, default=1000, help="ブートストラップの回数")
    p.add_argument("--seed", type=int, default=0, help="乱数のシード (再現性のため固定)")
    p.add_argument("--mode", choices=MODES + ("both",), default="both")
    args = p.parse_args()

    modes = MODES if args.mode == "both" else (args.mode,)
    print(f"--- ブートストラップ {args.n_boot} 回, 乱数シード {args.seed}, "
          f"{int(CI_LEVEL * 100)}% 区間 (パーセンタイル法) ---")
    for mode in modes:
        run_mode(mode, args.n_boot, args.seed)


if __name__ == "__main__":
    main()
