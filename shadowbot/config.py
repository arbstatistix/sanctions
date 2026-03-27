import os
from dataclasses import dataclass, field
from typing import FrozenSet

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    # Secrets / environment
    telegram_bot_token: str
    moonshot_api_key: str
    local_docs_path: str

    # Model / API
    moonshot_base_url: str = "https://api.moonshot.ai/v1"
    model_name: str = "kimi-k2.5"
    max_tokens: int = 16000  # Kimi docs recommend >= 16000 for thinking models

    # Telegram / message shaping
    max_telegram_message_len: int = 4000

    # Local docs retrieval
    max_context_chars: int = 12000
    max_file_snippet_chars: int = 2000
    doc_cache_ttl_seconds: int = 60

    # Runtime / UX
    typing_interval_seconds: float = 4.0
    log_level: str = "INFO"
    max_llm_retries: int = 3
    max_tool_rounds: int = 10
    retry_backoff_base: float = 2.0
    bot_name: str = "ShadowBot"
    bot_username: str = "siddhanthmatebot"

    # Filesystem filters
    allowed_suffixes: FrozenSet[str] = field(
        default_factory=lambda: frozenset({
            ".txt", ".md", ".py", ".json", ".csv", ".log", ".yaml", ".yml"
        })
    )
    ignored_dirs: FrozenSet[str] = field(
        default_factory=lambda: frozenset({
            ".git", "__pycache__", ".venv", "venv", "node_modules"
        })
    )


def load_settings() -> Settings:
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    moonshot_api_key = (
        os.getenv("MOONSHOT_API_KEY", "").strip()
        or os.getenv("OPENAI_API_KEY", "").strip()
    )
    local_docs_path = os.getenv("LOCAL_DOCS_PATH", "./docs").strip()

    missing = []
    if not telegram_bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not moonshot_api_key:
        missing.append("MOONSHOT_API_KEY or OPENAI_API_KEY")

    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    return Settings(
        telegram_bot_token=telegram_bot_token,
        moonshot_api_key=moonshot_api_key,
        local_docs_path=local_docs_path,
        moonshot_base_url=os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1").strip(),
        model_name=os.getenv("KIMI_MODEL", "kimi-k2.5").strip(),
        max_tokens=int(os.getenv("KIMI_MAX_TOKENS", "16000")),
        max_telegram_message_len=int(os.getenv("MAX_TELEGRAM_MESSAGE_LEN", "4000")),
        max_context_chars=int(os.getenv("MAX_CONTEXT_CHARS", "12000")),
        max_file_snippet_chars=int(os.getenv("MAX_FILE_SNIPPET_CHARS", "2000")),
        doc_cache_ttl_seconds=int(os.getenv("DOC_CACHE_TTL_SECONDS", "60")),
        typing_interval_seconds=float(os.getenv("TYPING_INTERVAL_SECONDS", "4.0")),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        max_llm_retries=int(os.getenv("MAX_LLM_RETRIES", "3")),
        max_tool_rounds=int(os.getenv("MAX_TOOL_ROUNDS", "10")),
        retry_backoff_base=float(os.getenv("RETRY_BACKOFF_BASE", "2.0")),
        bot_name=os.getenv("BOT_NAME", "ShadowBot").strip(),
        bot_username=os.getenv("BOT_USERNAME", "siddhanthmatebot").strip(),
    )


settings = load_settings()