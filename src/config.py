import os
from pathlib import Path

import yaml
from dotenv import load_dotenv


def load_config(config_path: str = "config.yaml") -> dict:
    load_dotenv(override=True)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 从环境变量读取邮箱完整配置
    for account in config.get("email_accounts", []):
        name = account["name"].upper()
        account["address"] = os.getenv(f"EMAIL_{name}_ADDRESS", "")
        account["imap_server"] = os.getenv(f"EMAIL_{name}_IMAP_SERVER", "")
        account["imap_port"] = int(os.getenv(f"EMAIL_{name}_IMAP_PORT", "993"))
        account["use_ssl"] = os.getenv(f"EMAIL_{name}_USE_SSL", "true").lower() == "true"
        account["password"] = os.getenv(f"EMAIL_{name}_PASSWORD", "")

    # 从环境变量补充 OpenAI 兼容 API 配置
    config["openai"]["api_key"] = os.getenv("OPENAI_API_KEY", "")
    if os.getenv("OPENAI_BASE_URL"):
        config["openai"]["base_url"] = os.getenv("OPENAI_BASE_URL")
    if os.getenv("OPENAI_MODEL"):
        config["openai"]["model"] = os.getenv("OPENAI_MODEL")

    config["mysql"] = {
        "host": _env("MYSQL_HOST", "MYSQL_IP", "DB_HOST", default="127.0.0.1"),
        "port": int(_env("MYSQL_PORT", "DB_PORT", default="3306")),
        "user": _env("MYSQL_USER", "MYSQL_USERNAME", "DB_USER", "DB_USERNAME", default=""),
        "password": _env("MYSQL_PASSWORD", "DB_PASSWORD", default=""),
        "database": _env("MYSQL_DATABASE", "MYSQL_DB", "DB_DATABASE", "DB_NAME", default="email_ai"),
        "charset": _env("MYSQL_CHARSET", "DB_CHARSET", default="utf8mb4"),
    }

    return config


def get_project_root() -> Path:
    return Path(__file__).parent.parent


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default
