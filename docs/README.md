# `icc` ブランチ

2つの PAN が隣接したとき、自分の PAN 側の観測だけから相手の干渉を検知できるか ――
という実験の、**判定手法を3つ並べて比べる構成**。`save` ブランチ (提案手法1つを
F1 と AUC の両方で、sequential/simultaneous 両モードについて評価する) から、
比較の軸を「評価指標 × 測定モード」から「**判定手法**」に組み替えた。

## 1. 何をするブランチか

- **判定手法**: 3つ ―― 提案手法 / ΔPER のみ / RSSI のみ (§4)
- **評価指標**: AUC だけ (F1 は出さない)
- **測定モード**: simultaneous だけ (§2)
- **出力**: 折れ線グラフ (detection line) だけ。ヒートマップと ROC は出さない
- **実行**: `./script/sbatch_jobs.sh` 1本で、シミュレーションから図まで通る

`save` にあった F1・ヒートマップ・ROC 曲線・sequential 側の解析は入っていない。
削った理由は §8。

## 2. 測定モード ―― simultaneous に固定する

IEEE 802.15.4 の標準では、PER の計算に要る5つの MAC カウンタを**同時に測定できない**。
そこで1メトリックあたり 200 s の窓を順に割り当てるのが **`sequential`**。

```
    0 –   20       ウォームアップ（送信なし）
   20 –  220   W0  macTxSuccessCount
  220 –  420   W1  macRetryCount
  420 –  620   W2  macMultipleRetryCount
  620 –  820   W3  macTxFailCount
  820 – 1020   W4  macRxSuccessCount（= PER の分子）
 1020 – 1060       ドレイン
```

**`simultaneous`** は全メトリックを W0 の 200 s で同時に測る。1メトリックあたりの
観測時間が両モードで等しい (200 s) ので、時間分割そのもののコストだけを分離できる。
`simultaneous` は標準では実現できない測り方であり、実機では到達できない
**上界 (参照)** であって「従来方式」ではない。

**このブランチは simultaneous だけを解析する。** 見たいのが「時間分割のコスト」では
なく「判定手法の差」だからである。測定モードと手法を同時に振ると、折れ線の線種が
2つの軸に取られて図が読めなくなる。測定側の劣化が無い状態に条件を固定して、
手法だけを比べる。

`create_csv.py` は1本のトレースから両モードを変わらず集計する (simultaneous 側の
列には接尾辞 `_simultaneous`、sequential 側は接尾辞なし)。
**窓の定義にもシミュレーション側にも手を入れていない** ―― 窓を1つに縮めれば
30,000 ランの実時間は縮むが、シミュレーション条件そのものが `save` と変わって
過去の結果と比較できなくなるため。`analyze_csv.py` が sequential 側の列を
読まないだけである (`COLUMN_SUFFIX = "_simultaneous"` 固定)。

窓の定義は `script/interference_2pan_config.py` の `METRIC_WINDOW_ORDER` /
`metric_window()` / `simultaneous_window()` が唯一の定義元。

## 3. PER の定義

```
PER = 1 − (受信側が実際に受信したデータフレーム数)
          / (macTxSuccessCount + macRetryCount + macMultipleRetryCount + macTxFailCount)
```

分子は**受信側**の受信数、分母は**送信側**の MAC 再送カウンタ4種の和。
値は `[0, 1]` にクリップする。実装は `script/analyze_csv.py::_one_side_per()`。
`save` から変えていない。

| 方向 | 分子 | 分母の接頭辞 |
|---|---|---|
| UL（デバイス→コーディネータ） | `PANn_PC_Rx_from_Dev{d}` | `PANn_Dev{d}_to_Co_` |
| DL（コーディネータ→デバイス） | `PANn_Dev{d}_Rx_from_PC` | `PANn_Co_to_Dev{d}_` |

`macCsmaFailCount` は分母に入れていない。CSMA バックオフ上限による破棄は
「電波に出したが届かなかった」ではなく「混んでいて出せなかった」であり、
伝送路の品質を測る PER とは別の現象だという判断。

### 既知の問題: PER が構造的に負になり得る

分母から `macCsmaFailCount` を外しているため、**一度は電波に出て受信側に届いたのに
分母に入らないフレーム**が存在する（`driot_mac.cpp:841` の `ProcessCcaFailure` が
再送の途中でも発火し、`retryTxCount++` がコメントアウトされているため
`create_csv.py` が `csma_fail` に分類する）。

W0 内の1ノード・1方向について、`N = S+R+M+F` を分母、`a` を `F` のうち受信側に
一度も届かなかった数、`c` を `csma_fail` のうち届いていた数とすると

