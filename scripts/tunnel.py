import subprocess
import re
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
STATE_DIR = os.path.join(SKILL_DIR, ".state")
import shutil
import socket

_BIN_NAME = "cloudflared.exe" if os.name == "nt" else "cloudflared"
CLOUDFLARED_BIN = shutil.which("cloudflared") or os.path.expanduser(f"~/.local/bin/{_BIN_NAME}")


def _is_port_open(host, port):
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def start_tunnel(port=3065):
    os.makedirs(STATE_DIR, exist_ok=True)
    url_file = os.path.join(STATE_DIR, "public_url.txt")
    log_file = os.path.join(STATE_DIR, "cloudflared.log")

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
    # Respect existing proxy env vars, or auto-use local Clash/Mihomo if listening
    if not env.get("https_proxy") and not env.get("HTTPS_PROXY"):
        for p_port in (7897, 7890, 10809):
            if _is_port_open("127.0.0.1", p_port):
                env["all_proxy"] = f"socks5://127.0.0.1:{p_port}"
                env["https_proxy"] = f"http://127.0.0.1:{p_port}"
                env["http_proxy"] = f"http://127.0.0.1:{p_port}"
                break
    with open(log_file, "w", encoding="utf-8") as out:
        proc = subprocess.Popen(cmd, env=env, stdout=out, stderr=subprocess.STDOUT)

    # Wait up to 15 seconds to find the trycloudflare.com URL
    tunnel_url = None
    pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    
    for _ in range(30):
        time.sleep(0.5)
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                matches = pattern.findall(content)
                if matches:
                    tunnel_url = matches[0]
                    break

    if tunnel_url:
        with open(url_file, "w", encoding="utf-8") as f:
            f.write(tunnel_url)
        print(f"[Tunnel Ready] Public HTTPS URL: {tunnel_url}")
        return tunnel_url, proc
    else:
        print("[Tunnel Timeout] Could not acquire trycloudflare URL within 15s")
        return None, proc

def get_current_url():
    url_file = os.path.join(STATE_DIR, "public_url.txt")
    if os.path.exists(url_file):
        with open(url_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3065
    url, proc = start_tunnel(port)
    if url:
        print(f"\n==========================================")
        print(f"📱 手机端访问链接 (任何网络均可访问):")
        print(f"👉 {url}")
        print(f"👉 微信一键查询链接: {url}/api/push")
        print(f"==========================================\n")
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
