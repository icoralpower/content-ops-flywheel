#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核心函数单元测试 —— 只测数学与解析这两块最容易出错的地方。

运行: python3 tests/test_unit.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import content_ledger as cl  # noqa: E402

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


print("## 数字解析")
eq(cl.parse_num("1万"), 1e4, "1万")
eq(cl.parse_num("1.52万"), 15200, "1.52万")
eq(cl.parse_num("4.2w"), 42000, "4.2w")
eq(cl.parse_num("10k"), 10000, "10k")
eq(cl.parse_num("1,000"), 1000, "1,000")
eq(cl.parse_num("3.5"), 3.5, "3.5")
raises(lambda: cl.parse_num("一万"), ValueError, "中文数字不支持（应报错）")

print("\n## 区间解析")
eq(cl.parse_range("1万-2万"), [1e4, 2e4], "1万-2万")
eq(cl.parse_range("20000-10000"), [1e4, 2e4], "倒序自动纠正")
eq(cl.parse_range("5000"), [5000, 5000], "单值退化为点")
eq(cl.parse_range("1万~2万"), [1e4, 2e4], "支持 ~ 分隔")

print("\n## 指标别名归一（这是 upstream 静默失配的坑）")
for alias, canon in [
    ("播放", "views"), ("播放量", "views"), ("impressions", "views"),
    ("阅读量", "views"), ("views_total", "views"), ("total_views", "views"),
    ("点赞", "likes"), ("digg", "likes"), ("在看", "likes"),
    ("收藏", "collects"), ("favorite", "collects"), ("收藏数", "collects"),
    ("转发", "shares"), ("repost", "shares"), ("投币", "shares"),
    ("涨粉", "fan_delta"), ("fans", "fan_delta"), ("新增粉丝", "fan_delta"),
    ("私信", "dm"), ("咨询", "dm"), ("dm", "dm"),
    ("成交额", "gmv"), ("销售额", "gmv"), ("gmv", "gmv"),
    ("成交", "conv"), ("订单", "conv"), ("留资", "conv"),
]:
    eq(cl.canon_key(alias), canon, f"canon_key({alias})")
raises(lambda: cl.canon_key("播发量"), KeyError, "错别字指标名必须报错（不许静默忽略）")

print("\n## 平台方言标签")
eq(cl.label("xhs", "views"), "观看量", "小红书 views")
eq(cl.label("gzh", "views"), "阅读量", "公众号 views")
eq(cl.label("douyin", "views"), "播放量", "抖音 views")
eq(cl.label("gzh", "likes"), "在看", "公众号 likes")
eq(cl.label("tiktok", "gmv"), "GMV", "TikTok gmv")
eq(cl.label("xhs", "fan_delta"), "涨粉", "未覆盖键回落到通用名")

print("\n## 判定逻辑")
eq(cl.judge(150, 100, 200)[0], "命中 ✓", "区间内")
ok("大幅低于" in cl.judge(50, 100, 200)[0], "跌破下界 30%+ → 大幅低于")
ok("大幅超出" in cl.judge(300, 100, 200)[0], "冲破上界 40%+ → 大幅超出")
ok("低于预期" in cl.judge(85, 100, 200)[0], "轻微低于")
eq(round(cl.judge(150, 100, 200)[1], 2), 1.0, "方向系数 = 实际/中位")

print("\n## 秩相关（Spearman）")
eq(cl.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0, "完全正相关")
eq(cl.spearman([1, 2, 3, 4], [40, 30, 20, 10]), -1.0, "完全负相关")
eq(cl.spearman([1, 2, 3], [1, 2, 3]), 1.0, "n=3 边界")
eq(cl.spearman([1, 2], [1, 2]), None, "n<3 返回 None")
rho = cl.spearman([1, 1, 2, 2], [1, 2, 3, 4])
ok(rho is not None and 0 < rho < 0.95, f"含并列的秩（{rho:.2f}）")
eq(cl.spearman([1, 1, 1], [1, 2, 3]), None, "评分无差异 → None（不许崩）")

print("\n## 命中统计")
items = [{"id": 1, "predicted": {"views": [100, 200]}, "actual": {"views": 150}},
         {"id": 2, "predicted": {"views": [100, 200]}, "actual": {"views": 300}},
         {"id": 3, "predicted": {"views": [100, 200]}, "actual": {}}]
rows = cl.hit_stats(items)
eq(len(rows), 2, "无实际值的记录不计入分母")
eq(sum(1 for r in rows if r["hit"]), 1, "命中 1 条")

print("\n## 指纹（预测被改必须检出）")
it = {"predicted": {"views": [100, 200]}, "predict_note": "n", "score": 4.0, "scores": {}}
fp = cl.fingerprint(it)
it["predict_fingerprint"] = fp
ok(cl.verify_fingerprint(it), "未改动 → 通过")
it["predicted"] = {"views": [1, 2]}
ok(not cl.verify_fingerprint(it), "偷改预测 → 不通过")
it2 = {"predicted": {}, "predict_note": "", "score": 1}
ok(cl.verify_fingerprint(it2), "旧数据无指纹 → 不阻塞")

print("\n## 评分卡默认权重")
tot = sum(d["weight"] for d in cl.DEFAULT_RUBRIC["dimensions"])
eq(round(tot, 6), 1.0, f"七维权重之和 = {tot}")

print("\n" + "=" * 50)
if FAIL:
    print(f"✗ 失败 {len(FAIL)} 项:")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
print("✓ 全部通过")
