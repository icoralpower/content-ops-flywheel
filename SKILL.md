---
name: content-ops-flywheel
description: "Use when 做内容运营的自校准闭环——发布前锁预测、发布后回采算偏差、攒够 3 条证据才改评分卡。适配小红书/抖音/视频号/B站/公众号/TikTok。"
version: 1.0.0
author: 罗霖 (Hermes Agent)
license: MIT
metadata:
  hermes:
    tags: [content-ops, 内容运营, 小红书, 抖音, tiktok, 选题, 预测, 复盘, 校准, 账号矩阵, 爱极客]
    related_skills: [topic-direction-analysis, short-video-script, showoff-content-share, education-promo-materials, xhs-minitool, mcn-content-ops]
---

# 内容运营校准飞轮

**一句话**：内容运营最大的浪费不是发得少，是**每次都在用没校准过的直觉下注**——这条飞轮就是把直觉变成可回测的预测。

## 它解决什么

绝大多数内容团队只有"前的动作"（选题、写稿、发）和"后的数据"（后台的播放/点赞），中间**缺一道锁**：发布前没人写下"我预计这条多少播放、凭什么"。结果复盘只能复盘"结果好不好"，复盘不了"判断准不准"，标准永远原地不动。

这条飞轮强制三件事：

1. **发布前锁死预测区间 + 依据**（写进台账，改了会被指纹抓到）
2. **发布后必须回采并算偏差**（不看数据 = 没发过）
3. **单条现象不算证据**——同一偏差攒够 **3 条**才允许改评分卡，改完必须回测

## 八步循环

| 步 | 动作 | 产出 | 命令 |
|---|---|---|---|
| 1 | 账号档案 + 评分卡 | `account.md` | `init` |
| 2 | 候选池（≥10 条待拍） | 选题池 | （用 `topic-direction-analysis`） |
| 3 | 写稿 | 脚本 | （用 `short-video-script`） |
| 4 | **发布前打分 + 锁预测** | 预测记录 + 指纹 | `predict` |
| 5 | 登记发布 | URL + 采集窗口 | `publish` |
| 6 | T+24h / 7d / 30d 回采数据 + 热评 | 实际值 | `collect` |
| 7 | 偏差三问 | 对比表 | `report` → `review` |
| 8 | 攒够证据升级评分卡 | rubric v2 + changelog | `calibrate` |

## 核心规则（硬约束，不是建议）

- **`predict` 必须先于发布**。事后补预测就是自欺，指纹会暴露改动。
- **预测必须是区间不是点**。点预测在内容行业是假装精确。
- **`report` ≠ 复盘完成**。`report` 只写 `reported_at`；只有补齐偏差三问才 `reviewed_at`。别让"看过数据"冒充"想明白了"。
- **改评分卡需要 3 条同向证据**，且附编号进 changelog。单条爆款就改标准 = 拟合噪声。
- **评分卡改动后必须用近 10 条数据回测**（`calibrate` 看 ρ）。
- **命中率不是越高越好**：≥95% 说明区间给太宽（等于没预测），≤30% 说明区间没锚基线。

## 用法

```bash
L=~/dev/content-ops-flywheel/scripts/content_ledger.py

# 1. 建账号（平台决定指标口径）
python3 $L init aijike-xhs --platform xhs --nickname "爱极客·少年科创" --pillars "AI启蒙,硬件测评,亲子实验"

# 2. 发布前锁预测（指标名中英/黑话随便写，会自动归一）
python3 $L predict aijike-xhs --title "10块钱的传感器能干什么" \
  --dim-score hook=4.5 --dim-score retention=4 --dim-score value=4.5 --dim-score scene=4 \
  --dim-score engage=4 --dim-score convert=4.5 --dim-score native=4.5 \
  --metric 播放=1万-2万 --metric 点赞=300-600 --metric 收藏=100-300 --metric 涨粉=30-80 \
  --note "同题材上条 2.1万；开头换冲突式提问" --conf 0.6

# 3. 发布后登记
python3 $L publish aijike-xhs --id 1 --url "https://www.xiaohongshu.com/explore/xxx"

# 4. 回过数据（--metric 和便捷 flag 都能用，支持 1.52万 / 4.2w / 10k 简写）
python3 $L collect aijike-xhs --id 1 --metric 播放=1.52万 --likes 830 --collects 420 \
  --comments 96 --fan-delta 74 --top-comments "这个传感器哪里买;二年级能玩吗"

# 5. 看偏差（不置位复盘）
python3 $L report aijike-xhs

# 6. 偏差三问复盘（四项缺一不可，verdict 只收「模式」/「运气」）
python3 $L review aijike-xhs --id 1 --where "完播/hook" \
  --evidence "热评是「太专业看不懂」，开场就丢了非专业家长" \
  --verdict 模式 --obs "技术型选题开场必须先给生活化冲突"

# 7. 校准评分卡（秩相关 + 分档 + 失效维度检测）
python3 $L calibrate aijike-xhs

# 8. 导出 & 同步 Obsidian
python3 $L export aijike-xhs
```

环境变量：
- `CONTENT_OPS_HOME`（默认 `~/内容运营台账`）——台账数据根目录，**绝对路径，不随 cwd 漂移**
- `CONTENT_OPS_OBSIDIAN`（默认 `~/Documents/Obsidian Vault/资料库/内容运营`）——复盘 Markdown 自动镜像到这里

## 接驳你现有的内容流程

