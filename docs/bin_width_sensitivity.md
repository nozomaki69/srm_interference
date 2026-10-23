# 提案手法の RSSI ビン幅の感度分析

## 1. 目的

提案手法は、端末を RSSI でビンに分け、ビンごとの ΔPER 分散の最大値を干渉指標にしている。
ビン幅はこれまで **10 dBm** に固定していた (`analyze_csv.py` の `RSSI_BIN_SIZE_DBM`)。
この値を変えたときに AUC がどう変わるかを調べ、10 dBm という選び方に結果が
どれだけ依存しているかを示す。

ビン幅にはトレードオフがある:

- **細いビン**: 同じリングの端末だけを比べられる (RSSI 差による PER 差がビン内に混ざりにくい)。
  だがビン内の端末数 m が減り、分散の推定がばらつく。m < 2 のビンは使えないので、
  細すぎると有効ビンが1つも作れない Seed (縮退) が出る
- **太いビン**: 端末数は増えるが、RSSI の違う端末が混ざる。ビンが1つになると、
  ΔPER only から「起点より弱い端末を除いた」だけのものに近づく

## 2. 何を振り、何を固定するか

| 項目 | 値 |
|---|---|
| ビン幅 | **1〜20 dBm、1 dBm 刻み (20 通り)**。既定の 10 dBm を含む |
| ビンの起点 | 固定: 受信感度 + `RSSI_BIN_ANCHOR_OFFSET_DBM` (3.0 dBm) |
| 有効ビンの最小端末数 | 固定: 2 (`select_bins()` の `min_count`) |
| 指標 | 固定: 有効ビンごとの ΔPER 分散の最大値 (`_score_proposed()`) |
| PER・ΔPER・端末の絞り込み | 固定 (`_one_side_per()` / `_iter_seeds()`) |
| 測定モード | 両方 (single-query = simultaneous / multi-query = sequential) |
| 条件 | 既存と同じ 300 条件 × 2 PAN。AUC は干渉あり 100 / 干渉なし 100 Seed |

**再シミュレーションは不要。** ビン幅に依存するのは提案手法の後処理だけで、
入力 `plots/simulation_results.csv` の ΔPER / RSSI はビン幅に依存しない。
ΔPER only / RSSI only はビンを使わないので、ビン幅を変えても値は変わらない
(図では参照線として既存の値を重ねる)。

## 3. 実装

- `analyze_csv.py`: ビン幅を引数で渡せるようにした (`select_bins()` /
  `compute_seed_scores()` / `run_interference_detection()` の `bin_size`)。
  **省略時は従来どおり `RSSI_BIN_SIZE_DBM` (10 dBm)** で、既存の解析結果は変わらない。
  以前は `select_bins(bin_size=RSSI_BIN_SIZE_DBM)` と既定値が関数定義時に固定されていて、
  定数を書き換えても反映されない形だったので、呼び出し時に読む形 (`bin_size=None`) にした。
- `script/bin_width_sensitivity.py`: モードごとに `simulation_results.csv` を1回だけ読み
  (`load_and_aggregate()`。ここが重い)、ビン幅 20 通りで提案手法のスコアと AUC を出す。
  95% 信頼区間は `bootstrap_auc.bootstrap_group()` をそのまま使う (層別、1000 回、乱数シード固定)。
  **ビン幅 10 dBm の AUC が既存の `interference_detection_results*.csv` の proposed と
  全条件で一致することを毎回確かめ**、一致しなければ止まる。
- **点推定の AUC は、区間と同じスコア (CSV に書くときと同じ `.9g` の文字列から読んだ値) から出す。**
  最初は検知側 (`run_interference_detection()`) の AUC をそのまま使い、区間側と一致することを
  assert していたが、計算機での初回実行がビン幅の細い側でこの assert で落ちた。原因は同順位の扱い:
  数学的に同じ分散でも `np.var` は端末の並び順で最下位ビットが変わり (端末 2-3 台・離散的な PER の
  組で試すと約 1 割)、丸める前の float で順位を付ける検知側は本来の同順位を任意の向きに割ってしまう。
  細いビンでは端末数が少なく PER も離散値なので同じスコアの Seed が多く、AUC が 4 桁目でずれる。
  同順位を同順位として数える `.9g` 側を正とし、検知側の値は `auc_direct` 列に残して、ずれた件数と
  最大差をビン幅ごとにログに出す。10 dBm では両者は既存の 900 行すべてで一致している
  (既存の `bootstrap_auc.py` の照合と同じ)。
- `script/plot_bin_width_sensitivity.py`: 作図。断面の取り方 (自/相手の読み替え、
  対称ペアは PAN1) と体裁は `plot_detection_lines.py` を import して共有する。
- `script/sbatch_bin_width_sensitivity.sh`: 計算機で上の2つを SLURM に投げ、完了を待って
  行数を検証する。既存の結果ファイルには触らない。

## 4. 出力 (`plots/bin_width_sensitivity/`)

| ファイル | 内容 |
|---|---|
| `auc_binwidth_{single,multi}.csv` | ビン幅 × 300 条件 × 2 PAN = 6000 行。`bin_width_dbm, bandwidth, distance, pan1_offload, pan2_offload, pan, auc, auc_ci_low, auc_ci_high, n_boot, auc_direct, n_degenerate_interf, n_degenerate_no_interf` |
| `bin_diagnostics_{single,multi}.csv` | ビン幅 × (PAN, チャネル) ごとの、Seed あたり有効ビン数・ビン内端末数 (中央値・最大)・縮退 Seed 数 |
| `auc_{single,multi}_proposed_binwidth_grid_otherload<L>.pdf` | 3×3 グリッド (行 = 自帯域、列 = 相手帯域)。横軸 = ビン幅、縦軸 = AUC、線 = 自PAN負荷 5本、10 dBm に縦の破線。相手負荷 5 通り |
| `auc_{single,multi}_binwidth_summary.pdf` | 横軸 = ビン幅。左 = 45 条件 (9 ペア × 自負荷 5) の平均 AUC、右 = 最小 AUC。線 = 相手負荷。ΔPER only / RSSI only の同じ集計値を水平線で重ねる |
| `auc_binwidth_plotted_values.csv` | 上の図に描いた値 (両モード) |

## 5. 実行 (計算機)

```sh
git pull
./script/sbatch_bin_width_sensitivity.sh      # 解析 + 作図。完了まで待つ
git add plots/bin_width_sensitivity && git commit && git push
```

手元で図だけ描き直すときは `python3 script/plot_bin_width_sensitivity.py`
(`auc_binwidth_*.csv` さえあればよい)。

## 6. 結果

(計算機での実行後に追記する)