```
n_rx = N − a + c        PER = (a − c) / N
```

となり、`c > a` のとき負になる。simultaneous の実測クリップ率は **0.278%**
（分母に `macCsmaFailCount` を足せば `c ≤ C` より `a − c + C ≥ 0` が常に成立し、
クリップは厳密に 0 件になる）。

**この挙動は把握した上でそのままにしてある。** 3手法とも同じ PER を使うので、
手法間の比較には影響しない。直すなら `_one_side_per()` の分母に
`macCsmaFailCount` を1項足すところから。

## 4. 判定の統計量 ―― 3手法

どれも Seed ごとに1つのスカラー (干渉指標) を出し、「値が大きいほど干渉あり」の
向きに揃える。対象は `RSSI != 0` の端末 (= 1フレームも受信できなかった端末を除く)
で3手法とも共通。絞り込みは `analyze_csv.py::_iter_seeds()` に集約してある。

| 手法 | キー | 指標 | 使う量 |
|---|---|---|---|
| 提案手法 | `proposed` | RSSIビンごとの ΔPER 分散の、そのSeed内での**最大値** | ΔPER + RSSI |
| ΔPER のみ | `dper` | 全端末の ΔPER の分散（ビン分けしない） | ΔPER |
| RSSI のみ | `rssi` | 全端末の**平均 RSSI** | RSSI |

`ΔPER_d = PER_DL(d) − PER_UL(d)`。定義元は `analyze_csv.py` の
`DETECTION_METHODS` / `_score_proposed()` / `_score_dper()` / `_score_rssi()`。

**ベースラインは提案手法から材料を1つずつ抜いたものである。** `dper` は提案手法から
`select_bins()` を外しただけなので、提案手法との差がそのまま**RSSI ビン分割の寄与**に
なる。`rssi` は ΔPER を一切使わない。この2つを下に敷くことで、提案手法の性能が
「ΔPER を見ているから」なのか「RSSI でビン分けしているから」なのかを分けて読める。

### 提案手法のビン

RSSI でビン分けする。ビンの起点は**チャネル固有の固定値**
`RX_SENSITIVITY_DBM[ch] + 3.0 dBm`、幅 10 dBm（`analyze_csv.py` の
`RSSI_BIN_ANCHOR_OFFSET_DBM` / `RSSI_BIN_SIZE_DBM`）。端末が2個未満のビンは使わない。

起点を固定値にしているのは、以前の「そのSeedの実測RSSI最小値 + 5dBm」だと基準が
データ依存で、負荷や帯域でRSSI分布がずれるだけでビン境界と端末の切れ方が変わり、
「同じリングの端末どうしを比べる」という前提がぶれていたため。最弱端を落とす理由
自体は変わらず、セル端は PER が 0.5 付近になり二項ノイズ `p(1-p)/n` が最大になるので、
干渉が無くても端末間のばらつきが大きく出て誤検知の床を決めてしまうからである。

### 向きの扱い

3手法とも `METHOD_SIGN` が `+1`、つまり「大きいほど干渉あり」で片側固定。
`rssi` を `+1` に置いているのは、干渉で弱い端末のフレームが落ちるぶん、受信できた
フレームの平均RSSIが上振れするという想定による。

**AUC の向きは補正しない** (`max(auc, 1-auc)` のような処理を入れない)。
想定が外れていれば AUC が 0.5 を下回る形で現れるが、それは「指標が干渉の有無と
逆相関している」という情報そのものである。向きを変えたくなったら `METHOD_SIGN` の
1行だけを `-1` にする。詳細は `docs/auc.md`。

### スコアを作れなかった Seed

`proposed` は有効ビンが1つも作れなかったとき、`dper` は端末が2台未満のときに
スコアを作れない。そのときは `METHOD_DEGENERATE_SCORE`（干渉の証拠が最も弱い側の端）を
入れ、件数を検知結果CSVの `n_degenerate_*` 列に残す。`rssi` だけは平均RSSIが dBm で
下限を持たないので `0.0` ではなく `-inf` を入れる（`0.0` は実測値 -60 dBm 前後より
遥かに大きく、最強の陽性証拠に化けてしまう）。`save` の実データでは縮退は 0 件だった。

## 5. 実行

```sh
./script/sbatch_jobs.sh
```

これ1本で、config 生成 → シミュレーション → トレース解析 → 3手法の解析 →
折れ線グラフ まで通る。

パイプラインの形:

1. `interference_2pan_config.py` が Jinja2 テンプレートから
   `.config`/`.pos`/`.statconfig` をパラメータスイープ分生成する
   （12帯域ペア × 負荷 5×5 × Seed 100 = 30,000 ラン）
