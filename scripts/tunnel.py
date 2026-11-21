import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from core import ensure_state_dir, load_config, push_wechat

_BIN_NAME = "cloudflared.exe" if os.name == "nt" else "cloudflared"
CLOUDFLARED_BIN = shutil.which("cloudflared") or os.path.expanduser(f"~/.local/bin/{_BIN_NAME}")


def _is_port_open(host, port):
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def _get_state_dir():
    try:
        return ensure_state_dir(load_config())
    except Exception:
        d = os.path.join(os.path.dirname(SCRIPT_DIR), ".state")
        os.makedirs(d, exist_ok=True)
        return d


def _set_tunnel_status(msg):
    status_file = os.path.join(_get_state_dir(), "tunnel_status.txt")
    try:
        with open(status_file, "w", encoding="utf-8") as f:
            f.write(msg)
    except OSError:
        pass


def get_tunnel_status():
    status_file = os.path.join(_get_state_dir(), "tunnel_status.txt")
    if os.path.exists(status_file):
        try:
            with open(status_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            pass
    return ""


def clear_current_url():
    for fname in ("public_url.txt", "tunnel_status.txt"):
        fpath = os.path.join(_get_state_dir(), fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except OSError:
                pass


def format_public_links(base_url, cfg=None):
    token = ""
    if cfg:
        token = (cfg.get("web_access_token") or "").strip()
    suffix = f"?key={token}" if token else ""
    return f"{base_url}/{suffix}" if suffix else base_url, f"{base_url}/api/push{suffix}"


def _cleanup_stale_cloudflared():
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/IM", "cloudflared.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.run(["pkill", "-f", "cloudflared tunnel"], stderr=subprocess.DEVNULL)
        time.sleep(0.5)
    except Exception:
        pass


def _kill_proc(proc):
    if proc is None:
        return
    if proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _build_env():
    env = os.environ.copy()
    if not env.get("https_proxy") and not env.get("HTTPS_PROXY"):
        for p_port in (7897, 7890, 10809):
            if _is_port_open("127.0.0.1", p_port):
                env["all_proxy"] = f"socks5://127.0.0.1:{p_port}"
                env["https_proxy"] = f"http://127.0.0.1:{p_port}"
                env["http_proxy"] = f"http://127.0.0.1:{p_port}"
                break
    return env


def _try_protocol(port, protocol, log_file):
    """Launch cloudflared with given protocol and wait until edge connection ACTUALLY registers."""
    cmd = [CLOUDFLARED_BIN, "tunnel", "--protocol", protocol, "--url", f"http://127.0.0.1:{port}"]
    env = _build_env()
    with open(log_file, "w", encoding="utf-8") as out:
        proc = subprocess.Popen(cmd, env=env, stdout=out, stderr=subprocess.STDOUT)

    pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    tunnel_url = None
    registered = False
    last_err = ""

    # Wait up to 16s for BOTH the trycloudflare URL AND "Registered tunnel connection"
    for _ in range(32):
        time.sleep(0.5)
        if proc.poll() is not None:
            break
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if not tunnel_url:
                matches = pattern.findall(content)
                if matches:
                    tunnel_url = matches[0]
            if "Registered tunnel connection" in content:
                registered = True
                break
            # Fast-fail if repeated edge connection failures are logged
            if content.count("ERR Failed to dial") >= 2 or content.count("TLS handshake with edge error") >= 2:
                if "TLS handshake with edge error" in content:
                    last_err = "TLS 握手被中断 (当前代理节点或网络拦截了 Cloudflare 7844 端口)"
                else:
                    last_err = "QUIC/UDP 连接超时 (当前代理节点或网络拦截了 UDP 7844 端口)"
                break

    if tunnel_url and registered:
        return tunnel_url, proc, ""

    _kill_proc(proc)
    return None, None, last_err or f"协议 {protocol} 在 16s 内未能注册到 Cloudflare 边缘节点"


def start_tunnel(port=3065):
    """Start Cloudflare Quick Tunnel with automatic quic -> http2 fallback and real registration check."""
    state_dir = _get_state_dir()
    url_file = os.path.join(state_dir, "public_url.txt")
    log_file = os.path.join(state_dir, "cloudflared.log")

    clear_current_url()

    if not CLOUDFLARED_BIN or not os.path.exists(CLOUDFLARED_BIN):
        msg = f"未找到 cloudflared ({CLOUDFLARED_BIN})，请运行 relay-monitor init 安装"
        _set_tunnel_status(f"FAILED: {msg}")
        print(f"[Tunnel Error] {msg}")
        return None, None

    _cleanup_stale_cloudflared()

    errors = []
    for proto in ("quic", "http2"):
        print(f"[Tunnel] 正在尝试建立 Cloudflare 隧道 (protocol={proto})...")
        tunnel_url, proc, err = _try_protocol(port, proto, log_file)
        if tunnel_url and proc:
            tmp_file = f"{url_file}.tmp.{os.getpid()}"
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write(tunnel_url)
            os.replace(tmp_file, url_file)
            _set_tunnel_status(f"OK ({proto})")
            print(f"[Tunnel Ready] Public HTTPS URL ({proto}): {tunnel_url}")
            return tunnel_url, proc
        errors.append(f"{proto}: {err}")
        print(f"[Tunnel] {proto} 连接失败: {err}")

    reason = "Cloudflare 7844 端口被当前网络/代理节点拦截（quic 与 http2 均未连上）"
    _set_tunnel_status(f"FAILED: {reason}")
    print(f"[Tunnel Failed] {reason}")
    print("[Tunnel Tip] 解决方案：在代理软件中切换支持 UDP/7844 的节点，或将 *.argotunnel.com 设为直连。")
    return None, None


def _probe_tunnel_alive(url, cfg):
    """Verify public tunnel URL is actually serving HTTP 200."""
    dash_url, _ = format_public_links(url, cfg)
    try:
        req = urllib.request.Request(dash_url, method="HEAD", headers={"User-Agent": "RelayMonitorWatchdog/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 400
    except Exception:
        return False


def start_tunnel_with_watchdog(port=3065):
    """Start tunnel with smart watchdog: exponential backoff & verified-only WeChat pushes (zero spam)."""
    state = {"proc": None, "url": None, "stop": False}
    url, proc = start_tunnel(port)
    state["proc"] = proc
    state["url"] = url

    def _sleep_interruptible(seconds):
        end = time.time() + seconds
        while time.time() < end and not state["stop"]:
            time.sleep(min(2.0, max(0.1, end - time.time())))

    def _watch():
        # Exponential backoff steps when tunnel cannot connect: 5m -> 15m -> 30m -> 60m
        backoff_steps = [300, 900, 1800, 3600]
        backoff_idx = 0 if url else 0
        was_healthy = bool(url)
        notified_down = False
        consecutive_fails = 0
        # Give freshly started tunnel 30s for DNS propagation before first health probe
        last_probe = time.time()

        while not state["stop"]:
            # Case 1: No active tunnel right now -> wait backoff then try once
            if state["proc"] is None or state["url"] is None:
                wait_sec = backoff_steps[min(backoff_idx, len(backoff_steps) - 1)]
                print(f"[Tunnel Watchdog] 隧道未就绪，将在 {wait_sec // 60} 分钟后静默重试（不影响本地自动巡检）...")
                _sleep_interruptible(wait_sec)
                if state["stop"]:
                    break

                new_url, new_proc = start_tunnel(port)
                state["proc"] = new_proc
                state["url"] = new_url
                if new_url and new_proc:
                    # Wait briefly for DNS propagation and verify HTTP 200 BEFORE notifying WeChat!
                    _sleep_interruptible(5)
                    try:
                        cfg = load_config()
                    except Exception:
                        cfg = {}
                    if _probe_tunnel_alive(new_url, cfg):
                        backoff_idx = 0
                        consecutive_fails = 0
                        was_healthy = True
                        notified_down = False
                        last_probe = time.time()
                        dash_url, push_url = format_public_links(new_url, cfg)
                        push_wechat(
                            "📱 手机看板隧道已恢复连通",
                            f"### 📱 手机公网看板已恢复正常访问！\n\n- **手机看板**：{dash_url}\n- **微信一键查**：{push_url}",
                            cfg,
                        )
                    else:
                        print("[Tunnel Watchdog] 新隧道未通过公网 HTTP 200 校验，暂不推送微信。")
                        _kill_proc(new_proc)
                        state["proc"] = None
                        state["url"] = None
                        clear_current_url()
                        _set_tunnel_status("FAILED: 隧道已分配域名但公网健康检查未通过")
                        backoff_idx += 1
                else:
                    backoff_idx += 1
                continue

            # Case 2: Active tunnel exists -> check process & periodic probe
            _sleep_interruptible(15)
            if state["stop"]:
                break

            p = state["proc"]
            if p is not None and p.poll() is not None:
                print("[Tunnel Watchdog] cloudflared 进程意外退出，准备重连...")
                state["proc"] = None
                state["url"] = None
                clear_current_url()
                consecutive_fails = 0
                continue

            if time.time() - last_probe >= 120:
                last_probe = time.time()
                try:
                    cfg = load_config()
                except Exception:
                    cfg = {}
                if _probe_tunnel_alive(state["url"], cfg):
                    consecutive_fails = 0
                    was_healthy = True
                    notified_down = False
                    backoff_idx = 0
                else:
                    consecutive_fails += 1
                    print(f"[Tunnel Watchdog] 公网探针失败 ({consecutive_fails}/3)")
                    if consecutive_fails >= 3:
                        print("[Tunnel Watchdog] 隧道连续 3 次探针失败，释放旧隧道并进入退避重连...")
                        _kill_proc(state["proc"])
                        state["proc"] = None
                        state["url"] = None
                        clear_current_url()
                        _set_tunnel_status("FAILED: 隧道连接中断，正在后台低频重试")
                        consecutive_fails = 0
                        if was_healthy and not notified_down:
                            notified_down = True
                            push_wechat(
                                "⚠️ 手机看板隧道暂时断开",
                                "### ⚠️ 手机公网看板隧道暂时不可用\n\n后台每 5 分钟的模型自动巡检与 GLM 恢复通知**仍正常运行**，隧道将在网络恢复后自动重连（已开启退避防刷屏）。",
                                cfg,
                            )

    t = threading.Thread(target=_watch, daemon=True)
    t.start()
    return url, state


def get_current_url():
    url_file = os.path.join(_get_state_dir(), "public_url.txt")
    if os.path.exists(url_file):
        with open(url_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None


if __name__ == "__main__":
    p = int(sys.argv[1]) if len(sys.argv) > 1 else 3065
    u, proc = start_tunnel(p)
    if u:
        print(f"\n📱 手机端访问看板: {u}\n")
        try:
            proc.wait()
        except KeyboardInterrupt:
            _kill_proc(proc)
