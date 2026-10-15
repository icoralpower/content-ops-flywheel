#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""content_ledger.py —— 内容运营校准台账

发布前锁预测 → 发布后回采 → 偏差三问 → 攒够证据再改评分卡。
单文件、零第三方依赖、Python 3.8+。

用法:
  content_ledger.py init <账号> --platform xhs [--nickname 名字] [--pillars "A,B,C"]
  content_ledger.py predict <账号> --title T --score 4.2 [--pillar 支柱]
      --metric views=1万-2万 --metric likes=300-600 [--note 依据] [--conf 0.6]
  content_ledger.py publish <账号> --id N [--url U] [--windows 24h,72h,7d]
  content_ledger.py collect <账号> --id N --metric views=15200 --likes 830
      [--top-comments "评论1;评论2"]
  content_ledger.py report <账号> [--id N]
  content_ledger.py review <账号> --id N --where 完播 --evidence "..." \
      --verdict 模式 --obs "一句话观察" [--obs-code OBS-01]
  content_ledger.py calibrate <账号>
  content_ledger.py list <账号>
  content_ledger.py export <账号>

设计要点（相对 upstream mcn-content-ops 的修正）:
  1. 指标别名归一 —— 预测与回填共用一张别名表，键名写错会报错而不是静默不统计
  2. 预测指纹 —— predict 时算 sha256，之后被手改会被检出
  3. reported / reviewed 分离 —— 只是对比过 ≠ 复盘完成
  4. 数据目录固定绝对路径（CONTENT_OPS_HOME），不随 cwd 漂移
  5. 命中率过宽/过窄自动预警（区间校准）
  6. 评分卡可配置 + calibrate 算评分与实际数据的秩相关，识别失效维度
