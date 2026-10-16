# AUC のブートストラップ信頼区間

## 目的

AUC は条件ごとに「干渉あり 100 Seed」と「干渉なし 100 Seed」から1つの値を出しているだけで、
Seed の選び方でどれだけぶれるかが分からない。Seed を復元抽出し直すブートストラップを
**1000 回**行い、AUC の **95% 信頼区間**を出す。

## 再シミュレーションは要らない

ブートストラップに必要なのは Seed ごとのスコアだけで、これは `analyze_csv.py` が
`plots/detection_scores{,_simultaneous}.csv` に書き出してコミット済み。このスコアから
AUC を計算し直すと、検知結果 CSV の `auc` と 2モード × 300 条件のすべてで一致する
（スクリプトが実行のたびに確かめる）。したがって手元で完結し、計算機での
シミュレーションも再解析も要らない。

## 計算方法

条件（bandwidth, distance, pan1_offload, pan2_offload, pan）ごとに:

1. 干渉あり 100 個、干渉なし 100 個のスコアを、**それぞれの群の中で**復元抽出する
   （層別ブートストラップ。群の大きさは 100 / 100 のまま）
2. 抽出した 200 個で AUC を計算する。定義は `analyze_csv._rank_auc()` と同じ
   （Mann-Whitney U / (n_pos × n_neg)、同順位は midrank）
3. これを 1000 回繰り返し、1000 個の AUC の **2.5% 点と 97.5% 点**を 95% 信頼区間とする
   （パーセンタイル法）

- **点推定は今の AUC（全 Seed から出した値）のまま**。ブートストラップは区間を出すことにだけ使う。
  ブートストラップ平均は参考として列に残す
- 乱数のシードは固定（既定 0）。何度回しても同じ結果になる。回数とシードは
  `--n-boot` / `--seed` で変えられる
- パーセンタイル法なので、分布が偏った条件（AUC が 1.0 に張り付く条件など）では、
  点推定が区間の端に来ることがある。区間外に出た行があれば件数を表示する

## 出力

| ファイル | 内容 |
|---|---|
| `plots/auc_bootstrap.csv` | sequential。300 行 |
| `plots/auc_bootstrap_simultaneous.csv` | simultaneous。300 行 |

列は `bandwidth, distance, pan1_offload, pan2_offload, pan, auc, auc_boot_mean, auc_ci_low, auc_ci_high, n_boot`。

AUC の折れ線（`plot_detection_lines.py --metric auc`）は、この CSV があれば各線の
95% 区間を同じ色の髭（エラーバー）で重ねる。同じ負荷の髭が真上に重ならないよう、
系列ごとに横へ少し（1.5% 刻み）ずらして描く。目盛りは本来の負荷の位置のまま。`auc_plotted_values.csv` にも
`auc_ci_low` / `auc_ci_high` 列が付く。F1 の図は変えない。

## 実行

```sh
python3 script/bootstrap_auc.py                       # 数十秒
python3 script/plot_detection_lines.py --metric auc   # 髭 (エラーバー) 付きの折れ線
```

`script/plot_figures.sh` が折れ線の前に `bootstrap_auc.py` を呼ぶので、
`run_analysis.sh` / `sbatch_reanalyze.sh` で解析をやり直したときも自動で作られる。
