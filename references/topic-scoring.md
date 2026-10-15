# 选题打分：HKR 去重排序 + 垂类多样性 + 平台分级

一句话：**候选池是脏的**——同一条新闻有五个标题、三个链接、两个垂类，直接进"发布前锁预测"只会把噪声锁成基准。这一步先把池子压干净、排好序、分好平台。

```
候选池（多源、重复、噪声）→ topic_scorer → Top5 + 平台清单 → 人挑 2-3 条 → predict 锁预测
```

## 来源与授权

| 项 | 值 |
|---|---|
| 方法来源 | `github.com/lijinhongucl-pixel/content-orchestrator-lite`（HKR 模型 + 三级去重 + 多样性 + 平台分级） |
| 许可 | 上游**未附许可证** = 默认保留所有权利 |
| 处理方式 | **只取"方法/流程"层面的思想，不复制任何代码或文字**，本实现全部新写（著作权不保护方法本身） |
| 上游实测 | 其 `aggregate_hkr.py` 能跑（10→9 去重正确），但有 10 处 `/home/gem` 硬编码、脚本路径写错、7 个依赖 skill 未随仓交付 → 不可直接依赖 |

## 五个零件 → 本实现落点

| 上游零件 | 本实现 | 相比上游的改动 |
|---|---|---|
| ① HKR 公式 `round((H+K+R)/15*10, 1)` | `hkr_score()` | 加 1~5 越界校验、拦 `bool`（Python 里 `True==1` 会被静默当 1 分） |
| ② 三级去重（URL 全等 / 标题相似 / 实体词重合） | `url_key()` + `title_similarity()` + `entity_overlap()` + `dedupe()` | ①URL 先摘 `utm_*`/`fbclid`/`spm` 等跟踪参数再比；②实体重合用 `|A∩B|/min(|A|,|B|)`（不被长标题稀释）+ 停用词过滤（"重磅/发布/最新"不许凑分）；③单趟贪心聚类、保持输入顺序 → **确定性** |
| ③ 多样性保护（同垂类 Top5 最多 2 条） | `select_top()` | 改成两趟：第一趟严格守名额（宁可不满员），第二趟才破例补位并打 `backfilled` 标记 → 违规可见，不静默 |
| ④ 平台分级分配 | `assign_platforms()` + `PLATFORM_TIERS` | Top1→4 路（公众号/小红书/抖音/X）、Top2-3→2 路、Top4-5→1 路；名次超出规则返回空（不发） |
| ⑤ 各平台自检 checklist / 情绪曲线 / 认知反差公式 | **仍在 SKILL.md 与 references**，不进代码 | 这类是写作提示词，属于人/模型环节，不适合塞进脚本 |

未搬的两个上游零件（备查，将来要自建多 Agent 流水线时再取）：上游有 `event_bus.py`（文件系统 `.done` token 事件总线 + `wait_all` 超时降级）和 `pipeline_state.py`（state.json 检查点 + `fcntl` 文件锁 + `resume` 断点续跑），**功能可用但上游自身 0 引用（写了没接线）**。

## 用法

```bash
S=~/dev/content-ops-flywheel/scripts/topic_scorer.py

# 算完直接看名次表（不给 --out 就只打印）
python3 $S --input pool.json --top 5 --print-summary

# 落盘给下一步用
python3 $S --input pool.json --out ranked.json --top 5

# 调阈值试敏感度（不改文件）
python3 $S --input pool.json --similarity 0.75 --entity-overlap 0.5 --dry-run --print-summary
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--top` | 5 | 取前几名 |
| `--max-per-vertical` | 2 | TopN 内同一垂类最多几条 |
| `--similarity` | 0.6 | 标题相似度阈值（第二级） |
| `--entity-overlap` | 0.6 | 实体词重合阈值（第三级） |
| `--dry-run` | — | 只算不写 |
| `--print-summary` | — | 打印名次表 |

退出码：`0` 正常；`2` 输入有问题（文件读不到 / 非 JSON / 候选缺 title / 既无 hkr 又无 hkr_score / 结构认不出）——**任何一项都不静默跳过**。

## 输入格式（三种写法都收）

