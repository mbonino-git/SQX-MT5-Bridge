"""Tests for Deployer: copies .mq5 files to MT5 instances.

Tests path resolution for portable/normal modes, file copy, and backup creation.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Adjust import path for tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import MT5Target
from services.deployer import Deployer


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def deployer():
    """Create a Deployer instance."""
    return Deployer()


@pytest.fixture
def portable_target():
    """MT5Target in portable mode (no data_path, MQL5 under install_path)."""
    return MT5Target(
        name="Portable Test",
        install_path="/fake/mt5_portable",
        data_path=None,
        is_portable=True,
    )


@pytest.fixture
def normal_target():
    """MT5Target in normal mode (data_path set, MQL5 under data_path)."""
    return MT5Target(
        name="Normal Test",
        install_path="/fake/mt5_normal",
        data_path="/fake/mt5_data",
        is_portable=False,
    )


@pytest.fixture
def source_dir(tmp_path):
    """Create a temporary source directory with a .mq5 file."""
    src = tmp_path / "source"
    src.mkdir()
    mq5_file = src / "strategy.mq5"
    mq5_file.write_text("void OnTick() { }")
    return src


def _to_posix(path_str: str) -> str:
    """Normalize a path string to POSIX separators for comparison."""
    return path_str.replace("\\", "/")


# ── Path Resolution Tests ─────────────────────────────────────────


class TestGetExpertsPath:
    """Tests for get_experts_path() method."""

    def test_portable_mode_uses_install_path(self, deployer, portable_target):
        """Portable mode: Experts path = install_path/MQL5/Experts/"""
        path = deployer.get_experts_path(portable_target)
        assert _to_posix(path) == "/fake/mt5_portable/MQL5/Experts"

    def test_normal_mode_uses_data_path(self, deployer, normal_target):
        """Normal mode: Experts path = data_path/MQL5/Experts/"""
        path = deployer.get_experts_path(normal_target)
        assert _to_posix(path) == "/fake/mt5_data/MQL5/Experts"

    def test_normal_mode_with_data_path_does_not_use_install_path(
        self, deployer, normal_target
    ):
        """When data_path is set, install_path should NOT appear in experts path."""
        path = deployer.get_experts_path(normal_target)
        assert "/fake/mt5_normal" not in _to_posix(path)

    def test_portable_mode_without_data_path(self, deployer):
        """Portable with no data_path at all."""
        target = MT5Target(
            name="Minimal Portable",
            install_path="/my/install",
            data_path=None,
            is_portable=True,
        )
        path = deployer.get_experts_path(target)
        assert _to_posix(path) == "/my/install/MQL5/Experts"

    def test_normal_mode_with_explicit_data_path(self, deployer):
        """Normal mode with explicit data_path."""
        target = MT5Target(
            name="Normal with data",
            install_path="/some/install",
            data_path="/custom/data/path",
            is_portable=False,
        )
        path = deployer.get_experts_path(target)
        assert _to_posix(path) == "/custom/data/path/MQL5/Experts"


# ── File Copy Tests ───────────────────────────────────────────────


class TestDeployFile:
    """Tests for deploy_file() method."""

    def test_deploy_file_copies_to_portable_experts(
        self, deployer, portable_target, source_dir
    ):
        """File should be copied to portable target's Experts folder."""
        mq5 = source_dir / "strategy.mq5"
        with tempfile.TemporaryDirectory() as tmpdir:
            portable_target.install_path = tmpdir
            dest = deployer.deploy_file(
                portable_target, str(mq5), "strategy.mq5"
            )
            assert os.path.isfile(dest)
            assert dest.endswith("strategy.mq5")
            assert "MQL5" in _to_posix(dest)
            assert "Experts" in _to_posix(dest)

    def test_deploy_file_copies_to_normal_experts(
        self, deployer, normal_target, source_dir
    ):
        """File should be copied to normal target's Experts folder."""
        mq5 = source_dir / "strategy.mq5"
        with tempfile.TemporaryDirectory() as tmpdir:
            normal_target.data_path = tmpdir
            dest = deployer.deploy_file(
                normal_target, str(mq5), "strategy.mq5"
            )
            assert os.path.isfile(dest)
            assert dest.endswith("strategy.mq5")

    def test_deploy_file_returns_destination_path(
        self, deployer, portable_target, source_dir
    ):
        """deploy_file should return the full destination path as a string."""
        mq5 = source_dir / "strategy.mq5"
        with tempfile.TemporaryDirectory() as tmpdir:
            portable_target.install_path = tmpdir
            dest = deployer.deploy_file(
                portable_target, str(mq5), "strategy.mq5"
            )
            assert isinstance(dest, str)
            assert os.path.isabs(dest)

    def test_deploy_file_content_matches_source(
        self, deployer, portable_target, source_dir
    ):
        """Deployed file content should match the source file."""
        mq5 = source_dir / "strategy.mq5"
        with tempfile.TemporaryDirectory() as tmpdir:
            portable_target.install_path = tmpdir
            dest = deployer.deploy_file(
                portable_target, str(mq5), "strategy.mq5"
            )
            assert Path(dest).read_text() == "void OnTick() { }"

    def test_deploy_file_overwrites_existing(
        self, deployer, portable_target, source_dir
    ):
        """Deploying should overwrite an existing file with the same name."""
        mq5 = source_dir / "strategy.mq5"
        with tempfile.TemporaryDirectory() as tmpdir:
            portable_target.install_path = tmpdir
            # Deploy once
            deployer.deploy_file(portable_target, str(mq5), "strategy.mq5")
            # Modify source and deploy again
            mq5.write_text("void OnTick() { updated }")
            dest = deployer.deploy_file(
                portable_target, str(mq5), "strategy.mq5"
            )
            assert Path(dest).read_text() == "void OnTick() { updated }"

    def test_deploy_file_creates_experts_directory(
        self, deployer, portable_target, source_dir
    ):
        """deploy_file should create Experts directory if it doesn't exist."""
        mq5 = source_dir / "strategy.mq5"
        with tempfile.TemporaryDirectory() as tmpdir:
            portable_target.install_path = tmpdir
            # No MQL5/Experts exists yet
            dest = deployer.deploy_file(
                portable_target, str(mq5), "strategy.mq5"
            )
            assert os.path.isdir(os.path.dirname(dest))


