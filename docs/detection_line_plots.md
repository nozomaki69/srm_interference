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

## 7. AUC について

AUC も要望されているが、**今回は入っていない**。

`interference_detection_results*.csv` は最良閾値 1 点の混同行列しか持たず、ROC が
引けない。`auc` ブランチには sklearn ベースの ROC 実装があるが、あちらは
`analyze_csv.py` 自体を持たない別世代のツールチェーンで流用できない。

入れるときの手順:

1. `analyze_csv.py:890-904` の `interf_values` / `no_interf_values`（Seed ごとの
   最大ビン分散、各 100 要素）がそのまま使える。`evaluate_interference_detection()`
   を呼ぶ直前に AUC を計算する。
2. 分散の判定は `>= th` の片側のみ（`analyze_csv.py:826`）なので、
   `roc_auc_score` をそのまま使ってよい。`analyze_cv.py` の方は `rule` が `ge`/`le` の
   両方を取る（`analyze_cv.py:200-207`）ので、そちらに入れる場合は向きの扱いが要る。
3. 退化した Seed は 0.0 に固定される（`analyze_csv.py:789, 809`）ため同値が多い。
   粗い閾値グリッド上の台形則ではなく、順位ベースの tie 対応 AUC を使うこと。
   `analyze_csv.py` は既に `scipy.stats` を import しているので
   `scipy.stats.mannwhitneyu` でも出せる（sklearn 1.9.0 も利用可）。
4. `fieldnames`（`analyze_csv.py:934-940`）に `auc` を追加。
5. 計算機で `analyze_csv.py --mode td` と `--mode conv` を再実行して CSV を作り直す。
   `plots/simulation_results.csv` が要るのでローカルでは完結しない。
6. 図は `python3 script/plot_detection_lines.py --metric auc` を実行するだけ。
   スクリプト側の変更は不要。
