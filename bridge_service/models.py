"""Pydantic models for the SQX-MT5 Bridge Service.

Provides request/response validation models for all bridge entities.
These models are used by the API routers and service layer.
"""

from pydantic import BaseModel, Field


class AIProvider(BaseModel):
    """AI provider configuration for code review and fixing."""

    name: str = Field(..., min_length=1, description="Human-readable provider name")
    type: str = Field(
        ...,
        min_length=1,
        description="Provider type: 'openai-compatible', 'claude', or 'openai'",
    )
    base_url: str | None = Field(
        None, description="Base URL for API requests (required for openai-compatible)"
    )
    api_key: str | None = Field(None, description="API authentication key")
    model: str | None = Field(None, description="Model identifier")
    is_default: bool = Field(False, description="Whether this is the default provider")


class MT5Target(BaseModel):
    """MT5 terminal installation target."""

    name: str = Field(..., min_length=1, description="Human-readable target name")
    install_path: str = Field(
        ..., min_length=1, description="Path to MT5 terminal64.exe directory"
    )
    data_path: str | None = Field(
        None, description="Path to MQL5 data folder (None for portable mode)"
    )
    is_portable: bool = Field(False, description="Whether this is a portable MT5 instance")
    is_active: bool = Field(True, description="Whether this target is active")


class Deployment(BaseModel):
    """Strategy deployment tracking record."""

    strategy_name: str = Field(..., min_length=1, description="SQX strategy name")
    mt5_target_id: int = Field(..., ge=1, description="FK to mt5_targets table")
    ai_provider_id: int = Field(..., ge=1, description="FK to ai_providers table")
    status: str = Field(
        ...,
        pattern=r"^(pending|reviewing|compiling|fixing|deployed|failed|rolled_back)$",
        description="Current deployment status",
    )
    sqx_version: str | None = Field(
        None, description="SQX version the strategy was exported from"
    )
    deployed_version: str | None = Field(
        None, description="Version deployed to MT5"
    )
    errors_found: int = Field(0, ge=0, description="Number of compilation errors found")
    errors_fixed: int = Field(0, ge=0, description="Number of compilation errors fixed")
    ai_review_log: str | None = Field(
        None, description="AI review conversation log"
    )
    compilation_log: str | None = Field(
        None, description="MT5 compilation output log"
    )


class Backup(BaseModel):
    """Backup record for strategy files."""

    deployment_id: int = Field(..., ge=1, description="FK to deployments table")
    strategy_name: str | None = Field(None, description="Strategy name at backup time")
    file_path: str | None = Field(None, description="Path to backup file")
    file_hash: str | None = Field(None, description="SHA-256 hash of backup file")


class Comparison(BaseModel):
    """SQX vs MT5 performance comparison record."""

    deployment_id: int = Field(..., ge=1, description="FK to deployments table")
    sqx_metrics: str | None = Field(
        None, description="SQX backtest metrics as JSON string"
    )
    mt5_metrics: str | None = Field(
        None, description="MT5 backtest metrics as JSON string"
    )
    deltas: str | None = Field(
        None, description="Difference between SQX and MT5 metrics as JSON string"
    )
    status: str | None = Field(
        None, description="Comparison result: 'match', 'mismatch', or 'pending'"
    )
    report_path: str | None = Field(
        None, description="Path to the generated comparison report"
    )