"""
import argparse
import csv
import glob
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone, timedelta

VERSION = "1.0.0"
CN = timezone(timedelta(hours=8))

# ---------------------------------------------------------------- 配置

HOME = os.path.expanduser(os.environ.get("CONTENT_OPS_HOME", "~/内容运营台账"))
OBSIDIAN = os.path.expanduser(
    os.environ.get(
        "CONTENT_OPS_OBSIDIAN",
        "~/Documents/Obsidian Vault/资料库/内容运营",
    )
)

# 规范指标键 -> (中文名, 单位)
CANON = {
    "views": ("流量", "次"),
    "likes": ("点赞", "个"),
    "comments": ("评论", "条"),
    "collects": ("收藏", "个"),
    "shares": ("分享", "次"),
    "fan_delta": ("涨粉", "人"),
    "dm": ("私信", "条"),
    "conv": ("转化", "单"),
    "gmv": ("成交额", "元"),
}

# 平台方言：同一个规范键在不同后台叫不同名字，报告里必须说用户那边的话
PLATFORM_LABELS = {
    "xhs": {"views": "观看量", "collects": "收藏", "shares": "分享"},
    "douyin": {"views": "播放量", "collects": "收藏", "shares": "分享"},
    "shipinhao": {"views": "播放量", "shares": "转发"},
    "bilibili": {"views": "播放量", "shares": "投币/转发", "likes": "点赞"},
    "tiktok": {"views": "播放量", "gmv": "GMV"},
    "gzh": {"views": "阅读量", "likes": "在看", "shares": "转发", "collects": "收藏"},
}


def label(platform, key):
    """按平台方言取指标显示名，取不到回落到通用名。"""
    return PLATFORM_LABELS.get(platform or "", {}).get(key) or CANON[key][0]


# 别名 -> 规范键。中英混写、平台黑话都收进来，写错直接报错。
ALIAS = {
    "views": ["views", "view", "play", "plays", "impression", "impressions",
              "exposure", "read", "reads", "vv", "pv",
              "流量", "播放", "播放量", "浏览", "浏览量", "阅读", "阅读量",
              "曝光", "曝光量", "观看", "观看量", "展示"],
    "likes": ["likes", "like", "digg", "thumb", "thumbs", "hearts",
              "点赞", "赞", "点赞数", "心心", "在看"],
    "comments": ["comments", "comment", "replies", "reply",
                 "评论", "评论数", "留言", "回复"],
    "collects": ["collects", "collect", "favorite", "favorites", "fav", "favs",
                 "bookmark", "bookmarks", "stars", "saves",
                 "收藏", "收藏数", "藏书", "星标"],
    "shares": ["shares", "share", "repost", "reposts", "retweet", "forward",
               "forwards", "coins",
               "分享", "分享数", "转发", "转发数", "投币", "转推"],
    "fan_delta": ["fan", "fans", "fan_delta", "fans_delta", "followers",
                  "follower", "new_fans", "subscribers", "subs", "follow",
                  "涨粉", "粉丝", "粉丝数", "新增粉丝", "关注", "增粉"],
    "dm": ["dm", "dms", "message", "messages", "inbox", "chat",
           "私信", "私信数", "咨询", "咨询数", "消息"],
    "conv": ["conv", "conversion", "conversions", "orders", "order", "sales",
             "purchase", "purchases", "leads", "cvr",
             "转化", "转化数", "下单", "订单", "成交", "成交单数", "留资"],
    "gmv": ["gmv", "revenue", "amount", "sales_amount", "turnover", "成交额",
            "成交金额", "销售额", "营收", "GMV"],
}
_ALIAS_LOOKUP = {}
for _canon, _names in ALIAS.items():
    for _n in _names:
        _ALIAS_LOOKUP[_n.lower()] = _canon
    _ALIAS_LOOKUP[_canon] = _canon


def canon_key(raw):
    """把任意写法归一成规范指标键；不认识就抛 KeyError。"""
    k = str(raw).strip().lower().replace(" ", "").replace("-", "_")
    if k in _ALIAS_LOOKUP:
        return _ALIAS_LOOKUP[k]
    # 去掉常见后缀: views_total / total_views / views_num ...
    for pre in ("total_", "sum_"):
        if k.startswith(pre) and k[len(pre):] in _ALIAS_LOOKUP:
            return _ALIAS_LOOKUP[k[len(pre):]]
    for suf in ("_total", "_num", "_cnt", "_count", "_num_total"):
        if k.endswith(suf) and k[: -len(suf)] in _ALIAS_LOOKUP:
            return _ALIAS_LOOKUP[k[: -len(suf)]]
    raise KeyError(
        f"不认识的指标名「{raw}」。可用: {', '.join(sorted(CANON))} "
        f"（中文别名如 播放/点赞/收藏/转发/涨粉/成交额 也可）"
    )


# 平台预设：默认指标顺序 = 报告里的主要指标顺序，第一个视作主指标
PLATFORMS = {
    "xhs": {"label": "小红书",
            "metrics": ["views", "likes", "collects", "comments", "shares",
                        "fan_delta", "dm"],
            "windows": ["24h", "7d", "30d"]},
    "douyin": {"label": "抖音",
               "metrics": ["views", "likes", "comments", "shares", "collects",
                           "fan_delta", "conv"],
               "windows": ["2h", "24h", "7d"]},
    "shipinhao": {"label": "视频号",
                  "metrics": ["views", "likes", "comments", "shares",
                              "collects", "fan_delta"],
                  "windows": ["24h", "7d"]},
    "bilibili": {"label": "B站",
                 "metrics": ["views", "likes", "comments", "collects",
                             "shares", "fan_delta"],
                 "windows": ["48h", "7d", "30d"]},
    "tiktok": {"label": "TikTok",
               "metrics": ["views", "likes", "comments", "shares",
                           "fan_delta", "gmv"],
               "windows": ["24h", "72h", "7d"]},
    "gzh": {"label": "公众号",
            "metrics": ["views", "likes", "comments", "shares", "fan_delta"],
            "windows": ["24h", "7d"]},
    "custom": {"label": "自定义", "metrics": [], "windows": ["24h", "7d"]},
}

# 默认评分卡（小红书/抖音通用短视频口径），可用参考文件覆盖
DEFAULT_RUBRIC = {
    "version": "v1",
    "gate": 3.5,
    "dimensions": [
        {"name": "Hook 强度", "key": "hook", "weight": 0.25,
         "note": "前 3 秒有没有给出看点/冲突/悬念"},
        {"name": "完播结构", "key": "retention", "weight": 0.20,
         "note": "节奏、钩子链、时长与密度匹配"},
        {"name": "价值密度", "key": "value", "weight": 0.15,
         "note": "单点价值能不能一句话复述"},
        {"name": "场景匹配", "key": "scene", "weight": 0.15,
         "note": "是否命中目标人群高频场景"},
        {"name": "互动钩子", "key": "engage", "weight": 0.10,
         "note": "有没有明确的评论/收藏/转发诱因"},
        {"name": "转化路径", "key": "convert", "weight": 0.10,
         "note": "内容即使用场景，引导顺滑不俗气"},
        {"name": "平台感", "key": "native", "weight": 0.05,
         "note": "符合该平台的内容语法与本地梗"},
    ],
    "changelog": [],
}

# ---------------------------------------------------------------- 文件与存储

def state_dir():
    return os.path.join(HOME, "state")


def account_dir(account):
    return os.path.join(HOME, "accounts", account)


def state_path(account):
    return os.path.join(state_dir(), f"{account}.json")


def load(account, must_exist=True):
    p = state_path(account)
    if not os.path.exists(p):
        if must_exist:
            sys.exit(f"账号「{account}」未初始化。先运行: init {account} --platform xhs")
        return None
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    for it in data.get("items", []):
        it["_fingerprint_ok"] = verify_fingerprint(it)
    return data


def save(account, data):
    os.makedirs(state_dir(), exist_ok=True)
    tmp = state_path(account) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, state_path(account))


def now_iso():
    return datetime.now(CN).isoformat(timespec="seconds")


def fingerprint(item):
    payload = json.dumps(
        {"predicted": item.get("predicted") or {},
         "predict_note": item.get("predict_note") or "",
         "score": item.get("score"),
         "scores": item.get("scores") or {}},
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def verify_fingerprint(item):
    fp = item.get("predict_fingerprint")
    if not fp:
        return True  # 旧数据
    return fp == fingerprint(item)


def next_id(items):
    return max((i["id"] for i in items), default=0) + 1


def find_item(data, iid):
    it = next((i for i in data["items"] if i["id"] == iid), None)
    if not it:
        sys.exit(f"未找到记录 #{iid}")
    return it


# ---------------------------------------------------------------- 数字解析

_NUM = re.compile(r"^([\d,]+(?:\.\d+)?)\s*(万|w|k|m|亿|千)?$")


def parse_num(s):
    """支持 1万 / 1.5w / 10k / 1,000 / 10000"""
    s = str(s).strip().replace(" ", "")
    m = _NUM.match(s)
    if not m:
        raise ValueError(f"无法解析数字: {s}")
    v = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "").lower()
    mult = {"万": 1e4, "w": 1e4, "k": 1e3, "千": 1e3, "m": 1e6, "亿": 1e8}
    return v * mult.get(unit, 1)


def parse_range(s):
    """lo-hi 或单值 -> [lo, hi]"""
    parts = re.split(r"\s*[-~]\s*", str(s).strip())
    if len(parts) == 1:
        v = parse_num(parts[0])
        return [v, v]
    if len(parts) == 2:
        lo, hi = parse_num(parts[0]), parse_num(parts[1])
        if lo > hi:
            lo, hi = hi, lo
        return [lo, hi]
    raise ValueError(f"区间格式错误: {s}（应为 1万-2万 或 10000）")


def fmt_num(v):
    if v is None:
        return "-"
    if v >= 1e8:
        return f"{v/1e8:.2f}亿"
    if v >= 1e4:
        return f"{v/1e4:.2f}万"
    if v == int(v):
        return f"{int(v):,}"
    return f"{v:,.1f}"


def parse_kv(s):
    if "=" not in s:
        raise ValueError(f"指标格式错误: {s}（应为 名称=值 或 名称=下界-上界）")
    k, _, v = s.partition("=")
    return canon_key(k.strip()), v.strip()


# ---------------------------------------------------------------- 判定与统计

def judge(actual, lo, hi):
    """返回 (标签, 方向系数) 方向系数=actual/区间中心"""
    mid = (lo + hi) / 2 if hi != lo else lo
    ratio = (actual / mid) if mid else None
    if actual < lo:
        tag = "大幅低于 ◼◼" if actual < lo * 0.7 else "低于预期 ◼"
    elif actual > hi:
        tag = "大幅超出 ▲▲" if actual > hi * 1.4 else "超出预期 ▲"
    else:
        tag = "命中 ✓"
    return tag, ratio


def ranks(xs):
    """平均秩（处理并列）"""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    if dx == 0 or dy == 0:
        return None
    rho = num / (dx * dy)
    # 抹掉浮点尾数，让完全单调时干净地给出 ±1.0
    rho = round(rho, 10)
    return 1.0 if rho > 1 else (-1.0 if rho < -1 else rho)


def hit_stats(items, metric=None):
    """命中率 / 覆盖率诊断"""
    rows = []
    for it in items:
        for k, rng in (it.get("predicted") or {}).items():
            if metric and k != metric:
                continue
            a = (it.get("actual") or {}).get(k)
            if a is None or not rng:
                continue
            lo, hi = rng[0], rng[1] if len(rng) > 1 else rng[0]
            ok = lo <= a <= hi
            rows.append({"id": it["id"], "metric": k, "lo": lo, "hi": hi,
                         "actual": a, "hit": ok})
    return rows


# ---------------------------------------------------------------- 命令

def cmd_init(args):
    if os.path.exists(state_path(args.account)):
        sys.exit(f"账号「{args.account}」已存在: {state_path(args.account)}")
    plats = [p.strip() for p in (args.platform or "xhs").split(",") if p.strip()]
    for p in plats:
        if p not in PLATFORMS:
            sys.exit(f"未知平台「{p}」。可选: {', '.join(PLATFORMS)}")
    main = plats[0]
    data = {
        "account": args.account,
        "nickname": args.nickname or args.account,
        "platforms": plats,
        "main_platform": main,
        "pillars": [p.strip() for p in (args.pillars or "").split(",") if p.strip()],
        "rubric": json.loads(json.dumps(DEFAULT_RUBRIC)),
        "observations": [],
        "created_at": now_iso(),
        "items": [],
    }
    os.makedirs(account_dir(args.account), exist_ok=True)
    save(args.account, data)
    _write_account_md(data)
    print(f"✓ 已初始化 {args.account}（{PLATFORMS[main]['label']}）")
    print(f"  台账: {state_path(args.account)}")
    print(f"  文档: {os.path.join(account_dir(args.account), 'account.md')}")
    print(f"  评分卡: {DEFAULT_RUBRIC['version']} / "
          f"{len(DEFAULT_RUBRIC['dimensions'])} 维 / 门槛 {DEFAULT_RUBRIC['gate']}")


def cmd_predict(args):
    data = load(args.account)
    predicted, unrecognized = {}, []
    for m in args.metric or []:
        try:
            k, v = parse_kv(m)
        except KeyError as e:
            unrecognized.append(str(e))
            continue
        predicted[k] = parse_range(v)
    if unrecognized:
        sys.exit("\n".join(unrecognized))
    if not predicted:
        sys.exit("至少要有一个 --metric，例如 --metric views=1万-2万")
    if args.score is not None and not (1 <= args.score <= 5):
        sys.exit(f"评分必须在 1-5 之间，收到 {args.score}")
    dims = {d["key"]: d["weight"] for d in data["rubric"]["dimensions"]}
    dim_names = {d["name"]: d["key"] for d in data["rubric"]["dimensions"]}
    scores = {}
    for s in args.dim_score or []:
        if "=" not in s:
            sys.exit(f"维度分格式错误: {s}（应为 key=分，如 hook=4.5）")
        k, _, v = s.partition("=")
        k = k.strip()
        if k not in dims:
            if k in dim_names:
                k = dim_names[k]
            else:
                sys.exit(f"维度「{k}」不在评分卡里。可用: {', '.join(sorted(dims))}")
        try:
            sv = float(v.strip())
        except ValueError:
            sys.exit(f"维度分必须是数字: {s}")
        if not (1 <= sv <= 5):
            sys.exit(f"维度分必须在 1-5 之间: {s}")
        scores[k] = sv
    if args.score is None and scores:
        # 只给了部分维度时按已给维度权重重归一，避免总分被系统性压低
        wsum = sum(dims[k] for k in scores)
        args.score = round(sum(scores[k] * dims[k] for k in scores) / wsum, 2)
        if set(scores) != set(dims):
            missing = ", ".join(sorted(set(dims) - set(scores)))
            print(f"  注: 只评了 {len(scores)}/{len(dims)} 个维度，总分按已给维度归一"
                  f"（未评: {missing}）")

    it = {
        "id": next_id(data["items"]),
        "title": args.title,
        "pillar": args.pillar or "",
        "platform": args.platform or data["main_platform"],
        "score": args.score,
        "scores": scores,
        "predicted": predicted,
        "confidence": args.conf,
        "predict_note": args.note or "",
        "predicted_at": now_iso(),
        "published_at": None, "url": None,
        "collect_windows": args.windows.split(",") if args.windows else
                           PLATFORMS[data["main_platform"]]["windows"],
        "actual": {}, "collected_at": {},
        "top_comments": [],
        "reported_at": None, "reviewed_at": None,
        "retro": None,
    }
    it["predict_fingerprint"] = fingerprint(it)
    data["items"].append(it)
    save(args.account, data)
    print(f"✓ 已锁预测 #{it['id']}「{it['title']}」 score={it['score']} conf={it['confidence']}")
    for k, (lo, hi) in predicted.items():
        print(f"    {label(it['platform'], k):<4}({k})  {fmt_num(lo)} - {fmt_num(hi)}")
    print(f"  指纹 {it['predict_fingerprint']}（发布后改动会被 report 检出）")


def cmd_publish(args):
    data = load(args.account)
    it = find_item(data, args.id)
    if it.get("published_at"):
        sys.exit(f"#{args.id} 已登记发布（{it['published_at']}），不可重复登记")
    if not verify_fingerprint(it):
        print("⚠ 预测内容已被手工改动，指纹不匹配（建议先核对台账）")
    it["published_at"] = now_iso()
    it["url"] = args.url or ""
    if args.windows:
        it["collect_windows"] = [w.strip() for w in args.windows.split(",") if w.strip()]
    save(args.account, data)
    print(f"✓ 已登记发布 #{it['id']}「{it['title']}」")
    print(f"  采集窗口: {', '.join(it['collect_windows'])}（到点用 collect 回填）")


def cmd_collect(args):
    data = load(args.account)
    it = find_item(data, args.id)
    actual = dict(it.get("actual") or {})
    cols = dict(it.get("collected_at") or {})
    # 1) --metric k=v 形式
    for m in args.metric or []:
        try:
            k, v = parse_kv(m)
        except KeyError as e:
            sys.exit(str(e))
        actual[k] = parse_num(v)
        cols[k] = now_iso()
    # 2) 便捷 flag 形式（--views 830 --likes ...）
    for k in CANON:
        v = getattr(args, k.replace("-", "_"), None)
        if v is not None:
            actual[k] = parse_num(v)
            cols[k] = now_iso()
    if args.window:
        it["collected_window"] = args.window
    if args.top_comments:
        it["top_comments"] = (it.get("top_comments") or []) + [
            c.strip() for c in re.split(r"[;；]", args.top_comments) if c.strip()
        ]
    if not actual:
        sys.exit("没有回填任何指标。用 --metric views=15200 或 --views 15200")
    it["actual"] = actual
    it["collected_at"] = cols
    save(args.account, data)
    print(f"✓ 已回填 #{it['id']}「{it['title']}」")
    for k, v in actual.items():
        rng = (it.get("predicted") or {}).get(k)
        if rng:
            tag, ratio = judge(v, rng[0], rng[1] if len(rng) > 1 else rng[0])
            print(f"    {label(it['platform'], k):<4}({k})  {fmt_num(v):>10}   "
                  f"预测 {fmt_num(rng[0])}-{fmt_num(rng[-1])}   {tag}")
        else:
            print(f"    {label(it['platform'], k):<4}({k})  {fmt_num(v):>10}   （无预测值）")


def _print_report(data, items, use_color=True):
    rows = hit_stats(items)
    if not rows:
        print("没有可对比的记录（需先 collect 回填实际数据）")
        return None

    by_id = {}
    for r in rows:
        by_id.setdefault(r["id"], []).append(r)
    titles = {i["id"]: i["title"] for i in items}

    print(f"{'ID':<4}{'标题':<22}{'指标':<10}{'预测区间':<20}{'实际':>10}  判定")
    print("-" * 88)
    tampered = []
    for it in items:
        iid = it["id"]
        if not (it.get("predicted")):
            print(f"{iid:<4}{titles[iid][:20]:<22}（无预测值，跳过对比）")
            continue
        if not verify_fingerprint(it):
            tampered.append(iid)
        for r in by_id.get(iid, []):
            tag, _ = judge(r["actual"], r["lo"], r["hi"])
            print(f"{iid:<4}{titles[iid][:20]:<22}"
                  f"{label(it['platform'], r['metric']):<10}"
                  f"{fmt_num(r['lo'])+'-'+fmt_num(r['hi']):<20}"
                  f"{fmt_num(r['actual']):>10}  {'✓' if r['hit'] else ' '} {tag}")
    print("-" * 88)

    hits = sum(1 for r in rows if r["hit"])
    rate = hits / len(rows)
    print(f"预测命中率: {hits}/{len(rows)} = {rate:.0%}   （区间覆盖率，不是收益率）")
    if rate >= 0.95 and len(rows) >= 6:
        print("⚠ 命中率 ≥95%：预测区间可能给得过宽，先收紧区间再谈准不准")
    elif rate <= 0.30 and len(rows) >= 6:
        print("⚠ 命中率 ≤30%：区间过窄或基线没锚住，先看基线数据（账号中位数/对标）")
    if tampered:
        print(f"⚠ 以下记录的预测在发布后被改动过（指纹不匹配）: {tampered}")

    # 方向性偏差：主指标
    main = data["main_platform"]
    primary = (PLATFORMS[main]["metrics"] or list(CANON))[0]
    pr = [r for r in rows if r["metric"] == primary]
    if len(pr) >= 2:
        ratios = [r["actual"] / ((r["lo"] + r["hi"]) / 2) for r in pr
                  if (r["lo"] + r["hi"]) > 0]
        if ratios:
            avg = sum(ratios) / len(ratios)
            bias = "系统性高估" if avg < 0.9 else ("系统性低估" if avg > 1.1 else "基本无系统偏差")
            print(f"{label(data['main_platform'], primary)}偏差倾向: 实际/预测中位 = {avg:.2f} → {bias}")
    return {"hits": hits, "total": len(rows), "rate": rate}


def cmd_report(args):
    data = load(args.account)
    items = [find_item(data, args.id)] if args.id else \
            [i for i in data["items"] if i.get("actual")]
    if not items:
        sys.exit("没有回填过实际数据的记录")
    stats = _print_report(data, items)
    for it in items:
        if it.get("actual") and not it.get("reported_at"):
            it["reported_at"] = now_iso()
    save(args.account, data)
    print("\n下一步 → 逐条复盘（偏差三问）:")
    pend = [i["id"] for i in items if not i.get("reviewed_at")]
    print(f"  content_ledger.py review {args.account} --id {pend[0] if pend else 1} "
          f"--where <推荐/完播/互动/转化> --evidence \"评论区证据\" "
          f"--verdict <模式|运气> --obs \"一句话观察\"")
    print("  （reported_at 已更新；reviewed 只在真正写完复盘后置位）")
    return stats


def cmd_review(args):
    data = load(args.account)
    it = find_item(data, args.id)
    if not it.get("actual"):
        sys.exit(f"#{args.id} 还没回填实际数据，先 collect")
    for f, label in (("where", "--where 偏差环节"),
                     ("evidence", "--evidence 评论区证据"),
                     ("verdict", "--verdict 模式/运气"),
                     ("obs", "--obs 一句话观察")):
        if not getattr(args, f):
            sys.exit(f"复盘必须补齐 {label}（这是这套方法的核心，不接受空值）")
    if args.verdict not in ("模式", "运气"):
        sys.exit("--verdict 只能是「模式」或「运气」——分不清就先写「运气」并说明不确定")

    it["reviewed_at"] = now_iso()
    it["retro"] = {"where": args.where, "evidence": args.evidence,
                   "verdict": args.verdict, "obs": args.obs}

    # 观察记录累计
    obs_code = args.obs_code or f"OBS-{len(data['observations']) + 1:02d}"
    found = next((o for o in data["observations"] if o["code"] == obs_code), None)
    if found:
        if it["id"] not in found["evidence"]:
            found["evidence"].append(it["id"])
    else:
        data["observations"].append(
            {"code": obs_code, "text": args.obs,
             "evidence": [it["id"]], "created_at": now_iso()})
    save(args.account, data)

    md = _retro_md(data, it, obs_code)
    rr_dir = os.path.join(account_dir(args.account), "retrospectives")
    os.makedirs(rr_dir, exist_ok=True)
    fn = f"RR-{datetime.now(CN).strftime('%Y%m%d')}-{it['id']:03d}.md"
    rr_path = os.path.join(rr_dir, fn)
    with open(rr_path, "w", encoding="utf-8") as f:
        f.write(md)
    _write_observations(data)
    _write_account_md(data)
    obs_path = os.path.join(account_dir(args.account), "observations.md")
    if os.path.isdir(os.path.dirname(OBSIDIAN)):
        tgt = os.path.join(OBSIDIAN, args.account)
        os.makedirs(tgt, exist_ok=True)
        shutil.copy2(rr_path, os.path.join(tgt, fn))
        shutil.copy2(obs_path, os.path.join(tgt, "observations.md"))
        print(f"  ↳ 已同步 Obsidian: {tgt}")

    print(f"✓ 复盘已归档: {rr_path}")
    print(f"  观察 {obs_code} 现有证据 {len(next(o for o in data['observations'] if o['code'] == obs_code)['evidence'])} 条")
    trig = [o for o in data["observations"] if len(o["evidence"]) >= 3]
    if trig:
        print("\n★ 评分卡升级触发：以下观察已被 ≥3 条复盘证据支撑")
        for o in trig:
            print(f"    {o['code']}：{o['text']}  (证据 {'/'.join(map(str,o['evidence']))})")
        print("  → 按 references/rubric-cn.md 的升级流程改 rubric（改完跑 calibrate 回测）")
    else:
        print(f"  升级还需 ≥{3 - len(next(o for o in data['observations'] if o['code']==obs_code)['evidence'])} 条同类证据")


def cmd_calibrate(args):
    data = load(args.account)
    items = [i for i in data["items"] if i.get("actual") and i.get("score")]
    if len(items) < 3:
        sys.exit(f"校准至少需要 3 条「有评分+有实际数据」的记录，当前 {len(items)} 条")
    main = data["main_platform"]
    primary = (PLATFORMS[main]["metrics"] or list(CANON))[0]
    xs, ys, keep = [], [], []
    for it in items:
        a = (it.get("actual") or {}).get(primary)
        if a is None:
            continue
        xs.append(it["score"])
        ys.append(a)
        keep.append(it)
    if len(xs) < 3:
        sys.exit(f"有 {primary}（{label(data['main_platform'], primary)}）实际数据的记录不足 3 条")

    rho = spearman(xs, ys)
    print(f"评分卡校准 · {data['account']} · {data['rubric']['version']}")
    print(f"样本 {len(xs)} 条，主指标 = {label(data['main_platform'], primary)}")
    print(f"Spearman ρ(评分, 实际) = {rho:.2f}" if rho is not None else "ρ 无法计算（评分无差异）")
    if rho is not None:
        if rho >= 0.5:
            print("  → 评分卡有效：分数高确实更跑得动，继续攒样本")
        elif rho >= 0.3:
            print("  → 弱相关：评分卡方向对但区分度不够，优先调权重")
        else:
            print("  → 几乎零相关：当前维度抓的不是主要矛盾，考虑换维度而非调权重")

    # 分档校准表
    order = sorted(keep, key=lambda i: i["score"])
    buckets = [("≤3.5 门槛下", lambda s: s < 3.5),
               ("3.5-4.0", lambda s: 3.5 <= s < 4.0),
               ("4.0-4.5", lambda s: 4.0 <= s < 4.5),
               ("≥4.5", lambda s: s >= 4.5)]
    med_all = sorted(ys)[len(ys) // 2]
    print(f"\n{'评分档':<12}{'条数':>5}{'实际中位(相对全量)':>22}")
    print("-" * 42)
    for bucket_name, fn in buckets:
        vals = [a for s, a in zip(xs, ys) if fn(s)]
        if not vals:
            continue
        m = sorted(vals)[len(vals) // 2]
        ratio = m / med_all if med_all else 0
        print(f"{bucket_name:<12}{len(vals):>5}{fmt_num(m)+f'  ({ratio:.2f}x)':>22}")

    # 维度失效检测
    dims = {d["key"]: d["name"] for d in data["rubric"]["dimensions"]}
    scored = [i for i in items if i.get("scores")]
    if len(scored) >= 5:
        print("\n维度区分度（与主指标秩相关，样本 ≥5 才有意义）:")
        weak = []
        for k, name in dims.items():
            px = [i["scores"][k] for i in scored if k in i["scores"]]
            py = [(i["actual"] or {}).get(primary) for i in scored if k in i["scores"]]
            pair = [(a, b) for a, b in zip(px, py) if b is not None]
            if len(pair) < 5:
                continue
            r = spearman([a for a, _ in pair], [b for _, b in pair])
            if r is None:
                continue
            flag = "  ← 失效候选" if abs(r) < 0.2 else ""
            print(f"  {name:<10} ρ={r:+.2f}{flag}")
            if abs(r) < 0.2:
                weak.append(name)
        if weak:
            print(f"  → 连续 5+ 条零相关即可删除或重定义: {', '.join(weak)}（删之前先确认不是评分口径问题）")
    print("\n提示: 评分卡改动要写进 rubric changelog，附证据编号，改完用近 10 条回测。")


def cmd_list(args):
    data = load(args.account)
    print(f"账号 {data['account']}（{PLATFORMS[data['main_platform']]['label']}）"
          f"  记录 {len(data['items'])} 条  观察 {len(data['observations'])} 条")
    if not data["items"]:
        print("（还没有记录，先 predict）")
        return
    print(f"{'ID':<5}{'状态':<10}{'评分':<6}{'标题':<26}{'预测':<22}{'实际'}")
    print("-" * 96)
    for it in data["items"]:
        if it.get("reviewed_at"):
            st = "已复盘"
        elif it.get("reported_at"):
            st = "已对比"
        elif it.get("published_at"):
            st = "已发布"
        else:
            st = "预测中"
        pred = " ".join(f"{label(it['platform'], k)}{fmt_num(v[0])}-{fmt_num(v[-1])}"
                        for k, v in (it.get("predicted") or {}).items())
        act = " ".join(f"{label(it['platform'], k)}{fmt_num(v)}"
                       for k, v in (it.get("actual") or {}).items())
        flag = "" if verify_fingerprint(it) else " ⚠改过"
        print(f"{it['id']:<5}{st:<10}{str(it.get('score') or '-'):<6}"
              f"{it['title'][:24]:<26}{pred[:20]:<22}{act}{flag}")


def cmd_export(args):
    data = load(args.account)
    _write_account_md(data)
    _write_observations(data)
    md = _ledger_md(data)
    p = os.path.join(account_dir(args.account), "ledger.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"✓ 已导出 Markdown 台账: {p}")
    if os.path.isdir(os.path.dirname(OBSIDIAN)):
        tgt = os.path.join(OBSIDIAN, args.account)
        os.makedirs(tgt, exist_ok=True)
        for fn in ("account.md", "observations.md", "ledger.md"):
            src = os.path.join(account_dir(args.account), fn)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(tgt, fn))
        print(f"  ↳ 已同步 Obsidian: {tgt}")


# ---------------------------------------------------------------- 回采提醒

def _win_hours(w):
    m = re.fullmatch(r"\s*(\d+)\s*([hdwm])\s*", str(w).lower())
    if not m:
        return None
    return int(m.group(1)) * {"h": 1, "d": 24, "w": 168, "m": 720}[m.group(2)]


def _published_hours_ago(published_at):
    try:
        t = datetime.fromisoformat(str(published_at))
    except (TypeError, ValueError):
        return None
    now = datetime.now(t.tzinfo) if t.tzinfo else datetime.now()
    return (now - t).total_seconds() / 3600.0


def cmd_due(args):
    """列出到点该回采的条目。没有任何待采时**不输出**（cron 看门狗靠空输出静默）。"""
    datas = [load(args.account)] if args.account else _load_all()
    if not datas:
        sys.exit(f"没有找到账号台账（{state_dir()}）。")
    rows = []
    for d in datas:
        plat = d["main_platform"]
        primary = (PLATFORMS[plat]["metrics"] or list(CANON))[0]
        for it in d.get("items", []):
            if not it.get("published_at"):
                continue
            el = _published_hours_ago(it["published_at"])
            if el is None or el < 0:
                continue
            wins = []
            for w in (it.get("collect_windows") or PLATFORMS[plat]["windows"]):
                h = _win_hours(w)
                if h is not None:
                    wins.append((h, w))
            if not wins:
                continue
            wins.sort()
            base = {
                "account": d["account"], "id": it["id"], "title": it["title"],
                "platform": PLATFORMS[plat]["label"], "elapsed_h": round(el, 1),
                "primary": primary, "primary_label": label(plat, primary),
                "predicted": (it.get("predicted") or {}).get(primary),
            }
            due = [w for h, w in wins if h <= el]
            if not due:
                if args.all:
                    nxt = dict(base, due="", state="未到期",
                               next_in_h=round(wins[0][0] - el, 1))
                    rows.append(nxt)
                continue
            done_h = _win_hours(it.get("collected_window") or "0h") or 0
            pend = [w for h, w in wins if h <= el and h > done_h]
            if not pend:
                if args.all:
                    rows.append(dict(base, due="", state="已采"))
                continue
            has_actual = (it.get("actual") or {}).get(primary) is not None
            rows.append(dict(base, due=pend[0], also_due=pend[1:],
                             state="补采" if has_actual else "首采"))
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    todo = [r for r in rows if r["due"]]
    rest = [r for r in rows if not r["due"]]
    if not todo and not args.all:
        return  # 看门狗模式：无待采 → 零输出
    if todo:
        print(f"待回采 {len(todo)} 条 · {now_iso()}")
        for r in todo:
            extra = f"，另有 {'/'.join(r['also_due'])} 已到期未采" if r["also_due"] else ""
            print(f"  {r['platform']} {r['account']} #{r['id']}「{r['title']}」"
                  f" 已发布 {r['elapsed_h']:.0f}h → 应采 {r['due']} 窗口（{r['state']}{extra}）")
            print(f"    content-ledger collect {r['account']} --id {r['id']} "
                  f"--window {r['due']} --metric '{r['primary']}=<平台后台实际值>'")
        print("  ※ 数字从平台后台抄录，勿估算——自动抓数会让校准失去可信度。")
    elif args.all:
        print(f"暂无待回采 · {now_iso()}")
    if args.all:
        if rest:
            print(f"其余 {len(rest)} 条：")
            for r in rest:
                tail = (f"还有 {r['next_in_h']:.0f}h 到期" if r["state"] == "未到期"
                        else "已回采")
                print(f"  {r['platform']} {r['account']} #{r['id']}「{r['title']}」"
                      f" {r['state']}（{tail}）")
        if not rows:
            print("没有已登记的发布记录。")


# ---------------------------------------------------------------- 账号矩阵

def _load_all():
    """读取 HOME 下全部账号台账。"""
    datas = []
    for f in sorted(glob.glob(os.path.join(state_dir(), "*.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                datas.append(json.load(fh))
        except (OSError, ValueError):
            continue
    return datas


def _norm_title(t):
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(t)).lower()


def _similar(a, b):
    """粗粒度同题判定：完全相同、互相包含、或前 6 字相同。"""
    if not a or not b:
        return False
    if a == b:
        return True
    if a in b or b in a:
        return True
    return len(a) >= 6 and len(b) >= 6 and a[:6] == b[:6]


def _account_stats(d):
    main = d["main_platform"]
    primary = (PLATFORMS[main]["metrics"] or list(CANON))[0]
    items = d.get("items", [])
    rows = hit_stats(items)
    scored = [i["score"] for i in items if i.get("score")]
    prim = sorted((i.get("actual") or {}).get(primary) for i in items
                  if (i.get("actual") or {}).get(primary) is not None)
    best, best_v = None, None
    for i in items:
        v = (i.get("actual") or {}).get(primary)
        if v is not None and (best_v is None or v > best_v):
            best, best_v = i, v
    return {
        "account": d["account"],
        "platform": main,
        "platform_label": PLATFORMS[main]["label"],
        "primary": primary,
        "primary_label": label(main, primary),
        "items": len(items),
        "reviewed": sum(1 for i in items if i.get("reviewed_at")),
        "hit_rate": (sum(1 for r in rows if r["hit"]) / len(rows)) if rows else None,
        "avg_score": (sum(scored) / len(scored)) if scored else None,
        "median_primary": prim[len(prim) // 2] if prim else None,
        "best_title": best["title"] if best else None,
        "best_value": best_v,
        "pillars": d.get("pillars") or [],
    }


def cmd_matrix(args):
    datas = _load_all()
    if not datas:
        sys.exit(f"没有找到任何账号台账（{state_dir()}）。先 init 一个账号。")
    stats = [_account_stats(d) for d in datas]

    print(f"账号矩阵总览 · {len(stats)} 个账号 · 数据根 {HOME} · {now_iso()}")
    print("=" * 108)
    print(f"{'账号':<18}{'平台':<8}{'条数':>5}{'已复盘':>7}{'命中率':>8}"
          f"{'均分':>7}{'主指标中位':>12}  最强条")
    print("-" * 108)
    for s in stats:
        rate = f"{s['hit_rate']:.0%}" if s["hit_rate"] is not None else "-"
        avg = f"{s['avg_score']:.2f}" if s["avg_score"] is not None else "-"
        med = fmt_num(s["median_primary"]) if s["median_primary"] is not None else "-"
        best = f"{s['best_title'][:18]} {fmt_num(s['best_value'])}" if s["best_title"] else "-"
        print(f"{s['account']:<18}{s['platform_label']:<8}{s['items']:>5}{s['reviewed']:>7}"
              f"{rate:>8}{avg:>7}{med:>12}  {best}")
    total = sum(s["items"] for s in stats)
    done = sum(s["reviewed"] for s in stats)
    print("-" * 108)
    print(f"合计 {total} 条，已复盘 {done} 条（{done/total:.0%}）。"
          f"未复盘 {total - done} 条 —— 矩阵的复利点在复盘，不在发布量。")

    # ---- 支柱 × 账号 表现矩阵
    pillars = []
    for d in datas:
        for i in d.get("items", []):
            p = i.get("pillar") or "（未标）"
            if p not in pillars:
                pillars.append(p)
    if pillars != ["（未标）"]:
        print("\n支柱 × 账号 表现矩阵（格 = 条数 / 均分 / 主指标中位）")
        print("-" * 108)
        w = 22
        print(f"{'账号':<18}" + "".join(f"{p[:10]:<{w}}" for p in pillars))
        for d, s in zip(datas, stats):
            primary = s["primary"]
            cells = []
            for p in pillars:
                sub = [i for i in d.get("items", [])
                       if (i.get("pillar") or "（未标）") == p]
                if not sub:
                    cells.append("-")
                    continue
                sc = [i["score"] for i in sub if i.get("score")]
                av = f"{sum(sc)/len(sc):.2f}" if sc else "-"
                pv = sorted((i.get("actual") or {}).get(primary) for i in sub
                            if (i.get("actual") or {}).get(primary) is not None)
                md = fmt_num(pv[len(pv) // 2]) if pv else "-"
                cells.append(f"{len(sub)}/{av}/{md}")
            print(f"{s['account']:<18}" + "".join(f"{c[:w-1]:<{w}}" for c in cells))
        print(f"  ※ 中位=该账号主指标。某格「条数少但均分/中位高」= 这个账号最适合这个支柱，"
              f"值得加投；「条数多但中位低」= 惯性产出，该砍。")

    # ---- 跨账号复用候选
    print(f"\n跨账号复用候选（跑通 ≥{args.threshold:.2f}x 预测中位、且其他账号还没做过的题）")
    print("-" * 108)
    n = 0
    for d in datas:
        s = _account_stats(d)
        primary = s["primary"]
        for it in d.get("items", []):
            rng = (it.get("predicted") or {}).get(primary)
            a = (it.get("actual") or {}).get(primary)
            if a is None or not rng:
                continue
            mid = (rng[0] + rng[-1]) / 2
            if mid <= 0 or a / mid < args.threshold:
                continue
            t = _norm_title(it["title"])
            for o in datas:
                if o["account"] == d["account"]:
                    continue
                if any(_similar(t, _norm_title(x["title"]))
                       for x in o.get("items", [])):
                    continue
                print(f"  {d['account']}#{it['id']}「{it['title']}」{fmt_num(a)}"
                      f"（{a/mid:.2f}x 预测中位）→ 可在 {o['account']}"
                      f"（{PLATFORMS[o['main_platform']]['label']}）做同题改写")
                n += 1
    if not n:
        print("  （暂无：要么还没有跑出超预期的题，要么各账号都做过了）")

    if args.csv:
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["账号", "平台", "条数", "已复盘", "命中率", "均分",
                         "主指标", "主指标中位", "最强条", "最强条数值"])
            for s in stats:
                wr.writerow([s["account"], s["platform_label"], s["items"],
                             s["reviewed"],
                             f"{s['hit_rate']:.3f}" if s["hit_rate"] is not None else "",
                             f"{s['avg_score']:.2f}" if s["avg_score"] is not None else "",
                             s["primary_label"],
                             s["median_primary"] if s["median_primary"] is not None else "",
                             s["best_title"] or "",
                             s["best_value"] if s["best_value"] is not None else ""])
        print(f"\n✓ 汇总已导出 CSV: {args.csv}（UTF-8-BOM，Excel 直接开不乱码）")


# ---------------------------------------------------------------- Markdown 渲染

def _write_account_md(data):
    a = data
    lines = [
        f"# {a['nickname']} 账号档案 {a['rubric']['version']}",
        "",
        f"- 台账账号：`{a['account']}`",
        f"- 平台：{'、'.join(PLATFORMS[p]['label'] for p in a['platforms'])}",
        f"- 内容支柱：{'、'.join(a['pillars']) if a['pillars'] else '（待补）'}",
        f"- 创建时间：{a['created_at']}",
        f"- 记录数：{len(a['items'])}",
        "",
        "## 评分卡 " + a["rubric"]["version"],
        "",
        "| 维度 | 权重 | 说明 |",
        "|---|---|---|",
    ]
    for d in a["rubric"]["dimensions"]:
        lines.append(f"| {d['name']} | {d['weight']:.0%} | {d.get('note','')} |")
    lines += ["", f"发布门槛：≥{a['rubric']['gate']}；低于门槛回炉或放弃。", ""]
    if a["rubric"].get("changelog"):
        lines += ["## 评分卡变更日志", ""]
        for c in a["rubric"]["changelog"]:
            lines += [f"### {c.get('version')} — {c.get('date')}",
                      f"- 变更：{c.get('change')}",
                      f"- 证据：{c.get('evidence')}",
                      f"- 回测：{c.get('retest','')}", ""]
    p = os.path.join(account_dir(a["account"]), "account.md")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_observations(data):
    lines = [f"# {data['account']} 观察记录", "",
             "同一观察被 ≥3 条复盘证据支撑时，触发评分卡升级流程。", ""]
    if not data["observations"]:
        lines.append("（暂无）")
    for o in data["observations"]:
        n = len(o["evidence"])
        mark = " ★可升级" if n >= 3 else ""
        lines.append(f"- **{o['code']}**：{o['text']}"
                     f"（证据 {n} 条：{'/'.join('#'+str(i) for i in o['evidence'])}）{mark}")
    p = os.path.join(account_dir(data["account"]), "observations.md")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _retro_md(data, it, obs_code):
    rows = hit_stats([it])
    a = it.get("actual") or {}
    lines = [
        f"# 复盘 RR-{datetime.now(CN).strftime('%Y%m%d')}-{it['id']:03d}",
        "",
        f"- 账号：{data['account']}　平台：{PLATFORMS[it['platform']]['label']}"
        f"　评分：{it.get('score')}",
        f"- 标题：{it['title']}",
        f"- 发布：{it.get('published_at') or '-'}　链接：{it.get('url') or '-'}",
        f"- 采集窗口：{it.get('collected_window') or ','.join(it.get('collect_windows') or [])}",
        "",
        "## 预测 vs 实际",
        "",
        "| 指标 | 预测区间 | 实际 | 判定 |",
        "|---|---|---|---|",
    ]
    for r in rows:
        tag, _ = judge(r["actual"], r["lo"], r["hi"])
        lines.append(f"| {label(it['platform'], r['metric'])} | {fmt_num(r['lo'])}-{fmt_num(r['hi'])} "
                     f"| {fmt_num(r['actual'])} | {tag} |")
    if not rows:
        lines.append("| （无预测值可对比） | | | |")
    hits = sum(1 for r in rows if r["hit"])
    if rows:
        lines.append(f"\n本条命中率：{hits}/{len(rows)}")
    lines += ["", f"- 预测依据：{it.get('predict_note') or '（未写）'}",
              f"- 置信度：{it.get('confidence')}", ""]
    if it.get("top_comments"):
        lines += ["## 评论区证据", ""]
        for c in it["top_comments"]:
            lines.append(f"- {c}")
        lines.append("")
    retro = it.get("retro") or {}
    lines += [
        "## 偏差定位",
        "",
        retro.get("where", ""), "",
        "## 评论区证据解读",
        "",
        retro.get("evidence", ""), "",
        f"## 结论（{retro.get('verdict','')}）",
        "",
        "判断依据：见上两节。", "",
        "## 沉淀",
        "",
        f"{obs_code}：{retro.get('obs','')}", "",
    ]
    return "\n".join(lines)


def _ledger_md(data):
    lines = [f"# {data['account']} 内容台账", "",
             f"> 平台 {'、'.join(PLATFORMS[p]['label'] for p in data['platforms'])}"
             f" · 评分卡 {data['rubric']['version']} · 导出于 {now_iso()}", "",
             "| ID | 状态 | 评分 | 标题 | 支柱 | 预测 | 实际 | 命中 | 复盘结论 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for it in data["items"]:
        if it.get("reviewed_at"):
            st = "已复盘"
        elif it.get("reported_at"):
            st = "已对比"
        elif it.get("published_at"):
            st = "已发布"
        else:
            st = "预测中"
        rows = hit_stats([it])
        hit = f"{sum(1 for r in rows if r['hit'])}/{len(rows)}" if rows else "-"
        pred = "<br>".join(f"{label(it['platform'], k)} {fmt_num(v[0])}-{fmt_num(v[-1])}"
                           for k, v in (it.get("predicted") or {}).items())
        act = "<br>".join(f"{label(it['platform'], k)} {fmt_num(v)}"
                          for k, v in (it.get("actual") or {}).items())
        verdict = (it.get("retro") or {}).get("verdict", "")
        lines.append(f"| {it['id']} | {st} | {it.get('score') or '-'} | {it['title']} "
                     f"| {it.get('pillar') or '-'} | {pred or '-'} | {act or '-'} "
                     f"| {hit} | {verdict or '-'} |")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI

def build_parser():
    ap = argparse.ArgumentParser(
        description="内容运营校准台账 v" + VERSION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--version", action="version", version=VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="创建账号台账")
    p.add_argument("account")
    p.add_argument("--platform", default="xhs",
                   help="xhs/douyin/shipinhao/bilibili/tiktok/gzh，多个用逗号")
    p.add_argument("--nickname", default="")
    p.add_argument("--pillars", default="", help="内容支柱，逗号分隔")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("predict", help="发布前锁预测（必写）")
    p.add_argument("account")
    p.add_argument("--title", required=True)
    p.add_argument("--score", type=float, default=None)
    p.add_argument("--dim-score", action="append", default=[],
                   help="维度分 k=v，可多次；给了维度分可自动加权算总分")
    p.add_argument("--pillar", default="")
    p.add_argument("--platform", default="")
    p.add_argument("--metric", action="append", default=[],
                   help="k=lo-hi 或 k=v，可多次")
    p.add_argument("--note", default="")
    p.add_argument("--conf", type=float, default=0.5)
    p.add_argument("--windows", default="")
    p.set_defaults(fn=cmd_predict)

    p = sub.add_parser("publish", help="登记发布")
    p.add_argument("account")
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--url", default="")
    p.add_argument("--windows", default="")
    p.set_defaults(fn=cmd_publish)

    p = sub.add_parser("collect", help="回填实际数据")
    p.add_argument("account")
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--metric", action="append", default=[])
    for k in CANON:
        p.add_argument(f"--{k.replace('_','-')}", type=None, default=None)
    p.add_argument("--window", default="")
    p.add_argument("--top-comments", default="")
    p.set_defaults(fn=cmd_collect)

    p = sub.add_parser("report", help="偏差报告（只对比，不算复盘完成）")
    p.add_argument("account")
    p.add_argument("--id", type=int)
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("review", help="偏差三问复盘归档")
    p.add_argument("account")
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--where", default="")
    p.add_argument("--evidence", default="")
    p.add_argument("--verdict", default="")
    p.add_argument("--obs", default="")
    p.add_argument("--obs-code", default="")
    p.set_defaults(fn=cmd_review)

    p = sub.add_parser("calibrate", help="评分卡校准（秩相关+分档+失效维度）")
    p.add_argument("account")
    p.set_defaults(fn=cmd_calibrate)

    p = sub.add_parser("list", help="列出记录")
    p.add_argument("account")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("export", help="导出 Markdown 台账 / 同步 Obsidian")
    p.add_argument("account")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("due", help="列出到点该回采的条目（无待采则静默，供 cron 看门狗）")
    p.add_argument("account", nargs="?", default="")
    p.add_argument("--all", action="store_true", help="连未到期/已采的也列出")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_due)

    p = sub.add_parser("matrix", help="账号矩阵总览（跨账号对比/支柱矩阵/复用候选）")
    p.add_argument("--threshold", type=float, default=1.0,
                   help="复用候选门槛：实际/预测中位 ≥ 该值（默认 1.0）")
    p.add_argument("--csv", default="", help="导出汇总 CSV 路径")
    p.set_defaults(fn=cmd_matrix)
    return ap


def main():
    ap = build_parser()
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
