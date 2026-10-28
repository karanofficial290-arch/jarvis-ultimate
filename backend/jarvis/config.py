"""Backend configuration, loaded only from environment variables.

Secrets (API keys, signing key) never live in client apps or source code.
"""
from __future__ import annotations

import os
import secrets
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ProviderName = Literal["none", "local-rules", "anthropic", "openai-compatible"]
SearchProviderName = Literal["none", "brave", "tavily"]


class Settings(BaseModel):
    env: Literal["development", "production", "test"] = "development"
    secret_key: str = Field(min_length=32)
    database_path: str = "jarvis.db"
    allow_registration: bool = False  # first user can always register

    # LLM provider. The model is never hardcoded: it must come from config.
    llm_provider: ProviderName = "local-rules"
    llm_model: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""  # for openai-compatible (OpenAI, Groq, OpenRouter, Ollama ...)
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 2
    llm_max_tokens: int = 1024

    search_provider: SearchProviderName = "none"
    search_api_key: str = ""
    search_timeout_s: float = 15.0

    access_token_ttl_s: int = 12 * 3600
    device_token_ttl_s: int = 3600
    pairing_code_ttl_s: int = 600
    device_wait_s: float = 20.0  # how long chat waits for a device task result
    tool_timeout_s: float = 20.0
    max_tool_rounds: int = 5
    default_timezone: str = "UTC"
    cors_origins: list[str] = []

    @field_validator("secret_key")
    @classmethod
    def _not_placeholder(cls, v: str) -> str:
        if "change-me" in v.lower():
            raise ValueError("JARVIS_SECRET_KEY is still the placeholder value")
        return v

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider in ("none", "local-rules"):
            return False
        if not self.llm_model:
            return False
        if self.llm_provider == "anthropic":
            return bool(self.llm_api_key)
        return bool(self.llm_base_url)


def _bool(v: str | None, default: bool = False) -> bool:
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def load_settings(environ: dict[str, str] | None = None) -> Settings:
    e = dict(os.environ if environ is None else environ)
    env = e.get("JARVIS_ENV", "development")
    secret = e.get("JARVIS_SECRET_KEY", "")
    if not secret:
        if env == "production":
            raise RuntimeError("JARVIS_SECRET_KEY must be set in production")
        # Development convenience: ephemeral key (tokens die on restart).
        secret = secrets.token_urlsafe(48)
    raw = {
        "env": env,
        "secret_key": secret,
        "database_path": e.get("JARVIS_DATABASE_PATH", "jarvis.db"),
        "allow_registration": _bool(e.get("JARVIS_ALLOW_REGISTRATION")),
        "llm_provider": e.get("JARVIS_LLM_PROVIDER", "local-rules"),
        "llm_model": e.get("JARVIS_LLM_MODEL", ""),
        "llm_api_key": e.get("JARVIS_LLM_API_KEY", ""),
        "llm_base_url": e.get("JARVIS_LLM_BASE_URL", ""),
        "search_provider": e.get("JARVIS_SEARCH_PROVIDER", "none"),
        "search_api_key": e.get("JARVIS_SEARCH_API_KEY", ""),
        "default_timezone": e.get("JARVIS_DEFAULT_TIMEZONE", "UTC"),
        "cors_origins": [o for o in e.get("JARVIS_CORS_ORIGINS", "").split(",") if o],
    }
    for key, cast in (
        ("llm_timeout_s", float), ("llm_max_retries", int), ("llm_max_tokens", int),
        ("search_timeout_s", float), ("device_wait_s", float), ("tool_timeout_s", float),
    ):
        val = e.get("JARVIS_" + key.upper())
        if val:
            raw[key] = cast(val)
    return Settings(**raw)


def load_dotenv(path: str = ".env", environ: dict[str, str] | None = None) -> int:
    """Minimal .env loader (KEY=VALUE lines). Real environment variables always win."""
    env = os.environ if environ is None else environ
    if not os.path.isfile(path):
        return 0
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.split(" #", 1)[0].strip().strip('"').strip("'")
            if key and key not in env:
                env[key] = value
                n += 1
    return n


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
