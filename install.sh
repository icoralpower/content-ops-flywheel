#!/bin/bash
# 把本 skill 安装/更新到 skillshare，并同步到各 AI 工具（Hermes/Codex/OpenClaw/OpenCode）
# 用法: bash install.sh
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
ROOT="${SKILLSHARE_SKILLS:-$HOME/.config/skillshare/skills}"
DEST="$ROOT/marketing/content-ops-flywheel"

case "$DEST" in
  *content-ops-flywheel) ;;
  *) echo "拒绝执行：目标路径异常 $DEST" >&2; exit 1 ;;
esac

echo "源:   $SRC"
echo "目标: $DEST"

mkdir -p "$(dirname "$DEST")"
# 不用 rm -rf：目标已存在时直接覆盖文件即可（不做删除同步）
mkdir -p "$DEST"
cp -R "$SRC/." "$DEST/"

chmod +x "$DEST/scripts/content_ledger.py" "$DEST/tests/"*.sh 2>/dev/null || true

# 让脚本能作为命令直接调用
mkdir -p "$HOME/.local/bin"
ln -sf "$SRC/scripts/content_ledger.py" "$HOME/.local/bin/content-ledger"
chmod +x "$SRC/scripts/content_ledger.py"

if command -v skillshare >/dev/null 2>&1; then
  skillshare sync
else
  echo "⚠ 未找到 skillshare，仅完成本地安装（手动复制到各工具目录）"
fi

echo "✓ 安装完成: $DEST"
echo "  命令: content-ledger --help  （若 ~/.local/bin 不在 PATH，用 $SRC/scripts/content_ledger.py）"
