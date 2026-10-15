#!/bin/bash
# content_ledger.py 全链路验收测试
set -u
cd ~/dev/content-ops-flywheel
export CONTENT_OPS_HOME=~/.hermes/cache/scratch/co-test/ledger
export CONTENT_OPS_OBSIDIAN=~/.hermes/cache/scratch/co-test/obsidian/资料库/内容运营
rm -rf ~/.hermes/cache/scratch/co-test
mkdir -p "$CONTENT_OPS_OBSIDIAN"
S="python3 scripts/content_ledger.py"

echo "########## 1. init ##########"
$S init demo-xhs --platform xhs --nickname "爱极客·少年科创" --pillars "AI启蒙,硬件测评" || exit 1

echo; echo "########## 2. predict（中文指标名 播放/点赞/收藏/涨粉 走别名归一；维度分自动加权） ##########"
$S predict demo-xhs --title "10块钱的传感器能干什么" \
  --dim-score hook=4.5 --dim-score retention=4.0 --dim-score value=4.5 --dim-score scene=4.0 \
  --dim-score engage=4.0 --dim-score convert=4.5 --dim-score native=4.5 \
  --metric 播放=1万-2万 --metric 点赞=300-600 --metric 收藏=100-300 --metric 涨粉=30-80 \
  --note "同题材上条2.1万播放；开头换冲突式提问" --conf 0.6 || exit 1

echo; echo "########## 3. 错误指标名 / 评分越界 / 维度名写错 必须报错 ##########"
$S predict demo-xhs --title t --score 4 --metric 播发量=1000-2000; echo "  [期望非0] exit=$?"
$S predict demo-xhs --title t --score 7 --metric views=100-200; echo "  [期望非0] exit=$?"
$S predict demo-xhs --title t --score 4 --dim-score hooook=4 --metric views=100-200; echo "  [期望非0] exit=$?"

echo; echo "########## 4. 补 3 条用于校准（分数分档） ##########"
$S predict demo-xhs --title "三年级就能做的显微镜" --score 4.6 --metric 播放=2万-3万 --metric 点赞=600-1200 --note "对标爆款结构" --conf 0.7 >/dev/null
$S predict demo-xhs --title "为什么孩子拆玩具不是坏事" --score 3.9 --metric 播放=5000-9000 --metric 点赞=150-400 --note "观点型，受众偏窄" --conf 0.5 >/dev/null
$S predict demo-xhs --title "机器人比赛的隐藏规则" --score 3.2 --metric 播放=1500-4000 --metric 点赞=40-150 --note "信息密度高，钩子弱" --conf 0.4 >/dev/null

echo; echo "########## 5. publish 全部 + 重复登记必须拒绝 ##########"
for i in 1 2 3 4; do $S publish demo-xhs --id $i --url "https://www.xiaohongshu.com/explore/d$i" >/dev/null; done
$S publish demo-xhs --id 1 --url "https://x"; echo "  [期望非0] exit=$?"

echo; echo "########## 6. collect 全部（含 1.52万 / 4.2w 简写；混用便捷 flag） ##########"
$S collect demo-xhs --id 1 --metric 播放=1.52万 --likes 830 --collects 420 --comments 96 --fan-delta 74 \
  --top-comments "这个传感器哪里买;二年级能玩吗;求教程"
$S collect demo-xhs --id 2 --metric views=4.2w --likes 2100 --collects 1300 --fan-delta 210 --top-comments "求同款;求链接"
$S collect demo-xhs --id 3 --metric views=8600 --likes 240 --collects 190 --fan-delta 41 --top-comments "说得太对了"
$S collect demo-xhs --id 4 --metric views=2600 --likes 78 --collects 44 --fan-delta 12 --top-comments "太专业看不懂"

echo; echo "########## 7. report（应检出低分条大幅低于、高分条超出；命中率不宜 100%） ##########"
$S report demo-xhs

echo; echo "########## 8. list（状态语义: 预测中/已发布/已对比/已复盘 必须区分） ##########"
$S list demo-xhs

echo; echo "########## 9. review 复盘（缺字段必须拒绝；verdict 只收 模式/运气） ##########"
$S review demo-xhs --id 4 --where "Hook" --verdict 模式; echo "  [期望非0] exit=$?"
$S review demo-xhs --id 4 --where "完播/hook 强度不足，前3秒直接进参数表" \
  --evidence "热评第一条是「太专业看不懂」，说明开场就丢失了非专业家长" \
  --verdict 模式 --obs "技术型选题开场必须先给生活化冲突，再进参数" 
$S review demo-xhs --id 4 --where "重复" --evidence "x" --verdict 玄学 --obs "y"; echo "  [期望非0] exit=$?"

echo; echo "########## 10. calibrate（秩相关 + 分档 + 维度失效检测） ##########"
$S calibrate demo-xhs

echo; echo "########## 11. 指纹篡改检测 ##########"
python3 - <<'PY'
import json,os
p=os.path.expanduser(os.environ["CONTENT_OPS_HOME"])+"/state/demo-xhs.json"
d=json.load(open(p,encoding="utf-8"))
d["items"][0]["predicted"]["views"]=[100,200]   # 偷改预测区间
json.dump(d,open(p,"w",encoding="utf-8"),ensure_ascii=False,indent=2)
print("  已把 #1 的预测区间偷改成 [100,200]")
PY
$S report demo-xhs --id 1 | tail -6
echo; echo "  list 里的篡改标记:"; $S list demo-xhs | grep "改过"

echo; echo "########## 12. export + Obsidian 落盘验证 ##########"
$S export demo-xhs
echo "--- 台账目录:"; find "$CONTENT_OPS_HOME" -type f | sed "s|$CONTENT_OPS_HOME/||"
echo "--- Obsidian 目录:"; find "$CONTENT_OPS_OBSIDIAN" -type f | sed "s|$CONTENT_OPS_OBSIDIAN/||"

echo; echo "########## 13. 产物抽样 ##########"
echo "--- 复盘 Markdown:"; ls "$CONTENT_OPS_HOME/accounts/demo-xhs/retrospectives/" 2>/dev/null
head -30 "$CONTENT_OPS_HOME/accounts/demo-xhs/retrospectives/"*.md 2>/dev/null
echo; echo "--- observations.md:"; cat "$CONTENT_OPS_HOME/accounts/demo-xhs/observations.md"
echo; echo "--- ledger.md 前 12 行:"; head -12 "$CONTENT_OPS_HOME/accounts/demo-xhs/ledger.md"
echo; echo "########## 测试结束 ##########"
