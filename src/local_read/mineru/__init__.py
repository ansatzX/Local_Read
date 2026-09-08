# Copyright (c) 2025
# This source code is licensed under MIT License.

"""
MinerU integration utilities for Local_Read.

This package provides integration with MinerU's document parsing capabilities,
including PDF classification, layout analysis, and more.
"""

from .pdf_classify import classify_pdf

__all__ = ["classify_pdf"]
