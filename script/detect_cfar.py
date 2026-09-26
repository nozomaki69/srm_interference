#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CFAR (Constant False Alarm Rate) 方式の干渉検知。

analyze_csv.py の evaluate_interference_detection() が
「interf / no_interf 両方のラベルを見て F1 を最大化する tau」を選んでいるのに対し、
こちらは **H0 (= no_interf, 自組織が干渉なしの状態で自力で観測できるデータ) だけ**から
tau を決める。実運用では「干渉あり」のラベル付きデータは手に入らないので、
こちらが実際に達成可能な性能になる (analyze_csv.py 側は genie-aided な上限)。

------------------------------------------------------------------
なぜ H0 だけで tau が決められるのか
------------------------------------------------------------------
無干渉時の検定統計量 T (= RSSIビン内 ΔPER 分散の最大値) の水準は、
ほぼ全部が「PER を有限回の送信から推定したことによる二項ノイズ」で決まる。
デバイス i・方向 d の推定分散は

    v_i,d = p_d(1-p_d) / N_i,d

で、N も p も自PANの MAC カウンタそのものなので **自組織だけで計算できる**。
これに、シャドウイングとビン幅に由来する「同じRSSIリング内でも真に少し違う」分の
下駄 sigma2_het を足したものが、ビン内分散の期待値になる:

    E[s2_b] = vbar_b + sigma2_het        (vbar_b = ビン内デバイスの v_i の平均)

したがって

    Z_b = s2_b / (vbar_b + sigma2_het)      T_norm = max_b Z_b

と正規化すれば、負荷・伝送速度が変わっても T_norm の帰無分布はほぼ動かず、
tau を条件横断で1つに決められる。較正が要るのは sigma2_het ただ1つで、
それも no_interf データ (= 自組織の無干渉時の姿) だけから推定できる。

------------------------------------------------------------------
3つのサブコマンド
------------------------------------------------------------------
  extract  : simulation_results.csv -> bin_statistics.csv
             (RSSIビンごとに s2 と vbar を出す。ここが一番重い)
  calibrate: no_interf の学習用 seed だけから sigma2_het と tau_alpha を決める
  evaluate : 取り置いた no_interf seed で FPR、interf 全 seed で TPR を測り、
             plots/cfar_results.csv に書き出す