```
topic-direction-analysis   ← 选题评估（第2步）
        ↓ 选中的题
short-video-script / xhs-minitool / showoff-content-share   ← 出稿（第3步）
        ↓ 成稿
content-ops-flywheel: predict   ← 发布前锁预测（第4步）★ 现有流程缺的就是这里
        ↓ 发布
content-ops-flywheel: collect / report / review   ← 回采 + 偏差三问（第6-7步）★ 复盘也缺
        ↓ 攒证据
content-ops-flywheel: calibrate → 反哺 topic-direction-analysis 的评估维度
```

关键：**`calibrate` 的输出要回填到选题评估的标准里**。否则飞轮只转一半——数据攒了，标准没动。

## 陷阱（upstream mcn-content-ops 实测踩到的，本实现已修）

| # | 坑 | 本实现 |
|---|---|---|
| 1 | 顶层 `top_comments` 是死字段，实际写进了 `actual.top_comments` | 只存一处 `item["top_comments"]` |
| 2 | schema 写 `gmv_thb`、脚本只认 `gmv` → **静默不参与命中率**，不进分母也不报错 | 中英别名统一归一，不认识的名字**直接报错** |
| 3 | 数据目录相对 cwd，换目录跑就报"账号未初始化" | 固定绝对路径 + `CONTENT_OPS_HOME` |
| 4 | `report` 顺手置 `reviewed=True`，"对比过"冒充"复盘完成" | `reported_at` / `reviewed_at` 严格分离，复盘必须补三问 |
| 5 | `score` 不校验 1-5 范围 | 越界直接拦 |
| 6 | `--fan` 回填 vs `fan_delta` 预测命名不一致 | 同一张别名表，两边共用 |

## 反模式（明令禁止）

- 为了让命中率好看而事后收窄区间 → 指纹会抓
- 单条爆款就改评分卡（样本=1）
- 维度加到 >10 个（每维样本被稀释，谁都测不准）
- 用"感觉这条会火"替代 `--note` 里的**可验证依据**（对标数据/上次同题表现/评论区问题）

## 回采节奏与提醒（★ 已记录，待启用）

飞轮靠"到点回采"驱动，人肉记 T+24h 必漏。约定节奏：

| 时点 | 动作 | 命令 |
|---|---|---|
| 发布当时 | 登记 + 确认采集窗口 | `publish --id N --windows 24h,7d` |
| T+24h | 回采主指标（多数平台流量已出 70-90%） | `collect --id N --metric 播放=... --top-comments "..."` |
| 第 7 天 | 补长尾（小红书/B站/公众号长尾占比高） | `collect --id N --window 7d` |
| 每周固定一天 | 跑偏差 + 清复盘积压 | `report <账号>` → 逐条 `review` |

**随时手动查**：`content-ledger due` —— 列出所有到点该回采的条目，并直接给出可复制的 collect 命令；**没有待采就一声不响**。`due --all` 连未到期/已采的一起列，`due --json` 给程序消费。

**自动提醒：当前未启用**（等账号跑起来、有真实发布记录后再开）。做成**零 token 看门狗**：

```bash
# 1) 看门狗放进 cron 能读的目录（必须在 ~/.hermes/scripts/ 下）
cp ~/.config/skillshare/skills/content-ops-flywheel/scripts/due_collect.py ~/.hermes/scripts/

# 2) 每天 10:00 检查；--no-agent = 不调模型不花 token，脚本输出直接推送
hermes cron create "0 10 * * *" \
  --name "内容台账·回采提醒" \
  --no-agent --script due_collect.py --deliver local
```

语法要点：`hermes cron create <schedule> [prompt]`，`--name / --script / --deliver` 都是选项——**别写 `hermes cron add "<名字>" --schedule ... --prompt ...`**，那两个选项不存在，会直接报错。
`due_collect.py` 自己找引擎：本目录 → `CONTENT_OPS_ENGINE` → PATH 上的 `content-ledger` → skill 安装位，所以拷到 `~/.hermes/scripts/` 照样跑。
空输出 = 不推送。看门狗的正确姿态：没事别吵。

两条硬规矩：
1. 提醒只报"该采哪几条"，**实际数字必须本人从平台后台抄**——自动抓数会让台账失去可信度（数据来源不干净，校准就是自欺）。
2. 提醒不发就当没发过：漏采一天，那条记录的 24h 窗口就永久废了，只能标 `--window 7d` 降级使用。

## 文件

- `scripts/content_ledger.py` —— 单文件零依赖台账引擎（Python 3.8+）；子命令 init/predict/publish/collect/report/review/calibrate/list/export/**due**/**matrix**
- `scripts/due_collect.py` —— 回采看门狗，供 `hermes cron --no-agent --script` 调用
- `references/rubric-cn.md` —— 七维评分卡中文版：评级锚点、平台微调、升级流程
- `references/platform-metrics.md` —— 各平台指标口径 + 采集窗口 + 别名表
- `tests/test_unit.py` / `acceptance.sh` / `matrix.sh` / `due.sh` —— 单元 + 全链路 + 矩阵 + 回采断言（全为可失败断言式）
- `README.md` / `install.sh` —— 项目说明与安装脚本

## 来源与授权

方法论借鉴 `bianzigege/mcn-content-ops`（辫子哥哥，八步飞轮 + 七维评分卡 + 反幻觉机制）。该仓库**未附许可证**（默认保留所有权利），故本 skill **不复制其代码或文字**，仅采用"方法/流程"层面的思想并全部重写实现（著作权不保护方法本身）。表格中的六项坑为实测复现结果，用于说明本实现为何不同。
