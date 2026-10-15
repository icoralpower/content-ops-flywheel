#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""topic_scorer 单元测试 —— 打分公式、三级去重、多样性保护、平台分级、确定性。

运行: python3 tests/test_topic_scorer.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import topic_scorer as ts  # noqa: E402

FAIL = []


def eq(got, want, name):
    if got != want:
        FAIL.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  ✗ {name}: got {got!r}, want {want!r}")
    else:
        print(f"  ✓ {name}")


def ok(cond, name):
    eq(bool(cond), True, name)


def raises(fn, exc, name):
    try:
        fn()
    except exc:
        print(f"  ✓ {name}（正确抛出 {exc.__name__}）")
        return
    except Exception as e:  # noqa: BLE001
        FAIL.append(f"{name}: 抛了 {type(e).__name__} 而非 {exc.__name__}")
        print(f"  ✗ {name}: 抛了 {type(e).__name__} 而非 {exc.__name__}")
        return
    FAIL.append(f"{name}: 没报错")
    print(f"  ✗ {name}: 没报错")


print("## HKR 合成分")
eq(ts.hkr_score(5, 5, 5), 10.0, "满分三维 → 10.0")
eq(ts.hkr_score(1, 1, 1), 2.0, "最低三维 → 2.0")
eq(ts.hkr_score(5, 4, 5), 9.3, "9.33 保留 1 位小数 → 9.3")
eq(ts.hkr_score(4, 4, 5), 8.7, "8.66 → 8.7")
raises(lambda: ts.hkr_score(0, 3, 3), ValueError, "维度 0 越界必须报错")
raises(lambda: ts.hkr_score(6, 3, 3), ValueError, "维度 6 越界必须报错")
raises(lambda: ts.hkr_score("5", 3, 3), ValueError, "字符串维度必须报错")
raises(lambda: ts.hkr_score(True, 3, 3), ValueError, "布尔当数字要拦（Python 里 True==1）")

print("\n## URL 归一化（同一新闻不同 utm 必须判同一条）")
a = ts.url_key("https://Example.com/news/gpt6/?utm_source=x&utm_medium=wechat&id=7")
b = ts.url_key("https://example.com/news/gpt6?id=7")
eq(a, b, "去 utm + host 小写 + 去尾斜杠")
eq(ts.url_key("https://a.com/p#sec2"), ts.url_key("https://a.com/p"), "去 fragment")
ok(ts.url_key("https://a.com/p?id=1") != ts.url_key("https://a.com/p?id=2"), "不同 id 不误判")
eq(ts.url_key(""), "", "空 URL 归零")

print("\n## 标题相似度")
eq(ts.title_similarity("OpenAI 发布 GPT-6", "OpenAI 发布 GPT-6"), 1.0, "完全相同 → 1.0")
sim = ts.title_similarity("OpenAI发布GPT-6：推理成本下降90%", "OpenAI发布GPT-6！推理成本直降90%")
ok(sim >= 0.6, f"同事件改写（{sim:.2f}）≥ 0.6，应判重")
sim2 = ts.title_similarity("OpenAI发布GPT-6", "特斯拉裁员三千人")
ok(sim2 < 0.4, f"不同事件（{sim2:.2f}）远低于阈值")
eq(ts.title_similarity("", "x"), 0.0, "空标题不炸")

print("\n## 实体词重合度（停用词不许抬分）")
ov = ts.entity_overlap("OpenAI发布GPT-6：推理成本下降90%", "OpenAI发布GPT-6！推理成本直降90%")
ok(ov >= 0.6, f"同事件实体重合（{ov:.2f}）≥ 0.6")
ov2 = ts.entity_overlap("OpenAI发布GPT-6", "谷歌发布Gemini-3")
ok(ov2 < 0.6, f"不同公司不同模型（{ov2:.2f}）不判重")
ov3 = ts.entity_overlap("重磅发布最新消息", "重磅推出全新产品")
eq(ov3, 0.0, "全是停用词 → 重合度 0（不许靠\"重磅/发布\"凑分）")

print("\n## 三级去重")
# L1：URL 归一化后完全相同（不同 utm 也算同一条）
l1 = [{"title": "OpenAI发布GPT-6：推理成本下降90%", "url": "https://a.com/x?utm_source=rss",
       "vertical": "ai-models", "hkr": {"h": 5, "k": 5, "r": 4}, "source": "realtime"},
      {"title": "OpenAI 发布 GPT-6，推理成本降九成", "url": "https://a.com/x",
       "vertical": "ai-paper", "hkr": {"h": 5, "k": 4, "r": 5}, "source": "aihot"},
      {"title": "特斯拉裁员三千人", "url": "https://c.com/t", "vertical": "auto",
       "hkr": {"h": 3, "k": 3, "r": 4}}]
