# content-ops-flywheel · 内容运营校准飞轮

把"内容直觉"变成**可回测的预测**：发布前锁死预测区间和依据，发布后回采算偏差，同一偏差攒够 3 条证据才允许改评分卡。

自研实现，面向中文内容平台（小红书 / 抖音 / 视频号 / B站 / 公众号）+ TikTok，**支持账号矩阵**。

## 为什么自己写而不是用现成的

方法论来自 `bianzigege/mcn-content-ops`（八步飞轮 + 七维评分卡 + 反幻觉机制）——**方法值得学，代码不值得依赖**。实测原仓库发现六处会让人白干的问题：

| # | 问题 | 后果 | 本实现 |
|---|---|---|---|
| 1 | 仓库**无许可证**（默认保留所有权利） | 不可复制/修改/再分发/商用 | 只采用方法层思想，代码全部重写 |
| 2 | `top_comments` 文档画在顶层、代码写进 `actual` | 顶层永远是死字段 | 只存一处 |
| 3 | schema 写 `gmv_thb`、脚本只认 `gmv` | 键名对不上时**静默不进统计**，不报错 | 统一别名表，不认识就报错 |
| 4 | 数据目录相对 cwd | 换目录跑就"账号未初始化" | 固定绝对路径 + 环境变量 |
| 5 | `report` 顺手置 `reviewed=True` | "看过数据"冒充"复盘完成" | `reported_at` / `reviewed_at` 分离 |
| 6 | `score` 不校验范围；`--fan` 与 `fan_delta` 命名打架 | 脏数据 + 预测回填对不上 | 越界拦截 + 同一张别名表 |

另外原版**只有单账号单文件**，做不了矩阵——这正是自研最大的增量。

## 安装

```bash
# 脚本直接可执行，无第三方依赖（Python 3.8+）
chmod +x scripts/content_ledger.py
python3 scripts/content_ledger.py --help
```

作为 skill 使用：仓库根目录即 skill 目录（`SKILL.md` + `scripts/` + `references/`）。已登记到 skillshare 并同步至 Hermes / Codex / OpenClaw / OpenCode：

```bash
bash install.sh        # skillshare install --force 登记 + sync + 建 content-ledger 软链
```

⚠️ 手动把目录 `cp` 进 `~/.config/skillshare/skills/` **不会被登记**，`sync` 也不会链接到各端——必须走 `install.sh`（或 `skillshare install <路径> --force`）。

## 命令速查

```bash
L=python3\ scripts/content_ledger.py

$L init <账号> --platform xhs --nickname "名字" --pillars "支柱1,支柱2"
$L predict <账号> --title T --dim-score hook=4.5 ... --metric 播放=1万-2万 --note "依据" --conf 0.6
$L publish <账号> --id N --url U
$L collect <账号> --id N --metric 播放=1.52万 --likes 830 --top-comments "评论1;评论2"
$L report  <账号>            # 偏差对比（不等于复盘完成）
$L review  <账号> --id N --where 环节 --evidence 评论证据 --verdict 模式|运气 --obs "观察"
$L calibrate <账号>          # 秩相关 + 分档 + 失效维度检测
$L list    <账号>
$L export  <账号>            # 导出 Markdown + 同步 Obsidian
$L matrix  [--csv out.csv]   # 账号矩阵总览 + 支柱矩阵 + 跨账号复用候选
$L due     [--all] [--json]  # 到点该回采的条目（无待采则静默，供 cron 看门狗）
```

环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `CONTENT_OPS_HOME` | `~/内容运营台账` | 台账数据根（绝对路径） |
| `CONTENT_OPS_OBSIDIAN` | `~/Documents/Obsidian Vault/资料库/内容运营` | 复盘 Markdown 镜像目标 |

## 目录结构

```
content-ops-flywheel/
├── SKILL.md                      # 八步飞轮 + 硬约束 + 接驳现有流程
├── README.md
├── scripts/
│   ├── content_ledger.py         # 引擎（单文件，零依赖）
│   └── due_collect.py            # 回采看门狗（cron --no-agent --script）
├── references/
│   ├── rubric-cn.md              # 七维评分卡中文版 + 评级锚点 + 升级流程
│   └── platform-metrics.md       # 平台口径 / 采集窗口 / 别名表
└── tests/
    ├── test_unit.py              # 解析·判定·秩相关·指纹（含边界）
    ├── acceptance.sh             # 全链路验收（含错误路径必须报错）
    ├── matrix.sh                 # 账号矩阵验收
    └── due.sh                    # 回采提醒验收（含看门狗静默验证）
```

## 设计原则

1. **不静默失败**——指标名认不出、评分越界、复盘缺字段、重复登记发布，一律报错退出。
2. **预测不可篡改**——`predict` 生成 sha256 指纹，`predict` 后改动会被 `report` / `list` 标 ⚠ 检出。
3. **口径跟着平台走**——报告里说"观看量"（小红书）、"播放量"（抖音）、"阅读量"（公众号），不说"流量"。
4. **防过拟合**——命中率 ≥95% 提醒区间太宽，≤30% 提醒区间没锚基线；评分卡改动用近 10 条回测。
5. **复盘是复利的唯一来源**——矩阵总览直接报"未复盘 N 条"。

## 台账产物

```
$CONTENT_OPS_HOME/
├── state/<账号>.json                 # 机器状态（预测指纹、实际值、复盘）
└── accounts/<账号>/
    ├── account.md                    # 账号档案 + 评分卡 + 变更日志
    ├── observations.md               # 观察记录（★ 标记已攒够 3 条可升级）
    ├── ledger.md                     # 全量台账表
    └── retrospectives/RR-*.md        # 逐条复盘（自动镜像到 Obsidian）
```

## 测试

```bash
python3 tests/test_unit.py     # 单元
bash tests/acceptance.sh       # 全链路（含错误路径）
bash tests/matrix.sh           # 矩阵
bash tests/due.sh              # 回采提醒（含看门狗静默验证）
```

## 回采提醒（看门狗）

`content-ledger due` 列出到点该回采的条目，并直接给出可复制的 `collect` 命令；**没有待采时零输出**。`due --all` 连未到期/已采的一起列，`due --json` 给程序消费。

自动化（**当前未启用**，等有真实发布记录后再开）：

```bash
cp scripts/due_collect.py ~/.hermes/scripts/
hermes cron create "0 10 * * *" --name "内容台账·回采提醒" \
  --no-agent --script due_collect.py --deliver local
```

`--no-agent` 不调模型、不花 token，脚本有输出才推送。数字必须从平台后台人肉抄录——自动抓数会让校准失去可信度。

## 来源与授权

方法论思想借鉴 `bianzigege/mcn-content-ops`（作者：辫子哥哥）。原仓库未附许可证，本仓库**不包含其任何代码或文字**，实现与文档均为独立重写。著作权不保护方法、流程本身，故飞轮与评分卡的思路可自由采用。

本仓库代码以 MIT 授权。
