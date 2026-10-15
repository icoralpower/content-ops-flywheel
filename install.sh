#!/bin/bash
# 安装/更新本 skill 到 skillshare，并同步到各 AI 工具（Hermes / Codex / OpenClaw / OpenCode）
# 用法: bash install.sh
#
# 为什么走 install 而不是 cp：
#   skillshare 只在 install 时才登记 skill。手动往 sources/skills/ 拷目录不会被 sync 链接，
#   会出现「文件在但各端看不到」；而且和已登记的副本并存会导致重复入口。
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"

if ! command -v skillshare >/dev/null 2>&1; then
  echo "✗ 未找到 skillshare CLI，无法分发。脚本本体仍可直接运行："
  echo "    python3 $SRC/scripts/content_ledger.py --help"
  exit 1
fi

chmod +x "$SRC/scripts/content_ledger.py" "$SRC/tests/"*.sh 2>/dev/null || true

echo "▸ 登记/更新 $SRC"
skillshare install "$SRC" --force -y

echo "▸ 同步到各端"
skillshare sync

echo
echo "▸ 各端链接状态"
for d in "$HOME/.hermes/skills" "$HOME/.codex/skills" \
         "$HOME/.openclaw/skills" "$HOME/.config/opencode/skills"; do
  [ -d "$d" ] || continue
  if [ -e "$d/content-ops-flywheel" ]; then
    printf "  ✓ %s\n" "${d/#$HOME/~}"
  else
    printf "  ✗ %s（未链接，检查 config.yaml 的 targets）\n" "${d/#$HOME/~}"
  fi
done

# 让脚本能作为命令直接调用（~/.local/bin 通常已在 PATH）
mkdir -p "$HOME/.local/bin"
ln -sf "$SRC/scripts/content_ledger.py" "$HOME/.local/bin/content-ledger"
echo
echo "✓ 完成。命令: content-ledger --help"
echo "  重新导出后记得跑一次 tests: bash tests/acceptance.sh && bash tests/matrix.sh"
