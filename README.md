# Relay Monitor — 中转站大模型健康巡检与移动端联动工作流

一个零第三方依赖（纯 Python 标准库）的中转站大模型可用性监控、手机端实时看板与微信（Server酱）自动告警工作流，同时支持 **Antigravity Skill** 与 **GitHub Actions** 云端定时巡检。

## 核心功能

- **并发全量测速**：自动拉取 `/v1/models` 并结合自定义关注列表（如 `glm-5.3-flash[1M]`），并发探测 `/v1/messages` 真实可用性与响应延迟。
- **手机端实时看板 (`web_server.py` + `cloudflared`)**：
  - 暗黑响应式移动端页面，支持按 GLM / Claude / MiniMax 分类筛选；
  - 内置「🔄 立即重新检测」与「📲 推送到微信」按钮；
  - 支持 `GET /api/push` 一键链接，可加入手机桌面或 iOS 快捷指令，点开即查并推送报告到微信。
- **状态变更自动告警**：检测到 GLM 系列从不可用恢复（`RECOVERED`），或中转站全线熔断（`ALL_DOWN`）时，自动通过 Server酱推送微信提醒。
- **双模运行**：
  - 本地 CLI 与常驻后台守护进程（`relay-monitor daemon start`）；
  - GitHub Actions 云端定时巡检（`.github/workflows/monitor.yml`）。

## 快速开始

### 1. 本地安装

```bash
git clone https://github.com/asq2w3/relay-monitor.git
cd relay-monitor
./install.sh
```

编辑 `~/.gemini/config/skills/relay-monitor/config.json`，填入你的中转站地址、API Token 与 Server酱 `SendKey`。

### 2. 常用命令

```bash
# 单次全量检测
relay-monitor check

# 检测并推送完整报告到微信
relay-monitor check --push

# 启动手机端 Web 看板 + Cloudflare 公网隧道
relay-monitor daemon start
relay-monitor daemon status
relay-monitor daemon stop
```

### 3. GitHub Actions 云端工作流

在仓库 **Settings -> Secrets and variables -> Actions** 中配置以下 Secrets：
- `RELAY_BASE_URL`：中转站地址（如 `http://your-gateway:3060`）
- `RELAY_TOKEN`：API Token
- `SERVERCHAN_KEY`：Server酱 SendKey

配置完成后，工作流会每 30 分钟自动巡检一次，也可在 **Actions** 页面手动点击 **Run workflow** 立即触发并推送报告到微信。
