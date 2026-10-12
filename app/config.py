from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    genai_enabled: bool = _flag("GENAI_ENABLED")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    genai_model: str = os.getenv("GENAI_MODEL", "gpt-4o-mini")
    openai_timeout_seconds: float = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "20"))
    web_search_enabled: bool = _flag("WEB_SEARCH_ENABLED")
    brave_search_api_key: str = os.getenv("BRAVE_SEARCH_API_KEY", "")
    brave_search_endpoint: str = os.getenv(
        "BRAVE_SEARCH_ENDPOINT", "https://api.search.brave.com/res/v1/web/search"
    )
    max_search_results: int = int(os.getenv("MAX_SEARCH_RESULTS", "5"))
    nli_enabled: bool = _flag("NLI_ENABLED")
    nli_model: str = os.getenv("NLI_MODEL", "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli")
    nli_support_threshold: float = float(os.getenv("NLI_SUPPORT_THRESHOLD", "0.72"))
    nli_contradiction_threshold: float = float(os.getenv("NLI_CONTRADICTION_THRESHOLD", "0.72"))
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "15"))
    max_files: int = int(os.getenv("MAX_FILES", "5"))
    allowed_origins: tuple[str, ...] = tuple(
        item.strip()
        for item in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")
        if item.strip()
    )


settings = Settings()
