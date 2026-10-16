# PER 定義：受信側の受信数を分子にする版（`one_side_correct_measure`）

`correct_mesure` を起点に、PER の**分子だけ**を受信側の受信数に置き換えたブランチ。
分母は `correct_mesure` のまま（MAC 再送カウンタ4種の和）。

---

## 1. 定義

```
PER = 1 - (受信側が受信したデータフレーム数)
          / (macTxSuccessCount + macRetryCount + macMultipleRetryCount + macTxFailCount)
```

実装は `script/analyze_csv.py` の `_one_side_per()`。

### 分子に使う列

方向によって列が変わる（`create_csv.py` が出力するもの）。

| 方向 | 分母の接頭辞 | 分子（受信数） |
|---|---|---|
| UL（デバイス → コーディネータ） | `PANn_Dev{dev}_to_Co_` | `PANn_PC_Rx_from_Dev{dev}` |
| DL（コーディネータ → デバイス） | `PANn_Co_to_Dev{dev}_` | `PANn_Dev{dev}_Rx_from_PC` |

## 2. `correct_mesure` との違い

| | `correct_mesure` | `one_side_correct_measure`（本ブランチ） |
|---|---|---|
| 分子 | `macTxFailCount` | **分母 − 受信側の受信数** |
| 分母 | 4カウンタの和 | 4カウンタの和（同じ） |
| 測る側 | **送信側**（ACK が返ったかどうか） | **受信側**（実際に届いたかどうか） |
| 意味 | 再送上限まで粘っても ACK が返らなかったフレームの割合 | 受信側に届かなかったフレームの割合 |

`correct_mesure` は送信側の ACK 受信状況だけで決まる。本ブランチは受信側の受信数を
直接使うので、送達を受信側から片側（one side）で測ることになる。

`macCsmaFailCount`（CSMA でチャネルを取れず送信すらせずに破棄）と
`PANn_*_Unresolved`（シミュレーション終了時点で未確定）が分母から外れる点は
`correct_mesure` と同じ。

## 3. ★重要な注意★ 構造的に PER ≥ 0 が保証されない

分母は「決着のついた**フレーム数**」だが、分子に使う受信数は `create_csv.py` が
`Ev= RxFrame`（`frame_type == "Data"`）を **1行ごとに数えたもの**で、
**再送フレームの重複受信もそのまま加算される**。

ACK だけが失われて再送された場合、受信側は同じフレームを2回以上受け取るため、

```
受信数 > 分母   ->   1 - 受信数/分母 < 0
```

が起こり得る。実装では `[0, 1]` にクリップし、**クリップが起きた件数を必ず標準出力に出す**。

```
--- PER clip: 受信数 > 分母 となり 0 にクリップした件数 N / M (x.xx%) ---
```

`correct_mesure` の `_mac_per()` のコメントが受信数ベースを採らない理由として挙げていたのが
まさにこの重複受信の問題である（原文: 「ACKだけが失われて再送されたフレームを受信側が
重複受信して『成功』と二重に数えてしまい、ACK損失が損失として現れない」）。

**したがって実データで回したら、まずこのクリップ率を確認すること。**
率が高いなら、この定義は ACK 損失を損失として捉えられておらず、
`correct_mesure` の送信側定義より PER を過小評価していることになる。

### 重複を除いた版が必要になった場合

`create_csv.py` 側で、受信側の重複受信を除外して数える（受信済み SequenceNumber を
デバイスごとに覚えて、既知の seq の再受信をカウントしない）必要がある。
本ブランチでは `create_csv.py` には手を入れていないので、`simulation_results.csv` は
`correct_mesure` で作ったものをそのまま使える。

## 4. 実行方法

`create_csv.py` を変更していないため、**`simulation_results.csv` の再生成は不要**。
`correct_mesure` で作った既存のものをそのまま使える。

```sh
python3 script/analyze_csv.py
```

出力は `correct_mesure` と同じく `plots/interference_detection_results.csv` と
`plots/<帯域>/<距離>m/<interf|no_interf>/*.pdf`。**ファイル名が同じなので、
`correct_mesure` の結果と比較したい場合は退避してから実行すること。**

## 5. 検証したこと

`_one_side_per()` の単体テスト（実ヘッダ 1037 列を使い、列名解決も込みで確認）:

| ケース | 分母 | 受信数 | PER | 期待 |
|---|---:|---:|---:|---:|
| 通常 (UL) | 100 | 90 | 0.1000 | 0.1000 |
| 通常 (DL) | 100 | 90 | 0.1000 | 0.1000 |
| 全損（受信 0） | 100 | 0 | 1.0000 | 1.0000 |
| 全着（受信 = 分母） | 100 | 100 | 0.0000 | 0.0000 |
| 重複受信 → 負 | 100 | 110 | 0.0000 | 0.0000（クリップ検出 1 件） |
| 分母 0 | 0 | 0 | 0.0000 | 0.0000 |

加えて、合成 `simulation_results.csv`（重複受信を最大 8% 混ぜたもの）で
`load_and_aggregate()` を通し、全 PER が `[0, 1]` に収まること、
クリップ診断が機能すること（1.17%）を確認した。

## 6. このブランチに無いもの

`cfar_detection` ブランチで追加した以下は**本ブランチには入っていない**
（起点が `correct_mesure` のため）。

- `script/detect_cfar.py`（H0 のみから閾値を決める CFAR 検知）
- `create_heatmap.py` の F1 下限（0.667）対応
- `analyze_csv.py` の距離基準ノードの修正

PER 定義の比較が済んで方針が決まったら、採用する定義を `cfar_detection` 側に
取り込む形になる。
