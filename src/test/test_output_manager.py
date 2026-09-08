"""
Unit tests for Output Manager.

This module contains comprehensive tests for the OutputManager class,
including:
- Directory creation in correct location
- Directory naming conventions
- Subdirectories creation
- File path generation
"""

import pytest
import os
import time
import re
from pathlib import Path
from unittest.mock import patch

# Import the module
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from local_read.output_manager import OutputManager


class TestOutputManager:
    """Tests for OutputManager class."""

    def test_output_dir_creation(self, tmp_path):
        """Test that output directory is created in the correct location."""
        # Create a temporary input file
        input_file = tmp_path / "test_document.pdf"
        input_file.touch()

        # Initialize OutputManager with tmp_path as base
        manager = OutputManager(base_dir=tmp_path)

        # Create output directory
        output_dir = manager.create_output_dir(str(input_file))

        # Verify the directory was created
        assert output_dir.exists()
        assert output_dir.is_dir()

        # Verify it's under .local_read
        assert output_dir.parent.name == ".local_read_mcp"
        assert output_dir.parent.parent == tmp_path

    def test_output_dir_naming(self, tmp_path):
        """Test that output directory follows naming convention."""
        # Mock time to have predictable timestamp
        fixed_time = time.mktime(time.strptime("2026-04-10 14:30:45", "%Y-%m-%d %H:%M:%S"))
        fixed_struct_time = time.localtime(fixed_time)

        with patch('time.localtime', return_value=fixed_struct_time):
            manager = OutputManager(base_dir=tmp_path)

            # Test with normal filename
            input_file = tmp_path / "my_report.pdf"
            output_dir = manager.create_output_dir(str(input_file))

            # Check directory name format: safe_filename_timestamp
            dir_name = output_dir.name
            expected_timestamp = "20260410_143045"
            assert f"_{expected_timestamp}_" in dir_name
            assert dir_name.startswith("my_report_")

            # Test with filename containing special characters
            input_file2 = tmp_path / "my report 2026!@#$%^&*().pdf"
            output_dir2 = manager.create_output_dir(str(input_file2))

            dir_name2 = output_dir2.name
            # Special characters should be replaced with _
            assert "my_report_2026__________" in dir_name2

    def test_repeated_input_has_independent_output(self, tmp_path):
        manager = OutputManager(base_dir=tmp_path)
        first = manager.create_output_dir("same.pdf")
        second = manager.create_output_dir("same.pdf")
        assert first != second
        (first / "output.md").write_text("first run")
        assert not (second / "output.md").exists()

    def test_subdirectories_creation(self, tmp_path):
        """Test that images subdirectory is created."""
        manager = OutputManager(base_dir=tmp_path)
        input_file = tmp_path / "test.pdf"
        output_dir = manager.create_output_dir(str(input_file))

        # Check that images directory exists
        images_dir = output_dir / "images"
        assert images_dir.exists()
        assert images_dir.is_dir()

    def test_get_file_path(self, tmp_path):
        """Test that get_output_path returns correct path."""
        manager = OutputManager(base_dir=tmp_path)
        input_file = tmp_path / "test.pdf"
        output_dir = manager.create_output_dir(str(input_file))

        # Test getting a file path
        file_path = manager.get_output_path(output_dir, "result.json")
        expected_path = output_dir / "result.json"
        assert file_path == expected_path

        # Test with subdirectory
        file_path2 = manager.get_output_path(output_dir, "images/page1.png")
        expected_path2 = output_dir / "images" / "page1.png"
        assert file_path2 == expected_path2

    def test_default_base_dir(self, monkeypatch, tmp_path):
        """Test that default base dir is current working directory."""
        # Change working directory to tmp_path
        monkeypatch.chdir(tmp_path)

        manager = OutputManager()
        input_file = tmp_path / "test.pdf"
        output_dir = manager.create_output_dir(str(input_file))

        # Verify .local_read is in current working directory
        assert output_dir.parent.parent == tmp_path


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
