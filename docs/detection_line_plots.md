# 干渉検知性能の折れ線グラフ

`script/plot_detection_lines.py` の設計と、図の読み方の記録。

## 1. なぜヒートマップでは足りないのか

検知性能はこれまで `plots/heatmaps{,_conv}/` のヒートマップでしか見られなかった。
自PAN負荷 × 相手PAN負荷の 5×5 格子に F1 を色で示したもので、1 枚 25 セル × 12 枚ある。

読みたい断面は本来ひとつで、

> **相手が最大負荷（100%）で動いているとき、自分の負荷を 20% から 100% まで上げると
> 検知性能はどう落ちるか。それは帯域の組み合わせでどう違うか。**

これはヒートマップの各枚から 1 行ずつ抜き出して並べ直さないと見えない。
さらに `create_heatmap.py` は軸を `pan1_offload`（y）/ `pan2_offload`（x）に固定して
いて（`create_heatmap.py:88-89`）、`PAN2` の図では軸の意味が入れ替わる。軸ラベルも
タイトルも削除されている（`:109`）ので、どちらが自分でどちらが相手かは図から読めない。

そこで **相手負荷 = 100% の 1 行だけを切り出した折れ線グラフ**を作る。
横軸は自PAN負荷、縦軸は F1、線は相手の帯域。**自分 / 相手を明示的に読み替える**ことが
この図のもう一つの目的である。

## 2. own / other の導出規則

結果 CSV の 1 行から、検知を行っている側（`pan` 列）を「自分」として読み替える。

```
A, B       = bandwidth.split("vs")              # A = PAN1 の kbps, B = PAN2 の kbps
own_bw     = A if pan == "PAN1" else B
other_bw   = B if pan == "PAN1" else A
own_load   = pan1_offload if pan == "PAN1" else pan2_offload
other_load = pan2_offload if pan == "PAN1" else pan1_offload
```

`"AvsB"` を「PAN1 が A kbps、PAN2 が B kbps」と読んでよい根拠は 2 つある。

1. ラベルは `get_bandwidth_label()`（`analyze_csv.py:232-236`）が
   `sorted((CHANNEL_KBPS[pan1_ch], CHANNEL_KBPS[pan2_ch]))` で作る。
2. 生成側の `TARGET_BANDWIDTH_PATTERNS`（`interference_2pan_config.py:97`）は
   全パターンが `kbps(PAN1) ≤ kbps(PAN2)` を満たす。

したがって 1 のソートは恒等写像で、順序は失われていない。
読み替えの並び順は `plot_cv_distribution.py:103-104` の慣例に合わせてある。

### 対称ペアで PAN1 のみを使う理由

`50vs50` / `100vs100` / `200vs200` では PAN1 と PAN2 の両方が「自分」の条件を満たし、
2 本の独立な系列が取れる。しかし非対称ペア（`50vs100` など）では、ある
`(own_bw, other_bw)` に該当するのは片方の PAN だけである。

両方を平均すると対称ペアの 3 本だけが 200+200 Seed、他の 6 本が 100+100 Seed となり、
**線によってノイズ水準が変わってしまう**。図の目的は 9 本を横並びで比較することなので、
対称ペアは `pan == "PAN1"` の行だけを採り、全線を 100+100 Seed に揃える。

### 抽出結果

`other_load == 100` で絞ると、`(own_bw, other_bw)` の 9 通りすべてについて
自負荷 20/40/60/80/100% の 5 点が td / conv とも欠けなく揃う。

| own \ other | 50 | 100 | 200 |
|---|---|---|---|
| 50 | `50vs50` PAN1 | `50vs100` PAN1 | `50vs200` PAN1 |
| 100 | `50vs100` PAN2 | `100vs100` PAN1 | `100vs200` PAN1 |
| 200 | `50vs200` PAN2 | `100vs200` PAN2 | `200vs200` PAN1 |

## 3. 入力

統計量は**従来の分散**（ビン内 ΔPER 分散を閾値と比較）を使う。

| 入力 | モード |
|---|---|
| `plots/interference_detection_results.csv` | td（1 メトリック 1 窓） |
| `plots/interference_detection_results_conv.csv` | conv（全メトリックを W0 で同時測定） |

どちらもリポジトリに追跡されているので、**この図の生成は計算機を使わずローカルで完結する**。

> **注意**: 現在の両 CSV は 10/2 付で、`analyze_csv.py`（10/3 更新）より古い。
> 値が最新の解析コードを反映していない可能性がある。スクリプトは入力 CSV の
> 更新時刻を標準出力に出すので、解析を回し直したら図も作り直すこと。