```json
{"candidates": [
  {"title": "OpenAI发布GPT-6：推理成本下降90%",
   "url": "https://openai.com/blog/gpt6?utm_source=rss",
   "summary": "可选，参与第三级实体比对",
   "vertical": "ai-models",
   "hkr": {"h": 5, "k": 5, "r": 4},
   "source": "realtime-search", "heat": 1820}
]}
```

也接受 `{"verticals": {"ai-models": [...], ...}}`（按垂类分组）和裸数组 `[...]`。
`hkr` 与 `hkr_score` 二选一：给了 `hkr` 三维就按公式折算，给了 `hkr_score` 就直接用。

输出（`--out`）：

```json
{"params": {...},
 "stats": {"input": 7, "after_dedup": 6, "merged_away": 1, "dropped_below_floor": 1},
 "top": [{"rank": 1, "hkr_score": 9.3, "title": "...", "verticals": ["ai-models","ai-paper"],
          "platforms": ["公众号","小红书","抖音","X/Twitter"], "merged_from": 2, "dedup_layer": "L2_TITLE", "aliases": [...]}],
 "others": [...], "dropped": [...]}
```

每条都带 `dedup_layer`（`L1_URL` / `L2_TITLE` / `L3_ENTITY` / 空）+ `merged_from` + `aliases`（被并掉的原标题）——**为什么算成一条是可追溯的**，这是和"只看最终 5 条"最大的区别。

## HKR 打分口径

| 维度 | 问什么 | 1 分 | 3 分 | 5 分 |
|---|---|---|---|---|
| **H** 有趣/反转 | 有没有"情理之中、意料之外" | 平铺直叙 | 有亮点 | 反直觉且能一句话说清 |
| **K** 信息量/数据 | 有没有具体数字、机制、可验证事实 | 全是形容词 | 有一两个数字 | 硬数据 + 可复现细节 |
| **R** 共鸣/争议 | 谁会因此受益/受损、会想讨论吗 | 与目标读者无关 | 沾边 | 直接关系读者利益与身份 |

合成分 `round((h+k+r)/15×10, 1)`；**低于 6.0 直接淘汰**（`dropped` 里留档）——三维合计 9 分以下意味着至少一维只有 1 分，写出来就是注水。

打分是主观的，所以**必须可复核**：把三维分数和理由一起写进候选池，事后回采时可以拿"预测准不准"反推"打分严不严"——这正是本飞轮"攒够 3 条证据才改评分卡"的纪律。

## 阈值怎么调

| 现象 | 调法 |
|---|---|
| 同一条新闻被拆成两条发了 | `--similarity` 降到 0.5 ~ 0.55，或 `--entity-overlap` 降到 0.5 |
| 不同事件被判成一条（误合并） | `--similarity` 提到 0.7，`--entity-overlap` 提到 0.7 |
| 一个垂类霸榜 | `--max-per-vertical` 降到 1 |
| 只要前 3 条 | `--top 3` |

**别一次改两个阈值**：去重是三级串联，改一处先跑一遍看 `merged_away` 和 `dropped` 的构成，确认是谁在起作用。

## 陷阱

1. **候选缺分不许放过**——脚本会直接报错并指出第几条。上游那种"缺分当 0 分悄悄排到最后"会让高分条目被埋。
2. **URL 不去跟踪参数等于没去重**——同一条新闻从 RSS、公众号、群转发拿到三个链接，只有摘掉 `utm_*` / `spm` / `fbclid` 才会判成一条。
3. **停用词表是必要的**——中文 2-gram 会把"重磅发布""最新消息"切成大量公共片段，不过滤的话任意两条新闻的实体重合度都能到 0.6。
4. `--strict` 心态同样适用：脚本给的 Top5 是**建议排序**，不是结论；最终发哪 2-3 条仍由人挑，挑完立刻 `predict` 锁预测。

## 反模式

- 别用 Top1 一条就发：Top1 分到 4 路是为了多平台铺同一事件，**不是让你把同一篇稿改标题发四遍**（内容要按平台重写，见 `content-ops-flywheel` 八步循环第 3 步）。
- 别跳过人去自动发：选题打分是确定性的，平台表达不是。
- 别把 `dropped` 扔掉：淘汰条目留着，月末看"当初淘汰的是不是后来的爆款"——这是评分卡校准的输入。
