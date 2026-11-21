#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-platform (Linux / Windows / macOS) one-click installer for Relay Monitor."""

import glob
import os
import shutil
import subprocess
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main():
    repo_dir = os.path.dirname(os.path.realpath(__file__))
    skill_dir = os.path.expanduser("~/.gemini/config/skills/relay-monitor")
    scripts_dst = os.path.join(skill_dir, "scripts")
    bin_dir = os.path.expanduser("~/.local/bin")

    os.makedirs(scripts_dst, exist_ok=True)
    os.makedirs(bin_dir, exist_ok=True)

    shutil.copy2(os.path.join(repo_dir, "SKILL.md"), os.path.join(skill_dir, "SKILL.md"))
    shutil.copy2(os.path.join(repo_dir, "config.example.json"), os.path.join(skill_dir, "config.example.json"))
    for py_file in glob.glob(os.path.join(repo_dir, "scripts", "*.py")):
        dst_file = os.path.join(scripts_dst, os.path.basename(py_file))
        shutil.copy2(py_file, dst_file)
        if os.name != "nt":
            os.chmod(dst_file, 0o755)

    cli_path = os.path.join(scripts_dst, "relay_cli.py")

    if os.name == "nt":
        cmd_content = f'@echo off\r\n"{sys.executable}" "{cli_path}" %*\r\n'
        shim_paths = [os.path.join(bin_dir, "relay-monitor.cmd")]
        py_scripts = os.path.join(os.path.dirname(sys.executable), "Scripts")
        if os.path.isdir(py_scripts) and os.access(py_scripts, os.W_OK):
            shim_paths.append(os.path.join(py_scripts, "relay-monitor.cmd"))
        for shim in shim_paths:
            with open(shim, "w", encoding="utf-8") as f:
                f.write(cmd_content)
        print(f"[✓] 已创建 Windows 全局命令: {shim_paths[-1]}")
        if len(shim_paths) == 1 and bin_dir.lower() not in os.environ.get("PATH", "").lower():
            print(f"💡 提示: 请将 {bin_dir} 加入系统环境变量 PATH，即可在任意终端直接运行 relay-monitor")
    else:
        link_path = os.path.join(bin_dir, "relay-monitor")
        if os.path.lexists(link_path):
            os.remove(link_path)
        os.symlink(cli_path, link_path)
        print(f"[✓] 已创建全局命令软链: {link_path}")
        if bin_dir not in os.environ.get("PATH", "").split(":"):
            print(f'💡 提示: 请将 {bin_dir} 加入 PATH (export PATH="$HOME/.local/bin:$PATH")')

    print("============================================================")
    print(f"[✓] 已安装 Relay Monitor 技能至: {skill_dir}")
    print("============================================================")

    cfg_path = os.path.join(skill_dir, "config.json")
    if not os.path.exists(cfg_path):
        print("\n检测到尚未配置中转站与微信通知，即将进入傻瓜式配置向导...")
        subprocess.run([sys.executable, cli_path, "init"], check=False)
    else:
        print(f"\n检测到已有配置文件: {cfg_path}")
        print("如需重新配置或更换微信 SendKey，随时运行: relay-monitor init")


if __name__ == "__main__":
    main()
