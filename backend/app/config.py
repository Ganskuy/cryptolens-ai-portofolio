from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")
    database_url: str = "sqlite:///./cryptolens.db"
    redis_url: str = "redis://localhost:6385/0"
    data_mode: Literal["live", "fixture"] = "fixture"
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_model: str = "deepseek/deepseek-v3.2"
    ai_enabled: bool = False
    ai_total_token_limit: int = Field(100000, ge=0, le=100000)
    ai_daily_usd_limit: float = Field(2, ge=0, le=2)
    poll_seconds: int = Field(300, ge=120)
    cookie_secure: bool = False
    allowed_origin: str = "http://localhost:3100"
    deployment_mode: Literal["local", "production"] = "local"
    auth_mode: Literal["local", "required"] = "local"
    analytics_retention_days: int = Field(30, ge=1, le=365)
    daily_retention_days: int = Field(1826, ge=366, le=3653)
    hourly_retention_days: int = Field(90, ge=1, le=365)
    universe_pages: int = Field(4, ge=1, le=80)
    universe_poll_seconds: int = Field(3600, ge=600)
    stream_rotation_seconds: int = Field(82800, ge=1, le=82800)
    market_ws_url: str = "ws://localhost:8100/api/v1/stream/market"
    ai_mode: Literal["grounded", "legacy"] = "grounded"
    ai_narration: bool = False

    @model_validator(mode="after")
    def secure_deployment(self):
        if self.deployment_mode == "production" and (
            self.auth_mode != "required"
            or not self.cookie_secure
            or not self.allowed_origin.startswith("https://")
            or self.ai_mode != "grounded"
        ):
            raise ValueError(
                "Production mode requires accounts, secure cookies, HTTPS origin and grounded AI"
            )
        return self


@lru_cache
def settings() -> Settings:
    return Settings()
