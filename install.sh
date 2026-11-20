#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$HOME/.gemini/config/skills/relay-monitor"
BIN_DIR="$HOME/.local/bin"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$SKILL_DIR/scripts" "$BIN_DIR"
cp "$REPO_DIR/SKILL.md" "$SKILL_DIR/"
cp "$REPO_DIR/config.example.json" "$SKILL_DIR/"
cp "$REPO_DIR/scripts/"*.py "$SKILL_DIR/scripts/"
chmod +x "$SKILL_DIR/scripts/relay_cli.py"

if [ ! -f "$SKILL_DIR/config.json" ]; then
  cp "$REPO_DIR/config.example.json" "$SKILL_DIR/config.json"
  echo "[!] Created $SKILL_DIR/config.json from template. Please edit it with your API token and ServerChan SendKey."
fi

ln -sf "$SKILL_DIR/scripts/relay_cli.py" "$BIN_DIR/relay-monitor"
echo "[✓] Installed relay-monitor skill to $SKILL_DIR"
echo "[✓] Linked CLI command to $BIN_DIR/relay-monitor"
