#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import signal
import subprocess
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from core import (
    analyze_and_update_state,
    ensure_access_token,
    ensure_state_dir,
    format_markdown_report,
    load_config,
    push_wechat,
    scan_models,
)
from setup_wizard import run_wizard
from tunnel import clear_current_url, format_public_links, get_current_url, start_tunnel_with_watchdog
from web_server import run_server


def _get_daemon_paths():
    try:
        state_dir = ensure_state_dir(load_config())
    except Exception:
        state_dir = os.path.join(SKILL_DIR, ".state")
        os.makedirs(state_dir, exist_ok=True)
    return os.path.join(state_dir, "daemon.pid"), os.path.join(state_dir, "daemon.log")


def _write_github_summary(curr_state):
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        try:
            with open(summary_file, "a", encoding="utf-8") as f:
                f.write(format_markdown_report(curr_state) + "\n")
        except Exception:
            pass


def cmd_check(args):
    cfg = load_config()
    print("⏳ 正在探测中转站所有模型 (并发探测)...")
    results = scan_models(cfg)
    curr_state, _ = analyze_and_update_state(results, cfg)
    _write_github_summary(curr_state)

    total = curr_state["total"]
    alive = curr_state["alive_count"]
    kw = curr_state.get("watch_keyword", "glm").upper()
    print(f"\n📊 探测结果: {alive}/{total} 模型可用 (状态: {curr_state['overall_status']})")
    print(f"重点关注 ({kw}) 状态: {curr_state['glm_status']} (可用: {curr_state['glm_alive'] or '无'})")

    print("\n🟢 在线模型明细:")
    for m, lat in sorted(curr_state["alive_models"].items(), key=lambda x: x[1]):
        print(f"  - {m:<32} {lat}s")

    if curr_state["dead_models"]:
        print("\n🔴 离线/异常模型:")
        for m, err in sorted(curr_state["dead_models"].items()):
            print(f"  - {m:<32} {err}")

    if args.push:
        print("\n📲 正在推送报告至手机微信...")
        report_md = format_markdown_report(curr_state)
        title = f"【即时巡检】中转站模型健康报告 ({alive}/{total} 可用)"
        ok = push_wechat(title, report_md, cfg)
        if ok:
            print("✅ 微信推送成功！")
        else:
            print("❌ 微信推送失败，请检查 ServerChan SendKey 配置。")


def cmd_poll_step(args):
    """Single-step iteration designed for Antigravity schedule / GitHub Actions."""
    cfg = load_config()
    results = scan_models(cfg)
    curr_state, prev_state = analyze_and_update_state(results, cfg)
    _write_github_summary(curr_state)

    kw = curr_state.get("watch_keyword", "glm").upper()

    # 1. Target family recovered (e.g., GLM)
    if curr_state["glm_status"] == "RECOVERED":
        models_str = ", ".join(curr_state["glm_alive"])
        title = f"🎉 {kw} 系列模型已恢复可用！"
        desp = (
            f"### 🎉 {kw} 渠道已正式恢复可用！\n\n"
            f"恢复模型：**{models_str}**\n\n"
            f"现在可以随时开工使用！\n\n*巡检时间：{curr_state['time_str']}*"
        )
        push_wechat(title, desp, cfg)
        print(f"GLM_STATUS: RECOVERED -> {models_str}")
        return

    # 2. Total outage
    if curr_state["overall_status"] == "ALL_DOWN" and prev_state.get("overall_status") != "ALL_DOWN":
        title = "🚨 警报：中转站模型已全线宕机！"
        desp = (
            f"### 🚨 中转站全部 {curr_state['total']} 个模型不可用\n\n"
            f"所有模型均无法响应，请检查中转站服务器状态。\n\n*巡检时间：{curr_state['time_str']}*"
        )
        push_wechat(title, desp, cfg)
        print("STATUS: ALL_DOWN")
        return

    # 3. Recovered from ALL_DOWN (even if GLM is still down)
    if curr_state.get("overall_recovered"):
        title = f"⚡ 中转站已解除全线熔断 ({curr_state['alive_count']}/{curr_state['total']} 可用)"
        desp = format_markdown_report(curr_state)
        push_wechat(title, desp, cfg)
        print(f"STATUS: RECOVERED (COUNT: {curr_state['alive_count']}/{curr_state['total']})")
        return

    # Normal silent report
    print(f"STATUS: {curr_state['overall_status']} (COUNT: {curr_state['alive_count']}/{curr_state['total']})")
    print(f"GLM_STATUS: {curr_state['glm_status']}")


