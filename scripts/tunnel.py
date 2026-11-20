import subprocess
import re
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
STATE_DIR = os.path.join(SKILL_DIR, ".state")
import shutil

CLOUDFLARED_BIN = shutil.which("cloudflared") or os.path.expanduser("~/.local/bin/cloudflared")

def start_tunnel(port=3065):
    os.makedirs(STATE_DIR, exist_ok=True)
    url_file = os.path.join(STATE_DIR, "public_url.txt")
    log_file = os.path.join(STATE_DIR, "cloudflared.log")

    if not os.path.exists(CLOUDFLARED_BIN):
        print(f"[Tunnel Error] {CLOUDFLARED_BIN} not found")
        return None

    # Clean up any stale cloudflared instances
    try:
        subprocess.run(["pkill", "-f", "cloudflared tunnel"], stderr=subprocess.DEVNULL)
        time.sleep(0.5)
    except Exception:
        pass

    cmd = [CLOUDFLARED_BIN, "tunnel", "--url", f"http://127.0.0.1:{port}"]
    env = os.environ.copy()
    env["all_proxy"] = "socks5://127.0.0.1:7897"
    env["https_proxy"] = "http://127.0.0.1:7897"
    env["http_proxy"] = "http://127.0.0.1:7897"
    with open(log_file, "w") as out:
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
