import os
import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import concurrent.futures

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")

def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def ensure_state_dir(cfg):
    state_dir = cfg.get("state_dir", ".state")
    if not os.path.isabs(state_dir):
        state_dir = os.path.join(SKILL_DIR, state_dir)
    os.makedirs(state_dir, exist_ok=True)
    return state_dir

def get_models(cfg):
    url = f"{cfg['base_url'].rstrip('/')}/v1/models"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {cfg['token']}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            models = [m["id"] for m in data.get("data", [])]
            for wm in cfg.get("watch_models", []):
                if wm not in models:
                    models.append(wm)
            return sorted(models)
    except Exception as e:
        return cfg.get("watch_models", ["glm-5.3-flash[1M]", "claude-sonnet-4-6", "MiniMax-M3"])

def test_model(model_name, cfg):
    url = f"{cfg['base_url'].rstrip('/')}/v1/messages"
    payload = json.dumps({
        "model": model_name,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "hi"}]
    }).encode("utf-8")
    
    req = urllib.request.Request(url, data=payload)
    req.add_header("x-api-key", cfg["token"])
    req.add_header("anthropic-version", "2023-06-01")
    req.add_header("content-type", "application/json")
    
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=cfg.get("request_timeout_seconds", 4)) as resp:
            latency = round(time.time() - t0, 2)
            return {
                "model": model_name,
                "alive": True,
                "latency": latency,
                "code": 200,
                "error": None
            }
    except urllib.error.HTTPError as e:
        latency = round(time.time() - t0, 2)
        err_msg = ""
        try:
            err_msg = e.read().decode("utf-8", errors="ignore")[:100]
        except Exception:
            pass
        return {
            "model": model_name,
            "alive": False,
            "latency": latency,
            "code": e.code,
            "error": f"HTTP {e.code}: {err_msg or e.reason}"
        }
    except Exception as e:
        latency = round(time.time() - t0, 2)
        return {
            "model": model_name,
            "alive": False,
            "latency": latency,
            "code": 0,
            "error": str(e)
        }

def scan_models(cfg, models=None):
    if models is None:
        models = get_models(cfg)
    
    max_workers = cfg.get("max_concurrency", 5)
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(test_model, m, cfg): m for m in models}
        for future in concurrent.futures.as_completed(future_map):
            res = future.result()
            results[res["model"]] = res
    return results

def push_wechat(title, desp, cfg):
    sendkey = cfg.get("serverchan_sendkey")
    if not sendkey:
        print("[Push Warning] serverchan_sendkey not configured")
        return False
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    data = urllib.parse.urlencode({"title": title, "desp": desp}).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            res = json.loads(r.read().decode())
            return res.get("code") == 0
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
            pass
            
    total = len(results)
    alive_items = [r for r in results.values() if r["alive"]]
    alive_count = len(alive_items)
    alive_names = sorted([r["model"] for r in alive_items])
    
    # Analyze GLM models
    glm_results = {m: r for m, r in results.items() if "glm" in m.lower()}
    glm_alive = [m for m, r in glm_results.items() if r["alive"]]
    prev_glm_alive = prev_state.get("glm_alive", [])
    
    glm_status = "STILL_DOWN"
    if glm_alive:
        if not prev_glm_alive:
            glm_status = "RECOVERED"
        else:
            glm_status = "ALIVE"
    else:
        glm_status = "DOWN"
        
    # Analyze Overall Status
    if alive_count == 0:
        overall_status = "ALL_DOWN"
    elif alive_count < total // 2:
        overall_status = "DEGRADED"
    else:
        overall_status = "HEALTHY"
        
    current_state = {
        "timestamp": int(time.time()),
        "time_str": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": total,
        "alive_count": alive_count,
        "overall_status": overall_status,
        "glm_status": glm_status,
        "glm_alive": glm_alive,
        "alive_models": {r["model"]: r["latency"] for r in alive_items},
        "dead_models": {r["model"]: r["error"] for r in results.values() if not r["alive"]}
    }
    
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(current_state, f, ensure_ascii=False, indent=2)
        
    return current_state, prev_state

def format_markdown_report(state):
    lines = []
    t_str = state["time_str"]
    alive = state["alive_count"]
    total = state["total"]
    status_icon = "🟢" if state["overall_status"] == "HEALTHY" else ("🟡" if state["overall_status"] == "DEGRADED" else "🔴")
    
    lines.append(f"### {status_icon} 中转站模型健康巡检报告 ({t_str})")
    lines.append(f"- **综合健康度**：{state['overall_status']} ({alive}/{total} 可用)")
    
    # GLM highlight
    if state["glm_alive"]:
        lines.append(f"- **智谱 GLM 系列**：🟢 正常 ({', '.join(state['glm_alive'])})")
    else:
        lines.append("- **智谱 GLM 系列**：🔴 异常 (限流或无可用上游)")
        
    lines.append("\n#### ⚡ 当前可用模型明细：")
    sorted_alive = sorted(state["alive_models"].items(), key=lambda x: x[1])
    for m, lat in sorted_alive:
        lines.append(f"- `{m}`：{lat}s")
        
    if state["dead_models"]:
        lines.append("\n#### ⚠️ 异常模型：")
        for m, err in sorted(state["dead_models"].items())[:6]:
            clean_err = (err or "Unknown").replace("\n", " ")[:40]
            lines.append(f"- `{m}`：`{clean_err}`")
            
    lines.append("\n---\n*由 Antigravity Relay Monitor 自动化工作流生成*")
    return "\n".join(lines)