def cmd_serve(args):
    cfg = load_config()
    ensure_access_token(cfg)
    port = args.port or cfg.get("web_port", 3065)
    host = args.host or cfg.get("web_host", "127.0.0.1")

    tunnel_state = None
    if args.tunnel or args.public:
        print("🌐 正在启动 Cloudflare 移动端公网安全隧道...")
        url, tunnel_state = start_tunnel_with_watchdog(port)
        if url:
            dash_url, push_url = format_public_links(url, cfg)
            print("\n========================================================")
            print(f"📱 手机端访问看板: {dash_url}")
            print(f"👉 手机微信一键查询链接: {push_url}")
            print("   (已启用访问密钥保护，防止公网陌生人滥用)")
            print("========================================================\n")

    try:
        run_server(port=port, host=host)
    finally:
        if tunnel_state:
            tunnel_state["stop"] = True
            if tunnel_state.get("proc"):
                tunnel_state["proc"].terminate()


def _is_pid_running(pid):
    if os.name == "nt":
        try:
            res = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
            return str(pid) in res.stdout
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _stop_pid_tree(pid):
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"🛑 已停止守护进程及子进程 (PID: {pid})")
        return
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
        print(f"🛑 已停止守护进程及子进程 (PGID: {pgid})")
    except Exception:
        os.kill(pid, signal.SIGTERM)
        print(f"🛑 已停止守护进程 (PID: {pid})")


def cmd_daemon(args):
    action = args.action
    pid_file, log_file = _get_daemon_paths()

    if action == "status":
        if os.path.exists(pid_file):
            with open(pid_file, "r", encoding="utf-8") as f:
                pid = int(f.read().strip())
            if _is_pid_running(pid):
                print(f"🟢 后台守护进程正在运行 (PID: {pid})")
                url = get_current_url()
                if url:
                    cfg = load_config()
                    dash_url, push_url = format_public_links(url, cfg)
                    print(f"📱 手机公网看板: {dash_url}")
                    print(f"⚡ 微信一键查询: {push_url}")
                return
        print("⚪ 后台守护进程未运行。")
        return

    elif action == "stop":
        if os.path.exists(pid_file):
            with open(pid_file, "r", encoding="utf-8") as f:
                pid = int(f.read().strip())
            try:
                _stop_pid_tree(pid)
            except Exception as e:
                print(f"停止失败: {e}")
            if os.path.exists(pid_file):
                os.remove(pid_file)
            clear_current_url()
        else:
            print("未找到运行中的守护进程。")
        return

    elif action == "start":
        if os.path.exists(pid_file):
            with open(pid_file, "r", encoding="utf-8") as f:
                pid = int(f.read().strip())
            if _is_pid_running(pid):
                print(f"守护进程已在运行中 (PID: {pid})")
                return

        cfg = load_config()
        ensure_access_token(cfg)
        port = cfg.get("web_port", 3065)

        # Clear stale URL before spawning so we never print an outdated link
        clear_current_url()

        cmd = [
            sys.executable,
            "-u",
            os.path.realpath(__file__),
            "serve",
            "--port", str(port),
            "--tunnel",
        ]
        log_out = open(log_file, "a", encoding="utf-8")
        popen_kwargs = {"stdout": log_out, "stderr": subprocess.STDOUT}
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            popen_kwargs["start_new_session"] = True
        proc = subprocess.Popen(cmd, **popen_kwargs)
        with open(pid_file, "w", encoding="utf-8") as f:
            f.write(str(proc.pid))

        print(f"🚀 后台服务与手机隧道启动中 (PID: {proc.pid})...")
        print(f"日志文件: {log_file}")

        # Poll up to 15s for fresh public tunnel URL
        url = None
        for _ in range(30):
            time.sleep(0.5)
            url = get_current_url()
            if url:
                break

        if url:
            dash_url, push_url = format_public_links(url, cfg)
            print(f"📱 手机端访问看板: {dash_url}")
            print(f"⚡ 手机微信一键查询: {push_url}")
        else:
            print("⚠️  隧道 URL 尚未生成，请稍后运行 `relay-monitor daemon status` 查看，或检查日志文件。")


def main():
    parser = argparse.ArgumentParser(description="中转站模型监控与移动端联动工作流 CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="交互式傻瓜配置向导（含微信 SendKey 获取引导与测试）")

    p_check = subparsers.add_parser("check", help="单次全量检测模型可用性与延迟")
    p_check.add_argument("--push", action="store_true", help="探测完成后将报告推送到微信")

    subparsers.add_parser("poll-step", help="执行单轮巡检 (供 Antigravity 定时任务 / GitHub Actions 调度)")

    p_serve = subparsers.add_parser("serve", help="启动手机端 Web 监控看板")
    p_serve.add_argument("--host", default=None, help="监听地址 (默认 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=None, help="Web 监听端口 (默认 3065)")
    p_serve.add_argument("--tunnel", "--public", action="store_true", help="同时启动 Cloudflare 手机公网访问隧道")

    p_daemon = subparsers.add_parser("daemon", help="长期后台常驻守护管理")
    p_daemon.add_argument("action", choices=["start", "stop", "status"], help="start / stop / status")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        if args.command == "init":
            run_wizard()
        elif args.command == "check":
            cmd_check(args)
        elif args.command == "poll-step":
            cmd_poll_step(args)
        elif args.command == "serve":
            cmd_serve(args)
        elif args.command == "daemon":
            cmd_daemon(args)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
