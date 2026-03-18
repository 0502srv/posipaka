"""Pydantic Settings — єдине місце конфігурації Posipaka."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_")

    provider: Literal[
        "anthropic", "openai", "ollama",
        "mistral", "gemini", "groq", "deepseek", "xai",
    ] = "mistral"
    model: str = "mistral-large-latest"
    fallback_model: str = "mistral-small-latest"
    fallback_provider: Literal[
        "anthropic", "openai", "ollama",
        "mistral", "gemini", "groq", "deepseek", "xai",
    ] = "groq"
    api_key: SecretStr = SecretStr("")
    fallback_api_key: SecretStr = SecretStr("")
    base_url: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.7

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        allowed = (
            "anthropic", "openai", "ollama",
            "mistral", "gemini", "groq", "deepseek", "xai",
        )
        if v not in allowed:
            raise ValueError(f"Невідомий LLM провайдер: {v}")
        return v


class TelegramSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TELEGRAM_")

    token: SecretStr = SecretStr("")
    owner_id: int = 0
    allowed_user_ids: list[int] = Field(default_factory=list)
    rate_limit_per_minute: int = 20
    rate_limit_per_hour: int = 100
    webhook_url: str = ""
    use_webhook: bool = False


class DiscordSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DISCORD_")

    token: SecretStr = SecretStr("")
    guild_id: str = ""
    channel_id: str = ""


class SlackSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SLACK_")

    bot_token: SecretStr = SecretStr("")
    app_token: SecretStr = SecretStr("")
    channel: str = ""


class WhatsAppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WHATSAPP_")

    account_sid: SecretStr = SecretStr("")
    auth_token: SecretStr = SecretStr("")
    from_number: str = ""
    webhook_url: str = ""


class SignalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIGNAL_")

    phone_number: str = ""
    signal_cli_url: str = "http://localhost:8080"


class MemorySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEMORY_")

    short_term_limit: int = 50
    chroma_enabled: bool = True
    chroma_path: str = ""
    sqlite_path: str = ""
    encrypt: bool = False


class SecuritySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SECURITY_")

    injection_threshold: float = 0.7
    audit_enabled: bool = True
    max_input_length: int = 8000
    max_upload_size_mb: int = 20
    approval_timeout_seconds: int = 300


class GoogleSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GOOGLE_")

    credentials_path: str = ""
    token_path: str = ""


class BrowserSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BROWSER_")

    headless: bool = True
    browser_type: str = "chromium"
    timeout_ms: int = 30000


class SoulSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOUL_")

    name: str = "Posipaka"
    persona: str = ""
    language: str = "auto"
    timezone: str = "Europe/Kyiv"


class WebSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WEB_")

    host: str = "0.0.0.0"
    port: int = 8080
    secret_key: SecretStr = SecretStr("")


class CostSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COST_")

    daily_budget_usd: float = 5.0
    per_request_max_usd: float = 0.50
    per_session_max_usd: float = 2.0
    warning_threshold: float = 0.8


class Settings(BaseSettings):
    """Головна конфігурація Posipaka — агрегує всі підконфіги."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # Шлях до workspace
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".posipaka")

    # Підконфіги
    llm: LLMSettings = Field(default_factory=LLMSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    discord: DiscordSettings = Field(default_factory=DiscordSettings)
    slack: SlackSettings = Field(default_factory=SlackSettings)
    whatsapp: WhatsAppSettings = Field(default_factory=WhatsAppSettings)
    signal: SignalSettings = Field(default_factory=SignalSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    google: GoogleSettings = Field(default_factory=GoogleSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    soul: SoulSettings = Field(default_factory=SoulSettings)
    web: WebSettings = Field(default_factory=WebSettings)
    cost: CostSettings = Field(default_factory=CostSettings)

    # Активні канали
    enabled_channels: list[str] = Field(default_factory=lambda: ["cli"])

    def ensure_data_dir(self) -> None:
        """Створити data_dir та піддиректорії якщо не існують."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "logs").mkdir(exist_ok=True)
        (self.data_dir / "skills").mkdir(exist_ok=True)
        (self.data_dir / "chroma").mkdir(exist_ok=True)

    @property
    def soul_md_path(self) -> Path:
        return self.data_dir / "SOUL.md"

    @property
    def user_md_path(self) -> Path:
        return self.data_dir / "USER.md"

    @property
    def memory_md_path(self) -> Path:
        return self.data_dir / "MEMORY.md"

    @property
    def audit_log_path(self) -> Path:
        return self.data_dir / "audit.log"

    @property
    def sqlite_db_path(self) -> Path:
        if self.memory.sqlite_path:
            return Path(self.memory.sqlite_path)
        return self.data_dir / "memory.db"

    @property
    def chroma_db_path(self) -> Path:
        if self.memory.chroma_path:
            return Path(self.memory.chroma_path)
        return self.data_dir / "chroma"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton — повертає одну інстанцію Settings."""
    return Settings()
