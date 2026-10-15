#!/usr/bin/env python3
"""测试用：把某账号某条记录的 published_at 回拨 N 小时。

用法: _backdate.py <CONTENT_OPS_HOME> <账号> <ID> <小时数>
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

home, acc, iid, hours = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
p = os.path.join(home, "state", acc + ".json")
with open(p, encoding="utf-8") as fh:
    d = json.load(fh)

tz = timezone(timedelta(hours=8))
t = (datetime.now(tz) - timedelta(hours=hours)).isoformat(timespec="seconds")
for it in d["items"]:
    if it["id"] == iid:
        it["published_at"] = t

with open(p, "w", encoding="utf-8") as fh:
    json.dump(d, fh, ensure_ascii=False, indent=2)
print(f"#{iid} published_at ← {t}")
