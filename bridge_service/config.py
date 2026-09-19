"""Configuration settings for the SQX-MT5 Bridge Service."""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables with sensible defaults."""

    app_name: str = Field(default="SQX-MT5 Bridge Service")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080)
    debug: bool = Field(default=False)

    # Database
    database_path: str = Field(default="bridge_service.db")

    # MT5 defaults
    metaeditor_path: str = Field(default="C:/Program Files/MetaTrader 5/metaeditor64.exe")
    terminal_path: str = Field(default="C:/Program Files/MetaTrader 5/terminal64.exe")

    # AI defaults
    default_ai_provider: str | None = Field(default=None)
    max_compile_retries: int = Field(default=3)
    max_concurrent_backtests: int = Field(default=3)

    model_config = {
        "env_prefix": "BRIDGE_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()
