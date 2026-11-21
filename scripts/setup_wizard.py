#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interactive foolproof setup wizard for Relay Monitor."""

import json
import os
import platform
import re
import shutil
import subprocess
import urllib.request
import webbrowser

from core import CONFIG_PATH, SKILL_DIR, push_wechat


def _detect_claude_code_env():
    """Auto-detect base_url and token from ~/.claude/settings.json if present."""
    settings_path = os.path.expanduser("~/.claude/settings.json")
    if not os.path.exists(settings_path):
        return "", ""
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            env = json.load(f).get("env", {})
        raw_url = env.get("ANTHROPIC_BASE_URL", "")
        token = env.get("ANTHROPIC_AUTH_TOKEN", "")
        # Extract embedded upstream URL if wrapped in local proxy path
        matches = re.findall(r"https?://[^\s/]+(?::\d+)?", raw_url)
        base_url = matches[-1] if matches else raw_url
        return base_url.rstrip("/"), token
    except Exception:
        return "", ""


def _prompt(label, default="", secret=False):
    if default:
        masked = f"{default[:6]}...{default[-4:]}" if (secret and len(default) > 12) else default
        tip = f" [默认: {masked}]"
    else:
        tip = ""
    val = input(f"{label}{tip}: ").strip()
    return val if val else default


def _install_cloudflared():
    existing = shutil.which("cloudflared") or os.path.expanduser("~/.local/bin/cloudflared")
    if existing and os.path.exists(existing):
        print(f"✅ 已检测到 cloudflared: {existing}")
        return

    ans = input("\n是否自动下载 cloudflared（用于生成手机 4G/5G 公网访问看板链接）？[Y/n]: ").strip().lower()
    if ans in ("n", "no"):
        print("⏭️  跳过 cloudflared 安装（后续仍可使用本地检测与微信推送）。")
        return

    system = platform.system().lower()
    machine = platform.machine().lower()
    if system != "linux":
        print("⚠️  非 Linux 系统请手动安装 cloudflared（macOS: brew install cloudflared）。")
        return

    arch = "amd64" if machine in ("x86_64", "amd64") else ("arm64" if "arm" in machine or "aarch64" in machine else "")
    if not arch:
        print(f"⚠️  暂不支持自动下载架构 {machine}，请手动安装 cloudflared。")
        return

    url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
    bin_dir = os.path.expanduser("~/.local/bin")
    os.makedirs(bin_dir, exist_ok=True)
    target = os.path.join(bin_dir, "cloudflared")
    print(f"⏳ 正在下载 cloudflared ({arch}) 到 {target} ...")
    try:
        urllib.request.urlretrieve(url, target)
        os.chmod(target, 0o755)
        print("✅ cloudflared 安装成功！")
    except Exception as e:
        print(f"❌ 下载失败（请检查网络或代理）: {e}")


def _setup_github_secrets(cfg):
    if not shutil.which("gh"):
        return
    git_dir = os.path.join(SKILL_DIR, ".git")
    if not os.path.exists(git_dir):
        return
    ans = input("\n检测到 GitHub CLI (gh) 与当前仓库，是否一键将配置写入 GitHub Actions Secrets？[y/N]: ").strip().lower()
    if ans not in ("y", "yes"):
        return

    secrets = {
        "RELAY_BASE_URL": cfg["base_url"],
        "RELAY_TOKEN": cfg["token"],
        "SERVERCHAN_KEY": cfg["serverchan_sendkey"],
    }
    for k, v in secrets.items():
        if not v:
            continue
        try:
            subprocess.run(["gh", "secret", "set", k, "--body", v], cwd=SKILL_DIR, check=True)
            print(f"  ✅ 已设置 Secret: {k}")
        except Exception as e:
            print(f"  ❌ 设置 {k} 失败: {e}")


def run_wizard():
    print("============================================================")
    print("🚀 Relay Monitor 傻瓜式初始化向导")
    print("============================================================")

    existing_cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                existing_cfg = json.load(f)
        except Exception:
            pass

    detected_url, detected_token = _detect_claude_code_env()
    default_url = existing_cfg.get("base_url") or detected_url or "http://127.0.0.1:3060"
    default_token = existing_cfg.get("token") or detected_token

    print("\n--- 第 1 步：配置中转站接口 ---")
    if detected_url:
        print(f"💡 已从 ~/.claude/settings.json 自动识别到配置，直接回车即可沿用！")
    base_url = _prompt("1. 请输入中转站地址 (Base URL)", default_url).rstrip("/")
    token = _prompt("2. 请输入中转站 API Token", default_token, secret=True)

    print("\n--- 第 2 步：获取并绑定微信通知 Token (Server酱 SendKey) ---")
    print("📱 只需 10 秒即可免费绑定个人微信提醒（无需自建服务器）：")
    print("   1) 打开网址: https://sct.ftqq.com")
    print("   2) 使用微信扫码登录 → 点击顶部菜单「Key & API」→ 复制 SendKey（形如 SCTxxxx）")
    print("   3) 在「消息通道」中确认已绑定微信服务号/方糖公众号")

    default_key = existing_cfg.get("serverchan_sendkey", "")
    if not default_key:
        open_browser = input("\n是否尝试自动打开浏览器前往 sct.ftqq.com 扫码获取？[Y/n]: ").strip().lower()
        if open_browser not in ("n", "no"):
            try:
                webbrowser.open("https://sct.ftqq.com")
            except Exception:
                pass

    sendkey = ""
    while True:
        sendkey = _prompt("\n3. 请粘贴你的 Server酱 SendKey (留空跳过)", default_key, secret=True)
        if not sendkey:
            print("⚠️  未配置 SendKey，将跳过微信推送功能。")
            break
        if not sendkey.startswith("SCT"):
            print("⚠️  提示：Server酱 Turbo 版的 SendKey 通常以 'SCT' 开头，请确认是否粘贴完整。")
        test_cfg = {"serverchan_sendkey": sendkey}
        print("⏳ 正在向你的微信发送测试通知，请留意手机微信...")
        if push_wechat("🎉 Relay Monitor 微信通知已连通", "恭喜！你的中转站监控微信推送通道配置成功。", test_cfg):
            print("✅ 测试消息发送成功！请查看手机微信确认收到。")
            break
        retry = input("❌ 推送失败，是否重新输入 SendKey？[Y/n]: ").strip().lower()
        if retry in ("n", "no"):
            break

    example_path = os.path.join(SKILL_DIR, "config.example.json")
    cfg = {}
    if os.path.exists(example_path):
        with open(example_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    cfg.update(existing_cfg)
    cfg["base_url"] = base_url
    cfg["token"] = token
    cfg["serverchan_sendkey"] = sendkey

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.chmod(CONFIG_PATH, 0o600)
    print(f"\n✅ 配置已加密保存至: {CONFIG_PATH} (权限 600)")

    _install_cloudflared()
    _setup_github_secrets(cfg)

    print("\n============================================================")
    print("🎉 初始化完成！现在你可以直接使用以下命令：")
    print("   relay-monitor check --push   # 立即测速并推送到微信")
    print("   relay-monitor daemon start   # 启动手机看板与 24h 自动巡检")
    print("============================================================")


if __name__ == "__main__":
    run_wizard()
