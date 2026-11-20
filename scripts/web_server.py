import http.server
import json
import urllib.parse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
STATE_DIR = os.path.join(SKILL_DIR, ".state")
sys.path.insert(0, SCRIPT_DIR)

from core import load_config, scan_models, analyze_and_update_state, push_wechat, format_markdown_report

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>中转站模型监控看板</title>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --card-border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --green: #10b981;
      --green-bg: rgba(16, 185, 129, 0.15);
      --red: #ef4444;
      --red-bg: rgba(239, 68, 68, 0.15);
      --yellow: #f59e0b;
      --blue: #3b82f6;
      --primary: #6366f1;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
      padding: 16px;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }
    .container { max-width: 600px; margin: 0 auto; }
    header { margin-bottom: 20px; text-align: center; }
    header h1 { font-size: 20px; font-weight: 700; margin-bottom: 4px; }
    header p { font-size: 13px; color: var(--text-muted); }

    .glm-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 16px;
      margin-bottom: 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    .glm-info h3 { font-size: 16px; margin-bottom: 2px; }
    .glm-info p { font-size: 12px; color: var(--text-muted); }
    .badge {
      font-size: 13px;
      font-weight: 600;
      padding: 6px 12px;
      border-radius: 20px;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .badge-green { background: var(--green-bg); color: var(--green); border: 1px solid var(--green); }
    .badge-red { background: var(--red-bg); color: var(--red); border: 1px solid var(--red); }

    .stats-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-bottom: 16px;
    }
    .stat-box {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 14px;
      text-align: center;
    }
    .stat-val { font-size: 24px; font-weight: 700; color: var(--blue); }
    .stat-lbl { font-size: 12px; color: var(--text-muted); margin-top: 2px; }

    .action-group {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 20px;
    }
    button {
      border: none;
      border-radius: 10px;
      padding: 12px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      transition: all 0.2s;
    }
    .btn-primary { background: var(--primary); color: #fff; }
    .btn-wechat { background: #07c160; color: #fff; }
    button:active { opacity: 0.8; transform: scale(0.98); }
    button:disabled { opacity: 0.5; cursor: not-allowed; }

    .tabs {
      display: flex;
      gap: 8px;
      margin-bottom: 12px;
      overflow-x: auto;
      padding-bottom: 4px;
    }
    .tab-btn {
      background: var(--card-bg);
      color: var(--text-muted);
      border: 1px solid var(--card-border);
      padding: 6px 12px;
      border-radius: 8px;
      font-size: 12px;
      white-space: nowrap;
    }
    .tab-btn.active { background: var(--blue); color: #fff; border-color: var(--blue); }

    .model-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .model-item {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 12px 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .model-name {
      font-size: 14px;
      font-weight: 500;
      word-break: break-all;
    }
    .model-meta {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .lat-tag {
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 6px;
      font-weight: 600;
    }
    .lat-fast { background: var(--green-bg); color: var(--green); }
    .lat-med { background: rgba(245, 158, 11, 0.15); color: var(--yellow); }
    .lat-err { background: var(--red-bg); color: var(--red); }

    #toast {
      position: fixed;
      bottom: 24px;
      left: 50%;
      transform: translateX(-50%);
      background: rgba(15, 23, 42, 0.95);
      border: 1px solid var(--primary);
      color: #fff;
      padding: 10px 18px;
      border-radius: 20px;
      font-size: 13px;
      display: none;
      z-index: 1000;
      box-shadow: 0 10px 15px -3px rgba(0,0,0,0.5);
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>⚡ 中转站模型监控</h1>
      <p id="update-time">正在载入数据...</p>
    </header>

    <div class="glm-card">
      <div class="glm-info">
        <h3>智谱 GLM 系列 (主推)</h3>
        <p>包含 1M 上下文专用模型</p>
      </div>
      <div id="glm-badge" class="badge badge-green">检测中...</div>
    </div>

    <div class="stats-row">
      <div class="stat-box">
        <div id="alive-count" class="stat-val">--/--</div>
        <div class="stat-lbl">在线模型数</div>
      </div>
      <div class="stat-box">
        <div id="avg-latency" class="stat-val">--s</div>
        <div class="stat-lbl">平均响应耗时</div>
      </div>
    </div>

    <div class="action-group">
      <button id="btn-scan" class="btn-primary" onclick="triggerScan()">🔄 立即重新检测</button>
      <button id="btn-push" class="btn-wechat" onclick="triggerPush()">📲 推送到微信</button>
    </div>

    <div class="tabs">
      <button class="tab-btn active" onclick="setFilter('all', this)">全部</button>
      <button class="tab-btn" onclick="setFilter('glm', this)">智谱 GLM</button>
      <button class="tab-btn" onclick="setFilter('claude', this)">Claude 映射</button>
      <button class="tab-btn" onclick="setFilter('minimax', this)">MiniMax 系列</button>
    </div>

    <div id="model-list" class="model-list"></div>
  </div>

  <div id="toast"></div>

  <script>
    let currentData = null;
    let currentFilter = 'all';

    function showToast(msg) {
      const t = document.getElementById('toast');
      t.innerText = msg;
      t.style.display = 'block';
      setTimeout(() => { t.style.display = 'none'; }, 2500);
    }

    function render() {
      if (!currentData) return;
      document.getElementById('update-time').innerText = '最后检测：' + (currentData.time_str || '--');
      document.getElementById('alive-count').innerText = `${currentData.alive_count}/${currentData.total}`;
      
      // Calculate avg latency
      const latencies = Object.values(currentData.alive_models || {});
      if (latencies.length > 0) {
        const avg = (latencies.reduce((a, b) => a + b, 0) / latencies.length).toFixed(2);
        document.getElementById('avg-latency').innerText = avg + 's';
      }

      // GLM Badge
      const glmBadge = document.getElementById('glm-badge');
      if (currentData.glm_alive && currentData.glm_alive.length > 0) {
        glmBadge.className = 'badge badge-green';
        glmBadge.innerHTML = '● 正常可用';
      } else {
        glmBadge.className = 'badge badge-red';
        glmBadge.innerHTML = '● 暂时限流/维护';
      }

      // Model List
      const listContainer = document.getElementById('model-list');
      listContainer.innerHTML = '';

      const items = [];
      for (const [m, lat] of Object.entries(currentData.alive_models || {})) {
        items.push({ name: m, alive: true, latency: lat, err: null });
      }
      for (const [m, err] of Object.entries(currentData.dead_models || {})) {
        items.push({ name: m, alive: false, latency: null, err: err });
      }

      items.sort((a, b) => {
        if (a.alive && !b.alive) return -1;
        if (!a.alive && b.alive) return 1;
        return (a.latency || 99) - (b.latency || 99);
      });

      const filtered = items.filter(it => {
        const n = it.name.toLowerCase();
        if (currentFilter === 'glm') return n.includes('glm');
        if (currentFilter === 'claude') return n.includes('claude');
        if (currentFilter === 'minimax') return n.includes('minimax');
        return true;
      });

      filtered.forEach(it => {
        const div = document.createElement('div');
        div.className = 'model-item';
        let tagHtml = '';
        if (it.alive) {
          const cls = it.latency < 1.5 ? 'lat-fast' : 'lat-med';
          tagHtml = `<span class="lat-tag ${cls}">● ${it.latency}s</span>`;
        } else {
          tagHtml = `<span class="lat-tag lat-err">× 离线</span>`;
        }
        div.innerHTML = `<span class="model-name">${it.name}</span><div class="model-meta">${tagHtml}</div>`;
        listContainer.appendChild(div);
      });
    }

    function setFilter(filter, btn) {
      currentFilter = filter;
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      render();
    }

    async function loadStatus() {
      try {
        const res = await fetch('/api/status');
        currentData = await res.json();
        render();
      } catch (e) {
        showToast('加载失败，请检查网络');
      }
    }

    async function triggerScan() {
      const btn = document.getElementById('btn-scan');
      btn.disabled = true;
      btn.innerText = '⏳ 探测中(约4s)...';
      try {
        const res = await fetch('/api/scan');
        currentData = await res.json();
        render();
        showToast('探测完成！');
      } catch (e) {
        showToast('探测请求失败');
      } finally {
        btn.disabled = false;
        btn.innerText = '🔄 立即重新检测';
      }
    }

    async function triggerPush() {
      const btn = document.getElementById('btn-push');
      btn.disabled = true;
      btn.innerText = '⏳ 推送中...';
      try {
        const res = await fetch('/api/push');
        const data = await res.json();
        if (data.success) {
          showToast('✅ 报告已成功推送到微信！');
        } else {
          showToast('❌ 推送失败：' + (data.error || '未知错误'));
        }
      } catch (e) {
        showToast('推送请求异常');
      } finally {
        btn.disabled = false;
        btn.innerText = '📲 推送到微信';
      }
    }

    // Auto-load on start
    loadStatus();
  </script>
</body>
</html>
"""

class RelayMonitorHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Keep server quiet
        return

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        
        cfg = load_config()
        state_file = os.path.join(STATE_DIR, "monitor_state.json")

        if path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
            return

        elif path == "/api/status":
            if os.path.exists(state_file):
                with open(state_file, "r", encoding="utf-8") as f:
                    content = f.read()
            else:
                # Scan once if no state exists
                results = scan_models(cfg)
                curr_state, _ = analyze_and_update_state(results, cfg)
                content = json.dumps(curr_state, ensure_ascii=False)

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
            return

        elif path == "/api/scan":
            results = scan_models(cfg)
            curr_state, _ = analyze_and_update_state(results, cfg)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(curr_state, ensure_ascii=False).encode("utf-8"))
            return

        elif path == "/api/push":
            # Mobile shortcut: scan and push directly to WeChat
            results = scan_models(cfg)
            curr_state, _ = analyze_and_update_state(results, cfg)
            report_md = format_markdown_report(curr_state)
            title = f"【手机即时查询】中转站模型状态 ({curr_state['alive_count']}/{curr_state['total']} 可用)"
            success = push_wechat(title, report_md, cfg)

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": success,
                "alive_count": curr_state["alive_count"],
                "total": curr_state["total"],
                "glm_alive": curr_state["glm_alive"]
            }, ensure_ascii=False).encode("utf-8"))
            return

        else:
            self.send_response(404)
            self.end_headers()

import threading
import time

def _background_polling_loop():
    while True:
        try:
            cfg = load_config()
            interval = cfg.get("poll_interval_seconds", 300)
            time.sleep(interval)
            results = scan_models(cfg)
            curr_state, prev_state = analyze_and_update_state(results, cfg)
            
            if curr_state["glm_status"] == "RECOVERED":
                models_str = ", ".join(curr_state["glm_alive"])
                title = "🎉 智谱 GLM 系列模型已恢复可用！"
                desp = f"### 🎉 GLM 渠道已正式恢复可用！\n\n恢复模型：**{models_str}**\n\n本地 Claude Code 1M 上下文已就绪，可随时直接开工使用！\n\n*巡检时间：{curr_state['time_str']}*"
                push_wechat(title, desp, cfg)
            elif curr_state["overall_status"] == "ALL_DOWN" and prev_state.get("overall_status") != "ALL_DOWN":
                title = "🚨 警报：中转站模型已全线宕机！"
                desp = f"### 🚨 中转站全部模型不可用\n\n所有模型均无法响应，请检查中转站服务器状态。\n\n*巡检时间：{curr_state['time_str']}*"
                push_wechat(title, desp, cfg)
        except Exception:
            time.sleep(10)

def run_server(port=3065):
    t = threading.Thread(target=_background_polling_loop, daemon=True)
    t.start()
    server_address = ("0.0.0.0", port)
    httpd = http.server.ThreadingHTTPServer(server_address, RelayMonitorHandler)
    print(f"[Web Dashboard] Running at http://0.0.0.0:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[Web Dashboard] Stopped.")

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3065
    run_server(port)
