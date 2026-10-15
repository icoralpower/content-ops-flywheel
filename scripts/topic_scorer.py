#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选题打分器：HKR 三维打分 → 三级去重 → 垂类多样性保护 → 平台分级分配。

单文件、零依赖（Python 3.8+）、纯确定性——同样的输入永远给同样的排序，
没有随机、没有时间依赖、不联网。用它是为了在「发布前锁预测」之前，
先把候选池里同一条新闻的十个版本压成一条，并把 Top5 分到该发的平台。

用法:
    python3 topic_scorer.py --input pool.json --out ranked.json --top 5
    python3 topic_scorer.py --input pool.json --dry-run --print-summary

输入的三种写法都收:
    {"candidates": [ {...}, ... ]}                 # 推荐
    {"verticals": {"ai-models": [ {...} ], ...}}   # 按垂类分组
    [ {...}, ... ]                                 # 裸数组

单条候选（h/k/r 与 hkr_score 二选一）:
    {"title": "...", "summary": "...", "url": "https://...",
     "vertical": "ai-models", "hkr": {"h": 5, "k": 4, "r": 5},
     "hkr_score": 9.3, "source": "realtime-search", "heat": 128}

方法的出处见 references/topic-scoring.md（重写自一份未附许可证的实现，只取方法不搬代码）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# ---------------------------------------------------------------- 常量与口径

# HKR 三维：H 有趣/反转、K 信息量/数据、R 共鸣/争议，各 1~5 分
HKR_DIMS = ("h", "k", "r")
HKR_MAX = 15.0          # 3 维 × 5 分
HKR_FLOOR = 6.0         # 低于 6.0 直接淘汰：维度太薄，写出来也是垃圾

# 平台分级分配：Top1 全渠道铺，Top2-3 主阵地，Top4-5 只挑一个轻量渠道
PLATFORM_TIERS = (
    {"ranks": (1, 1), "platforms": ["公众号", "小红书", "抖音", "X/Twitter"]},
    {"ranks": (2, 3), "platforms": ["公众号", "小红书"]},
    {"ranks": (4, 5), "platforms": ["小红书"]},
)

# 去重第三级用：这些词出现频率极高，不参与实体词重合度计算
STOPWORDS = frozenset("""
的 了 是 在 和 与 及 或 而 就 都 也 还 又 很 更 最 会 能 要 将 把 被 从 到 对 为 以 之 其 这 那 有 无 不 没
一个 一种 一款 我们 你们 他们 它 我 你 他 她 这个 那个 这些 那些 什么 怎么 如何 为什么 以及 但是 并且 因为
今天 昨天 明天 刚刚 近日 日前 最新 重磅 突发 独家 快讯 消息 新闻 报道 宣布 发布 推出 上线 正式 首次
the a an and or of to in on at for with by from as is are was were be been it its this that these those
new launch launches launched says said will would can could may might just now latest today report
""".split())

# URL 去重前先摘掉这些跟踪参数：同一条新闻带不同 utm 也必须是同一条
TRACKING_QUERY_KEYS = re.compile(r"^(utm_|ref$|ref_|spm$|from$|share_|fbclid$|gclid$|source$|si$)", re.I)


def hkr_score(h: float, k: float, r: float) -> float:
    """HKR 合成分：三维各 1~5，折算到 10 分制并保留 1 位小数。

    >>> hkr_score(5, 5, 5)
    10.0
    >>> hkr_score(1, 1, 1)
    2.0
    """
    for name, v in zip(HKR_DIMS, (h, k, r)):
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ValueError("HKR 维度 %s 必须是数字，收到 %r" % (name, v))
        if not 1 <= v <= 5:
            raise ValueError("HKR 维度 %s 必须在 1~5 之间，收到 %r" % (name, v))
    return round((h + k + r) / HKR_MAX * 10.0, 1)


# ------------------------------------------------------------------ 文本归一化

