# DR-IoTモジュール用サンプルシナリオ: driot_measure_communication_dist

## 1. 概要

本シナリオは、DR-IoT の通信性能評価を目的とする。
具体的には、CoordinatorノードとDeviceノード間の距離をパラメトリックに変化させ、複数のチャネル帯域幅における通信可能距離と通信品質（PDR, スループット）を計測する。

全てのプロセスはコマンドライン上で完結するよう設計されており、VisualLabは使用しない。設定ファイルの自動生成、シミュレーションの並列実行、結果の集計とグラフ化までをスクリプトによって自動化する。

## 2. ディレクトリ構成

```
.
├── commandline/
│   ├── plots/
│   │   ├── pdr_vs_distance.png
│   │   └── throughput_vs_distance.png
│   ├── script/
│   │   ├── generate_configs.py
│   │   ├── plot_results.py
│   │   └── run_all_simulations.sh
│   ├── template/
│   │   ├── TEMPLATE.config.j2
│   │   ├── TEMPLATE.pos.j2
│   │   └── TEMPLATE.statconfig.j2
│   ├── ref/
│   │   ├── empty.txt
│   │   └── driotmodes.ber
│   ├── sim*
│   └── (generated_files)
└── README.md
```

### ファイル・ディレクトリ説明

| パス                      | 説明                                                                                                                               |
| :------------------------ | :--------------------------------------------------------------------------------------------------------------------------------- |
| `commandline/plots/`      | `plot_results.py`によって生成されたグラフ画像 (`.png`) の出力先。                                                                  |
| `commandline/script/`     | 本シナリオの自動化処理を担うスクリプト群。                                                                                         |
| `.../generate_configs.py` | **設定ファイル生成スクリプト (Python)**。`template/`ディレクトリにあるJinja2テンプレート（`.j2`ファイル）を使用して、シミュレーションに必要な設定ファイル（`.config`, `.pos`, `.statconfig`）を動的に生成する。距離とチャネル帯域幅の全組み合わせを自動で作成する。 |
| `.../run_all_simulations.sh`| **シミュレーション実行スクリプト (Bash)**。`commandline/`ディレクトリに生成された全ての`.config`ファイルを検索し、Scenargieシミュレータ (`./sim`) を実行する。`xargs`コマンドを利用して、最大5つのシミュレーションを並列で実行し、全体の処理時間を短縮する。 |
| `.../plot_results.py`     | **結果プロットスクリプト (Python)**。シミュレーション完了後に出力された全`.stat`ファイルの内容を集計する。通信距離に対するPDR（パケット到達率）とMACスループットを計算し、`matplotlib`ライブラリを用いて結果をグラフ（`.png`画像）として`plots/`ディレクトリに出力する。 |
| `commandline/template/`   | `generate_configs.py`が使用する**Jinja2テンプレート**群。Jinja2はPythonのテンプレートエンジンで、変数やループを使ってテキストファイル（この場合は設定ファイル）を効率的に生成できる。 |
| `commandline/sim*`        | Scenargieシミュレータの実行ファイル本体（またはそれへのシンボリックリンク）。                                                      |
| `(generated_files)`       | スクリプト実行により`commandline/`内に生成されるファイル群 (`*.config`, `*.pos`, `*.stat`, `*.trace`など)。                     |
| `README.md`               | このドキュメント。                                                                                                                 |

## 3. シミュレーションパラメータ

*   **ノード構成**:
    *   Coordinator: 1台 (Node ID: 1)
    *   Device: 1台 (Node ID: 2)
*   **距離**: 1 km から 20 km まで 1 km 刻み
*   **チャネル帯域幅**: 6.25, 12.5, 25, 50, 100, 200, 400 kHz
*   **トラフィック**: DeviceからCoordinatorへのCBR (Constant Bit Rate) 通信。データレートは、各チャネル帯域幅で定義された最大値に設定。

## 4. 実行手順

プロジェクトのルートディレクトリから、以下の手順でスクリプトを実行する。

### 環境設定

結果プロット用のPythonライブラリ (`numpy`, `matplotlib`) と、設定生成用の `jinja2` をインストールする。

```sh
pip install numpy matplotlib jinja2
```

### 設定ファイルの生成

`generate_configs.py` を実行し、`commandline/`ディレクトリにシミュレーション設定ファイル群を生成する。

```sh
cd commandline
python3 ./script/generate_configs.py
```

### シミュレーションの実行

`run_all_simulations.sh` を実行し、生成された設定ファイルに基づいて全シミュレーションを実行する。完了後、結果ファイル (`.stat`など) が `commandline/` に出力される。

```sh
bash ./script/run_all_simulations.sh
```

### 結果の可視化

`plot_results.py` を実行し、`commandline/plots/` ディレクトリに最終的なグラフを生成する。

```sh
python3 ./script/plot_results.py
```