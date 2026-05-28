import os
from pathlib import Path

import yaml
from dotenv import load_dotenv


def load_config(config_path: str = "config.yaml") -> dict:
    load_dotenv()

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

    return config


def get_project_root() -> Path:
    return Path(__file__).parent.parent