extract を通しておけば、以降の較正・評価・感度解析は bin_statistics.csv だけで回せる
(巨大な simulation_results.csv を読み直さなくてよい)。ビン幅を変える感度解析だけは
extract からやり直す必要がある (--bin-size)。
"""

import os
import sys
import csv
import json
import argparse
from collections import defaultdict

import numpy as np
from scipy import stats

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# ビンの切り方と干渉ラベルの判定は analyze_csv.py と共有する。
# ここで定義を複製すると「どのビンを使うか」の定義が2箇所に増えて必ずずれるため、
# 必ず import して使うこと。
from analyze_csv import (  # noqa: E402
    select_bins,
    get_interf_label,
    get_bandwidth_label,
    CHANNEL_KBPS,
    NUM_DEVICE,
    PAN1_DEVS,
    PAN2_DEVS,
    RSSI_BIN_SIZE_DBM,
)

PLOT_BASE_DIR = os.path.join(SCRIPT_DIR, "..", "plots")
RAW_CSV = os.path.join(PLOT_BASE_DIR, "simulation_results.csv")
BIN_CSV = os.path.join(PLOT_BASE_DIR, "bin_statistics.csv")
CALIB_JSON = os.path.join(PLOT_BASE_DIR, "cfar_calibration.json")
RESULT_CSV = os.path.join(PLOT_BASE_DIR, "cfar_results.csv")

# PER の分母を構成する4カウンタ。analyze_csv._mac_per() と同じ定義。
# macCsmaFailCount は「再送上限に達してACKが返らなかった」に当たらないので入れない。
PER_COUNTERS = (
    "macTxSuccessCount",
    "macRetryCount",
    "macMultipleRetryCount",
    "macTxFailCount",
)

# 学習 (較正) に使う seed 数。既定では seed 0..49 を較正、50..99 を評価に使う。
DEFAULT_TRAIN_SEEDS = 50

# 判定を行うのに必要な、1デバイス・1方向あたりの最低試行回数。
# これを下回るデバイスは統計量から外す (B5: 適用限界の自己判定)。
# 0 を指定すると現行 analyze_csv.py と同じ「全デバイスを使う」挙動になる。
DEFAULT_N_MIN = 0


# ============================================================
# PER と二項ノイズ
# ============================================================
def per_and_var(row, idx, prefix):
    """(PER, 二項ノイズの分散, 試行回数 N) を返す。

    PER の定義は analyze_csv._mac_per() と同一:
        PER = macTxFailCount / (4カウンタの和)

    分散の推定には p̂ をそのまま使わず (F+0.5)/(N+1) を使う。
    p̂ = 0 または 1 のとき p̂(1-p̂)/N が 0 に潰れてしまい、
    ノイズ水準を系統的に過小評価するため (Agresti-Coull 流の平滑化)。
    PER そのものは平滑化せず、生の p̂ を返す。
    """
    n_fail = row[idx[prefix + "macTxFailCount"]]
    total = 0
    for name in PER_COUNTERS:
        total += row[idx[prefix + name]]

    if total <= 0:
        return 0.0, np.nan, 0

    p_hat = n_fail / total
    p_smooth = (n_fail + 0.5) / (total + 1.0)
    return p_hat, p_smooth * (1.0 - p_smooth) / total, total


def pan_device_arrays(row, idx, pan, devs):
    """1つの PAN について、デバイス並びの (ΔPER, RSSI, v, N_min) を返す。

    v は上下リンクの二項ノイズ分散の和で、ΔPER = PER_DL - PER_UL の
    推定誤差分散そのもの (上下は独立に推定しているため単純和になる)。
    """
    delta = np.empty(len(devs))
    rssi = np.empty(len(devs))
    v = np.empty(len(devs))
    n_min = np.empty(len(devs))

    for i, dev in enumerate(devs):
        p_dl, v_dl, n_dl = per_and_var(row, idx, f"{pan}_Co_to_Dev{dev}_")
        p_ul, v_ul, n_ul = per_and_var(row, idx, f"{pan}_Dev{dev}_to_Co_")

        delta[i] = p_dl - p_ul
        rssi[i] = row[idx[f"{pan}_PC_RSSI_Avg_from_Dev{dev}"]]
        v[i] = v_dl + v_ul
        n_min[i] = min(n_dl, n_ul)

    return delta, rssi, v, n_min


def bin_records(delta, rssi, v, n_min, bin_size, n_min_gate):
    """1 seed・1 PAN 分を RSSI ビンに分け、ビンごとの統計量を返す。

    ビンの切り方 (select_bins) は analyze_csv.py と共有しているので、
    「どのビンを使うか」の定義は1箇所のまま。

    戻り値: (ビンごとの dict のリスト, 有効デバイス数)
    """
    valid = (rssi != 0) & np.isfinite(v) & (n_min >= n_min_gate)
    r_v = rssi[valid]
    d_v = delta[valid]
    v_v = v[valid]

    out = []
    if r_v.size == 0:
        return out, 0

    for b, (upper, lower) in enumerate(select_bins(r_v, bin_size=bin_size)):
        mask = (r_v > lower) & (r_v <= upper)
        m = int(np.count_nonzero(mask))
        if m < 2:
            continue
        out.append({
            "bin_index": b,
            "m": m,
            # s2 は不偏分散 (ddof=1)。E[s2] = vbar + sigma2_het が素直に成り立つ。
            "s2": float(np.var(d_v[mask], ddof=1)),
            # s2_pop は現行 analyze_csv.compute_seed_max_variance() と同じ ddof=0。
            # 旧統計量との比較のために残しておく。
            "s2_pop": float(np.var(d_v[mask], ddof=0)),
            "vbar": float(np.mean(v_v[mask])),
            "rssi_upper": float(upper),
            "rssi_lower": float(lower),
        })

    return out, int(np.count_nonzero(valid))


# ============================================================
# extract: simulation_results.csv -> bin_statistics.csv
# ============================================================
BIN_CSV_FIELDS = [
    "bandwidth", "label", "pan1_ch", "pan2_ch", "distance",
    "pan1_offload", "pan2_offload", "seed", "pan",
    "own_kbps", "own_offload", "other_offload",
    "bin_index", "m", "s2", "s2_pop", "vbar",
    "rssi_upper", "rssi_lower", "n_valid_dev",
]


def extract(raw_csv, bin_csv, bin_size, n_min_gate):
    if not os.path.isfile(raw_csv):
        raise FileNotFoundError(
            f"生データが見つかりません: {raw_csv}\n"
            "  sbatch_jobs.sh が出力する plots/simulation_results.csv が必要です。\n"
            "  .gitignore 対象なので、計算機側から取得してください。"
        )

    os.makedirs(os.path.dirname(bin_csv), exist_ok=True)

    n_rows = 0
    n_bins = 0
    with open(raw_csv, "r", encoding="utf-8", newline="") as fin, \
            open(bin_csv, "w", encoding="utf-8", newline="") as fout:

        reader = csv.reader(fin)
        header = next(reader)
        idx = {name: i for i, name in enumerate(header)}
        # float として読むのは RSSI 列だけ (analyze_csv.load_and_aggregate と同じ方針)。
        is_float_col = ["RSSI" in name for name in header]

        writer = csv.DictWriter(fout, fieldnames=BIN_CSV_FIELDS)
        writer.writeheader()

        for raw in reader:
            # 途中で落ちた解析ジョブの部分CSVが混ざっていると列がずれるので必ず検査する。
            if len(raw) != len(header):
                raise ValueError(
                    f"{raw_csv}: 列数が一致しません "
                    f"(header {len(header)} 列 / row {len(raw)} 列)。"
                )
            row = [float(x) if fl else int(float(x))
                   for x, fl in zip(raw, is_float_col)]

            pan1_ch = row[idx["PAN1_CH"]]
            pan2_ch = row[idx["PAN2_CH"]]
            base = {
                "bandwidth": get_bandwidth_label(pan1_ch, pan2_ch),
                "label": get_interf_label(pan1_ch, pan2_ch),
                "pan1_ch": pan1_ch,
                "pan2_ch": pan2_ch,
                "distance": row[idx["Distance"]],
                "pan1_offload": row[idx["PAN1_Offload"]],
                "pan2_offload": row[idx["PAN2_Offload"]],
                "seed": row[idx["Seed"]],
            }

            for pan, devs, ch in (("PAN1", PAN1_DEVS, pan1_ch),
                                  ("PAN2", PAN2_DEVS, pan2_ch)):
                delta, rssi, v, n_min = pan_device_arrays(row, idx, pan, devs)
                recs, n_valid = bin_records(delta, rssi, v, n_min, bin_size, n_min_gate)

                own_load = base["pan1_offload"] if pan == "PAN1" else base["pan2_offload"]
                other_load = base["pan2_offload"] if pan == "PAN1" else base["pan1_offload"]

                for rec in recs:
                    rec.update(base)
                    rec["pan"] = pan
                    rec["own_kbps"] = CHANNEL_KBPS[ch]
                    rec["own_offload"] = own_load
                    rec["other_offload"] = other_load
                    rec["n_valid_dev"] = n_valid
                    writer.writerow(rec)
                    n_bins += 1

            n_rows += 1
            if n_rows % 10000 == 0:
                print(f"  ... {n_rows} 行処理, ビン {n_bins} 件")

    print(f"--- extract 完了: {n_rows} ラン -> {n_bins} ビン を {bin_csv} に出力 ---")
    return n_rows, n_bins


# ============================================================
# bin_statistics.csv の読み込みと seed 単位への集約
# ============================================================
INT_FIELDS = {"pan1_ch", "pan2_ch", "distance", "pan1_offload", "pan2_offload",
              "seed", "own_kbps", "own_offload", "other_offload",
              "bin_index", "m", "n_valid_dev"}
FLOAT_FIELDS = {"s2", "s2_pop", "vbar", "rssi_upper", "rssi_lower"}


def load_bins(bin_csv):
    if not os.path.isfile(bin_csv):
        raise FileNotFoundError(
            f"{bin_csv} がありません。先に `detect_cfar.py extract` を実行してください。"
        )
    rows = []
    with open(bin_csv, "r", encoding="utf-8", newline="") as f:
        for rec in csv.DictReader(f):
            for k in INT_FIELDS:
                rec[k] = int(rec[k])
            for k in FLOAT_FIELDS:
                rec[k] = float(rec[k])
            rows.append(rec)
    return rows


def seed_key(rec):
    """1回の観測 (= 1 seed の 1 PAN) を一意に決めるキー。"""
    return (rec["bandwidth"], rec["label"], rec["distance"],
            rec["pan1_offload"], rec["pan2_offload"], rec["pan"], rec["seed"])


def group_by_seed(bins):
    groups = defaultdict(list)
    for rec in bins:
        groups[seed_key(rec)].append(rec)
    return groups


def t_norm(bin_recs, sigma2_het):
    """正規化統計量 T_norm = max_b s2_b / (vbar_b + sigma2_het)。

    ビンが1つも無い観測は判定不能なので None を返す (陽性にも陰性にも数えない)。
    """
    best = None
    for rec in bin_recs:
        denom = rec["vbar"] + sigma2_het
        if denom <= 0:
            continue
        z = rec["s2"] / denom
        if best is None or z > best:
            best = z
    return best


def t_raw(bin_recs):
    """現行 analyze_csv.compute_seed_max_variance() と同じ生統計量 (ddof=0 の最大分散)。"""
    best = None
    for rec in bin_recs:
        if best is None or rec["s2_pop"] > best:
            best = rec["s2_pop"]
    return best


# ============================================================
# calibrate: H0 (no_interf) の学習用 seed だけから sigma2_het と tau を決める
# ============================================================
def calib_scope_key(rec, scope):
    """較正を何単位で行うか。

    global    : 全条件で1つの sigma2_het / tau。最も強い主張になる。
    own_config: 自PANの伝送速度と自PAN負荷ごと。実運用で組織が自分について
                知っている情報だけで層別できるので、こちらも正当。
                相手PANの情報は絶対に使わない (使うと自力で決められなくなる)。
    """
    if scope == "global":
        return ("global",)
    if scope == "own_config":
        return (rec["own_kbps"], rec["own_offload"])
    raise ValueError(f"unknown scope: {scope}")


def _chi2_median_ratio(m):
    """median(chi2_{m-1}) / (m-1)。s2 の中央値が期待値より小さい分の補正係数。

    H0 では s2_b ~ (vbar_b + sigma2_het) * chi2_{m-1}/(m-1) なので、
    s2_b の中央値は期待値の _chi2_median_ratio(m) 倍にしかならない
    (m=5 で 0.84、m=10 で 0.93)。補正せずに中央値から sigma2_het を引くと、
    vbar が sigma2_het より大きい領域で系統的に過小推定になる。
    """
    return float(stats.chi2.median(m - 1) / (m - 1))


def estimate_sigma2_het_moment(train_bins):
    """積率法による sigma2_het の推定。**診断用**であり、較正には使わない。

    ビンごとに sigma2_het_b = s2_b / median_ratio(m_b) - vbar_b を求め中央値を取る。

    この推定量は二項ノイズ vbar が sigma2_het より十分大きい領域で
    系統的に過小推定になる (単体テストで N=48, p=0.3, m=6 のとき真値の 0〜50%)。
    理由は2つ:
      - ΔPER が離散的で、標本分散の chi2 近似が小標本 (m=6) で崩れる
      - vbar 自体が同じ標本から推定された量で、平滑化 (f+0.5)/(N+1) により
        低 PER 側で上振れする
    したがって「sigma2_het の真値をいくつと推定したか」を論文に書く用途にのみ使い、
    閾値の較正には fit_sigma2_het_invariance() を使うこと。
    """
    if not train_bins:
        return 0.0
    excess = [rec["s2"] / _chi2_median_ratio(rec["m"]) - rec["vbar"]
              for rec in train_bins if rec["m"] >= 2]
    if not excess:
        return 0.0
    return max(0.0, float(np.median(excess)))


def _flatten_for_search(groups):
    """seed 単位のビン群を、分位点探索用のフラットな配列に畳む。

    戻り値 (s2, vbar, starts):
      s2/vbar は全ビンを観測順に並べた配列、starts は観測ごとの開始位置。
      np.maximum.reduceat(z, starts) で観測ごとの max が一発で取れる。
    """
    s2, vbar, starts = [], [], []
    for recs in groups:
        if not recs:
            continue
        starts.append(len(s2))
        for rec in recs:
            s2.append(rec["s2"])
            vbar.append(rec["vbar"])
    if not s2:
        return None
    return np.asarray(s2), np.asarray(vbar), np.asarray(starts)


def fit_sigma2_het_invariance(train_by_stratum, alpha_ref, n_grid=80):
    """H0 データのみから sigma2_het を決める（較正に使う本命の方法）。

    sigma2_het を「真値を当てる量」としてではなく、
    **正規化の目的を直接満たす調整パラメータ**として決める:

        H0 における T_norm の (1-alpha_ref) 分位点が、
        動作点（自PAN伝送速度 x 自PAN負荷）を跨いで一定になるような sigma2_het

    を選ぶ。分位点の層間ばらつき（変動係数）を最小化する 1 次元探索。
    これがちょうど「単一の tau を条件横断で使える」という主張そのものなので、
    積率推定の偏りに悩まされずに済む。**参照するのは H0 のデータだけ**なので、
    自組織だけで実施できるという性質は保たれる。

    train_by_stratum: {層キー: [その層の観測 (= ビンの list) の list]}
    """
    flat = {}
    for key, groups in train_by_stratum.items():
        f = _flatten_for_search(groups)
        if f is not None and len(f[2]) >= 2:
            flat[key] = f
    if len(flat) < 2:
        # 層が1つしかないなら不変性を評価できない。積率推定に退避する。
        return None

    # 探索範囲は vbar の代表値を基準に、0 から その 10 倍まで。
    ref = np.median(np.concatenate([f[1] for f in flat.values()]))
    grid = np.concatenate([[0.0], np.geomspace(ref * 1e-3, ref * 10.0, n_grid - 1)])

    best_sigma2, best_cv = 0.0, np.inf
    for sigma2 in grid:
        quantiles = []
        for s2, vbar, starts in flat.values():
            z = s2 / (vbar + sigma2)
            t = np.maximum.reduceat(z, starts)
            quantiles.append(np.quantile(t, 1.0 - alpha_ref, method="higher"))
        q = np.asarray(quantiles, dtype=float)
        if not np.all(np.isfinite(q)) or q.mean() <= 0:
            continue
        cv = float(q.std() / q.mean())
        if cv < best_cv:
            best_cv, best_sigma2 = cv, float(sigma2)

    return best_sigma2, best_cv


def calibrate(bins, alpha_list, scope, train_seeds, alpha_ref=0.05):
    """no_interf かつ seed < train_seeds のデータだけを使って較正する。

    interf 側のデータはこの関数の中で一切参照しない。これが
    「テストデータで閾値を調整している」という指摘への直接の回答になる。

    2段階:
      1. sigma2_het を、動作点 (自PAN伝送速度 x 自PAN負荷) を跨いで
         H0 の (1-alpha_ref) 分位点が一定になるように決める (全条件で1つ)
      2. その sigma2_het のもとで、scope ごとに tau_alpha を分位点として決める
    """
    train = [r for r in bins if r["label"] == "no_interf" and r["seed"] < train_seeds]
    if not train:
        raise ValueError("較正用のデータ (no_interf かつ seed < train_seeds) がありません。")

    train_groups = group_by_seed(train)

    # --- 1. sigma2_het の決定 (動作点を跨いだ不変性を基準にする) ---
    by_op = defaultdict(list)
    for recs in train_groups.values():
        by_op[(recs[0]["own_kbps"], recs[0]["own_offload"])].append(recs)

    fitted = fit_sigma2_het_invariance(by_op, alpha_ref)
    if fitted is None:
        sigma2_global = estimate_sigma2_het_moment(train)
        cv = float("nan")
        method = "moment (層が1つしかないため不変性フィット不可)"
    else:
        sigma2_global, cv = fitted
        method = "invariance"
    sigma2_moment = estimate_sigma2_het_moment(train)

    print(f"    sigma2_het = {sigma2_global:.6f} ({method}, "
          f"層間の分位点CV={cv:.4f}, 参考: 積率推定 {sigma2_moment:.6f})")

    # --- 2. scope ごとの tau ---
    calib = {}
    by_scope = defaultdict(list)
    for key, recs in train_groups.items():
        by_scope[calib_scope_key(recs[0], scope)].append(recs)

    for key, group_list in by_scope.items():
        sigma2 = sigma2_global
        values = [v for v in (t_norm(g, sigma2) for g in group_list) if v is not None]
        if not values:
            continue
        values = np.asarray(values, dtype=float)

        # 目標 alpha に対して学習標本が少なすぎると、(1-alpha) 分位点そのものが
        # 推定できない (標本 50 個で 99 パーセンタイルは決められない)。
        # 目安として 10/alpha 個を下回る場合は警告する。
        for a in alpha_list:
            if values.size < 10.0 / a:
                print(f"    警告: {key} の学習標本 {values.size} 個は "
                      f"alpha={a} には不足 (目安 {int(10.0 / a)} 個以上)。"
                      " tau が不安定になります。")

        calib[json.dumps(list(key))] = {
            "sigma2_het": sigma2,
            "n_train_obs": int(values.size),
            "n_train_bins": sum(len(g) for g in group_list),
            # method="higher" は分位点を標本点に切り上げる保守側の取り方。
            # 補間すると tau が小さくなり、実現 FPR が設計 alpha を上回りやすい。
            "tau": {f"{a:.3f}": float(np.quantile(values, 1.0 - a, method="higher"))
                    for a in alpha_list},
        }

    return {"scope": scope, "train_seeds": train_seeds,
            "alphas": list(alpha_list),
            "sigma2_het_global": sigma2_global,
            "sigma2_het_method": method,
            "sigma2_het_moment": sigma2_moment,
            "quantile_cv_across_operating_points": cv,
            "alpha_ref": alpha_ref,
            "by_scope": calib}


# ============================================================
# evaluate: 取り置いた no_interf で FPR、interf 全 seed で TPR
# ============================================================
def wilson_interval(k, n, z=1.96):
    """Wilson score 区間。n=100 の比率に素の正規近似を使うと端で破綻するため。"""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


RESULT_FIELDS = [
    "scope", "alpha", "bandwidth", "distance", "pan",
    "own_kbps", "own_offload", "other_offload",
    "sigma2_het", "tau",
    "n_h0_test", "n_h1", "fp", "tp",
    "fpr", "fpr_lo", "fpr_hi", "tpr", "tpr_lo", "tpr_hi",
    "n_undecidable_h0", "n_undecidable_h1",
]


def evaluate(bins, calib, alpha_list, train_seeds):
    scope = calib["scope"]
    groups = group_by_seed(bins)

    # 条件 x PAN 単位に、H0(評価用) と H1 の観測をまとめる
    conditions = defaultdict(lambda: {"h0": [], "h1": [], "meta": None})
    for key, recs in groups.items():
        bandwidth, label, distance, l1, l2, pan, seed = key
        rec0 = recs[0]
        cond = (bandwidth, distance, l1, l2, pan)
        entry = conditions[cond]
        if entry["meta"] is None:
            entry["meta"] = {
                "bandwidth": bandwidth, "distance": distance, "pan": pan,
                "own_kbps": rec0["own_kbps"],
                "own_offload": rec0["own_offload"],
                "other_offload": rec0["other_offload"],
                "scope_key": calib_scope_key(rec0, scope),
            }
        if label == "no_interf":
            # 学習に使った seed は評価から必ず外す
            if seed >= train_seeds:
                entry["h0"].append(recs)
        else:
            entry["h1"].append(recs)

    rows = []
    for cond, entry in sorted(conditions.items(), key=lambda kv: str(kv[0])):
        meta = entry["meta"]
        skey = json.dumps(list(meta["scope_key"]))
        if skey not in calib["by_scope"]:
            continue
        c = calib["by_scope"][skey]
        sigma2 = c["sigma2_het"]

        h0 = [t_norm(g, sigma2) for g in entry["h0"]]
        h1 = [t_norm(g, sigma2) for g in entry["h1"]]
        n_und_h0 = sum(1 for v in h0 if v is None)
        n_und_h1 = sum(1 for v in h1 if v is None)
        h0 = [v for v in h0 if v is not None]
        h1 = [v for v in h1 if v is not None]
        if not h0 or not h1:
            continue

        for a in alpha_list:
            tau = c["tau"][f"{a:.3f}"]
            fp = sum(1 for v in h0 if v >= tau)
            tp = sum(1 for v in h1 if v >= tau)
            fpr_lo, fpr_hi = wilson_interval(fp, len(h0))
            tpr_lo, tpr_hi = wilson_interval(tp, len(h1))
            rows.append({
                "scope": scope, "alpha": a,
                "bandwidth": meta["bandwidth"], "distance": meta["distance"],
                "pan": meta["pan"], "own_kbps": meta["own_kbps"],
                "own_offload": meta["own_offload"],
                "other_offload": meta["other_offload"],
                "sigma2_het": round(sigma2, 8), "tau": round(tau, 5),
                "n_h0_test": len(h0), "n_h1": len(h1), "fp": fp, "tp": tp,
                "fpr": round(fp / len(h0), 4),
                "fpr_lo": round(fpr_lo, 4), "fpr_hi": round(fpr_hi, 4),
                "tpr": round(tp / len(h1), 4),
                "tpr_lo": round(tpr_lo, 4), "tpr_hi": round(tpr_hi, 4),
                "n_undecidable_h0": n_und_h0, "n_undecidable_h1": n_und_h1,
            })

    return rows


def save_results(rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def print_summary(rows, alpha_list):
    print()
    print("=== 設計 alpha に対する実現 FPR (全条件をまとめた要約) ===")
    print(f"{'alpha':>7} {'条件数':>6} {'FPR中央':>9} {'FPR平均':>9} "
          f"{'FPR 5-95%':>16} {'TPR中央':>9}")
    for a in alpha_list:
        sub = [r for r in rows if abs(r["alpha"] - a) < 1e-12]
        if not sub:
            continue
        fpr = np.array([r["fpr"] for r in sub])
        tpr = np.array([r["tpr"] for r in sub])
        print(f"{a:7.3f} {len(sub):6d} {np.median(fpr):9.4f} {fpr.mean():9.4f} "
              f"{np.percentile(fpr, 5):7.4f}-{np.percentile(fpr, 95):<8.4f} "
              f"{np.median(tpr):9.4f}")
    print()
    print("実現 FPR が設計 alpha の近傍に乗っていれば、"
          "「H0 のみから決めた tau が条件横断で機能する」ことの直接の証拠になる。")


# ============================================================
# main
# ============================================================
def parse_alphas(text):
    return [float(x) for x in text.split(",") if x.strip()]


def main():
    parser = argparse.ArgumentParser(
        description="H0 (no_interf) のみから閾値を決める CFAR 干渉検知",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ex = sub.add_parser("extract", help="simulation_results.csv -> bin_statistics.csv")
    p_ex.add_argument("--raw-csv", default=RAW_CSV)
    p_ex.add_argument("--bin-csv", default=BIN_CSV)
    p_ex.add_argument("--bin-size", type=float, default=RSSI_BIN_SIZE_DBM,
                      help="RSSIビン幅[dBm] (既定は analyze_csv.RSSI_BIN_SIZE_DBM)")
    p_ex.add_argument("--n-min", type=int, default=DEFAULT_N_MIN,
                      help="1デバイス1方向あたりの最低試行回数。下回るデバイスは除外")

    p_run = sub.add_parser("run", help="calibrate + evaluate をまとめて実行")
    p_run.add_argument("--bin-csv", default=BIN_CSV)
    p_run.add_argument("--out-csv", default=RESULT_CSV)
    p_run.add_argument("--calib-json", default=CALIB_JSON)
    p_run.add_argument("--scope", choices=("global", "own_config"), default="global")
    p_run.add_argument("--train-seeds", type=int, default=DEFAULT_TRAIN_SEEDS,
                       help="較正に使う seed 数 (seed < この値 の no_interf のみ)")
    p_run.add_argument("--alphas", type=parse_alphas, default=[0.01, 0.05, 0.10])
    p_run.add_argument("--alpha-ref", type=float, default=0.05,
                       help="sigma2_het を決める際、どの alpha の分位点で"
                            "動作点間の不変性を評価するか")

    args = parser.parse_args()

    if args.command == "extract":
        extract(args.raw_csv, args.bin_csv, args.bin_size, args.n_min)
        return

    bins = load_bins(args.bin_csv)
    print(f"--- {args.bin_csv} から {len(bins)} ビンを読み込み ---")

    calib = calibrate(bins, args.alphas, args.scope, args.train_seeds, args.alpha_ref)
    os.makedirs(os.path.dirname(args.calib_json), exist_ok=True)
    with open(args.calib_json, "w", encoding="utf-8") as f:
        json.dump(calib, f, indent=2, ensure_ascii=False)
    print(f"--- 較正完了 (scope={args.scope}, 層数={len(calib['by_scope'])}) "
          f"-> {args.calib_json} ---")
    for key, c in sorted(calib["by_scope"].items()):
        taus = " ".join(f"a={a}:{t:.3f}" for a, t in sorted(c["tau"].items()))
        print(f"    {key}: sigma2_het={c['sigma2_het']:.6f} "
              f"n_obs={c['n_train_obs']} {taus}")

    rows = evaluate(bins, calib, args.alphas, args.train_seeds)
    save_results(rows, args.out_csv)
    print(f"--- 評価完了: {len(rows)} 行 -> {args.out_csv} ---")
    print_summary(rows, args.alphas)


if __name__ == "__main__":
    main()
