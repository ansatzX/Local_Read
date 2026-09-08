"""
Backend implementations for Local_Read.
"""

from .base import (
    BackendType,
    DocumentBackend,
    BackendRegistry,
    get_registry,
    register_simple_backend,
    register_vlm_hybrid_backend,
)

__all__ = [
    "BackendType",
    "DocumentBackend",
    "BackendRegistry",
    "get_registry",
    "register_simple_backend",
    "register_vlm_hybrid_backend",
]

# Register SimpleBackend (always available)
register_simple_backend()

# Register VlmHybridBackend (requires MinerU)
register_vlm_hybrid_backend()
