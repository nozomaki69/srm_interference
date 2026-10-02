# 変動係数（CV）による干渉判定（ブランチ `cv`）

## 1. 背景と狙い

これまでの検知統計量は **ΔPER（= PER_DL − PER_UL）の RSSI ビン内分散**だった。
分散は PER の絶対水準に依存するため、負荷・伝送速度・距離が変わると帰無水準が動き、
固定の閾値が条件を跨いで通用しない。実際 `icc` では帯域ペアごとに最適 τ が
0.039〜0.078 とばらついていた。

そこで **ΔPER の変動係数 CV = 標準偏差 / 平均** を使い、閾値と比較するだけで
干渉判定ができるかを調べる。平均で正規化した無次元量なので、PER の絶対水準に
依らない閾値が期待できる。

## 2. 統計量

各 Seed・各 PAN について:

```
ΔPER_i = PER_DL,i − PER_UL,i                （端末ごと）

for 各 RSSI ビン b (端末 2 台以上):
    m = mean(ΔPER in b)
    if |m| < MEAN_ABS_FLOOR:     # 分母が 0 に近いビンは使わない
        skip
    cv_b = std(ΔPER in b) / |m|

統計量 = max_b cv_b              （使えるビンが 1 つも無ければ 0.0 = 縮退）
```

- ビンの切り方は `analyze_csv.select_bins()` をそのまま使う（起点 = 受信感度 + 3 dBm、幅 10 dBm）
- 標準偏差は現行の分散統計量と揃えて `ddof=0`
- **分母は絶対値 `|mean|`** を使う。ΔPER は符号を持つため

## 3. ★ この統計量に固有の注意点

### 3-1. ΔPER の平均は 0 付近になりやすい

無干渉なら DL と UL の PER は近いので、ビン内平均 ΔPER は 0 付近に来る。
`CV = SD / |mean|` の分母が消えるため、**発散が例外ではなく通常のケース**になる。

対策として `MEAN_ABS_FLOOR`（既定 **0.001**）を設け、`|mean|` がこれ未満のビンは
使わない。`icc` の PER（0.05〜0.4 程度）と違って ΔPER の平均は桁が小さいので、
下限も小さく取る。

**実データでは、まず診断出力の「下限で捨てたビン数」と「縮退した観測数」を
確認すること。** これが大きければ、この統計量は成立していない。

### 3-2. 判定の向きが逆になり得る

干渉が強まると、ビン内の ΔPER は

- 平均 |m| が大きくなる（DL だけ悪化するため）
- 標準偏差も大きくなる（リング内で干渉の受け方が違うため）

の両方が起きる。CV = SD/|m| は比なので、**平均の増加が標準偏差の増加を上回れば
CV はむしろ下がる**。つまり「CV が大きい = 干渉あり」とは限らない。

そこで閾値判定は **`統計量 ≥ τ` と `統計量 ≤ τ` の両方を試し、F1 が高いほうを採用**
する。採用した向きは結果 CSV の `rule` 列（`ge` / `le`）に残す。
これにより「CV で干渉判定できるか」を公平に評価できる。

## 4. 閾値の決め方

`icc` と同じく、`interf` / `no_interf` 両方のラベルから **F1 を最大化する閾値**を選ぶ
（genie-aided な上限）。ただし閾値の候補は固定格子ではなく
**観測された統計量の値そのもの**を使う。CV は分散と違って 1 を大きく超え得るので、
固定格子だと上限の取り方で最適解を逃す。

F1 の構造的下限は `icc` と同じく `2·n_pos / (2·n_pos + n_neg)`（100 対 100 なら 0.667）。

## 5. 出力

### `plots/cv_detection_results{suffix}.csv`

```
bandwidth, distance, pan1_offload, pan2_offload, pan, link, rule,
best_threshold, TP, FP, FN, TN, precision, recall, fpr, f1,
n_interf_seeds, n_no_interf_seeds,
n_degenerate_interf, n_degenerate_no_interf,
n_floor_skipped_interf, n_floor_skipped_no_interf
```

既定（`--statistic delta`）では `link` 列は `delta` 固定で、
行数は 6 帯域ペア × 5×5 負荷 × 2 PAN = **300 行**（`icc` と同じ粒度）。

### ヒートマップ

`plots/heatmaps_cv{suffix}/heatmap_{帯域}_{距離}_{PAN}_delta.pdf` = **12 枚**。
カラーバーの下限は `icc` と同じく F1 の構造的下限に合わせ、下限に張り付いた
セル（検知失敗）は灰色で潰す。

## 6. 参考実装：UL / DL を別々に見る版

`--statistic links` を指定すると、ΔPER ではなく **UL の PER と DL の PER の CV を
それぞれ独立に**計算して判定する（`link` 列が `ul` / `dl`、行数は 600、図は 24 枚）。
本題は ΔPER 版だが、どちらの方向が効いているかを見たいときの補助として残してある。

## 7. 測定モード

`icc` の `--mode {td,conv}` をそのまま引き継ぐ。

| モード | 入力列 | 出力 |
|---|---|---|
| `td`（既定） | 接尾辞なし（時間分割測定） | `cv_detection_results.csv` |
| `conv` | `_conv`（W0 で同時測定） | `cv_detection_results_conv.csv` |

## 8. 実装するファイル

| ファイル | 内容 |
|---|---|
| `script/analyze_cv.py` | `analyze_csv.py` から `select_bins` / `bin_anchor_dbm` / `load_and_aggregate` を import して CV 統計量と判定を行う |
| `script/create_heatmap.py` | `--statistic {variance,cv}`。cv のときは `cv_detection_results*` を読み、`link` 次元も回す（既に実装済み） |

`analyze_csv.py` の分散ベースの経路には手を入れない。同じブランチで分散版と
CV 版の両方を出して比較できるようにするため。

## 9. 検証

1. `compute_seed_max_cv()` の単体テスト — `std/|mean|` が正しいこと、
   `|mean|` 下限でビンが除外されること、使えるビンが無いとき 0.0（縮退）を返すこと、
   ビンをまたいで最大が選ばれること
2. `evaluate_detection()` の単体テスト — `ge` / `le` の両方向を試し、
   F1 が高いほうが選ばれること。完全分離で F1=1.0、分離不能で F1=構造的下限
3. 合成 `simulation_results.csv` で end-to-end 実行し、出力が 300 行になること
4. 実データで **診断出力の「下限で捨てたビン数」「縮退した観測数」を最初に確認**。
   大きければこの統計量は成立していない
5. 分散版（`interference_detection_results.csv`）と F1 を比較し、
   帯域ペアを跨いだ閾値のばらつきが縮まっているかを見る
