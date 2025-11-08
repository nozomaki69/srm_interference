#!/bin/bash

# 機能:
# ../ ディレクトリ（commandline/）内の全 .config ファイルを対象に、
# シミュレーションを最大5つまで並列で実行する。
#
# 実行方法:
# commandline/script/ ディレクトリから ./run_all_simulations.sh を実行するか、
# プロジェクトルートから commandline/script/run_all_simulations.sh を実行する。

# スクリプト自身の場所を基準にcommandlineディレクトリのパスを決定
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
CMD_DIR=$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)

# commandline ディレクトリに移動して実行
cd "$CMD_DIR" || exit

# .config ファイルの数をチェック
NUM_CONFIGS=$(ls -1 *.config 2>/dev/null | wc -l)
if [ "$NUM_CONFIGS" -eq 0 ]; then
  echo "警告: 実行対象の .config ファイルが '$CMD_DIR' 内に見つかりません。"
  exit 0
fi

echo "シミュレーションを開始します... (最大5並列)"
echo "対象ディレクトリ: $CMD_DIR"
echo "対象ファイル数: $NUM_CONFIGS"
echo "--------------------------------------------------"

# lsで.configファイルをリストし、xargsで並列実行
# -P 5: 最大5プロセスで並列実行
# -n 1: 一度に1つの引数（ファイル名）をコマンドに渡す
# --no-run-if-empty: 入力がない場合はコマンドを実行しない
# ./sim: 実行するシミュレーションコマンド
ls -1 *.config | sort | xargs --no-run-if-empty -P 5 -n 1 ./sim

echo "--------------------------------------------------"
echo "全てのシミュレーションが完了しました。"