_PUNCT = re.compile("[" + re.escape(
    " \t\n\r，。、；：！？\"'“”‘’（）《》【】—….!?,;:<>|/\\~`@#$%^&*+=-") + "]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def norm_text(s: str) -> str:
    """小写 + 去标点空白，用于标题相似度比较。"""
    return _PUNCT.sub("", (s or "").lower())


def tokens(s: str) -> set:
    """切词：中文按 2-gram（无分词器也能抓住实体），英文/数字按词。

    去停用词后再做实体词重合度计算——"重磅发布"这种词不该让两条不同的新闻判成一条。
    """
    text = (s or "").lower()
    out = set()
    for word in re.findall(r"[a-z0-9][a-z0-9.+#\-]*", text):
        if word not in STOPWORDS and len(word) > 1:
            out.add(word)
    cjk = _CJK.findall(text)
    for i in range(len(cjk) - 1):
        gram = "".join(cjk[i:i + 2])
        out.add(gram)
    # 中文 2-gram 会切出"重磅"这类高频组合，按停用词表过滤
    return {t for t in out if t not in STOPWORDS}


def url_key(url: str) -> str:
    """归一化 URL：去 fragment、去跟踪参数、host 小写、去尾斜杠。"""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not TRACKING_QUERY_KEYS.match(k)]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path,
                       urlencode(query), ""))


