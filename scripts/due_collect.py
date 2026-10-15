#!/usr/bin/env python3
"""回采看门狗（供 hermes cron --no-agent --script 调用）。

有待回采 → 打印待办清单（含可直接复制的 collect 命令）
无待回采 → **不输出任何内容**（cron 空输出即不推送）

安装（把本文件拷到 ~/.hermes/scripts/ 后，它会自动去这些地方找引擎）：
    cp scripts/due_collect.py ~/.hermes/scripts/
    hermes cron create "0 10 * * *" --name "内容台账·回采提醒" \
      --no-agent --script due_collect.py --deliver local

引擎查找顺序：本文件同目录 → CONTENT_OPS_ENGINE → PATH 上的 content-ledger
→ ~/.config/skillshare/skills/content-ops-flywheel/scripts → ~/.hermes/skills/content-ops-flywheel/scripts
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _candidate_dirs():
    cands = [HERE, os.environ.get("CONTENT_OPS_ENGINE", "")]
    for d in os.environ.get("PATH", "").split(os.pathsep):
        p = os.path.join(d, "content-ledger") if d else ""
        if p and os.path.exists(p):
            cands.append(os.path.dirname(os.path.realpath(p)))
            break
    home = os.path.expanduser("~")
    cands += [
        os.path.join(home, ".config/skillshare/skills/content-ops-flywheel/scripts"),
        os.path.join(home, ".hermes/skills/content-ops-flywheel/scripts"),
    ]
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


for _d in _candidate_dirs():
    if os.path.exists(os.path.join(_d, "content_ledger.py")):
        sys.path.insert(0, _d)
        break

try:
    import content_ledger as cl  # noqa: E402
except ImportError:
    sys.stderr.write(
        "due_collect: 找不到 content_ledger.py。请确认 skill 已安装"
        "（bash install.sh），或用 CONTENT_OPS_ENGINE 指向它所在目录。\n"
    )
    sys.exit(1)

sys.argv = ["content_ledger.py", "due"] + sys.argv[1:]
cl.main()
