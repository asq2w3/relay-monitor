#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$HOME/.gemini/config/skills/relay-monitor"
BIN_DIR="$HOME/.local/bin"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$SKILL_DIR/scripts" "$BIN_DIR"
cp "$REPO_DIR/SKILL.md" "$SKILL_DIR/"
cp "$REPO_DIR/config.example.json" "$SKILL_DIR/"
cp "$REPO_DIR/scripts/"*.py "$SKILL_DIR/scripts/"
chmod +x "$SKILL_DIR/scripts/relay_cli.py" "$SKILL_DIR/scripts/setup_wizard.py"

ln -sf "$SKILL_DIR/scripts/relay_cli.py" "$BIN_DIR/relay-monitor"

echo "============================================================"
echo "[✓] 已安装 Relay Monitor 技能至: $SKILL_DIR"
echo "[✓] 已创建全局命令: $BIN_DIR/relay-monitor"
echo "============================================================"

# Ensure ~/.local/bin is in PATH notice
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  echo "💡 提示: 请将 ~/.local/bin 加入 PATH (export PATH=\"\$HOME/.local/bin:\$PATH\")"
fi

if [ ! -f "$SKILL_DIR/config.json" ]; then
  echo ""
  echo "检测到尚未配置中转站与微信通知，即将进入傻瓜式配置向导..."
  python3 "$SKILL_DIR/scripts/relay_cli.py" init
else
  echo ""
  echo "检测到已有配置文件: $SKILL_DIR/config.json"
  echo "如需重新配置或更换微信 SendKey，随时运行: relay-monitor init"
fi
