# `save` ブランチ

2つの PAN が隣接したとき、自分の PAN 側の観測だけから相手の干渉を検知できるか ――
という実験の、**整理済みの最小構成**。`cv` ブランチまでに試した推定量のうち
採用したものだけを残し、それ以外を削った。

## 1. 何をするブランチか

- **判定方法**: ΔPER の RSSI ビン内分散を閾値と比較する（1つだけ）
- **測定モード**: td と conv の両方
- **出力**: ヒートマップ・折れ線グラフ・ROC 曲線
- **実行**: `./script/sbatch_jobs.sh` 1本で、シミュレーションから図まで通る

`cv` ブランチにあった変動係数 CV・正規化分散 nvar・CV 分布図・配置図・
条件別の箱ひげ図は入っていない。`auc` ブランチ系統の旧ツールチェーンも無い。

## 2. 測定モード

IEEE 802.15.4 の標準では、PER の計算に要る5つの MAC カウンタを**同時に測定できない**。
そこで1メトリックあたり 200 s の窓を順に割り当てる。これが **td**（time division）。

```
    0 –   20       ウォームアップ（送信なし）
   20 –  220   W0  macTxSuccessCount
  220 –  420   W1  macRetryCount
  420 –  620   W2  macMultipleRetryCount
  620 –  820   W3  macTxFailCount
  820 – 1020   W4  macRxSuccessCount（= PER の分子）
 1020 – 1060       ドレイン
```

対照が **conv**（conventional）で、**全メトリックを W0 の 200 s で同時に測る**。
1メトリックあたりの観測時間が両モードで等しい（200 s）ので、時間分割そのものの
コストだけを分離できる。

窓の定義は `script/interference_2pan_config.py` の `METRIC_WINDOW_ORDER` /
`metric_window()` / `conventional_window()` が唯一の定義元。
`script/create_csv.py` は1本のトレースから両モードを同時に集計し、conv 側の列には
接尾辞 `_conv` を付ける。**ゲーティングはトレースのタイムスタンプを見た後処理なので、
driot にも base_simulator にも変更は入っていない。**

## 3. PER の定義

```
PER = 1 − (受信側が実際に受信したデータフレーム数)
          / (macTxSuccessCount + macRetryCount + macMultipleRetryCount + macTxFailCount)
```

分子は**受信側**の受信数、分母は**送信側**の MAC 再送カウンタ4種の和。
値は `[0, 1]` にクリップする。実装は `script/analyze_csv.py::_one_side_per()`。

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

となり、`c > a` のとき負になる。実測のクリップ率は **td 9.50% / conv 0.278%**。
conv は分母に `macCsmaFailCount` を足すとクリップが**厳密に 0 件**になる
（`c ≤ C` なので `a − c + C ≥ 0` が常に成立する）。td は分子 `Rx(W4)` と分母
`S(W0)+R(W1)+M(W2)+F(W3)` が互いに素なフレーム集合で包含関係の根拠自体が無く、
窓間のサンプリング雑音が主因（クリップが低負荷ほど多い ―― 20% で 17.4%、
100% で 4.9% ―― という負荷依存がその裏付け）。

**この挙動は把握した上でそのままにしてある。** 直すなら `_one_side_per()` の分母に
`macCsmaFailCount` を1項足すところから。

## 4. 検知の統計量

各 Seed について、

1. デバイスごとに `ΔPER = PER_DL − PER_UL` を取る
2. RSSI でビン分けする。ビンの起点は**チャネル固有の固定値**
   `RX_SENSITIVITY_DBM[ch] + 3.0 dBm`、幅 10 dBm（`analyze_csv.py` の
   `RSSI_BIN_ANCHOR_OFFSET_DBM` / `RSSI_BIN_SIZE_DBM`）
3. ビンごとに ΔPER の分散を取り、**その Seed 内での最大値**を干渉指標とする

起点を固定値にしているのは、以前の「そのSeedの実測RSSI最小値 + 5dBm」だと基準が
データ依存で、負荷や帯域でRSSI分布がずれるだけでビン境界と端末の切れ方が変わり、
「同じリングの端末どうしを比べる」という前提がぶれていたため。最弱端を落とす理由
自体は変わらず、セル端は PER が 0.5 付近で二項ノイズ `p(1-p)/n` が最大になり、
干渉が無くても端末間のばらつきが大きく出て誤検知の床を決めてしまうからである。

