# Email AI - 邮件自动整理工具

项目拆分为三个部分：

- `frontend/`：前端页面，只负责展示邮件处理结果、筛选搜索、向后端发送请求。
- `backend/`：常驻后端服务，负责 HTTP API、自动轮询新邮件、连接 MySQL、调用 AI 引擎。
- `ai_engine/`：AI 引擎，基于 LangChain `ChatOpenAI` 完成分类、摘要、待办提取。

旧的 `src/` 仍保留邮件抓取、预处理、数据模型、报告等基础模块，便于兼容已有测试和命令。

## 安装依赖

```bash
pip install -r requirements.txt
```

## 配置 `.env`

```env
# 邮箱配置（USER 对应 config.yaml 中 email_accounts 的 name: user）
EMAIL_USER_ADDRESS=your_email@example.com
EMAIL_USER_IMAP_SERVER=imap.example.com
EMAIL_USER_IMAP_PORT=993
EMAIL_USER_USE_SSL=true
EMAIL_USER_PASSWORD=your_app_password
EMAIL_USER_SMTP_SERVER=smtp.example.com
EMAIL_USER_SMTP_PORT=465
EMAIL_USER_SMTP_USE_SSL=true
EMAIL_USER_SMTP_USE_TLS=false
EMAIL_USER_SMTP_USERNAME=your_email@example.com
EMAIL_USER_SMTP_PASSWORD=your_app_password

# MySQL 配置（也兼容 MYSQL_IP / MYSQL_USERNAME）
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=email_ai
MYSQL_PASSWORD=your_mysql_password
MYSQL_DATABASE=email_ai
MYSQL_CHARSET=utf8mb4

# OpenAI 兼容 API / LangChain ChatOpenAI
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=qwen3-vl-235b-a22b-thinking
OPENAI_MODEL2=your_reviewer_model_name
```

MySQL 数据库需要先存在，后端启动后会自动创建 `emails`、`action_items`、`email_replies` 和日报相关表。

## 启动后端

```bash
python main.py backend --host 127.0.0.1 --port 8765
```

启动后端后它不会主动退出：

- 启动后立即检查一次未读新邮件
- 之后按 `config.yaml` 的 `schedule.check_interval_minutes` 持续轮询
- 每天 17:00 会处理昨天 17:00 到今天 17:00 的所有邮件，并由 AI 生成日报存入 MySQL
- 前端页面可访问 `http://127.0.0.1:8765`
- 前端“立即处理”按钮会请求 `POST /api/process`
- 前端列表数据来自 `GET /api/dashboard`
- 前端“生成日报”按钮会请求 `POST /api/reports/daily`
- 前端有“收件箱 / 垃圾邮件箱”切换，分类为 `垃圾邮件` 的邮件会进入单独的垃圾邮件箱
- AI 会在每封邮件处理后判断是否需要回复；需要回复时生成草稿，由前端人工审核、修改或让 AI 按意见改写，审核通过后才通过 SMTP 发送
- `OPENAI_MODEL2` 使用与老模型相同的 API Key 和 Base URL，作为回复审阅模型；审阅不通过时老模型会根据意见重写并再次审阅

常用参数：

```bash
# 每 5 分钟检查一次
python main.py backend --interval 5

# 只启动 API，不自动轮询邮箱
python main.py backend --no-auto
```

`daemon`、`watch`、`dashboard` 现在都是后端常驻服务入口的别名。

## API

- `GET /api/health`：后端健康状态和最近一次处理状态
- `GET /api/dashboard?days=30&category=all&q=`：邮件处理结果、统计、分类、待办
- `GET /api/dashboard?mailbox=spam`：垃圾邮件箱
- `GET /api/spam?days=30&q=`：垃圾邮件箱快捷接口
- `POST /api/process`：立即检查未读邮件并处理
- `POST /api/reports/daily`：立即生成一份 AI 日报
- `GET /api/reports/latest`：读取最新 AI 日报
- `POST /api/replies/{id}/save`：保存人工修改后的回复草稿
- `POST /api/replies/{id}/revise`：根据人工修改意见让 AI 重写回复草稿
- `POST /api/replies/{id}/send`：人工审核通过后发送回复邮件
- `POST /api/emails/{id}/delete`：逻辑删除邮件
- `POST /api/actions/{id}/delete`：逻辑删除待办事项

## 项目结构

```text
email/
├── frontend/          # 页面展示与请求发送
├── backend/           # 常驻 HTTP 服务、MySQL、邮件处理调度
├── ai_engine/         # LangChain AI 引擎
├── src/               # 邮件抓取、预处理、模型、报告等基础模块
├── prompts/           # 分类、摘要、待办提取 Prompt
├── tests/             # 单元测试
├── main.py            # 命令入口
├── config.yaml        # 非敏感配置
└── .env               # 账号、密码、IP、API Key
```

## 测试

```bash
python -m unittest discover
```

## 安全说明

- `.env` 已被 `.gitignore` 忽略，不要提交邮箱密码、MySQL 密码、API Key。
- 建议邮箱使用客户端授权码，不要使用网页登录密码。
