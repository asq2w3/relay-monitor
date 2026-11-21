import concurrent.futures
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")


def normalize_base_url(url):
    """Strip trailing slashes and redundant '/v1' suffix."""
    u = (url or "").strip().rstrip("/")
    if u.lower().endswith("/v1"):
        u = u[:-3].rstrip("/")
    return u


def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(
            f"未找到配置文件: {CONFIG_PATH}\n请先运行 `relay-monitor init` 完成傻瓜式配置。"
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["base_url"] = normalize_base_url(cfg.get("base_url", ""))
    return cfg


def save_config(cfg):
    tmp_path = f"{CONFIG_PATH}.tmp.{os.getpid()}.{threading.get_ident()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, CONFIG_PATH)
    if os.name != "nt":
        try:
            os.chmod(CONFIG_PATH, 0o600)
        except OSError:
            pass


def ensure_access_token(cfg):
    """Ensure a random web_access_token exists for protecting public mobile endpoints."""
    if "web_access_token" not in cfg:
        cfg["web_access_token"] = secrets.token_urlsafe(12)
        try:
            save_config(cfg)
        except Exception:
            pass
    return cfg.get("web_access_token", "")


def ensure_state_dir(cfg):
    state_dir = cfg.get("state_dir", ".state")
    if not os.path.isabs(state_dir):
        state_dir = os.path.join(SKILL_DIR, state_dir)
    os.makedirs(state_dir, exist_ok=True)
    return state_dir


def test_relay_connection(base_url, token):
    """Quick connectivity & auth check against /v1/models. Returns (ok, count_or_error)."""
    url = f"{normalize_base_url(base_url)}/v1/models"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("x-api-key", token)
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            models = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
            return True, len(models)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, f"认证失败 (HTTP {e.code})，请检查 API Token 是否正确"
        return False, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return False, f"无法连接中转站: {e}"


def get_models(cfg):
    url = f"{cfg['base_url']}/v1/models"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {cfg['token']}")
    req.add_header("x-api-key", cfg["token"])
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            models = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
            for wm in cfg.get("watch_models", []):
                if wm not in models:
                    models.append(wm)
            return sorted(set(models))
    except Exception:
        return list(cfg.get("watch_models", ["glm-5.3-flash[1M]", "claude-sonnet-4-6", "MiniMax-M3"]))


def _send_probe(model_name, cfg, api_format):
    if api_format == "openai":
        url = f"{cfg['base_url']}/v1/chat/completions"
        payload = json.dumps({
            "model": model_name,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}],
        }).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {cfg['token']}",
            "Content-Type": "application/json",
        }
    else:
        url = f"{cfg['base_url']}/v1/messages"
        payload = json.dumps({
            "model": model_name,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}],
        }).encode("utf-8")
        headers = {
            "x-api-key": cfg["token"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    req = urllib.request.Request(url, data=payload, headers=headers)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=cfg.get("request_timeout_seconds", 4)) as resp:
        _ = resp.read(256)
        return round(time.time() - t0, 2)


def test_model(model_name, cfg):
    primary_fmt = cfg.get("api_format", "anthropic").lower()
    t0 = time.time()
    try:
        latency = _send_probe(model_name, cfg, primary_fmt)
        return {
            "model": model_name,
            "alive": True,
            "latency": latency,
            "code": 200,
            "error": None,
        }
    except urllib.error.HTTPError as e:
        # Auto-fallback to OpenAI /v1/chat/completions if /v1/messages returns 404
        if e.code == 404 and primary_fmt == "anthropic":
            try:
                latency = _send_probe(model_name, cfg, "openai")
                return {
                    "model": model_name,
                    "alive": True,
                    "latency": latency,
                    "code": 200,
                    "error": None,
                }
            except urllib.error.HTTPError as e2:
                e = e2
            except Exception as e2:
                return {
                    "model": model_name,
                    "alive": False,
                    "latency": round(time.time() - t0, 2),
                    "code": 0,
                    "error": str(e2),
                }

        latency = round(time.time() - t0, 2)
        err_msg = ""
        try:
            err_msg = e.read().decode("utf-8", errors="ignore")[:120]
        except Exception:
            pass
        return {
            "model": model_name,
            "alive": False,
            "latency": latency,
            "code": e.code,
            "error": f"HTTP {e.code}: {err_msg or e.reason}",
        }
    except Exception as e:
        return {
            "model": model_name,
            "alive": False,
            "latency": round(time.time() - t0, 2),
            "code": 0,
            "error": str(e),
        }


def scan_models(cfg, models=None):
    if models is None:
        models = get_models(cfg)

    max_workers = max(1, int(cfg.get("max_concurrency", 5)))
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(test_model, m, cfg): m for m in models}
        for future in concurrent.futures.as_completed(future_map):
            res = future.result()
            results[res["model"]] = res
    return results


