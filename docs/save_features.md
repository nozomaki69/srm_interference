# save ブランチの機能を icc に取り込む

icc は「3手法（proposed / dper / rssi）の AUC 比較」に絞ったブランチだった。
save にある次の4つを、**3手法ぶん**取り込む。

1. **multi-query（sequential）**：測定モード sequential も解析し、single-query（simultaneous）と比べる
2. **ヒートマップ**：PAN1 負荷 × PAN2 負荷の 5×5 格子に AUC を色で出す
3. **ROC 曲線**：Seed 別スコアから曲線を描く
4. **ブートストラップ 95% 信頼区間**：1000 回。AUC の折れ線に髭で出す

F1（最良閾値での性能）は取り込まない。icc の方針どおり、3手法はスコアの単位が
違って共通の閾値グリッドが引けないので AUC だけで比べる（README §8）。

## 1. multi-query（sequential）

`create_csv.py` は1本のトレースから両モードの列を出しているので（sequential は接尾辞なし、
simultaneous は `_simultaneous`）、**シミュレーションのやり直しは要らない**。
`analyze_csv.py` に `--mode {sequential,simultaneous}` を足す（既定は従来どおり simultaneous）。
出力の名前は save と同じ規約：

| モード | 凡例での呼び名 | 検知結果 / Seed 別スコア |
|---|---|---|
| simultaneous | single-query | `*_simultaneous.csv`（従来と同じ） |
| sequential | multi-query | 接尾辞なし（`interference_detection_results.csv` など） |

sequential の CSV は `simulation_results.csv` からの**再解析が必要**で、これは計算機でしかできない
（手元に無い）。sequential の CSV が無いあいだ、作図は sequential 側を飛ばして注記を出す。

### 負荷のふるい分け

`analyze_csv.py` は `interference_2pan_config.OFFERED_LOAD_PERCENTS`（20〜100%）に無い負荷の
行を読み飛ばし、件数を表示する。icc_load200（20〜200%）の `simulation_results.csv` は
icc の全条件を含むので、**icc_load200 のシミュレーションが終わればその CSV で icc を再解析できる**
（設定は負荷のグリッド以外 icc と同じで、Seed も同じ）。

## 2. 図

| 図 | single-query | multi-query |
|---|---|---|
| 折れ線（3手法） | `plots/detection_lines/`（従来） | `plots/detection_lines_sequential/` |
| 折れ線（モード比較） | `plots/detection_lines_mode_compare/`（手法ごとに single 実線 / multi 点線） | ← |
| ヒートマップ | `plots/heatmaps_auc_simultaneous/{method}/` | `plots/heatmaps_auc/{method}/` |
| ROC | `plots/roc/simultaneous/` | `plots/roc/sequential/` |
| スコア分布 | `plots/score_histograms/`（従来） | `plots/score_histograms_sequential/` |

- **折れ線の髭**：ブートストラップの 95% 区間を、線と同じ色の髭で描く。同じ負荷の髭が
  重ならないよう系列ごとに横へ少しずらす（save と同じ）。目盛りは本来の位置のまま
- **モード比較**：1枚 = 手法1つ。色が相手帯域、線種が測定モード
  （凡例 `50 kbps (single-query)` / `50 kbps (multi-query)`。save と同じ）
- **ヒートマップ**：save の `create_heatmap.py` の AUC 版をそのまま移し、手法ごとにサブフォルダを分ける。
  軸は PAN1 / PAN2 のまま（save と同じ）。1手法 12 枚（6帯域ペア × 2PAN）
- **ROC**：save の `plot_roc.py` を移す。1枚 = (自帯域, 相手帯域, 手法)、線が自PAN負荷 5本。
  1モード 27 枚
- 断面の読み替えは `plot_detection_lines.own_other()` を使う（規則を2箇所に書かない）

## 3. ブートストラップ

save の `bootstrap_auc.py` を、手法の列を持つ icc のスコアCSVに合わせて移す。
計算方法（層別の復元抽出 1000 回、パーセンタイル法、乱数シード固定、点推定は従来の AUC）は
save と同じ。出力は `plots/auc_bootstrap{,_simultaneous}.csv`（各 900 行 = 300 条件 × 3手法）。
詳細は `docs/bootstrap.md`。

## 4. 実行

- 手元（single-query だけ）：`./script/plot_figures.sh`。ブートストラップ → 折れ線 → ヒートマップ →
  ROC → スコア分布の順に作る
- 計算機（multi-query も）：`./script/sbatch_reanalyze.sh`。両モードの解析と全部の図を作り、
  両モードの検知結果CSVが 900 行ずつあることを確かめる
