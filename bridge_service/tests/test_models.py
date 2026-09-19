"""Tests for Pydantic models: AIProvider, MT5Target, Deployment, Backup, Comparison."""

import os
import sys

import pytest
from pydantic import ValidationError

# Adjust import path for tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import AIProvider, MT5Target, Deployment, Backup, Comparison


# ── AIProvider Tests ───────────────────────────────────────────────


class TestAIProvider:
    def test_create_with_required_fields(self):
        provider = AIProvider(name="OpenAI", type="openai")
        assert provider.name == "OpenAI"
        assert provider.type == "openai"
        assert provider.base_url is None
        assert provider.api_key is None
        assert provider.model is None
        assert provider.is_default is False

    def test_create_with_all_fields(self):
        provider = AIProvider(
            name="Custom AI",
            type="openai-compatible",
            base_url="https://api.example.com",
            api_key="sk-12345",
            model="gpt-4",
            is_default=True,
        )
        assert provider.name == "Custom AI"
        assert provider.type == "openai-compatible"
        assert provider.base_url == "https://api.example.com"
        assert provider.api_key == "sk-12345"
        assert provider.model == "gpt-4"
        assert provider.is_default is True

    def test_missing_name_raises_error(self):
        with pytest.raises(ValidationError) as exc_info:
            AIProvider(type="openai")
        assert "name" in str(exc_info.value).lower()

    def test_missing_type_raises_error(self):
        with pytest.raises(ValidationError) as exc_info:
            AIProvider(name="Test")
        assert "type" in str(exc_info.value).lower()

    def test_name_must_be_string(self):
        with pytest.raises(ValidationError):
            AIProvider(name=123, type="openai")

    def test_type_must_be_string(self):
        with pytest.raises(ValidationError):
            AIProvider(name="Test", type=123)

    def test_model_dump(self):
        provider = AIProvider(name="Test", type="claude", model="claude-3")
        data = provider.model_dump()
        assert data["name"] == "Test"
        assert data["type"] == "claude"
        assert data["model"] == "claude-3"
        assert "id" not in data  # id is DB-managed, not in model

    def test_model_validate(self):
        data = {"name": "Test", "type": "openai"}
        provider = AIProvider.model_validate(data)
        assert provider.name == "Test"
        assert provider.type == "openai"


# ── MT5Target Tests ────────────────────────────────────────────────


class TestMT5Target:
    def test_create_with_required_fields(self):
        target = MT5Target(name="Main Terminal", install_path="C:\\MT5")
        assert target.name == "Main Terminal"
        assert target.install_path == "C:\\MT5"
        assert target.data_path is None
        assert target.is_portable is False
        assert target.is_active is True

    def test_create_with_all_fields(self):
        target = MT5Target(
            name="Portable Instance",
            install_path="D:\\MT5_Portable",
            data_path="D:\\MT5_Portable\\Data",
            is_portable=True,
            is_active=True,
        )
        assert target.name == "Portable Instance"
        assert target.install_path == "D:\\MT5_Portable"
        assert target.data_path == "D:\\MT5_Portable\\Data"
        assert target.is_portable is True
        assert target.is_active is True

    def test_portable_mode_data_path_optional(self):
        target = MT5Target(
            name="Portable",
            install_path="E:\\MT5",
            is_portable=True,
        )
        assert target.is_portable is True
        assert target.data_path is None

    def test_missing_name_raises_error(self):
        with pytest.raises(ValidationError) as exc_info:
            MT5Target(install_path="C:\\MT5")
        assert "name" in str(exc_info.value).lower()

    def test_missing_install_path_raises_error(self):
        with pytest.raises(ValidationError) as exc_info:
            MT5Target(name="Test")
        assert "install_path" in str(exc_info.value).lower()

    def test_inactive_target(self):
        target = MT5Target(
            name="Inactive",
            install_path="C:\\MT5",
            is_active=False,
        )
        assert target.is_active is False

    def test_model_dump(self):
        target = MT5Target(name="Test", install_path="C:\\MT5")
        data = target.model_dump()
        assert data["name"] == "Test"
        assert data["install_path"] == "C:\\MT5"
        assert data["is_active"] is True


# ── Deployment Tests ───────────────────────────────────────────────