# ── Backup Creation Tests ─────────────────────────────────────────


class TestCreateBackup:
    """Tests for create_backup() method."""

    def test_create_backup_copies_file(
        self, deployer, portable_target, source_dir
    ):
        """Backup should create a copy of the file with timestamp suffix."""
        mq5 = source_dir / "strategy.mq5"
        with tempfile.TemporaryDirectory() as tmpdir:
            portable_target.install_path = tmpdir
            # Deploy first so the file exists
            deployer.deploy_file(portable_target, str(mq5), "strategy.mq5")
            # Create backup
            backup_path = deployer.create_backup(
                portable_target, "strategy.mq5"
            )
            assert os.path.isfile(backup_path)
            assert backup_path.endswith(".mq5")
            # Backup filename should contain the original name
            assert "strategy" in backup_path.lower()

    def test_create_backup_returns_string_path(
        self, deployer, portable_target, source_dir
    ):
        """Backup path should be a string."""
        mq5 = source_dir / "strategy.mq5"
        with tempfile.TemporaryDirectory() as tmpdir:
            portable_target.install_path = tmpdir
            deployer.deploy_file(portable_target, str(mq5), "strategy.mq5")
            backup_path = deployer.create_backup(
                portable_target, "strategy.mq5"
            )
            assert isinstance(backup_path, str)

    def test_create_backup_content_matches_original(
        self, deployer, portable_target, source_dir
    ):
        """Backup file content should match the deployed file."""
        mq5 = source_dir / "strategy.mq5"
        with tempfile.TemporaryDirectory() as tmpdir:
            portable_target.install_path = tmpdir
            deployer.deploy_file(portable_target, str(mq5), "strategy.mq5")
            backup_path = deployer.create_backup(
                portable_target, "strategy.mq5"
            )
            assert Path(backup_path).read_text() == "void OnTick() { }"

    def test_create_backup_no_existing_file(
        self, deployer, portable_target, source_dir
    ):
        """Creating backup when file doesn't exist should raise an error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            portable_target.install_path = tmpdir
            with pytest.raises(FileNotFoundError):
                deployer.create_backup(portable_target, "nonexistent.mq5")

    def test_create_backup_multiple_backups_unique_names(
        self, deployer, portable_target, source_dir
    ):
        """Multiple backups should produce unique filenames."""
        mq5 = source_dir / "strategy.mq5"
        with tempfile.TemporaryDirectory() as tmpdir:
            portable_target.install_path = tmpdir
            deployer.deploy_file(portable_target, str(mq5), "strategy.mq5")
            backup1 = deployer.create_backup(
                portable_target, "strategy.mq5"
            )
            backup2 = deployer.create_backup(
                portable_target, "strategy.mq5"
            )
            assert backup1 != backup2
            assert os.path.isfile(backup1)
            assert os.path.isfile(backup2)
