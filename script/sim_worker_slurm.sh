#!/bin/bash
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1

# 引数として渡された .config ファイルのパスを受け取る
CONFIG_FILE=$1

# シミュレーションの実行
/home/arimoto/opt/scensim_env/scenargie_simulator/2.2/source/driot/sim "$CONFIG_FILE"
STATUS=$?

# 正常終了したときだけ完了マーカーを置く。
# .trace はシミュレータが起動直後に開くので、途中でクラッシュしても
# 中身が途切れたファイルが残ってしまい、件数を数えるだけでは失敗を検出できない。
# sbatch_jobs.sh はこの .done の数を投入件数と突き合わせて完走を確認する。
if [ $STATUS -eq 0 ]; then
    touch "${CONFIG_FILE%.config}.done"
fi

exit $STATUS