kept, merged = ts.dedupe(ts.prepare(l1))
eq(len(kept), 2, "3 条 → 2 条（URL 归一化后同一条并掉）")
eq(merged, 1, "合并计数 = 1")
eq(kept[0]["dedup_layer"], "L1_URL", "URL 相同 → 记 L1_URL")
ok(kept[0]["merged_from"] >= 2, "merged_from 记录来源条数")
eq(sorted(kept[0]["verticals"]), ["ai-models", "ai-paper"], "垂类取并集")
eq(kept[0]["hkr_score"], 9.3, "合并后取两条里更高的 HKR")

# L2：URL 不同但标题高度相似
l2 = [{"title": "OpenAI发布GPT-6：推理成本下降90%", "url": "https://a.com/x",
       "vertical": "ai-models", "hkr_score": 9.0},
      {"title": "OpenAI发布GPT-6！推理成本直降90%", "url": "https://b.com/y",
       "vertical": "ai-paper", "hkr_score": 8.0}]
k2, m2 = ts.dedupe(ts.prepare(l2))
eq((len(k2), m2), (1, 1), "标题相似 → 并成 1 条")
eq(k2[0]["dedup_layer"], "L2_TITLE", "记 L2_TITLE")

# L3：标题不像、但正文实体高度重合（同一事件的两种说法）
l3 = [{"title": "OpenAI发布GPT-6：推理成本下降90%", "url": "https://a.com/x",
       "summary": "OpenAI GPT-6 推理成本 下降 90% 每百万 token",
       "vertical": "ai-models", "hkr_score": 9.0},
      {"title": "推理成本暴跌：GPT-6 来了", "url": "https://b.com/y",
       "summary": "OpenAI GPT-6 推理成本 下降 90% 每百万 token",
       "vertical": "ai-paper", "hkr_score": 8.5}]
k3, m3 = ts.dedupe(ts.prepare(l3))
eq((len(k3), m3), (1, 1), "实体词重合 0.86 / 标题相似 0.25 → 并成 1 条")
eq(k3[0]["dedup_layer"], "L3_ENTITY", "记 L3_ENTITY（第三级救回跨平台同事件）")

# 代表条目取高分那条：低分在前、高分在后，代表应换成高分
low_first = [{"title": "同一个事件的说法甲", "url": "https://a.com/1",
              "vertical": "v1", "hkr_score": 6.5},
             {"title": "同一个事件的说法甲啊", "url": "https://a.com/2",
              "vertical": "v2", "hkr_score": 9.5}]
k4, _ = ts.dedupe(ts.prepare(low_first))
eq(k4[0]["hkr_score"], 9.5, "代表条目换成 HKR 更高的那条（不是先到的）")

print("\n## 打分前置校验（缺分不许静默放过）")
raises(lambda: ts.prepare([{"title": "没有分数的条目"}]),
       ValueError, "既无 hkr 又无 hkr_score → 报错")
raises(lambda: ts.prepare([{"title": "维度不全", "hkr": {"h": 5, "k": 4}}]),
       ValueError, "hkr 缺维度 → 报错并从错误信息里指出缺哪个")
raises(lambda: ts.dedupe([{"title": "  "}]),
       ValueError, "空标题 → 报错")

print("\n## 排序确定性")
items = ts.prepare([{"title": "B", "hkr_score": 8.0}, {"title": "A", "hkr_score": 8.0},
                    {"title": "C", "hkr_score": 9.0}])
eq([x["title"] for x in ts.rank_all(items)], ["C", "A", "B"], "同分按标题升序打破并列")

print("\n## 垂类多样性保护（两趟语义）")
# 候选充足：4 个垂类各 2 条 → 5 条全合规，不该出现补位
plenty = ts.prepare([{"title": "%s-%d" % (v, i), "vertical": v, "hkr_score": 9.0 - i * 0.1 - j * 0.3}
                     for j, v in enumerate(["ai-models", "auto", "game", "edu"])
                     for i in range(2)])
t5 = ts.select_top(plenty, top_n=5, max_per_vertical=2)
per = {}
for it in t5:
    per[it["vertical"]] = per.get(it["vertical"], 0) + 1
eq(len(t5), 5, "凑满 5 条")
eq(max(per.values()), 2, "没有任何垂类超过 2 条")
ok(not any(it.get("backfilled") for it in t5), "候选充足时一条补位都没有")