この指標を閾値と比較して干渉あり/なしを判定し、F1 が最大になる閾値を探す
(`evaluate_interference_detection()`)。あわせて閾値に依らない分離度として
順位ベースの AUC も出す (`_rank_auc()`)。

## 5. 実行

```sh
./script/sbatch_jobs.sh
```

これ1本で、config 生成 → シミュレーション → トレース解析 → td/conv 両モードの
解析 → ヒートマップ → 折れ線グラフ → ROC 曲線 まで通る。

パイプラインの形:

1. `interference_2pan_config.py` が Jinja2 テンプレートから
   `.config`/`.pos`/`.statconfig` をパラメータスイープ分生成する
   （12帯域ペア × 負荷 5×5 × Seed 100 = 30,000 ラン）
2. 各ランを `sim_worker_slurm.sh` 経由で SLURM に投入する。2,000 件ずつのバッチ
3. `create_csv.py` が `.trace` を 50 並列で解析し `plots/simulation_results.csv` に集約。
   `.trace` は巨大なのでバッチごとに削除する
4. `analyze_csv.py --mode {td,conv}` が検知結果 CSV と Seed 別スコア CSV を出す
5. `create_heatmap.py --mode {td,conv}` / `plot_detection_lines.py` /
   `plot_roc.py` が図を出す（手順は `run_analysis.sh` にまとめてある）

解析だけやり直すときは `./script/sbatch_reanalyze.sh`（再シミュレーション不要。
`plots/simulation_results.csv` だけあればよい）。

### SLURM ログ

シミュレーションは 30,000 ジョブ走るので、そのままだとログが 60,000 ファイルできる。
**一番最初に投入したジョブの `.out`/`.err` だけを残し、残りはバッチの集計が
終わった時点で削除する**（`sbatch_jobs.sh` の `prune_sim_logs`）。
書式を確認したいときのために1件だけ残す、という趣旨。

## 6. 出力

| パス | 内容 |
|---|---|
| `plots/simulation_results.csv` | トレースの集約（gitignore。巨大） |
| `plots/interference_detection_results.csv` | 検知結果 td |
| `plots/interference_detection_results_conv.csv` | 検知結果 conv |
| `plots/heatmaps/` | ヒートマップ td（6帯域ペア × 2 PAN = 12枚） |
| `plots/heatmaps_conv/` | ヒートマップ conv（12枚） |
| `plots/detection_lines/` | 折れ線グラフ（F1・AUC で12枚ずつ + 描画値の CSV） |
| `plots/detection_scores{,_conv}.csv` | Seed ごとの干渉指標。ROC の入力 |
| `plots/roc/` | ROC 曲線（6枚） |

### ヒートマップ

自PAN負荷（縦）× 相手PAN負荷（横）の 5×5 格子に F1 を色で出す。
1枚が (帯域ペア, PAN) の1組。

### 折れ線グラフ

**相手PAN負荷 = 100% の1行だけを切り出した断面**。横軸が自PAN負荷 20–100%、
縦軸が F1 または AUC、色が相手の帯域、線種が測定モード（conv 実線 / td 点線）。

ヒートマップは 25 セル × 12 枚あり、「相手が最大負荷のとき自分の負荷を上げると
検知性能がどう落ちるか」という一番見たい断面が読み取れない。さらに
`create_heatmap.py` は軸を `pan1`/`pan2` に固定しているので PAN2 の図では
自分と相手が入れ替わる。折れ線側は**自分 / 相手に明示的に読み替えている**。

読み替えの規則:

```
A, B       = bandwidth.split("vs")        # A = PAN1 の kbps, B = PAN2 の kbps
own_bw     = A if pan == "PAN1" else B
own_load   = pan1_offload if pan == "PAN1" else pan2_offload
other_load = pan2_offload if pan == "PAN1" else pan1_offload
```