2. 各ランを `sim_worker_slurm.sh` 経由で SLURM に投入する。2,000 件ずつのバッチ
3. `create_csv.py` が `.trace` を 50 並列で解析し `plots/simulation_results.csv` に集約。
   中間ファイル（`.config`/`.pos`/`.statconfig`/`.trace`/`.stat`/`.done`）は
   バッチの集計が済んだ時点でまとめて削除する。`.trace` が巨大なのが主な理由だが、
   `.pos` も 30,000 ラン分で約 187MB 溜まる。
   いずれもシミュレーション中にしか読まれないので、バッチ完了後は残す必要がない
4. `analyze_csv.py` が3手法ぶんの検知結果 CSV と Seed 別スコア CSV を出す
5. `plot_detection_lines.py` が折れ線を出す（手順は `run_analysis.sh` にまとめてある）

解析だけやり直すときは `./script/sbatch_reanalyze.sh`（再シミュレーション不要。
`plots/simulation_results.csv` だけあればよい）。

**作図の設定だけ変えたときは `./script/plot_figures.sh`。** 既存の CSV から図を
作り直すだけなので、155MB の `simulation_results.csv` を再パースしない。

### SLURM ログ

シミュレーションは 30,000 ジョブ走るので、そのままだとログが 60,000 ファイルできる。
**一番最初に投入したジョブの `.out`/`.err` だけを残し、残りはバッチの集計が
終わった時点で削除する**（`sbatch_jobs.sh` の `prune_sim_logs`）。
書式を確認したいときのために1件だけ残す、という趣旨。

## 6. 出力

| パス | 内容 |
|---|---|
| `plots/simulation_results.csv` | トレースの集約（gitignore。巨大） |
| `plots/interference_detection_results_simultaneous.csv` | 検知結果。**900行** = 6帯域ペア × 25負荷 × 2PAN × 3手法 |
| `plots/detection_scores_simultaneous.csv` | Seed ごとの干渉指標。180,000行 |
| `plots/detection_lines/` | 折れ線 16枚 + 描画値の CSV |
| `plots/score_histograms/` | 干渉あり/なしのスコア分布 9枚 |

### 検知結果 CSV の列

```
bandwidth, distance, pan1_offload, pan2_offload, pan, method, auc,
n_interf_seeds, n_no_interf_seeds, n_degenerate_interf, n_degenerate_no_interf
```

`method` 列が `proposed` / `dper` / `rssi` のどれか。`save` にあった
`best_threshold` / `TP` / `FP` / `FN` / `TN` / `precision` / `recall` / `fpr` / `f1` は
無い（§8）。

### 折れ線グラフ

**相手PAN負荷 = 100% の1行だけを切り出した断面**。横軸が自PAN負荷 20–100%、
縦軸が AUC、色が相手の帯域、**線種が判定手法**（proposed 実線 / dper 破線 / rssi 点線）。

断面を相手負荷 100% に固定するのは、一番見たいのが「相手が最大負荷のとき自分の
負荷を上げると検知性能がどう落ちるか」だから。

自分 / 相手の読み替え規則:

```
A, B       = bandwidth.split("vs")        # A = PAN1 の kbps, B = PAN2 の kbps
own_bw     = A if pan == "PAN1" else B
own_load   = pan1_offload if pan == "PAN1" else pan2_offload
other_load = pan2_offload if pan == "PAN1" else pan1_offload
```

`"AvsB"` を PAN1=A と読める根拠は、ラベルを作る `get_bandwidth_label()` が
ソートする一方で `TARGET_BANDWIDTH_PATTERNS` が常に `kbps(PAN1) ≤ kbps(PAN2)` を
満たすため、そのソートが恒等写像になること。実装は
`plot_detection_lines.py::own_other()` が唯一の定義元。

対称ペア（50vs50 / 100vs100 / 200vs200）は PAN1/PAN2 の両方が「自分」に該当するが、
**PAN1 のみを採る**。非対称ペアは片方の PAN しか該当しないので、全線を 1 PAN 分
(100+100 Seed) に揃えてノイズ水準を均一にするため。

#### 枚数と凡例

`tag` が `proposed` / `dper` / `rssi` / `compare` の4種、それぞれ自帯域3枚 +
3パネル1枚で**計16枚**。`compare` が3手法の重ね描き。

凡例は**符号化の軸ごとに1ブロック**出す ―― 色 (帯域) 3項目 + 線種 (手法) 3項目。
3手法 × 3帯域を総当たりで出すと9項目になり、どれが色の違いでどれが線種の違いなのかが
読み取れなくなるため。手法1つの図では線種の軸が無いので帯域のブロックだけを出す。