## 4. 出力（12 枚）

出力先は `plots/detection_lines/`。ファイル名は指標名で始める。

| ファイル | 内容 | 線 |
|---|---|---|
| `f1_own{50,100,200}_conv.pdf` | 自帯域ごと、conv のみ | 3 本 |
| `f1_own{50,100,200}_td.pdf` | 自帯域ごと、td のみ | 3 本 |
| `f1_own{50,100,200}_compare.pdf` | 自帯域ごと、conv + td | 6 本 |
| `f1_3panel_conv.pdf` | 自帯域 3 つを横並びサブプロット | 3 本/パネル |
| `f1_3panel_td.pdf` | 同上 | 3 本/パネル |
| `f1_3panel_compare.pdf` | 同上、conv + td | 6 本/パネル |

あわせて `f1_plotted_values.csv` に、実際に描画した
`(mode, own_bw, other_bw, own_load, value)` を出力する。図の数値を確かめる用と、
配色の「relief rule」（§5）への対応を兼ねる。

## 5. 符号化と体裁

- **色 = 相手の帯域**（50 / 100 / 200 kbps）。全図で統一。
- **線種 = 測定モード**。conv = 実線、td = 点線。
- **マーカー = 相手の帯域**。色に頼らず識別できるようにするための冗長符号化で、
  `plot_cv_distribution.py:41-50` が同じことをしている。

配色は dataviz のカテゴリカル枠スロット 1〜3（blue `#2a78d6` / orange `#eb6834` /
aqua `#1baf7a`）。この 3 スロットは全ペア（all-pairs）で light・dark 両モードの
ゲートを通ることが配色定義側に明記されている（最悪ペアで CVD ΔE 9.2 light /
9.4 dark、通常視 ΔE 24.0 light / 20.9 dark）。`plot_cv_distribution.py:36-40` が
スロット 1/2 を同じ出典で使っており、それを 3 色に延長した形。

ただしスロット 3 の aqua は light 面でコントラスト 3:1 を下回るため
**relief rule**（見える直接ラベルか表を添える）が適用される。対応として、
線が 3 本の図では各線の右端に直接ラベルを置き、6 本の図では凡例に加えて
`f1_plotted_values.csv` を必ず出力する。

その他:

- **図中の文字はすべて英語**。計算機（Linux）に日本語フォントが無く豆腐になるため
  （`plot_cv_distribution.py:42-43` に明文化された規則）。コメント・argparse ヘルプ・
  コンソール出力は日本語のまま。
- 体裁は `plot_cv_distribution.py` の系統に合わせる（`matplotlib.use("Agg")`、
  グリッドは `color="0.85"` の破線で `set_axisbelow(True)`、top/right スパイン非表示、
  `savefig(..., bbox_inches="tight")`）。`analyze_csv.py` の `FONT_SIZE = 45` 系は使わない。
- **y 軸は全図共通の `[0.65, 1.0]` に固定**する。図をまたいだ比較が目的なので
  自動スケールにしない。実測レンジは td 0.717–0.945 / conv 0.813–1.000。
- F1 = 2/3 ≈ 0.667 に薄い水平参照線を引く。全 Seed を「干渉あり」と判定したときの
  退化した F1 がこの値（precision 0.5 / recall 1.0）で、**これ以下は検知できて
  いないのと同じ**という下限を示す。
- 負荷グリッドは `interference_2pan_config.OFFERED_LOAD_PERCENTS`、帯域は
  `analyze_csv.CHANNEL_KBPS` から import する。`create_heatmap.py:14-18` と
  `analyze_csv.py:45-50` に「定数をハードコードせず生成側から import しろ」という
  規則があり、違反による過去の不具合がある。

## 6. 使い方

```sh
python3 script/plot_detection_lines.py                      # F1、12 枚すべて
python3 script/plot_detection_lines.py --format png         # 目視確認用
python3 script/plot_detection_lines.py --out-dir <dir>
python3 script/plot_detection_lines.py --td-csv <path> --conv-csv <path>
```

## 7. AUC

F1 と並べて AUC も出す。CSV の `auc` 列を使い、
`python3 script/plot_detection_lines.py --metric auc` で同じ12枚が AUC 版で出る。

### 定義

順位ベースの AUC（Mann-Whitney U / (n_pos * n_neg) と同じ）。

```
AUC = P(統計量_interf > 統計量_no_interf) + 0.5 * P(同値)
```

