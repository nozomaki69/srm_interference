# `icc_load200` ブランチ ―― 負荷を 20〜200% に広げる

`icc` ブランチ（干渉判定3手法の比較。全体の設計は `docs/README.md`）の負荷グリッドを
**20〜100% の5値から 20〜200% の10値（20% 刻み）に広げて**シミュレーションし直し、
3手法の比較結果を `plots/detection_lines_more/` に出す。

`icc` は 20〜100% の結果（`plots/detection_lines/`）を持ったまま残す。
このブランチの結果はこのブランチにだけ置く。

## 1. 何を変えるか

| 項目 | `icc` | `icc_load200` |
|---|---|---|
| 負荷グリッド `OFFERED_LOAD_PERCENTS` | 20, 40, 60, 80, 100 | 20, 40, …, 200（10値） |
| ラン数 | 12 × 5 × 5 × 100 = 30,000 | 12 × 10 × 10 × 100 = **120,000** |
| 検知結果CSVの行数 | 900 | **3,600**（6帯域ペア × 100負荷 × 2PAN × 3手法） |
| Seed 別スコアCSV | 180,000 行（約 10 MB） | 720,000 行（約 40 MB） |
| 折れ線の断面（相手PAN負荷） | 100% | **100% と 200% の両方** |
| 折れ線の出力先 | `plots/detection_lines/` | `plots/detection_lines_more/other100/`, `other200/` |

判定手法・PER の定義・測定モード（simultaneous 固定）・AUC の計算・時間窓・
シミュレーション条件（負荷以外）は `icc` と同じ。

## 2. 負荷グリッド

`script/interference_2pan_config.py` の `OFFERED_LOAD_PERCENTS` を
`list(range(20, 201, 20))` にする。`ALL_COMBOS` はここから作られるので
`--print-total` は自動で 120,000 になる。`create_csv.py` / `analyze_csv.py` は
負荷の値を CSV の `PAN1_Offload` / `PAN2_Offload` 列から読むだけなので手を入れない。

### 過飽和についての注意

負荷 L% は「衝突なし飽和容量に対する提供レートの比」（`offered_load_pps()`）。
100% を超えると提供レートが飽和容量を上回り、待ち行列は原理的に発散する。
実際に電波に出る負荷は 100% 付近で頭打ちになるので、120〜200% の条件どうしは
互いにほとんど区別がつかない可能性が高い。

`ed9bb8600e`（「負荷グリッドを 20-200% の10値から 20-100% の5値に絞る」）は
まさにこの理由で 200% までの範囲をやめていた。このブランチはそれを承知のうえで、
**過飽和域で3手法の差がどうなるか**を見るために範囲を戻す。
過飽和域で AUC が横ばいになるのは想定どおりの結果であり、不具合ではない。

ドレイン（40 s）は延ばさない。延ばすと 20〜100% の条件まで `icc` と変わってしまう。
過飽和域ではシミュレーション終了時にキューに残るフレームが増えるが、PER の分母は
決着したフレームだけ（`create_csv.py` の `unresolved` は分母に入らない）なので、
定義上の破綻は起きない。

## 3. 折れ線グラフ

`script/plot_detection_lines.py` を次のように変える。

- 断面を `OTHER_LOAD_PERCENTS = (100, 200)` の2つにする。
  - 100%：`icc` の図と同じ断面。横軸を 200% まで伸ばしたものとして直接比べられる。
  - 200%：相手が最大負荷のとき。
- 断面ごとに `plots/detection_lines_more/other{100,200}/` へ、`icc` と同じ構成の
  16 枚（手法3 + 比較1）×（自帯域3 + 3パネル1）を出す。計 32 枚。
- y 軸は2つの断面の全描画値から1つだけ決め、全図に同じ値を当てる
  （図をまたいで比較するため。考え方は `icc` の `choose_ylim()` と同じ）。
- 描画値は `plots/detection_lines_more/auc_plotted_values.csv` に1本で出し、
  `other_load_percent` 列で断面を区別する。
- 横軸の目盛りが 10 個になるので、図を横に広げる。

自分 / 相手の読み替え規則（`own_other()`）は変えない。断面の値を引数に取るように
するだけ。

### スコア分布のヒストグラム

`script/plot_score_histograms.py`（設計は `docs/README.md` の「スコア分布の
ヒストグラム」節）も同じ2断面に対応させ、`plots/score_histograms_more/other{100,200}/`
に 9 枚ずつ出す。列（自PAN負荷）は 10 個になる。`plots/score_histograms/` は
`icc` の 20〜100% の結果として残す。

## 4. 実行

計算機で:

```sh
git fetch
git checkout icc_load200
./script/sbatch_jobs.sh
```

- **起動時に既存の `plots/simulation_results.csv`（`icc` の 30,000 ラン分）が
  削除される。** 残したいなら事前に退避する。
- 実行時間は `icc` の約 4 倍。バッチ（2,000 件）の数は 15 → 60。
- `simulation_results.csv` は約 155 MB → 約 620 MB になる。

解析・作図だけやり直すときは `./script/sbatch_reanalyze.sh`（期待行数 3,600 で検証）、
図だけなら `./script/plot_figures.sh`。

## 5. 検証

手元で合成した `simulation_results.csv`（6帯域ペア × 負荷 10×10 × 数 Seed）に
`run_analysis.sh` を通し、検知結果CSVが 3,600 行・3手法そろうこと、
`detection_lines_more/other100/` と `other200/` に 16 枚ずつ出ることを確認する。