#### y 軸

`save` は AUC を `(0.50, 1.0)` に固定していた。0.5 がランダム判定の水準で、軸の
下端がそのまま床を示すからである。だが**ベースラインは 0.5 を下回り得る**ので、
下回った点が枠外に消えると図が嘘になる。そこで全描画値の最小値を先に見て、
`0.5` 未満があるときだけ 0.1 刻みで切り下げる。

**枚ごとには変えない。** 図をまたいで比較できることがこの図の目的なので、
1つ決めて全図に同じ値を当てる。選ばれた下端は実行時に標準出力に出る。

### スコア分布のヒストグラム（山）

AUC は「干渉ありのスコアの山」と「干渉なしのスコアの山」の離れ具合を、閾値を
ずらしながら測ったもの。数字だけでなく山そのものを見て、どう分離しているか
（あるいは重なっているか）を確かめるための図。実装は `script/plot_score_histograms.py`。

- **対象は折れ線と同じ断面**：相手PAN負荷 100%、自帯域 × 相手帯域の 9 通り、
  対称ペアは PAN1 側だけ。読み替えは `plot_detection_lines.py::own_other()` を
  そのまま使う（規則を2箇所に書かない）
- **1枚 = 帯域の組1つ**。行が手法（proposed / dper / rssi）、列が自PAN負荷 20–100%
- 横軸：proposed は RSSIビン内 ΔPER 分散の最大値、dper は全端末の ΔPER 分散、
  rssi は全端末の平均RSSI [dBm]。つまり各手法の Seed ごとのスコアそのもの
- 縦軸：シナリオ数（Seed 数。干渉あり・なし各 100）
- **干渉ありが赤、干渉なしが青**。両群に共通のビンで半透明に重ねる
- 横軸とビンは**行（手法）ごとに全負荷で共通**にする。負荷をまたいで山の位置を
  直接比べられるようにするため。範囲が全負荷ぶんに広がるので、ビンは 40 等分にしている
- 各パネルにそのセルの AUC を書く（`analyze_csv._rank_auc()` で再計算。折れ線の値と
  一致することを実行時に突き合わせる）
- スコアを作れなかった Seed（有限でない値。rssi の `-inf`）はヒストグラムに入れず、
  件数があればパネルに注記する
- 入力は `plots/detection_scores_simultaneous.csv`。出力は
  `plots/score_histograms/hist_own{自帯域}_other{相手帯域}.pdf` の 9 枚
- `plot_figures.sh` から呼ばれるので、`run_analysis.sh` / `sbatch_reanalyze.sh` でも
  自動で作られる

## 7. ファイル構成

```
script/
  interference_2pan_config.py   config/pos/statconfig の生成。窓の定義元
  sim_worker_slurm.sh           1ランを走らせる SLURM ワーカー
  create_csv.py                 .trace -> simulation_results.csv (sequential/simultaneous 同時)
  analyze_csv.py                PER・3手法の統計量・AUC・検知結果 CSV
  plot_detection_lines.py       折れ線グラフ。own/other の読み替え規則の定義元
  plot_score_histograms.py      干渉あり/なしのスコア分布 (山) のヒストグラム
  plot_figures.sh               図だけ作り直す (解析は走らせない)
  run_analysis.sh               解析から作図まで。下の2つから呼ばれる
  sbatch_jobs.sh                全体の driver
  sbatch_reanalyze.sh           解析と作図だけやり直す
template/                       Jinja2 テンプレート
docs/README.md                  このファイル
docs/auc.md                     AUC の詳細
```

`analyze_csv.py` は CSV を作るだけで、図は出さない。図は `plot_detection_lines.py` の担当。

## 8. ここで意図的にやっていないこと

- **F1 スコア**。閾値を1点に決めたときの性能で、しかも干渉の有無を知った上で
  最適化した値なので楽観側に偏る。それ以上に、3手法のスコアは分散 (proposed/dper) と
  dBm (rssi) で単位も値域も違い、**共通の閾値グリッドが引けない**。AUC は順位しか
  見ないので単調変換に不変で、この比較が成立する。`save` に実装がある
- **ヒートマップ**（負荷 5×5 の格子）と **ROC 曲線**。手法3つを重ねられるのが
  折れ線だけだから。どちらも `save` に実装がある
- **sequential モードの解析**。§2 のとおり
- **変動係数 CV / 正規化分散 nvar による判定**。`cv` ブランチにある
- **PER のクリップの修正**。§3 のとおり把握しているが未修正。3手法に等しく効くので
  手法間の比較には影響しない
- `base_simulator`（`source/simulator/`）の変更。ライセンス上の制約で触らない