def title_similarity(a: str, b: str) -> float:
    """标题相似度 [0,1]。"""
    na, nb = norm_text(a), norm_text(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def entity_overlap(a: str, b: str) -> float:
    """实体词重合度 = |A∩B| / min(|A|,|B|)（除以较小集合，短标题不被长标题稀释）。"""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / float(min(len(ta), len(tb)))


# ------------------------------------------------------------------ 三级去重


def _dup_reason(x: dict, y: dict, *, similarity: float, overlap: float):
    """返回 (是否同一条, 命中的层级名)。三级依次判定，先命中先算。"""
    kx, ky = x.get("_url_key") or "", y.get("_url_key") or ""
    if kx and kx == ky:
        return True, "L1_URL"
    if title_similarity(x["title"], y["title"]) >= similarity:
        return True, "L2_TITLE"
    if entity_overlap(x["title"] + " " + x.get("summary", ""),
                      y["title"] + " " + y.get("summary", "")) >= overlap:
        return True, "L3_ENTITY"
    return False, ""


def _merge(keep: dict, other: dict) -> None:
    """把 other 合进 keep（就地修改）。保留信息量更大的那份描述。"""
    keep["merged_from"] = keep.get("merged_from", 1) + other.get("merged_from", 1)
    keep["verticals"] = sorted(set(keep.get("verticals", [])) | set(other.get("verticals", [])))
    keep["sources"] = sorted({s for s in [keep.get("source"), other.get("source")] if s})
    if not keep.get("url") and other.get("url"):
        keep["url"] = other["url"]
    if len(other.get("summary") or "") > len(keep.get("summary") or ""):
        keep["summary"] = other["summary"]
    if len(other.get("title") or "") > len(keep.get("title") or ""):
        keep["title"] = other["title"]
    keep["heat"] = max(keep.get("heat") or 0, other.get("heat") or 0)
    keep["aliases"] = sorted(set(keep.get("aliases", [])) | {other["title"]})


def dedupe(items, *, similarity: float = 0.6, overlap: float = 0.6):
    """三级去重。单趟贪心聚类、保持输入顺序 —— 确定性，不随机（这点和上游不同）。

    返回 (去重后的列表, 被合并掉的数量)。
    """
    kept, merged_away = [], 0
    for raw in items:
        cur = dict(raw)
        cur["title"] = (cur.get("title") or "").strip()
        if not cur["title"]:
            raise ValueError("候选项缺 title：%r" % (raw.get("url") or raw))
        cur["_url_key"] = url_key(cur.get("url") or "")
        cur["verticals"] = [cur.get("vertical")] if cur.get("vertical") else []
        cur["merged_from"] = 1
        cur.setdefault("aliases", [])
        hit = None
        for i, k in enumerate(kept):
            same, reason = _dup_reason(k, cur, similarity=similarity, overlap=overlap)
            if same:
                hit = (i, reason)
                break
        if hit is None:
            cur["dedup_layer"] = ""
            kept.append(cur)
        else:
            i, reason = hit
            rep = kept[i]
            # 代表条目取 HKR 更高的那条；同分保持先来的（确定性）
            if cur.get("hkr_score", 0) > rep.get("hkr_score", 0):
                old = dict(rep)
                cur["merged_from"] = cur.get("merged_from", 1) + old.get("merged_from", 1)
                cur["verticals"] = sorted(set(cur.get("verticals", [])) | set(old.get("verticals", [])))
                cur["sources"] = sorted({s for s in [cur.get("source"), old.get("source")] if s})
                cur["aliases"] = sorted(set(cur.get("aliases", [])) | {old["title"]})
                cur["heat"] = max(cur.get("heat") or 0, old.get("heat") or 0)
                if not cur.get("url") and old.get("url"):
                    cur["url"] = old["url"]
                if len(old.get("summary") or "") > len(cur.get("summary") or ""):
                    cur["summary"] = old["summary"]
                cur["dedup_layer"] = reason
                kept[i] = cur
            else:
                layer = rep.get("dedup_layer")
                _merge(rep, cur)
                rep["dedup_layer"] = layer or reason
            merged_away += 1
    return kept, merged_away


# ------------------------------------------------------- 打分、排序、多样性


def prepare(items):
    """把候选池规范成带 hkr_score 的条目；缺分且缺 h/k/r 的直接报错，不静默放过。"""
    out = []
    for idx, raw in enumerate(items):
        cur = dict(raw)
        if "hkr_score" in cur and cur["hkr_score"] is not None:
            score = float(cur["hkr_score"])
        elif isinstance(cur.get("hkr"), dict):
            dims = cur["hkr"]
            missing = [d for d in HKR_DIMS if d not in dims]
            if missing:
                raise ValueError("候选 #%d 的 hkr 缺维度 %s" % (idx, ",".join(missing)))
            score = hkr_score(dims["h"], dims["k"], dims["r"])
        else:
            raise ValueError("候选 #%d（%s）既没有 hkr 也没有 hkr_score" %
                             (idx, cur.get("title") or cur.get("url") or "?"))
        cur["hkr_score"] = score
        cur["below_floor"] = score < HKR_FLOOR
        out.append(cur)
    return out


def rank_all(items):
    """排序：HKR 降序 → 标题升序（并列时的确定性打破）。"""
    return sorted(items, key=lambda x: (-x["hkr_score"], x["title"]))


def _verts(it) -> set:
    """取条目的垂类集合：去重后是 verticals（并集），未去重时回落单值 vertical。"""
    vs = it.get("verticals")
    if vs:
        return set(vs)
    return {it["vertical"]} if it.get("vertical") else set()


def select_top(items, top_n: int = 5, max_per_vertical: int = 2):
    """垂类多样性保护：同一垂类在 TopN 里最多占 max_per_vertical 条。

    两趟：
      第一趟严格守名额 —— 名额满了就跳过，宁可不满员；
      第二趟（仅当第一趟没凑够）才从落选里按分数补，补进来的标 backfilled=True，
      让操作者一眼看到「这 5 条里有几条是靠破例补上的」，而不是悄悄违反规则。
    """
    ranked = rank_all(items)
    picked, overflow = [], []
    for it in ranked:
        verts = _verts(it)
        counts = {}
        for p in picked:
            for v in _verts(p):
                counts[v] = counts.get(v, 0) + 1
        if len(picked) < top_n and not (verts and any(counts.get(v, 0) >= max_per_vertical
                                                     for v in verts)):
            picked.append(it)
        else:
            overflow.append(it)
    for it in overflow:
        if len(picked) >= top_n:
            break
        fill = dict(it)
        fill["backfilled"] = True
        picked.append(fill)
    return rank_all(picked)[:top_n]


def assign_platforms(rank: int, tiers=PLATFORM_TIERS):
    """按名次给平台清单。"""
    for tier in tiers:
        lo, hi = tier["ranks"]
        if lo <= rank <= hi:
            return list(tier["platforms"])
    return []


def score_pool(payload, *, top_n: int = 5, max_per_vertical: int = 2,
               similarity: float = 0.6, overlap: float = 0.6, tiers=PLATFORM_TIERS):
    """完整流程，返回结果字典（可直接 json.dump）。"""
    raw = normalize_payload(payload)
    prepared = prepare(raw)
    deduped, merged_away = dedupe(prepared, similarity=similarity, overlap=overlap)
    eligible = [x for x in deduped if not x["below_floor"]]
    dropped_low = [x for x in deduped if x["below_floor"]]
    top = select_top(eligible, top_n=top_n, max_per_vertical=max_per_vertical)

    top_out = []
    for i, it in enumerate(top, start=1):
        row = {k: v for k, v in it.items() if not k.startswith("_")}
        row["rank"] = i
        row["platforms"] = assign_platforms(i, tiers)
        top_out.append(row)

    rest = [x for x in rank_all(eligible) if x not in top]
    rest_out = []
    for it in rest:
        row = {k: v for k, v in it.items() if not k.startswith("_")}
        row["platforms"] = []
        rest_out.append(row)

    return {
        "params": {"top_n": top_n, "max_per_vertical": max_per_vertical,
                   "similarity": similarity, "entity_overlap": overlap,
                   "hkr_floor": HKR_FLOOR},
        "stats": {"input": len(raw), "after_dedup": len(deduped),
                  "merged_away": merged_away,
                  "dropped_below_floor": len(dropped_low)},
        "top": top_out,
        "others": rest_out,
        "dropped": [{k: v for k, v in x.items() if not k.startswith("_")} for x in dropped_low],
    }


def normalize_payload(payload):
    """收三种输入写法，统一成候选列表。"""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("输入必须是 JSON 对象或数组")
    if isinstance(payload.get("candidates"), list):
        default_v = payload.get("vertical")
        out = []
        for c in payload["candidates"]:
            c = dict(c)
            if default_v and not c.get("vertical"):
                c["vertical"] = default_v
            out.append(c)
        return out
    if isinstance(payload.get("verticals"), dict):
        out = []
        for v, lst in payload["verticals"].items():
            for c in lst:
                c = dict(c)
                c.setdefault("vertical", v)
                out.append(c)
        return out
    raise ValueError("输入里找不到 candidates 或 verticals")


# ------------------------------------------------------------------ 输出


def render_summary(result) -> str:
    lines = ["", "  名次  HKR   垂类            平台                          标题",
             "  " + "-" * 96]
    for row in result["top"]:
        verts = "/".join(row.get("verticals") or []) or "-"
        plat = "·".join(row["platforms"])
        mark = " ↺合%d" % row["merged_from"] if row.get("merged_from", 1) > 1 else ""
        bf = " [补位]" if row.get("backfilled") else ""
        lines.append("  %-4d %4.1f  %-14s %-28s %s%s%s" %
                     (row["rank"], row["hkr_score"], verts[:14], plat[:28],
                      row["title"][:44], mark, bf))
    s = result["stats"]
    lines.append("  " + "-" * 96)
    lines.append("  输入 %d 条 → 去重合并 %d 条 → 剩 %d 条；HKR < %.1f 淘汰 %d 条"
                 % (s["input"], s["merged_away"], s["after_dedup"],
                    result["params"]["hkr_floor"], s["dropped_below_floor"]))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="选题打分器：HKR 去重排序 + 垂类多样性 + 平台分级分配")
    ap.add_argument("--input", required=True, help="候选池 JSON")
    ap.add_argument("--out", help="结果写到哪里（不写就只打印）")
    ap.add_argument("--top", type=int, default=5, help="取前几名，默认 5")
    ap.add_argument("--max-per-vertical", type=int, default=2,
                    help="TopN 内同一垂类最多几条，默认 2")
    ap.add_argument("--similarity", type=float, default=0.6, help="标题相似度阈值，默认 0.6")
    ap.add_argument("--entity-overlap", type=float, default=0.6, help="实体词重合阈值，默认 0.6")
    ap.add_argument("--dry-run", action="store_true", help="只算不写文件")
    ap.add_argument("--print-summary", action="store_true", help="打印名次表")
    args = ap.parse_args(argv)

    try:
        with open(args.input, encoding="utf-8") as f:
            payload = json.load(f)
    except OSError as e:
        print("✗ 读不到输入：%s" % e, file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print("✗ 输入不是合法 JSON：%s" % e, file=sys.stderr)
        return 2

    try:
        result = score_pool(payload, top_n=args.top,
                            max_per_vertical=args.max_per_vertical,
                            similarity=args.similarity, overlap=args.entity_overlap)
    except ValueError as e:
        print("✗ 候选池有问题：%s" % e, file=sys.stderr)
        return 2

    if args.print_summary or not args.out:
        print(render_summary(result))
    if args.out and not args.dry_run:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("  → 已写 %s" % args.out)
    elif args.dry_run:
        print("  （--dry-run，未写文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
