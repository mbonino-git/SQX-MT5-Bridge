"""MT5 Deployer: copies .mq5 files to MT5 instances.

Handles both portable and normal MT5 installations.
Portable mode: MQL5/ is under install_path.
Normal mode: MQL5/ is under data_path.
"""

import os
import shutil
from datetime import datetime
from pathlib import Path

from models import MT5Target


class Deployer:
    """Deploys .mq5 files to MT5 terminal instances.

    Resolves the Experts folder path based on whether the target
    is a portable or normal installation, then copies files there.
    """

    def get_experts_path(self, target: MT5Target) -> str:
        """Resolve the MQL5/Experts/ path for a target.

        Portable mode: install_path/MQL5/Experts/
        Normal mode:   data_path/MQL5/Experts/

        Uses pathlib for cross-platform path construction.

        Args:
            target: The MT5 installation target.

        Returns:
            Full path to the MQL5/Experts/ directory (as a string).
        """
        if target.is_portable:
            base = Path(target.install_path)
        else:
            base = Path(target.data_path)
        return str(base / "MQL5" / "Experts")

    def deploy_file(
        self, target: MT5Target, source_path: str, filename: str
    ) -> str:
        """Copy a .mq5 file to the target's Experts folder.

        Creates the Experts directory if it doesn't exist.

        Args:
            target: The MT5 installation target.
            source_path: Absolute path to the source .mq5 file.
            filename: Destination filename (e.g. "MyEA.mq5").

        Returns:
            Full path to the deployed file.
        """
        experts_path = Path(self.get_experts_path(target))
        experts_path.mkdir(parents=True, exist_ok=True)
        dest = experts_path / filename
        shutil.copy2(source_path, str(dest))
        return str(dest)

    def create_backup(self, target: MT5Target, filename: str) -> str:
        """Create a timestamped backup of an existing file in the Experts folder.

        The backup is saved alongside the original file with a timestamp suffix,
        e.g. "MyEA_20260919_143052.mq5". Uses microseconds to guarantee
        uniqueness even when called rapidly.

        Args:
            target: The MT5 installation target.
            filename: Name of the file to back up (e.g. "MyEA.mq5").

        Returns:
            Full path to the backup file.

        Raises:
            FileNotFoundError: If the source file does not exist.
        """
        experts_path = Path(self.get_experts_path(target))
        source = experts_path / filename
        if not source.is_file():
            raise FileNotFoundError(f"Cannot backup: file not found at {source}")
        # Build timestamped backup name with microseconds for uniqueness
        stem = source.stem
        ext = source.suffix
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_name = f"{stem}_{timestamp}{ext}"
        backup_path = experts_path / backup_name
        shutil.copy2(str(source), str(backup_path))
        return str(backup_path)
