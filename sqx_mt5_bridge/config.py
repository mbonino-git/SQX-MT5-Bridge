"""Configuration settings for the SQX-MT5 Bridge."""

import json

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = Field(default="SQX-MT5 Bridge")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8090)
    debug: bool = Field(default=False)

    # MT5 paths
    metaeditor_path: str = Field(
        default="C:/Terminal/WORKBENCH-01/metaeditor64.exe",
        description="Path to metaeditor64.exe for compilation.",
    )
    terminal_path: str = Field(
        default="C:/Terminal/WORKBENCH-01/terminal64.exe",
        description="Path to the MT5 terminal64.exe (FTMO-Demo).",
    )

    # Symbol mapping: SQX symbol name -> MT5 symbol name
    # Format: pipe-separated key=value pairs, e.g. NAS100=US100.cash|US500=US500.cash
    # Or JSON object: {"NAS100":"US100.cash","US500":"US500.cash"}
    # Source: {project_root}/sqx_mt5_bridge/.env
    symbol_mapping: str = Field(
        default="",
        description="Map StrategyQuant symbol names to MT5-compatible names.",
    )

    # SQX data directory (for compile, MQ5 source lookup)
    sqx_data_dir: str = Field(
        default="C:/SQX_144.2953-1/user",
        description="Path to SQX user data directory (contains Projects/).",
    )

    # SQX API connection
    sqx_host: str = Field(
        default="localhost",
        description="Host where SQX REST API is listening.",
    )
    sqx_port: int = Field(
        default=8080,
        description="Port where SQX REST API is listening.",
    )

    model_config = {
        "env_prefix": "BRIDGE_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

    @property
    def symbol_mapping_dict(self) -> dict[str, str]:
        """Parse the raw symbol_mapping string into a dict."""
        raw = self.symbol_mapping.strip()
        if not raw:
            return {}

        # Try JSON first
        if raw.startswith("{"):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass

        # Fallback to pipe-separated key=value
        result: dict[str, str] = {}
        for pair in raw.split("|"):
            pair = pair.strip()
            if not pair:
                continue
            if "=" in pair:
                key, _, value = pair.partition("=")
                key = key.strip()
                value = value.strip()
                if key and value:
                    result[key] = value

        return result


settings = Settings()
