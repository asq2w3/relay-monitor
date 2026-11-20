#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import argparse
import subprocess
import signal

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from core import load_config, scan_models, analyze_and_update_state, push_wechat, format_markdown_report
from web_server import run_server
from tunnel import start_tunnel, get_current_url

PID_FILE = os.path.join(SKILL_DIR, ".state", "daemon.pid")
LOG_FILE = os.path.join(SKILL_DIR, ".state", "daemon.log")

def cmd_check(args):
    cfg = load_config()
    print("⏳ 正在探测中转站所有模型 (并发探测)...")
    results = scan_models(cfg)
    curr_state, _ = analyze_and_update_state(results, cfg)
    
    total = curr_state["total"]
    alive = curr_state["alive_count"]
    print(f"\n📊 探测结果: {alive}/{total} 模型可用 (状态: {curr_state['overall_status']})")
    print(f"智谱 GLM 系列状态: {curr_state['glm_status']} (可用: {curr_state['glm_alive'] or '无'})")
    
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
    """Single-step iteration designed for Antigravity native schedule tool."""
    cfg = load_config()
    results = scan_models(cfg)
    curr_state, prev_state = analyze_and_update_state(results, cfg)
    
    # Check trigger conditions:
    # 1. GLM recovered
    if curr_state["glm_status"] == "RECOVERED":
        models_str = ", ".join(curr_state["glm_alive"])
        title = "🎉 智谱 GLM 系列模型已恢复可用！"
        desp = f"### 🎉 GLM 渠道已正式恢复可用！\n\n恢复模型：**{models_str}**\n\n本地 Claude Code 1M 上下文已就绪，可随时直接开工使用！\n\n*巡检时间：{curr_state['time_str']}*"
        push_wechat(title, desp, cfg)
        print(f"GLM_STATUS: RECOVERED -> {models_str}")
        return
        
    # 2. Total outage
    if curr_state["overall_status"] == "ALL_DOWN" and prev_state.get("overall_status") != "ALL_DOWN":
        title = "🚨 警报：中转站模型已全线宕机！"
        desp = f"### 🚨 中转站全部模型不可用\n\n所有 31 个模型均无法响应，请检查中转站服务器状态。\n\n*巡检时间：{curr_state['time_str']}*"
        push_wechat(title, desp, cfg)
        print("STATUS: ALL_DOWN")
        return
        
    # Normal silent report
    print(f"STATUS: {curr_state['overall_status']} (COUNT: {curr_state['alive_count']}/{curr_state['total']})")
    print(f"GLM_STATUS: {curr_state['glm_status']}")

def cmd_serve(args):
    cfg = load_config()
    port = args.port or cfg.get("web_port", 3065)
    
    tunnel_proc = None
    if args.tunnel or args.public:
        print("🌐 正在启动 Cloudflare 移动端公网安全隧道...")
        url, tunnel_proc = start_tunnel(port)
        if url:
            print(f"\n========================================================")
            print(f"📱 手机端访问看板: {url}")
            print(f"👉 手机微信一键查询链接: {url}/api/push")
            print(f"   (可保存到手机浏览器书签，或添加到手机桌面，点击即查！)")
            print(f"========================================================\n")
            
    try:
        run_server(port)
    finally:
        if tunnel_proc:
            tunnel_proc.terminate()

def cmd_daemon(args):
    action = args.action
    os.makedirs(os.path.join(SKILL_DIR, ".state"), exist_ok=True)
    
    if action == "status":
        if os.path.exists(PID_FILE):
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 0)
                print(f"🟢 后台守护进程正在运行 (PID: {pid})")
                url = get_current_url()
                if url:
                    print(f"📱 手机公网看板: {url}")
                return
            except OSError:
                pass
        print("⚪ 后台守护进程未运行。")
        return

    elif action == "stop":
        if os.path.exists(PID_FILE):
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            try:
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGTERM)
                print(f"🛑 已停止守护进程及子进程 (PGID: {pgid})")
            except Exception:
                try:
                    os.kill(pid, signal.SIGTERM)
                    print(f"🛑 已停止守护进程 (PID: {pid})")
                except Exception as e:
                    print(f"停止失败: {e}")
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
        else:
            print("未找到运行中的守护进程。")
        return

    elif action == "start":
        if os.path.exists(PID_FILE):
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 0)
                print(f"守护进程已在运行中 (PID: {pid})")
                return
            except OSError:
                pass

        cfg = load_config()
        port = cfg.get("web_port", 3065)
        
        # Start serve --tunnel in background
        cmd = [
            sys.executable,
            "-u",
            os.path.realpath(__file__),
            "serve",
            "--port", str(port),
            "--tunnel"
        ]
        log_out = open(LOG_FILE, "a")
        proc = subprocess.Popen(cmd, stdout=log_out, stderr=subprocess.STDOUT, start_new_session=True)
        with open(PID_FILE, "w") as f:
            f.write(str(proc.pid))
                
        print(f"🚀 后台服务与手机隧道已启动 (PID: {proc.pid})")
        print(f"日志文件: {LOG_FILE}")
        time.sleep(2)
        url = get_current_url()
        if url:
            print(f"📱 手机端访问看板: {url}")
            print(f"👉 手机微信一键查询链接: {url}/api/push")

def main():
    parser = argparse.ArgumentParser(description="中转站模型监控与移动端联动工作流 CLI")
    subparsers = parser.add_subparsers(dest="command")

    # check
    p_check = subparsers.add_parser("check", help="单次全量检测模型可用性与延迟")
    p_check.add_argument("--push", action="store_true", help="探测完成后将报告推送到微信")

    # poll-step (Antigravity schedule entry)
    p_poll = subparsers.add_parser("poll-step", help="执行单轮巡检 (供 Antigravity 定时任务调度)")

    # serve
    p_serve = subparsers.add_parser("serve", help="启动手机端 Web 监控看板")
    p_serve.add_argument("--port", type=int, default=3065, help="Web 监听端口 (默认 3065)")
    p_serve.add_argument("--tunnel", "--public", action="store_true", help="同时启动 Cloudflare 手机公网访问隧道")

    # daemon
    p_daemon = subparsers.add_parser("daemon", help="长期后台常驻守护管理")
    p_daemon.add_argument("action", choices=["start", "stop", "status"], help="start / stop / status")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "check":
        cmd_check(args)
    elif args.command == "poll-step":
        cmd_poll_step(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "daemon":
        cmd_daemon(args)

if __name__ == "__main__":
    main()
