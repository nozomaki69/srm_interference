# 変動係数（CV）による干渉判定（ブランチ `cv`）

## 1. 背景と狙い

これまでの検知統計量は **ΔPER（= PER_DL − PER_UL）の RSSI ビン内分散**だった。
分散は PER の絶対水準に依存するため、負荷・伝送速度・距離が変わると帰無水準が動き、
固定の閾値が条件を跨いで通用しない。実際 `icc` では帯域ペアごとに最適 τ が
0.039〜0.078 とばらついていた。

そこで**変動係数 CV = 標準偏差 / 平均**を使う。平均で正規化した無次元量なので、
PER の絶対水準に依らない閾値が期待できる。

## 2. 設計の決定事項

| 項目 | 決定 |
|---|---|
| UL と DL | **それぞれ独立に判定**する。CV_ul と CV_dl に別々の閾値を求め、結果も別々に出す |
| 計算単位 | **RSSI ビン内**（現行踏襲）。起点 = 受信感度 + 3 dBm、幅 10 dBm |
| 平均 PER が 0 付近 | **平均 PER に下限を設ける**。下回るビンはその方向について使わない |

UL と DL を独立に見るので、ΔPER のような差分は取らない。
干渉は DL 側（受信点がリング上に散らばる）の CV をより強く押し上げるはずなので、
UL と DL のどちらが効くかもデータで分かる。

## 3. 統計量

各 Seed・各 PAN・各方向（ul / dl）について:

```
for 各 RSSI ビン b (端末 2 台以上):
    vals = そのビンの端末の PER（その方向）
    m    = mean(vals)
    if m < MEAN_PER_FLOOR:        # 下限を下回るビンはこの方向では使わない
        skip
    cv_b = std(vals, ddof=0) / m

統計量 = max_b cv_b       （使えるビンが 1 つも無ければ 0.0 = 縮退）
```

- ビンの切り方は `analyze_csv.select_bins()` をそのまま使う（定義を 1 箇所に保つ）
- 標準偏差は現行の分散統計量と揃えて `ddof=0`
- 下限 `MEAN_PER_FLOOR` は既定 0.01。下限で捨てたビン数を診断に出す
- 下限の判定は**方向ごとに独立**に行う（UL では使えるが DL では使えないビンがあり得る）

## 4. 閾値の決め方

`icc` と同じく、`interf` / `no_interf` 両方のラベルから **F1 を最大化する閾値**を選ぶ
（genie-aided な上限）。ただし閾値の候補は固定格子ではなく
**観測された統計量の値そのもの**を使う。

CV は分散と違って 1 を超え得るので、固定格子だと上限の取り方で最適解を逃す。
観測値を候補にすれば、どの範囲でも厳密に F1 最大の閾値が求まる。

F1 の構造的下限は `icc` と同じく `2·n_pos / (2·n_pos + n_neg)`（100 対 100 なら 0.667）。

## 5. 出力

### `plots/cv_detection_results.csv`

条件 × 方向ごとに 1 行。`icc` の `interference_detection_results.csv` に
**`link` 列（ul / dl）**を足した構成。

```
bandwidth, distance, pan1_offload, pan2_offload, pan, link,
best_threshold, TP, FP, FN, TN, precision, recall, fpr, f1,
n_interf_seeds, n_no_interf_seeds,
n_degenerate_interf, n_degenerate_no_interf,
n_floor_skipped_interf, n_floor_skipped_no_interf
```

行数は 6 帯域ペア × 5×5 負荷 × 2 PAN × 2 方向 = **600 行**。

### ヒートマップ

`plots/heatmaps_cv/heatmap_{帯域}_{距離}_{PAN}_{link}.pdf`、
6 帯域ペア × 2 PAN × 2 方向 = **24 枚**（`icc` の 12 枚の 2 倍）。

カラーバーの下限は `icc` と同じく F1 の構造的下限に合わせ、下限に張り付いた
セル（検知失敗）は灰色で潰す。

## 6. 測定モード

`icc` の `--mode {td,conv}` をそのまま引き継ぐ。

| モード | 入力列 | 出力 |
|---|---|---|
| `td`（既定） | 接尾辞なし（時間分割測定） | `cv_detection_results.csv` |
| `conv` | `_conv`（W0 で同時測定） | `cv_detection_results_conv.csv` |

これにより「CV にすると時間分割のコストが減るのか」も確認できる。

## 7. 実装するファイル

| ファイル | 内容 |
|---|---|
| `script/analyze_cv.py`（新規） | `analyze_csv.py` から `select_bins` / `bin_anchor_dbm` / `load_and_aggregate` / `evaluate_interference_detection` を import して CV 統計量と判定を行う |
| `script/create_heatmap.py` | `--statistic {variance,cv}` を追加。cv のときは `cv_detection_results{suffix}.csv` を読み、`link` 次元も回す |

`analyze_csv.py` の既存の分散ベースの経路には手を入れない。同じブランチで
分散版と CV 版の両方を出して比較できるようにするため。

## 8. 検証

1. `compute_seed_max_cv()` の単体テスト — 既知の PER 配列に対して
   `std/mean` が正しく出ること、平均下限でビンが除外されること、
   使えるビンが無いとき 0.0（縮退）を返すこと、UL と DL で独立に判定されること
2. 合成 `simulation_results.csv` で end-to-end 実行し、出力が 600 行になること、
   `link` 列が ul/dl に分かれること
3. 実データで `--mode td` と `--mode conv` の両方を実行し、
   分散版（`interference_detection_results.csv`）と F1 を比較する
4. 診断で「平均下限で捨てたビン数」が過大でないこと。過大なら
   `MEAN_PER_FLOOR` を見直す
