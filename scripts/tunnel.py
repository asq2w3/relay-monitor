import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time

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


def clear_current_url():
    url_file = os.path.join(_get_state_dir(), "public_url.txt")
    if os.path.exists(url_file):
        try:
            os.remove(url_file)
        except OSError:
            pass


def format_public_links(base_url, cfg=None):
    token = ""
    if cfg:
        token = (cfg.get("web_access_token") or "").strip()
    suffix = f"?key={token}" if token else ""
    return f"{base_url}/{suffix}" if suffix else base_url, f"{base_url}/api/push{suffix}"


def start_tunnel(port=3065):
    state_dir = _get_state_dir()
    url_file = os.path.join(state_dir, "public_url.txt")
    log_file = os.path.join(state_dir, "cloudflared.log")

    clear_current_url()

    if not CLOUDFLARED_BIN or not os.path.exists(CLOUDFLARED_BIN):
        print(f"[Tunnel Error] {CLOUDFLARED_BIN} not found. Run 'relay-monitor init' to install it.")
        return None, None

    # Clean up any stale cloudflared instances (cross-platform)
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(["pkill", "-f", "cloudflared tunnel"], stderr=subprocess.DEVNULL)
        time.sleep(0.5)
    except Exception:
        pass

    cmd = [CLOUDFLARED_BIN, "tunnel", "--url", f"http://127.0.0.1:{port}"]
    env = os.environ.copy()
    if not env.get("https_proxy") and not env.get("HTTPS_PROXY"):
        for p_port in (7897, 7890, 10809):
            if _is_port_open("127.0.0.1", p_port):
                env["all_proxy"] = f"socks5://127.0.0.1:{p_port}"
                env["https_proxy"] = f"http://127.0.0.1:{p_port}"
                env["http_proxy"] = f"http://127.0.0.1:{p_port}"
                break

    out = open(log_file, "w", encoding="utf-8")
    proc = subprocess.Popen(cmd, env=env, stdout=out, stderr=subprocess.STDOUT)

    tunnel_url = None
    pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

    for _ in range(30):
        time.sleep(0.5)
        if proc.poll() is not None:
            break
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                matches = pattern.findall(f.read())
                if matches:
                    tunnel_url = matches[0]
                    break

    if tunnel_url:
        tmp_file = f"{url_file}.tmp.{os.getpid()}"
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(tunnel_url)
        os.replace(tmp_file, url_file)
        print(f"[Tunnel Ready] Public HTTPS URL: {tunnel_url}")
        return tunnel_url, proc
    else:
        print("[Tunnel Timeout] Could not acquire trycloudflare URL within 15s")
        return None, proc


def start_tunnel_with_watchdog(port=3065):
    """Start tunnel and spawn a watchdog thread to auto-restart if cloudflared exits."""
    state = {"proc": None, "stop": False}
    url, proc = start_tunnel(port)
    state["proc"] = proc

    def _watch():
        while not state["stop"]:
            time.sleep(10)
            p = state["proc"]
            if p is not None and p.poll() is not None and not state["stop"]:
                print("[Tunnel Watchdog] cloudflared exited unexpectedly, restarting...")
                new_url, new_proc = start_tunnel(port)
                state["proc"] = new_proc
                if new_url:
                    try:
                        cfg = load_config()
                        dash_url, push_url = format_public_links(new_url, cfg)
                        push_wechat(
                            "📱 手机看板隧道已自动重连",
                            f"### 📱 手机公网看板已自动恢复\n\n- **手机看板**：{dash_url}\n- **微信一键查**：{push_url}",
                            cfg,
                        )
                    except Exception:
                        pass

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
            proc.terminate()
