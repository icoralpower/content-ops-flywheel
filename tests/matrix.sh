#!/bin/bash
# 账号矩阵（matrix / 跨账号复用 / CSV）验收
set -u
cd ~/dev/content-ops-flywheel
export CONTENT_OPS_HOME=~/.hermes/cache/scratch/co-mx/ledger
export CONTENT_OPS_OBSIDIAN=~/.hermes/cache/scratch/co-mx/obs
rm -rf ~/.hermes/cache/scratch/co-mx
S="python3 scripts/content_ledger.py"

echo "########## 建 3 个账号（小红书 / 抖音 / TikTok） ##########"
$S init aijike-xhs    --platform xhs    --nickname "爱极客·少年科创" --pillars "AI启蒙,硬件测评" >/dev/null
$S init aijike-dy     --platform douyin --nickname "爱极客·抖音"     --pillars "AI启蒙,亲子实验" >/dev/null
$S init aidata-tiktok --platform tiktok --nickname "AI Dad Global"   --pillars "硬件测评,AI启蒙" >/dev/null

echo; echo "########## A: 小红书（1 条跑通 2.5x，1 条不及，1 条待发） ##########"
$S predict aijike-xhs --title "10块钱的传感器能干什么" --score 4.3 --pillar 硬件测评 --metric 观看量=1万-2万 >/dev/null
$S predict aijike-xhs --title "孩子拆玩具到底该不该管" --score 3.6 --pillar AI启蒙  --metric 观看量=5000-9000 >/dev/null
$S predict aijike-xhs --title "机器人比赛的隐藏规则（还没发）" --score 3.9 --pillar AI启蒙 --metric 观看量=3000-6000 >/dev/null
$S publish aijike-xhs --id 1 >/dev/null; $S publish aijike-xhs --id 2 >/dev/null
$S collect aijike-xhs --id 1 --metric 观看量=3.8万 --likes 2100 >/dev/null
$S collect aijike-xhs --id 2 --metric 观看量=3200 --likes 90  >/dev/null
$S review aijike-xhs --id 1 --where "Hook" --evidence "评论区大量求链接" --verdict 模式 --obs "低单价硬件开箱钩子极强" >/dev/null

echo "########## B: 抖音（2 条，标题与 A 不同） ##########"
$S predict aijike-dy --title "3岁能玩的电路启蒙" --score 4.1 --pillar AI启蒙 --metric 播放量=2万-4万 >/dev/null
$S predict aijike-dy --title "厨房里的化学实验" --score 3.4 --pillar 亲子实验 --metric 播放量=8000-1.5万 >/dev/null
$S publish aijike-dy --id 1 >/dev/null; $S publish aijike-dy --id 2 >/dev/null
$S collect aijike-dy --id 1 --metric 播放量=2.6万 --likes 800 >/dev/null
$S collect aijike-dy --id 2 --metric 播放量=1.1万 --likes 210 >/dev/null

echo "########## C: TikTok（1 条，容器需 ≥3 条算校准，这里只测矩阵） ##########"
$S predict aidata-tiktok --title "Why kids should break toys" --score 4.0 --pillar 硬件测评 --metric 播放量=5000-1.2万 >/dev/null
$S publish aidata-tiktok --id 1 >/dev/null
$S collect aidata-tiktok --id 1 --metric 播放量=3.1万 --likes 1400 >/dev/null

echo; echo "########## matrix 总览 + 支柱矩阵 + 复用候选 ##########"
$S matrix --csv /tmp/matrix.csv

echo; echo "########## CSV 内容 ##########"
cat /tmp/matrix.csv
echo; echo "########## matrix 空目录必须给指引而非崩 ##########"
CONTENT_OPS_HOME=/tmp/nonexistent-co-$$ python3 scripts/content_ledger.py matrix; echo "  [期望非0] exit=$?"
echo; echo "########## 测试结束 ##########"
