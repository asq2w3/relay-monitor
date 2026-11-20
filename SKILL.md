---
name: relay-monitor
description: 中转站大模型健康巡检、移动端手机一键查询与后台自动轮询报警工作流。支持手机端随时随地查询模型可用性、微信一键推送巡检报告、智谱 GLM 挂掉自动后台监听并在上游解封恢复时通过 Server酱 发送即时微信通知。
---

# 中转站模型监控与移动端联动工作流 (/relay-monitor)

当用户需要**查询当前中转站模型是否可用**、**在手机端随时查看模型健康状态**、**后台持续轮询并在模型恢复时通知微信**时，激活并遵循此技能。

---

## 核心架构与能力一览

本工作流包含三大核心通道：

1. **📱 手机端公网看板 (Mobile Web Dashboard)**：
   - 手机浏览器随时打开专属暗黑响应式界面，查看 30+ 模型的实时存活与延迟（<1s 极速绿标）；
   - 界面内置 **「🔄 立即重新检测」** 实时并发刷新；
   - 界面内置 **「📲 推送到微信」**，一键调用 Server酱 将最新巡检简报发送至手机微信。
2. **📲 手机一键即时查 (One-Click Shortcut / Bookmark)**：
   - 用户可将 `https://<tunnel-url>/api/push` 保存为手机桌面快捷方式或浏览器书签；
   - 手机上点击该链接，后台立即并发探测并将排版精美的 Markdown 报告推送到微信，零打扰秒级查状态。
3. **⏰ 后台自动轮询与故障恢复报警 (Reactive Polling)**：
   - **Antigravity 会话内原生调度**：使用 `schedule` 工具注册周期性 Cron（`*/5 * * * *`），静默监听，检测到 GLM 解除限流恢复或中转站全线故障时，自动推送微信通知并唤醒 Agent 向用户汇报；
   - **系统级常驻守护进程 (Daemon)**：脱离 IDE 会话独立在后台运行，电脑不关机即可 24 小时自动巡检。

---

## 快速命令参考 (CLI)

系统已在 `~/.local/bin/relay-monitor` 创建全局软链接，任何终端可直接执行：

```bash
# 1. 终端立即进行一次全量模型并发探测
relay-monitor check

# 2. 探测并将完整健康报告推送到手机微信
relay-monitor check --push

# 3. 单次轮询判定 (供 Antigravity 定时调度或脚本调用)
relay-monitor poll-step

# 4. 启动手机端 Web 看板与公网访问隧道
relay-monitor serve --port 3065 --tunnel

# 5. 系统级后台常驻守护管理
relay-monitor daemon start    # 后台启动看板与隧道
relay-monitor daemon status   # 查看运行状态与当前手机访问链接
relay-monitor daemon stop     # 停止后台守护
```

---

## Agent 标准执行工作流

### 场景一：用户要求“一直轮询，直到有模型/GLM 能用通知我”

当用户要求后台持续轮询监听时，遵循以下标准动作：

1. **首轮探测确认基准**：
   ```bash
   relay-monitor poll-step
   ```
2. **注册 Antigravity 原生定时器**：
   使用 `schedule` 工具（严禁使用 shell `sleep` 循环），设置合理的迭代上限（例如 24 次，约 2 小时）：
   ```python
   schedule(
       CronExpression="*/5 * * * *",
       MaxIterations=24,
       Prompt="运行 relay-monitor poll-step 检查中转站模型。如果 GLM_STATUS 显示 RECOVERED 或 STATUS 为 ALL_DOWN，立即向用户汇报并结束任务；否则保持静默监听无需打扰用户。"
   )
   ```
3. **让出控制权**：
   注册完成后立即停止调用工具结束当前轮次，进入静默等待。
4. **触发唤醒与通知**：
   - 当收到定时任务唤醒且检测到 `GLM_STATUS: RECOVERED`：
     - 脚本已自动触发 Server酱 微信推送；
     - Agent 在会话中告知用户 GLM 已恢复，已推送手机，并使用 `manage_task(Action="kill")` 取消定时器。
   - 若状态未变，输出 HTML 注释保持静默。

---

### 场景二：用户要求“手机随时查询”

1. **检查/启动后台移动端服务**：
   ```bash
   relay-monitor daemon start
   relay-monitor daemon status
   ```
2. **向用户交付手机端专属链接**：
   - 交付 **手机端看板网址**（公网 HTTPS，自适应屏幕）；
   - 交付 **一键微信推送链接**（`https://.../api/push`）；
   - 指导用户在手机浏览器中“添加到主屏幕”，即可像原生 App 一样一键点击查看。

---

## 配置文件规范

配置文件位于：`~/.gemini/config/skills/relay-monitor/config.json`
包含中转站网关、凭据、Server酱 SendKey 与关注模型列表。