def push_wechat(title, desp, cfg):
    sendkey = (cfg.get("serverchan_sendkey") or "").strip()
    if not sendkey:
        print("[Push Warning] serverchan_sendkey not configured")
        return False
    url = f"https://sctapi.ftqq.com/{urllib.parse.quote(sendkey, safe='')}.send"
    data = urllib.parse.urlencode({"title": title, "desp": desp}).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.loads(r.read().decode("utf-8", errors="ignore"))
            if res.get("code") == 0:
                return True
            print(f"[Push API Error] {res.get('message') or res}")
            return False
    except Exception as e:
        print(f"[Push Error] {e}")
        return False


def analyze_and_update_state(results, cfg):
    state_dir = ensure_state_dir(cfg)
    state_file = os.path.join(state_dir, "monitor_state.json")

    prev_state = {}
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                prev_state = json.load(f)
        except Exception:
            prev_state = {}

    total = len(results)
    alive_items = [r for r in results.values() if r["alive"]]
    alive_count = len(alive_items)

    # Analyze target model family (default: "glm")
    watch_kw = (cfg.get("watch_keyword") or "glm").lower()
    glm_results = {m: r for m, r in results.items() if watch_kw in m.lower()}
    glm_alive = sorted([m for m, r in glm_results.items() if r["alive"]])
    prev_glm_alive = prev_state.get("glm_alive", [])

    if glm_alive:
        # Only report RECOVERED when transitioning from a known previous DOWN state
        if prev_state and not prev_glm_alive:
            glm_status = "RECOVERED"
        else:
            glm_status = "ALIVE"
    else:
        glm_status = "DOWN"

    # Analyze Overall Status
    if alive_count == 0:
        overall_status = "ALL_DOWN"
    elif total > 0 and alive_count < max(1, total // 2):
        overall_status = "DEGRADED"
    else:
        overall_status = "HEALTHY"

    overall_recovered = (
        bool(prev_state)
        and prev_state.get("overall_status") == "ALL_DOWN"
        and alive_count > 0
    )

    current_state = {
        "timestamp": int(time.time()),
        "time_str": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": total,
        "alive_count": alive_count,
        "overall_status": overall_status,
        "overall_recovered": overall_recovered,
        "watch_keyword": watch_kw,
        "glm_status": glm_status,
        "glm_alive": glm_alive,
        "alive_models": {r["model"]: r["latency"] for r in alive_items},
        "dead_models": {r["model"]: r["error"] for r in results.values() if not r["alive"]},
    }

    # Atomic write to avoid concurrent corruption
    tmp_file = f"{state_file}.tmp.{os.getpid()}.{threading.get_ident()}"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(current_state, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, state_file)

    return current_state, prev_state


def format_markdown_report(state):
    lines = []
    t_str = state["time_str"]
    alive = state["alive_count"]
    total = state["total"]
    status_icon = "🟢" if state["overall_status"] == "HEALTHY" else ("🟡" if state["overall_status"] == "DEGRADED" else "🔴")
    kw = state.get("watch_keyword", "glm").upper()

    lines.append(f"### {status_icon} 中转站模型健康巡检报告 ({t_str})")
    lines.append(f"- **综合健康度**：{state['overall_status']} ({alive}/{total} 可用)")

    if state["glm_alive"]:
        lines.append(f"- **重点关注 ({kw})**：🟢 正常 ({', '.join(state['glm_alive'])})")
    else:
        lines.append(f"- **重点关注 ({kw})**：🔴 异常 (限流或无可用上游)")

    lines.append("\n#### ⚡ 当前可用模型明细：")
    sorted_alive = sorted(state["alive_models"].items(), key=lambda x: x[1])
    if sorted_alive:
        for m, lat in sorted_alive:
            lines.append(f"- `{m}`：{lat}s")
    else:
        lines.append("- *(当前无可用模型)*")

    if state["dead_models"]:
        lines.append("\n#### ⚠️ 异常模型（最多展示前 8 个）：")
        for m, err in sorted(state["dead_models"].items())[:8]:
            clean_err = (err or "Unknown").replace("\n", " ")[:48]
            lines.append(f"- `{m}`：`{clean_err}`")

    lines.append("\n---\n*由 Relay Monitor 自动化工作流生成*")
    return "\n".join(lines)