実装は `analyze_csv.py::_rank_auc()`。`scipy.stats.rankdata` で順位を取るだけで、
新しい依存は増えていない（`analyze_csv.py:14` が既に `scipy.stats` を import している）。

**閾値グリッド上の台形則にしない理由。** `VARIANCE_THRESHOLDS` は
`np.arange(0.0, 1.001, 0.001)` で 1.0 打ち切り（`analyze_csv.py:757`）なので、
統計量が 1.0 を超える条件では ROC が途中で切れて AUC が頭打ちになる。生の値の
順位を使えば打ち切りが無い。同じ理由で、`best_threshold` が 1.0 に張り付いている
セルでは F1 も頭打ちの可能性があることに注意（AUC はその影響を受けない）。

**向きを補正しない理由。** 分散の判定は `>= th` の片側固定（`analyze_csv.py:826`）
なので AUC の向きは一意に決まる。`max(auc, 1 - auc)` のような補正はしていない。
0.5 を下回ったら「統計量が干渉の有無と逆相関している」という情報そのものなので、
潰さずにそのまま出す。

**同値の扱い。** 有効ビンが1つも作れなかった Seed は統計量が 0.0 に固定される
（`analyze_csv.py:789, 809`）ので、原理的には同値が溜まり得る。`rankdata` は
同順位に midrank を与えるため、同値ペアは正しく 0.5 として数えられる。
なお 10/2 時点のデータでは退化 Seed は td / conv とも全300セルで0件だったので、
現状これは効いていない（`n_degenerate_interf` / `n_degenerate_no_interf` 列で確認できる）。

### 図の違い

y 軸と参照線は指標ごとに変える（`plot_detection_lines.py` の `METRIC_SPEC`）。

| 指標 | y 軸 | 参照線 |
|---|---|---|
| `f1` | `[0.65, 1.0]` | 2/3 ... 全 Seed を陽性と判定したときの退化した F1 |
| `auc` | `[0.50, 1.0]` | 0.5 ... ランダム判定 (chance) |

未知の指標名を渡した場合は y 軸を自動スケールにし、参照線は引かない。

### `analyze_cv.py` には入れていない

CV / nvar の方は `rule` が `ge` と `le` の両方を取り、セルごとに勝った向きが
記録される（`analyze_cv.py:200-207`）。素の `AUC` は「高い方が陽性」を前提に
するので、向きを揃える設計判断（`max(a, 1-a)` にするか、向き付きで出すか）が
別途要る。そこを決めていないので入れていない。

## 8. 計算機での再解析

`auc` 列は既存の CSV には無いので、計算機で `analyze_csv.py` を回し直す必要がある。

```sh
git fetch && git checkout cv && git pull
bash script/sbatch_reanalyze.sh          # td と conv を --no-plots で SLURM に投入
# 完了後
python3 script/plot_detection_lines.py --metric auc
```

### 再シミュレーションは不要

必要なのは `plots/simulation_results.csv` だけ。

`load_and_aggregate` は `.pos` を読んだ時点で座標を `plots/positions.csv` に
**保存してから** `.pos` を消す（`analyze_csv.py:485-491`）。保存が削除より先なので、
2回目以降は `positions.csv` だけで動く（`:472-476`）。

さらに `positions.csv` も失われていた場合でも、**検知結果 CSV は正しく出る**。
座標が無いと `_calc_distance` が NaN を返すが（`:580-586`）、`*_dist` を使うのは
`plot_distance_vs_per_errorbar` だけで、`run_interference_detection` は
`pan{1,2}_{dl,ul,rssi}` しか見ない（`:877-898`）。`--no-plots` ならそもそも無関係。

> **注意**: `script/sbatch_jobs.sh:63-71` は新しいスイープの冒頭で
> `plots/positions.csv` を削除する。キャッシュを残したいなら再解析の前に
> `sbatch_jobs.sh` を回さないこと。

### `--no-plots`

`analyze_csv.py` は検知結果 CSV を書いた後（`:972-976`）に条件別プロットのループ
（`:981-1016`）を回す。300条件 x 6枚 = **1,800枚/モード**で、しかも箱ひげ側は
`run_interference_detection` が済ませたビニングを図ごとにやり直すため、ここが
実行時間の大半を占める。

列を追加しただけの再解析ではプロットは一切変わらないので `--no-plots` で飛ばす。
2つの工程は完全に独立していて、CSV の方が先に完了している
（`run_interference_detection` はプロット関数を呼ばず、プロットループは
`interference_rows` を読まない）。

図も作り直したいときは `bash script/sbatch_reanalyze.sh --with-plots`。
