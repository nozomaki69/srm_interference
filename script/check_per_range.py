#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""クリップ前の生 PER が値域 [0, 1] を外れる件数を Seed 別に数える。

決めたいのは一つだけ: 範囲外が特定の Seed に集中しているのか、全 Seed に均等に
散っているのか。前者なら外れ Seed を除外すれば済み、後者は PER の定義に由来する
構造的な問題で除外では直らない。設計と判断基準は docs/per_range_check.md を参照。

PER > 1 は n_rx >= 0 から構造的に起こり得ない。それでも数えるのは、1 件でも出たら
それは PER ではなく CSV の列ずれやカウンタ破損を意味するからで、PER の議論より先に
潰すべき別の問題として検出したい。

原因の切り分け (負荷別・RSSIビン別・方向別・分母に macCsmaFailCount を足した場合) は
diagnose_per_clip.py が担当する。こちらは Seed 軸だけを見る。

simulation_results.csv を1回読むだけ。再解析も再シミュレーションも不要。
"""

import os
import sys
import csv
import math
import argparse

import numpy as np
import scipy.stats as stats

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# 列名・デバイス番号・CSV パスは analyze_csv と共有する (二重定義しない)
import analyze_csv as A  # noqa: E402

COUNTERS4 = ("macTxSuccessCount", "macRetryCount",
             "macMultipleRetryCount", "macTxFailCount")

# 集計器のレイアウト。Seed x モードの数だけ作るので dict ではなく list で持つ。
N_OBS, N_NEG, N_GT1, N_INVALID, N_ZERO_DENOM, MIN_PER, MAX_PER = range(7)


def _new_acc():
    return [0, 0, 0, 0, 0, float("inf"), float("-inf")]


def build_plan(idx, modes):
    """(モード, [(n_rx の列番号, 4カウンタの列番号), ...]) を先に組み立てる。

    観測は 10^6 オーダーあるので、行ごとに f-string で列名を作って dict を引くと
    そこが支配的になる。列番号は行に依らないので最初に1回だけ解決しておく。
    """
    plan = []
    for mode in modes:
        sfx = "" if mode == "td" else "_conv"
        cols = []
        for pan, devs in (("PAN1", A.PAN1_DEVS), ("PAN2", A.PAN2_DEVS)):
            for dev in devs:
                # ul: デバイス -> コーディネータ / dl: コーディネータ -> デバイス。
                # 方向で分子の列名と分母の接頭辞が入れ替わる (docs/per_measurement.md §1)。
                for prefix, rx_col in (
                        (f"{pan}_Dev{dev}_to_Co_", f"{pan}_PC_Rx_from_Dev{dev}{sfx}"),
                        (f"{pan}_Co_to_Dev{dev}_", f"{pan}_Dev{dev}_Rx_from_PC{sfx}")):
                    cols.append((idx[rx_col],
                                 tuple(idx[prefix + n + sfx] for n in COUNTERS4)))
        plan.append((mode, cols))
    return plan


def scan(csv_file, modes):
    with open(csv_file, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {n: i for i, n in enumerate(header)}
        is_float = ["RSSI" in n for n in header]
        i_seed = idx["Seed"]

        plan = build_plan(idx, modes)
        accs = {}
        n_rows = 0

        for raw in reader:
            if len(raw) != len(header):
                raise ValueError(f"{csv_file}: 列数が一致しません "
                                 f"(header {len(header)} / row {len(raw)})")
            r = [float(x) if fl else int(float(x)) for x, fl in zip(raw, is_float)]
            n_rows += 1
            seed = r[i_seed]

            for mode, cols in plan:
                key = (mode, seed)
                a = accs.get(key)
                if a is None:
                    a = accs[key] = _new_acc()

                for i_rx, c4 in cols:
                    n_rx = r[i_rx]
                    denom = r[c4[0]] + r[c4[1]] + r[c4[2]] + r[c4[3]]

                    # 負の受信数・負の分母は PER の性質ではなくデータ破損。
                    if n_rx < 0 or denom < 0:
                        a[N_INVALID] += 1

                    if denom <= 0:
                        # _one_side_per() はここで無条件に 0.0 を返す
                        # (analyze_csv.py:374-375)。「完全送達」と区別がつかない。
                        a[N_ZERO_DENOM] += 1
                        continue

                    per = 1.0 - (n_rx / denom)
                    a[N_OBS] += 1
                    if per < 0.0:
                        a[N_NEG] += 1
                    elif per > 1.0:
                        a[N_GT1] += 1
                    if per < a[MIN_PER]:
                        a[MIN_PER] = per
                    if per > a[MAX_PER]:
                        a[MAX_PER] = per

    return accs, n_rows


def homogeneity(rows):
    """Seed x {負, 非負} の分割表に chi2 独立性検定をかける。

    観測数が 10^6 オーダーあるので p 値はわずかな差でも 0 に張り付く。判断に使うのは
    p ではなく効果量 (Cramer's V) と率の実寸のばらつき。docs/per_range_check.md §3。
    """
    table = [[a[N_NEG], a[N_OBS] - a[N_NEG]] for _, a in rows if a[N_OBS] > 0]
    total_neg = sum(t[0] for t in table)
    total_obs = sum(sum(t) for t in table)
    if len(table) < 2 or total_neg == 0 or total_neg == total_obs:
        return None
    chi2, p, dof, _ = stats.chi2_contingency(np.array(table))
    # 2列の分割表なので min(r-1, c-1) = 1。V = sqrt(chi2 / N)。
    return chi2, dof, p, math.sqrt(chi2 / total_obs)


def report_mode(mode, accs, out_rows):
    rows = sorted(((s, a) for (m, s), a in accs.items() if m == mode),
                  key=lambda x: x[0])
    if not rows:
        print(f"\n=== mode={mode}: 該当データなし ===")
        return

    print(f"\n=== Seed 別 PER 範囲外 (mode={mode}) ===")
    print(f"{'Seed':>6}{'判定数':>12}{'PER<0':>12}{'率':>9}"
          f"{'PER>1':>8}{'不正':>7}{'分母0':>8}{'最小PER':>11}{'最大PER':>10}")
    for seed, a in rows:
        n = a[N_OBS]
        rate = f"{100.0 * a[N_NEG] / n:7.2f}%" if n else "      -"
        lo = f"{a[MIN_PER]:11.4f}" if n else f"{'-':>11}"
        hi = f"{a[MAX_PER]:10.4f}" if n else f"{'-':>10}"
        print(f"{seed:>6}{n:>12}{a[N_NEG]:>12}{rate:>9}"
              f"{a[N_GT1]:>8}{a[N_INVALID]:>7}{a[N_ZERO_DENOM]:>8}{lo}{hi}")
        out_rows.append({
            "mode": mode, "seed": seed, "n_obs": n, "n_neg": a[N_NEG],
            "neg_rate": (a[N_NEG] / n) if n else "",
            "n_gt1": a[N_GT1], "n_invalid": a[N_INVALID],
            "n_zero_denom": a[N_ZERO_DENOM],
            "min_per": a[MIN_PER] if n else "",
            "max_per": a[MAX_PER] if n else "",
        })

    tot_obs = sum(a[N_OBS] for _, a in rows)
    tot_neg = sum(a[N_NEG] for _, a in rows)
    tot_gt1 = sum(a[N_GT1] for _, a in rows)
    tot_inv = sum(a[N_INVALID] for _, a in rows)
    tot_zd = sum(a[N_ZERO_DENOM] for _, a in rows)
    print(f"{'全体':>6}{tot_obs:>12}{tot_neg:>12}"
          f"{(f'{100.0 * tot_neg / tot_obs:7.2f}%' if tot_obs else '      -'):>9}"
          f"{tot_gt1:>8}{tot_inv:>7}{tot_zd:>8}")

    rates = np.array([a[N_NEG] / a[N_OBS] for _, a in rows if a[N_OBS] > 0])
    if rates.size == 0 or tot_obs == 0:
        return
    print(f"\n--- Seed 間ばらつき (mode={mode}, Seed {rates.size} 本) ---")
    print(f"  PER<0 率  平均 {rates.mean():.4%}  標準偏差 {rates.std(ddof=1):.4%}  "
          f"最小 {rates.min():.4%}  最大 {rates.max():.4%}")
    if rates.min() > 0:
        print(f"  最大/最小比 {rates.max() / rates.min():.3f}  (1.0 に近いほど均等)")

    # 二項分布の素のゆらぎだけで説明できる範囲か。Seed 依存の上乗せがあれば
    # 実測の標準偏差が期待値より数倍大きくなる。
    pbar = tot_neg / tot_obs
    n_mean = np.mean([a[N_OBS] for _, a in rows if a[N_OBS] > 0])
    exp_sd = math.sqrt(pbar * (1.0 - pbar) / n_mean) if n_mean > 0 else 0.0
    if exp_sd > 0:
        print(f"  二項ゆらぎから期待される標準偏差 {exp_sd:.4%}  "
              f"(実測/期待 = {rates.std(ddof=1) / exp_sd:.2f})")

    h = homogeneity(rows)
    if h is None:
        print("  chi2 均等性検定: 負が0件または全件のため実施せず")
    else:
        chi2, dof, p, v = h
        print(f"  chi2 均等性検定: chi2 = {chi2:.1f}  df = {dof}  p = {p:.3g}  "
              f"Cramer's V = {v:.4f}")
        print("    (観測数が多いので p は参考値。見るのは V と上の実寸)")


def main():
    p = argparse.ArgumentParser(
        description="クリップ前の生 PER が [0,1] を外れる件数を Seed 別に数える")
    p.add_argument("--mode", choices=("td", "conv", "both"), default="both")
    p.add_argument("--csv", default=A.CSV_FILE)
    p.add_argument("--out", default=os.path.join(A.PLOT_BASE_DIR,
                                                 "per_range_by_seed.csv"))
    args = p.parse_args()

    modes = ("td", "conv") if args.mode == "both" else (args.mode,)
    if not os.path.isfile(args.csv):
        raise FileNotFoundError(f"CSV file not found: {args.csv}")

    print(f"--- {args.csv} を読み込み（モード: {', '.join(modes)}）---")
    accs, n_rows = scan(args.csv, modes)
    print(f"読み込んだラン数: {n_rows}")

    out_rows = []
    for mode in modes:
        report_mode(mode, accs, out_rows)

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["mode", "seed", "n_obs", "n_neg",
                                          "neg_rate", "n_gt1", "n_invalid",
                                          "n_zero_denom", "min_per", "max_per"])
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n--- 明細を {args.out} に出力 ---")

    print("\n=== 読み方 (docs/per_range_check.md §4) ===")
    print("  PER>1 と 不正 が全モードで0件        -> 定義どおり。列ずれも無し")
    print("  PER>1 または 不正 が1件でもある      -> CSV が壊れている。最優先で調査")
    print("  V < 0.05 かつ 実測/期待 が 1 前後    -> 全 Seed 均等。構造的要因であり")
    print("                                          Seed の除外では直らない")
    print("  一部 Seed だけ率が突出               -> その Seed の除外を検討")
    print("  td だけ高く conv がほぼ0%            -> 窓の分割が主因 (td 固有)")
    print("  分母0 が多い                         -> PER=0 に化けた観測が多い")


if __name__ == "__main__":
    main()
