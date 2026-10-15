# RSSIビン幅の感度分析（ブランチ `icc_binwidth`）

## 目的

提案手法（RSSIビン内 ΔPER 分散の Seed 内最大値）は、ビン幅を 10 dBm に決め打ちしている
（`analyze_csv.py` の `RSSI_BIN_SIZE_DBM`）。この幅を **1〜20 dBm（1 dBm 刻み、20通り）**
で振り、干渉判定の AUC が一番良くなる幅を確かめる。

## 再シミュレーションは要らない

ビン幅は `analyze_csv.py` の `select_bins()` が、集約済みの
`plots/simulation_results.csv`（端末ごとの PER と RSSI）に当てているだけで、
シミュレーションの設定（`.config`）やトレースの集約（`create_csv.py`）には出てこない。
したがって **icc の `simulation_results.csv` があれば解析のやり直しだけで済む**。

ただし `simulation_results.csv` は gitignore されていて計算機にしか無いので、
解析は計算機で回す（`script/sbatch_bin_width.sh`。SLURM の1ジョブ）。

## 固定するもの

- ビンの起点：受信感度 + 3 dBm（`RSSI_BIN_ANCHOR_OFFSET_DBM`）。幅だけを振る
- ビンに入れる最低端末数：2（`select_bins()` の `min_count`）
- 条件：icc と同じ 6帯域ペア × 25負荷 × 2PAN、各 100 Seed（干渉あり・なし）
- AUC の定義：`analyze_csv._rank_auc()`

dper（全端末の ΔPER 分散）と rssi（全端末の平均RSSI）はビンを使わないので幅に依存しない。
1回だけ計算して、比較用の水平線として描く。

## 実装

- `analyze_csv.py`：`_score_proposed()` / `compute_seed_scores()` /
  `run_interference_detection()` に `bin_size` 引数を足す。既定値は
  `RSSI_BIN_SIZE_DBM` なので、通常の解析の出力は変わらない。
  `run_interference_detection()` には手法を絞る `methods` 引数も足す
- `script/bin_width_sensitivity.py`：`simulation_results.csv` を **1回だけ**読み
  （ここが重い）、幅ごとに `run_interference_detection(data, methods=("proposed",), bin_size=w)`
  を呼ぶ。結果を CSV に書き、図を作る。`--from-csv` で CSV から図だけ作り直せる
- `script/sbatch_bin_width.sh`：上を SLURM に投げて完了まで待ち、出力を検証する

## 「一番良い幅」の決め方

**全条件（6帯域ペア × 25負荷 × 2PAN = 300 個）の AUC の平均が最大の幅**とする。
同じ平均値が複数あれば狭い方を採る。平均だと条件ごとの違いが隠れるので、
折れ線と同じ断面（相手負荷 100%）で負荷別にも描いて、最適な幅が負荷でずれるかを見る。

## 出力（`plots/bin_width_sensitivity/`）

| ファイル | 内容 |
|---|---|
| `auc_by_bin_width.csv` | 幅 × 条件 × 手法の AUC。行数 = 20幅 × 300（proposed）+ 300 × 2（dper, rssi は `bin_width` 空欄）= 6,600 |
| `auc_vs_bin_width.pdf` | 横軸ビン幅、縦軸 全条件の平均 AUC。proposed の折れ線、dper / rssi の水平破線、最良の幅の印、10 dBm（今の設定）の縦線 |
| `auc_vs_bin_width_by_load.pdf` | 相手負荷 100% の断面。自帯域ごとの3パネル、線が自PAN負荷 20〜100%（相手帯域3つの平均） |
| `degenerate_vs_bin_width.pdf` | 幅ごとの「有効なビンが1つも作れなかった Seed の割合」。幅が狭いと増え、AUC が下がる原因になる |

断面の読み替え（自分 / 相手）は `plot_detection_lines.own_other()` を使う。
既存の解析結果（`interference_detection_results_simultaneous.csv` など）は上書きしない。

## 実行（計算機）

```sh
git fetch && git checkout icc_binwidth
./script/sbatch_bin_width.sh
```

`plots/simulation_results.csv` が icc の 30,000 ランぶん揃っていることが前提。
