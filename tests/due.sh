#!/bin/bash
# 回采提醒（due / 看门狗）验收 —— 断言式，任一不符 exit 1
set -u
cd ~/dev/content-ops-flywheel
H=~/.hermes/cache/scratch/co-due
export CONTENT_OPS_HOME=$H/ledger
S="python3 scripts/content_ledger.py"
D="python3 tests/_backdate.py $CONTENT_OPS_HOME"
FAIL=0
python3 -c "import shutil; shutil.rmtree('$H', ignore_errors=True)"

ok()  { echo "  ✓ $1"; }
no()  { echo "  ✗ $1"; FAIL=1; }
has() { case "$2" in *"$1"*) ok "$3" ;; *) no "$3  ← 未见「$1」" ;; esac; }
hasnt(){ case "$2" in *"$1"*) no "$3  ← 不该出现「$1」" ;; *) ok "$3" ;; esac; }

echo "########## 1. 建号 + 发 3 条，回拨时间 ##########"
$S init aijike-xhs --platform xhs --nickname "爱极客·少年科创" --pillars "AI启蒙" >/dev/null
for i in 1 2 3; do
  $S predict aijike-xhs --title "测试题$i" --score 4.0 --pillar AI启蒙 --metric views=1万-2万 >/dev/null
  $S publish aijike-xhs --id $i >/dev/null
done
$D aijike-xhs 1 26    # 24h 窗口到期
$D aijike-xhs 2 200   # 24h + 7d(168h) 都到期
$D aijike-xhs 3 3     # 未到期

echo; echo "########## 2. due：只报 #1 #2，#3 不出现 ##########"
O=$($S due); echo "$O"
has "待回采 2 条" "$O" "报出 2 条待采"
has "#1"          "$O" "#1（26h，应采 24h）在列"
has "#2"          "$O" "#2（200h）在列"
hasnt "#3"        "$O" "#3（3h，未到期）不出现"
has "另有 7d 已到期未采" "$O" "#2 提示 7d 也已到期"
has "views=<平台后台实际值>" "$O" "给出可直接复制的 collect 命令"
has "勿估算" "$O" "带「勿估算」提醒"

echo; echo "########## 3. 采 #1 的 24h → #1 消失 ##########"
$S collect aijike-xhs --id 1 --window 24h --metric views=1.6万 >/dev/null
O=$($S due)
has "待回采 1 条" "$O" "只剩 1 条"
hasnt "#1"        "$O" "已采的 #1 不再打扰"

echo; echo "########## 4. #2 采到 7d、再回拨 800h → 应转「补采 30d」 ##########"
$S collect aijike-xhs --id 2 --window 7d --metric views=2.4万 >/dev/null
$D aijike-xhs 2 800
O=$($S due)
has "#2"           "$O" "#2 仍在列（30d 到期）"
has "应采 30d 窗口" "$O" "正确升级到 30d 窗口"
has "补采"          "$O" "标为补采（已有 actual）"

echo; echo "########## 5. 全部采完 → due 必须完全静默（0 字节） ##########"
$S collect aijike-xhs --id 2 --window 30d --metric views=3.1万 >/dev/null
$S collect aijike-xhs --id 3 --window 24h --metric views=9000 >/dev/null
O=$($S due)
if [ -z "$O" ]; then ok "静默（0 字节）——cron 不会误推"; else no "应静默却输出：$O"; fi

echo; echo "########## 6. --all 列出全部状态 ##########"
O=$($S due --all); echo "$O"
has "已采"           "$O" "列出「已采」"
has "#3"             "$O" "#3 在列"
has "未到期（还有"    "$O" "#3 标为未到期（才发 3h，24h 窗口未到）"

echo; echo "########## 7. --json 机器可读 ##########"
O=$($S due --all --json)
has '"account"' "$O" "JSON 含 account 字段"
has '"state"'   "$O" "JSON 含 state 字段"
python3 -c "
import json,sys
rows = json.loads('''$O''')
assert isinstance(rows, list) and len(rows) == 3, rows
print('  ✓ JSON 可解析，3 条记录')
" || no "JSON 解析失败"

echo; echo "########## 8. 看门狗脚本（拷到 ~/.hermes/scripts/ 后自寻引擎） ##########"
mkdir -p ~/.hermes/scripts && cp scripts/due_collect.py ~/.hermes/scripts/
# 新发一条并回拨 26h：只有真有到期项，看门狗才该说话
$S predict aijike-xhs --title "看门狗题" --score 4.1 --pillar AI启蒙 --metric views=1万-2万 >/dev/null
$S publish aijike-xhs --id 4 >/dev/null
$D aijike-xhs 4 26
O=$(python3 ~/.hermes/scripts/due_collect.py)
echo "$O"
has "待回采"      "$O" "从 ~/.hermes/scripts/ 拷出去也能跑（自寻引擎）"
has "#4"          "$O" "报出到期的 #4"
hasnt "Traceback" "$O" "无异常栈"
# 采完 #4 → 看门狗必须静默
$S collect aijike-xhs --id 4 --window 24h --metric views=1.2万 >/dev/null
O=$(python3 ~/.hermes/scripts/due_collect.py)
if [ -z "$O" ]; then ok "采完后看门狗静默（cron 不误推）"; else no "应静默却输出：$O"; fi

echo; echo "########## 结果 ##########"
if [ "$FAIL" = 0 ]; then echo "✓ due 全部断言通过"; else echo "✗ 有断言失败"; fi
exit $FAIL
