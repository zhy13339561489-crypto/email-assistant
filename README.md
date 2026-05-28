# Email AI - 邮件自动整理工具

基于 Python 的邮件自动整理、分类、汇总工具。通过 IMAP 协议连接邮箱，使用大语言模型（兼容 OpenAI API）对邮件进行智能分类、摘要生成、待办提取，并提供 Web Dashboard 可视化界面。

## 功能特性

- **邮件获取** - IMAP 协议连接邮箱，支持多账户，兼容 Gmail / Outlook / 163 / 126 等
- **智能分类** - 自动将邮件归类为：工作、财务、订阅通知、社交、促销广告、重要紧急、垃圾邮件、其他
- **摘要生成** - 为每封邮件生成简短中文摘要，突出关键信息和截止日期
- **待办提取** - 从邮件中提取行动项，标注优先级和截止时间
- **定时调度** - 后台定时检查新邮件，每日/每周自动生成汇总报告
- **Web Dashboard** - 提供可视化界面，支持按分类筛选、搜索、查看详情
- **统计分析** - 邮件分类分布、高频发件人、待办事项统计

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`（或直接创建 `.env`），填入邮箱密码和 API Key：

```env
# 邮箱配置（name 与 config.yaml 中的 name 对应）
EMAIL_USER_ADDRESS=your_email@gmail.com
EMAIL_USER_IMAP_SERVER=imap.gmail.com
EMAIL_USER_IMAP_PORT=993
EMAIL_USER_USE_SSL=true
EMAIL_USER_PASSWORD=your_app_password

# OpenAI 兼容 API 配置
OPENAI_API_KEY=your_api_key
```

### 3. 编辑配置文件

编辑 `config.yaml`，根据需要调整邮箱账户、AI 模型、分类类别、调度时间等：

```yaml
email_accounts:
  - name: user          # 与 .env 中的 NAME 对应

openai:
  base_url: https://dashscope.aliyuncs.com/compatible-mode/v1  # 兼容 OpenAI 的 API 地址
  model: qwen3-vl-235b-a22b-thinking
```

### 4. 运行

```bash
# 处理新邮件（默认命令）
python main.py process

# 生成今日报告
python main.py report

# 生成周报
python main.py report-weekly

# 查看统计信息（默认最近 30 天）
python main.py stats --days 7

# 后台定时运行
python main.py daemon

# 启动 Web Dashboard
python main.py dashboard --host 127.0.0.1 --port 8765
```

## 项目结构

```
email/
├── main.py                  # CLI 入口
├── config.yaml              # 配置文件
├── .env                     # 环境变量（密码、API Key，不入版本控制）
├── requirements.txt         # Python 依赖
├── src/
│   ├── models.py            # 数据模型（EmailData, ProcessResult 等）
│   ├── config.py            # 配置加载（YAML + 环境变量）
│   ├── fetcher.py           # IMAP 邮件获取
│   ├── preprocessor.py      # 邮件预处理（清洗、截断、上下文构建）
│   ├── ai_engine.py         # AI 处理（分类、摘要、待办提取）
│   ├── storage.py           # SQLite 存储
│   ├── reporter.py          # 报告生成（文本 / HTML）
│   ├── scheduler.py         # 定时调度（APScheduler）
│   └── dashboard.py         # Web Dashboard 服务端
├── prompts/                 # LLM Prompt 模板
│   ├── classify.txt
│   ├── summarize.txt
│   └── extract_actions.txt
├── templates/               # HTML 报告模板
│   └── daily_report.html
├── frontend/                # Dashboard 前端
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── data/                    # 运行时数据（SQLite 数据库、日志）
└── tests/                   # 单元测试
```

## 架构概览

```
调度层 (APScheduler)
    │
    ▼
邮件获取层 (IMAP)
    │
    ▼
预处理层（清洗签名/转发、截断长文本）
    │
    ▼
AI 处理层（分类 + 摘要 + 待办提取）
    │
    ▼
存储层 (SQLite)
    │
    ▼
输出层（文本报告 / HTML 报告 / Web Dashboard）
```

## 技术栈

| 模块 | 技术 |
|------|------|
| 邮件协议 | `imaplib`（标准库） |
| 邮件解析 | `email`（标准库） + `beautifulsoup4` |
| AI 接口 | `openai` SDK（兼容任意 OpenAI API 格式的服务） |
| 数据库 | `sqlite3`（标准库） |
| 定时任务 | `APScheduler` |
| 配置管理 | `PyYAML` + `python-dotenv` |
| 日志 | `loguru` |
| 前端 | 原生 HTML / CSS / JavaScript |

## 运行测试

```bash
python -m pytest tests/
```

## 安全说明

- 邮箱密码和 API Key 仅存于 `.env` 文件，已加入 `.gitignore`
- 邮件正文不落盘，仅存储元数据和 AI 生成的摘要
- 建议使用应用专用密码（App Password）而非主密码连接邮箱