`"AvsB"` を PAN1=A と読める根拠は、ラベルを作る `get_bandwidth_label()` が
ソートする一方で `TARGET_BANDWIDTH_PATTERNS` が常に `kbps(PAN1) ≤ kbps(PAN2)` を
満たすため、そのソートが恒等写像になること。

対称ペア（50vs50 / 100vs100 / 200vs200）は PAN1/PAN2 の両方が「自分」に該当するが、
**PAN1 のみを採る**。非対称ペアは片方の PAN しか該当しないので、全線を 1 PAN 分
(100+100 Seed) に揃えてノイズ水準を均一にするため。

### ROC 曲線

`auc` 列は面積の数値でしかないので、「低 FPR 側で素直に立ち上がっているのか、
高 FPR 側でようやく稼いでいるのか」が分からない。閾値をどこに置くかの議論も
できない。そこで曲線そのものを描く。

断面は折れ線グラフと揃えてあり、相手PAN負荷 = 100% に固定。
1枚 = 自帯域 × 測定モードで 6 枚、1枚に 3 パネル（相手帯域）、
1パネルに 5 本（自PAN負荷 20–100%）、凡例に AUC を併記する。
色は順序のある量なので単一色相の濃淡（dataviz の blue ランプ 250→700）で、
負荷が上がる＝検知が難しくなる方向を濃くしている。

**ROC を引くには Seed ごとのスコアが要る。** 検知結果 CSV は最良閾値 1 点の
混同行列しか持たず、そこからは曲線を復元できない。そこで `analyze_csv.py` が
`plots/detection_scores{,_conv}.csv` にスコアを書き出す（300セル × 200 Seed）。
これを残しておけば、155MB の `simulation_results.csv` を再解析しなくても
曲線を引き直せるし、閾値の置き方を後から検討することもできる。

曲線の計算で注意している点が 1 つある。**同じスコアの点は 1 点にまとめる。**
同値を境に TP と FP が同時に増えるので、1 件ずつ点を打つと「先に TP だけ
増えた」ように見えて階段が嘘になる。こうして引いた曲線の台形則面積は
`_rank_auc()` が返す値と機械精度（2.2e-16）で一致することを実データ 600 セルで
検証してある。つまり**図に描いてある曲線の面積が、CSV の `auc` 列そのもの**である。

AUC と ROC の詳細（定義・実装・τ の動かし方・検証結果・実データの読み方）は
`docs/auc.md` にまとめてある。

## 7. ファイル構成

```
script/
  interference_2pan_config.py   config/pos/statconfig の生成。窓の定義元
  sim_worker_slurm.sh           1ランを走らせる SLURM ワーカー
  create_csv.py                 .trace -> simulation_results.csv (td/conv 同時)
  analyze_csv.py                PER・RSSIビン・分散統計量・検知結果 CSV
  create_heatmap.py             ヒートマップ
  plot_detection_lines.py       折れ線グラフ。own/other の読み替え規則の定義元
  plot_roc.py                   ROC 曲線
  run_analysis.sh               解析から作図までの手順。下の2つから呼ばれる
  sbatch_jobs.sh                全体の driver
  sbatch_reanalyze.sh           解析と作図だけやり直す
template/                       Jinja2 テンプレート
docs/README.md                  このファイル
docs/auc.md                     AUC と ROC 曲線の詳細
```

`analyze_csv.py` は CSV を作るだけで、図は出さない。
図は `create_heatmap.py` / `plot_detection_lines.py` / `plot_roc.py` の担当。

自分 / 相手の読み替え規則は `plot_detection_lines.py::own_other()` が唯一の
定義元で、`plot_roc.py` はそれを import して使う。2箇所に書くと片方だけ直して
静かにずれるため。

## 8. ここで意図的にやっていないこと

- **変動係数 CV / 正規化分散 nvar による判定**。`cv` ブランチにある。
  分散を閾値と比べる判定は統計的に弱いという問題意識から試したもので、
  このブランチには持ち込んでいない
- **条件別の箱ひげ図・距離-PER のエラーバー図・ノード配置図**。
  ヒートマップ・折れ線・ROC だけという方針のため
- **PER のクリップの修正**。§3 のとおり把握しているが未修正
- `base_simulator`（`source/simulator/`）の変更。ライセンス上の制約で触らない