class TestDeployment:
    def test_create_with_required_fields(self):
        deployment = Deployment(
            strategy_name="MyStrategy",
            mt5_target_id=1,
            ai_provider_id=1,
            status="pending",
        )
        assert deployment.strategy_name == "MyStrategy"
        assert deployment.mt5_target_id == 1
        assert deployment.ai_provider_id == 1
        assert deployment.status == "pending"
        assert deployment.sqx_version is None
        assert deployment.deployed_version is None
        assert deployment.errors_found == 0
        assert deployment.errors_fixed == 0
        assert deployment.ai_review_log is None
        assert deployment.compilation_log is None

    def test_create_with_all_fields(self):
        deployment = Deployment(
            strategy_name="TrendFollower",
            mt5_target_id=2,
            ai_provider_id=3,
            status="deployed",
            sqx_version="6.8.0",
            deployed_version="1.0.0",
            errors_found=5,
            errors_fixed=5,
            ai_review_log="All issues resolved",
            compilation_log="Build successful",
        )
        assert deployment.status == "deployed"
        assert deployment.errors_found == 5
        assert deployment.errors_fixed == 5

    def test_all_valid_statuses(self):
        valid_statuses = [
            "pending", "reviewing", "compiling", "fixing",
            "deployed", "failed", "rolled_back",
        ]
        for status in valid_statuses:
            deployment = Deployment(
                strategy_name="Test",
                mt5_target_id=1,
                ai_provider_id=1,
                status=status,
            )
            assert deployment.status == status

    def test_invalid_status_raises_error(self):
        with pytest.raises(ValidationError) as exc_info:
            Deployment(
                strategy_name="Test",
                mt5_target_id=1,
                ai_provider_id=1,
                status="invalid_status",
            )
        assert "status" in str(exc_info.value).lower()

    def test_missing_strategy_name_raises_error(self):
        with pytest.raises(ValidationError) as exc_info:
            Deployment(mt5_target_id=1, ai_provider_id=1, status="pending")
        assert "strategy_name" in str(exc_info.value).lower()

    def test_missing_status_raises_error(self):
        with pytest.raises(ValidationError) as exc_info:
            Deployment(
                strategy_name="Test",
                mt5_target_id=1,
                ai_provider_id=1,
            )
        assert "status" in str(exc_info.value).lower()

    def test_negative_ids_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            Deployment(
                strategy_name="Test",
                mt5_target_id=-1,
                ai_provider_id=1,
                status="pending",
            )
        assert "mt5_target_id" in str(exc_info.value).lower()

    def test_model_dump(self):
        deployment = Deployment(
            strategy_name="Test",
            mt5_target_id=1,
            ai_provider_id=1,
            status="pending",
        )
        data = deployment.model_dump()
        assert data["strategy_name"] == "Test"
        assert data["errors_found"] == 0


# ── Backup Tests ───────────────────────────────────────────────────


class TestBackup:
    def test_create_with_required_fields(self):
        backup = Backup(deployment_id=1)
        assert backup.deployment_id == 1
        assert backup.strategy_name is None
        assert backup.file_path is None
        assert backup.file_hash is None

    def test_create_with_all_fields(self):
        backup = Backup(
            deployment_id=1,
            strategy_name="MyStrategy",
            file_path="/backups/my_strategy_v1.mq5",
            file_hash="abc123def456",
        )
        assert backup.deployment_id == 1
        assert backup.strategy_name == "MyStrategy"
        assert backup.file_path == "/backups/my_strategy_v1.mq5"
        assert backup.file_hash == "abc123def456"

    def test_missing_deployment_id_raises_error(self):
        with pytest.raises(ValidationError) as exc_info:
            Backup()
        assert "deployment_id" in str(exc_info.value).lower()

    def test_negative_deployment_id_rejected(self):
        with pytest.raises(ValidationError):
            Backup(deployment_id=-1)

    def test_model_dump(self):
        backup = Backup(deployment_id=1)
        data = backup.model_dump()
        assert data["deployment_id"] == 1


# ── Comparison Tests ───────────────────────────────────────────────


class TestComparison:
    def test_create_with_required_fields(self):
        comparison = Comparison(deployment_id=1)
        assert comparison.deployment_id == 1
        assert comparison.sqx_metrics is None
        assert comparison.mt5_metrics is None
        assert comparison.deltas is None
        assert comparison.status is None
        assert comparison.report_path is None

    def test_create_with_all_fields(self):
        comparison = Comparison(
            deployment_id=1,
            sqx_metrics='{"profit": 1000, "sharpe": 1.5}',
            mt5_metrics='{"profit": 995, "sharpe": 1.49}',
            deltas='{"profit": -5, "sharpe": -0.01}',
            status="match",
            report_path="/reports/comparison_1.html",
        )
        assert comparison.deployment_id == 1
        assert comparison.status == "match"

    def test_missing_deployment_id_raises_error(self):
        with pytest.raises(ValidationError) as exc_info:
            Comparison()
        assert "deployment_id" in str(exc_info.value).lower()

    def test_model_dump(self):
        comparison = Comparison(deployment_id=1, status="mismatch")
        data = comparison.model_dump()
        assert data["deployment_id"] == 1
        assert data["status"] == "mismatch"


# ── JSON Serialization Tests ───────────────────────────────────────


class TestJSONSerialization:
    def test_ai_provider_json(self):
        provider = AIProvider(name="Test", type="openai")
        json_str = provider.model_dump_json()
        assert '"name":"Test"' in json_str
        assert '"type":"openai"' in json_str

    def test_deployment_json(self):
        deployment = Deployment(
            strategy_name="Test",
            mt5_target_id=1,
            ai_provider_id=1,
            status="pending",
        )
        json_str = deployment.model_dump_json()
        assert '"strategy_name":"Test"' in json_str
        assert '"status":"pending"' in json_str

    def test_roundtrip(self):
        original = AIProvider(name="Test", type="claude", model="claude-3")
        json_str = original.model_dump_json()
        restored = AIProvider.model_validate_json(json_str)
        assert original == restored
