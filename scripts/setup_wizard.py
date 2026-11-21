#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interactive foolproof setup wizard for Relay Monitor."""

import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import urllib.request
import webbrowser

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from core import CONFIG_PATH, SKILL_DIR, normalize_base_url, push_wechat, save_config, test_relay_connection
from tunnel import format_public_links, get_current_url


def _detect_claude_code_env():
    """Auto-detect base_url and token from ~/.claude/settings.json if present."""
    settings_path = os.path.expanduser("~/.claude/settings.json")
    if not os.path.exists(settings_path):
        return "", ""
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            env = json.load(f).get("env", {})
        raw_url = (env.get("ANTHROPIC_BASE_URL") or "").strip()
        token = (env.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
        # Unwrap proxy prefix like http://127.0.0.1:18787/bili/http://real-host:3060
        last_http = max(raw_url.rfind("https://"), raw_url.rfind("http://"))
        base_url = raw_url[last_http:] if last_http >= 0 else raw_url
        return normalize_base_url(base_url), token
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
    bin_name = "cloudflared.exe" if os.name == "nt" else "cloudflared"
    existing = shutil.which("cloudflared") or os.path.expanduser(f"~/.local/bin/{bin_name}")
    if existing and os.path.exists(existing):
        print(f"✅ 已检测到 cloudflared: {existing}")
        return

    ans = input("\n是否自动下载 cloudflared（用于生成手机 4G/5G 公网访问看板链接）？[Y/n]: ").strip().lower()
    if ans in ("n", "no"):
        print("⏭️  跳过 cloudflared 安装（后续仍可使用本地检测与微信推送）。")
        return

    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = "amd64" if machine in ("x86_64", "amd64") else ("arm64" if "arm" in machine or "aarch64" in machine else "")

    if system == "windows":
        url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    elif system == "linux" and arch:
        url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
    else:
        print("⚠️  暂不支持自动下载当前系统/架构，请手动安装 cloudflared（macOS: brew install cloudflared）。")
        return

    bin_dir = os.path.expanduser("~/.local/bin")
    os.makedirs(bin_dir, exist_ok=True)
    target = os.path.join(bin_dir, bin_name)
    print(f"⏳ 正在下载 cloudflared ({system}/{arch or 'amd64'}) 到 {target} ...")
    try:
        urllib.request.urlretrieve(url, target)
        if os.name != "nt":
            os.chmod(target, 0o755)
        print("✅ cloudflared 安装成功！")
    except Exception as e:
        print(f"❌ 下载失败（请检查网络或代理）: {e}")


def _find_git_repo_dir():
    for candidate in (os.getcwd(), SKILL_DIR):
        if os.path.isdir(os.path.join(candidate, ".git")):
            return candidate
    return None


def _setup_github_secrets(cfg):
    if not shutil.which("gh"):
        return
    repo_dir = _find_git_repo_dir()
    if not repo_dir:
        return
    ans = input(f"\n检测到 GitHub CLI (gh) 与仓库 ({repo_dir})，是否一键将配置写入 GitHub Actions Secrets？[y/N]: ").strip().lower()
    if ans not in ("y", "yes"):
        return

    secrets_map = {
        "RELAY_BASE_URL": cfg["base_url"],
        "RELAY_TOKEN": cfg["token"],
        "SERVERCHAN_KEY": cfg["serverchan_sendkey"],
    }
    for k, v in secrets_map.items():
        if not v:
            continue
        try:
            subprocess.run(["gh", "secret", "set", k, "--body", v], cwd=repo_dir, check=True)
            print(f"  ✅ 已设置 Secret: {k}")
        except Exception as e:
            print(f"  ❌ 设置 {k} 失败: {e}")


def run_wizard():
    print("============================================================")
    print("🚀 Relay Monitor 傻瓜式初始化向导 (Linux / Windows / macOS)")
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
        print("💡 已从 ~/.claude/settings.json 自动识别到配置，直接回车即可沿用！")
    while True:
        base_url = normalize_base_url(_prompt("1. 请输入中转站地址 (Base URL)", default_url))
        token = _prompt("2. 请输入中转站 API Token", default_token, secret=True)
        print("⏳ 正在测试中转站连通性与 Token 有效性...")
        ok, info = test_relay_connection(base_url, token)
        if ok:
            print(f"✅ 中转站连接成功！已获取到 {info} 个模型。")
            break
        print(f"⚠️  连接测试未通过：{info}")
        retry = input("是否重新输入地址或 Token？（选 n 将强制保存并继续）[y/N]: ").strip().lower()
        if retry not in ("y", "yes"):
            break
    api_format = _prompt("3. 接口格式 (anthropic 或 openai，默认自动回退)", existing_cfg.get("api_format", "anthropic")).lower()
    if api_format not in ("anthropic", "openai"):
        api_format = "anthropic"

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
        sendkey = _prompt("\n4. 请粘贴你的 Server酱 SendKey (留空跳过)", default_key, secret=True)
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
    cfg["api_format"] = api_format
    cfg["serverchan_sendkey"] = sendkey
    if not cfg.get("web_access_token"):
        cfg["web_access_token"] = secrets.token_urlsafe(12)

    save_config(cfg)
    print(f"\n✅ 配置已安全保存至: {CONFIG_PATH}")
    print(f"🔐 已生成手机看板访问保护密钥 (web_access_token)，防止公网陌生人滥用接口。")

    _install_cloudflared()
    _setup_github_secrets(cfg)

    start_now = input("\n是否立即启动 24h 后台守护与手机公网看板？[Y/n]: ").strip().lower()
    if start_now not in ("n", "no"):
        cli_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "relay_cli.py")
        subprocess.run([sys.executable, cli_path, "daemon", "start"], check=False)
        url = get_current_url()
        if url and cfg.get("serverchan_sendkey"):
            dash_url, push_url = format_public_links(url, cfg)
            send_link = input("是否将最新手机看板链接直接发送到你的微信？[Y/n]: ").strip().lower()
            if send_link not in ("n", "no"):
                desp = (
                    "### 📱 你的手机监控入口已就绪！\n\n"
                    f"- **手机 Web 实时看板**：{dash_url}\n"
                    f"- **微信一键极速查**：{push_url}\n\n"
                    "建议收藏本条消息，或将看板网址「添加到主屏幕」随时查看！"
                )
                if push_wechat("📱 Relay Monitor 手机监控入口已就绪", desp, cfg):
                    print("✅ 手机访问入口已发送到你的微信！")

    print("\n============================================================")
    print("🎉 初始化完成！常用命令：")
    print("   relay-monitor check --push   # 立即测速并推送到微信")
    print("   relay-monitor daemon status  # 查看后台守护与手机链接")
    print("============================================================")


if __name__ == "__main__":
    run_wizard()
