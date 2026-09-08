"""
Output Directory Manager for Local_Read.

This module provides the OutputManager class for managing output directories
where processing results are stored.
"""

import re
import time
from uuid import uuid4
from pathlib import Path
from typing import Optional


class OutputManager:
    """Manages output directories for storing processing results."""

    def __init__(self, base_dir: Optional[Path] = None):
        """
        Initialize OutputManager.

        Args:
            base_dir: Base directory where .local_read will be created.
                      If None, uses current working directory.
        """
        if base_dir is None:
            self.base_dir = Path.cwd()
        else:
            self.base_dir = Path(base_dir)

        self.root_output_dir = self.base_dir / ".local_read_mcp"

    def create_output_dir(self, input_path: str) -> Path:
        """
        Create an output directory for the given input file.

        The directory name is .local_read_mcp/<safe_filename>_<timestamp>_<id>/
        where:
        - safe_filename: input filename without extension, non-alphanumeric
                        characters replaced with _
        - timestamp: YYYYMMDD_HHMMSS format

        Also creates an 'images' subdirectory within the output directory.

        Args:
            input_path: Path to the input file.

        Returns:
            Path object pointing to the created output directory.
        """
        input_path_obj = Path(input_path)

        # Get filename without extension
        filename = input_path_obj.stem

        # Create safe filename - replace non-alphanumeric characters with _
        safe_filename = re.sub(r"[^a-zA-Z0-9_-]", "_", filename)

        # Generate timestamp
        timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())

        # Create directory name
        dir_name = f"{safe_filename}_{timestamp}_{uuid4().hex[:12]}"

        # Full output directory path
        output_dir = self.root_output_dir / dir_name

        # Create directories
        output_dir.mkdir(parents=True, exist_ok=False)

        # Create images subdirectory
        images_dir = output_dir / "images"
        images_dir.mkdir(exist_ok=True)

        return output_dir

    def get_output_path(self, output_dir: Path, filename: str) -> Path:
        """
        Get the full path for a file in the output directory.

        Args:
            output_dir: The output directory Path object.
            filename: The filename (can include subdirectories).

        Returns:
            Full Path object for the file.
        """
        return output_dir / filename
