# UL / DL の変動係数の分布を可視化する

## 1. 目的

干渉あり / なしで、上りリンクと下りリンクの PER の変動係数 (CV) が**実際に
どのような値を取るのか**を見る。判定方式を決める前に、分離があるのか・
どの向きに動くのか・閾値をどこに置けそうかをデータで確認するのが狙い。

背景として、ΔPER の CV は平均が 0 付近になるため破綻した（実データで τ 最大 268、
34% が縮退）。一方 UL / DL の PER は非負で平均が 0.05〜0.4 に離れているので、
CV は 0.25〜0.4 程度の狭い範囲に収まり発散しない（数値実験で確認済み）。

## 2. 統計量

`analyze_cv.compute_seed_max_cv()` と同じ定義を使う。

```
ビンごと: cv_b = std(PER in ビンb) / mean(PER in ビンb)      (ddof=0)
観測ごと: 統計量 = max_b cv_b
```

UL と DL でそれぞれ独立に計算する。ビンの切り方は `analyze_csv.select_bins()`
（起点 = 受信感度 + 3 dBm、幅 10 dBm）を共有する。

`--aggregate bin` を指定すると、max を取る前の**ビンごとの生の CV** を描く。
検知器が使うのは max だが、分布の素性を見るにはビン単位のほうが情報量が多い。

## 3. 図の設計

### 形の選択

| 図 | 形 | なぜこの形か |
|---|---|---|
| 1 | **ECDF**（累積分布）| 次の作業が「閾値を置く」ことなので、「閾値 τ で各クラスの何割が上に来るか」を直接読める形が最適 |
| 2 | **箱ひげ図**（x = 自PAN負荷）| 負荷に対して CV がどう動くかを、中央値と四分位で比較する |
| 3 | **散布図**（CV_ul × CV_dl）| UL を対照に使えるか＝比や差で分離が良くなるかを見る。y=x の線を引く |

いずれも UL / DL はパネルを分け、**色は干渉あり / なしの 2 値だけ**に使う。
色数を 2 に絞ることで CVD 下の分離に余裕を持たせる。

### 配色

`dataviz` の既定カテゴリパレットの slot 1 / slot 2 を使う。

| 役割 | light | dark |
|---|---|---|
| 無干渉 | `#2a78d6` (blue) | `#3987e5` |
| 干渉あり | `#eb6834` (orange) | `#d95926` |

検証結果（`validate_palette.js` と同じ計算を Python で実施。node が無いため）:

| mode | 通常視 ΔE | CVD 最小 ΔE | L 帯域 | 彩度 | コントラスト |
|---|---:|---:|---|---|---|
| light | 33.6 (floor 15) | 24.7 (target 8) | PASS | PASS | 4.30 / 3.12 |
| dark | 31.8 | 26.8 | PASS | PASS | 4.79 / 4.48 |

全チェック PASS。

### 色だけに頼らない

- 凡例は常に出す
- 散布図は**マーカー形状も変える**（無干渉 = 丸、干渉あり = 三角）
- ECDF は**線種も変える**（無干渉 = 実線、干渉あり = 破線）

これで CVD・白黒印刷でも識別できる。

### その他

- 二軸は使わない
- グリッドと軸は後退させる（薄いグレー、破線）
- 出力は論文に貼れる PDF

## 4. 実装

`script/plot_cv_distribution.py`（新規）

```sh
python3 script/plot_cv_distribution.py --mode conv
python3 script/plot_cv_distribution.py --mode td --aggregate bin
```

| 引数 | 既定 | 意味 |
|---|---|---|
| `--mode {td,conv}` | `td` | メトリックの測定方式 |
| `--aggregate {max,bin}` | `max` | 観測ごとの max を使うか、ビンごとの生値を使うか |
| `--pan {PAN1,PAN2,both}` | `both` | 対象 PAN |
| `--out-dir` | `plots/cv_distribution{suffix}/` | 出力先 |

データの読み込みは `analyze_csv.load_and_aggregate()` を共有する。
**`simulation_results.csv` から読むだけなので再シミュレーションは不要。**

出力:

```
plots/cv_distribution{suffix}/
  cv_ecdf.pdf        ECDF（UL / DL の2パネル）
  cv_box_by_load.pdf 箱ひげ図（x = 自PAN負荷、UL / DL の2パネル）
  cv_scatter.pdf     散布図（CV_ul × CV_dl、y=x 線つき）
  cv_summary.csv     図の元になった数値（中央値・四分位・件数）
```

## 5. 検証

1. 合成データで、干渉ありの DL だけばらつきを大きくした場合に、
   図の上で DL の分布だけが右にずれること
2. `cv_summary.csv` の中央値が図の箱の位置と一致すること
3. 生成した PDF を実際に開いて、ラベルの重なり・はみ出しが無いことを目視確認する
   （配色の検証は計算で済ませたが、レイアウトは見ないと分からない）
