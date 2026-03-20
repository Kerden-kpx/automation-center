# 钉钉GPT机器人集成 (DingTalk GPT Bot)

这是一个将钉钉机器人、数据库聚合与 Playwright 驱动的 GPT 自动化结合的样例实现。它接收用户在钉钉发送的查询（格式：`国家 广告名称 [SKU]`），在数据库中聚合广告数据，将聚合结果发送到已登录的 GPT 页面以获取分析结论，并把结果私聊回到钉钉用户。

主要目录：
- `main.py`：消息接收与处理入口（支持从环境变量读取配置）。
- `campaign_aggregator.py`：封装 `services/aggregate_data.py` 的聚合逻辑并返回 JSON。
- `gpt_automation.py`：使用 Playwright + CDP 向 GPT 发送消息并抓取回复。
- `test_send_markdown.py`：构造 Markdown 报告并可 dry-run 或实际发送到钉钉。

## 先决条件

- Python 3.8+
- Chrome（或 Chromium）已安装并能以调试模式启动
- 推荐在虚拟环境（venv）中运行

## 安装

1. 克隆仓库并进入子目录：

```bash
git clone <repo>
cd dingtalk_gpt_bot
```

2. 安装依赖（两种方式）：

- 使用 requirements（与项目可直接运行）：
```bash
pip install -r requirements.txt
```

- 或以可安装包方式（需要 `pyproject.toml`）：
```bash
pip install .
# 或用于开发安装
pip install -e .
```

3. 安装 Playwright 浏览器二进制（首次运行）：

```bash
playwright install chromium
```

## 环境变量与配置

建议在项目根或启动环境中使用环境变量管理敏感信息。项目提供 `env.example`（位于本目录）作为示例：

- `DING_CLIENT_ID`、`DING_CLIENT_SECRET`、`DING_ROBOT_CODE`：钉钉应用凭据（必填）。  
- `DING_STREAM_WS_PING_INTERVAL`、`DING_STREAM_WS_PING_TIMEOUT`：Stream WebSocket 心跳与超时（秒，可选，默认 `30` / `120`，网络抖动时可适当调大 timeout）。  
- `TOKEN_URL`、`TOKEN_REQUEST_KEY`：领星 OpenAPI 的自定义 token 服务配置（可选，优先于 APP_ID/APP_SECRET）。  
- `CDP_URL`：Chrome DevTools Protocol 地址，默认 `http://localhost:9222`。  
- 数据库相关：`DB_HOST`、`DB_PORT`、`DB_USER`、`DB_PASSWORD`、`DB_NAME`（由 `synchronize_data.Settings` 读取，具体实现请参见 `synchronize_data.py`）。

请**不要**将真实的 secret 提交到代码仓库；把 `.env` 加入 `.gitignore`。

## 启动 Chrome（调试模式）

在本地或生产机器上以调试模式启动 Chrome（需与 `CDP_URL` 一致）：

Windows:
```bash
chrome.exe --remote-debugging-port=9222
```

macOS:
```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
```

Linux:
```bash
google-chrome --remote-debugging-port=9222
```

## 运行机器人

确保环境变量已配置并且 Chrome 已以调试模式启动且已登录 GPT，然后：

```bash
python -m dingtalk_gpt_bot.main
# 或（直接运行脚本）
python dingtalk_gpt_bot/main.py
```

默认 `main.py` 会优先读取环境变量（`DING_CLIENT_ID` / `DING_CLIENT_SECRET` / `DING_ROBOT_CODE`），未设置时会回退到代码中的默认值（建议删除代码中的默认 secret 并强制使用环境变量）。
启动时会自动检查 CDP 调试浏览器是否可用，并检查 `GPT_URL` 页面是否已打开；若未打开会自动拉起浏览器并打开目标页面（`CHROME_USER_DATA_DIR` 可配置用户数据目录）。

## 自动同步（后台）

机器人启动后会自动启动后台同步任务，包含两类：

- **每小时同步**：campaign 报表聚合（与原逻辑一致）。
- **每天 0 点同步**：
  - `run_names`
  - `run_ad_groups`
  - `run_sb_creativity`
  - `run_sp_product_ads`
  - `run_queryword_reports`（仅同步过去 7 天，不包含今天和昨天）

如需调整同步内容或时间窗口，请修改 `dingtalk_gpt_bot/services/auto_sync.py`。

## 测试发送 Markdown（dry-run）

示例：
```bash
python dingtalk_gpt_bot/test_send_markdown.py --user-id 12345
python dingtalk_gpt_bot/test_send_markdown.py --user-id 12345 --send
```

`--send` 参数会实际调用钉钉发送接口；缺省为 dry-run，仅打印预览。

## 打包与发布（可选）

项目包含 `pyproject.toml`，可用标准工具打包：

```bash
pip install build
python -m build
# 生成 wheel 和 sdist，之后可上传到 PyPI 或私有仓库
```

若需在 `pyproject.toml` 中添加 `console_scripts` 入口点或填写 `authors` / `license` / `classifiers`，我可替你完善。

## 开发注意事项

- `campaign_aggregator.py` 调用 `services/aggregate_data.py` 的函数以合成聚合 JSON，确保数据库配置与表结构匹配。  
- `gpt_automation.py` 使用页面选择器抓取 GPT 返回内容；若 GPT 页面结构更新，选择器需要调整。  
- 日志与错误会尽量返回给钉钉用户；在开发环境建议将日志级别设为 DEBUG 以便排查。

## 安全

- 请务必通过环境变量管理密钥，不要在仓库中保留明文 `client_secret`。  
- `TOKEN_REQUEST_KEY` 同样应视为敏感信息，避免提交到仓库。  
- 在生产环境可使用机密管理服务或 CI/CD secrets 注入。  

如果你希望我将 README 中的“使用示例”替换为更详细的 CI / systemd service 单元示例，或把说明翻译成英文，请告诉我。