# 候选不足：只有 1 个垂类 3 条 → 第一趟守名额只出 2 条，必要时才补位
dominated = ts.prepare([{"title": "only-%d" % i, "vertical": "solo", "hkr_score": 9.0 - i}
                        for i in range(3)])
t_dom = ts.select_top(dominated, top_n=5, max_per_vertical=2)
eq(len(t_dom), 3, "候选不足时如实返回 3 条，不硬凑不报错")
eq(sum(1 for it in t_dom if it.get("backfilled")), 1, "破例补进来 1 条并打上 backfilled 标记")

# 第一趟就够：2 垂类各 2 条 + 第 3 个垂类 1 条 → 5 条全守规矩
mixed = ts.prepare([{"title": "a%d" % i, "vertical": "va", "hkr_score": 9.5 - i} for i in range(2)] +
                   [{"title": "b%d" % i, "vertical": "vb", "hkr_score": 8.5 - i} for i in range(2)] +
                   [{"title": "c0", "vertical": "vc", "hkr_score": 6.5}])
t_mix = ts.select_top(mixed, top_n=5, max_per_vertical=2)
eq(len(t_mix), 5, "5 条齐")
ok(not any(it.get("backfilled") for it in t_mix), "无需破例时不留补位标记")

print("\n## 平台分级分配")
eq(len(ts.assign_platforms(1)), 4, "Top1 → 4 路")
eq(len(ts.assign_platforms(2)), 2, "Top2 → 2 路")
eq(len(ts.assign_platforms(3)), 2, "Top3 → 2 路")
eq(len(ts.assign_platforms(4)), 1, "Top4 → 1 路")
eq(len(ts.assign_platforms(5)), 1, "Top5 → 1 路")
eq(ts.assign_platforms(6), [], "Top6 不在规则内 → 空（不发）")

print("\n## 输入三种写法等价")
cands = [{"title": "X1", "vertical": "v", "hkr_score": 8.0}]
f1 = ts.normalize_payload({"candidates": [{"title": "X1", "hkr_score": 8.0}], "vertical": "v"})
f2 = ts.normalize_payload({"verticals": {"v": [{"title": "X1", "hkr_score": 8.0}]}})
f3 = ts.normalize_payload([{"title": "X1", "vertical": "v", "hkr_score": 8.0}])
eq(f1, f2, "candidates 写法 == verticals 写法")
eq(f2, f3, "verticals 写法 == 裸数组")
raises(lambda: ts.normalize_payload({"foo": 1}), ValueError, "认不出的结构 → 报错")

print("\n## 端到端 + 确定性")
pool_e2e = {"candidates": [
    {"title": "OpenAI发布GPT-6：推理成本下降90%", "url": "https://a.com/x?utm_source=rss",
     "vertical": "ai-models", "hkr": {"h": 5, "k": 5, "r": 4}, "source": "realtime"},
    {"title": "OpenAI发布GPT-6！推理成本直降90%", "url": "https://b.com/y",
     "vertical": "ai-paper", "hkr": {"h": 5, "k": 4, "r": 5}, "source": "aihot"},
    {"title": "国产大模型开源新权重", "url": "https://c.com/z",
     "vertical": "ai-models", "hkr": {"h": 4, "k": 4, "r": 4}, "source": "realtime"},
    {"title": "某公司发布新模型", "url": "https://d.com/w",
     "vertical": "ai-models", "hkr": {"h": 2, "k": 2, "r": 2}},
    {"title": "特斯拉裁员三千人", "url": "https://e.com/v",
     "vertical": "auto", "hkr": {"h": 4, "k": 3, "r": 5}},
]}
r1 = ts.score_pool(pool_e2e, top_n=3)
eq(r1["stats"]["input"], 5, "输入 5 条")
eq(r1["stats"]["merged_away"], 1, "去重合并 1 条")
eq(r1["stats"]["after_dedup"], 4, "剩 4 条")
eq(r1["stats"]["dropped_below_floor"], 1, "HKR 4.0（<6.0）淘汰 1 条")
eq([x["rank"] for x in r1["top"]], [1, 2, 3], "名次连续")
eq(r1["top"][0]["title"], "OpenAI发布GPT-6：推理成本下降90%", "Top1 是最高分那条")
eq(len(r1["top"][0]["platforms"]), 4, "Top1 分到 4 路")
r2 = ts.score_pool(pool_e2e, top_n=3)
eq(json.dumps(r1, ensure_ascii=False, sort_keys=True),
   json.dumps(r2, ensure_ascii=False, sort_keys=True), "同样输入跑两遍结果完全一致（无随机）")

print("\n" + "=" * 50)
if FAIL:
    print(f"✗ 失败 {len(FAIL)} 项:")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
print("✓ 全部通过")
