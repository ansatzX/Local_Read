# Copyright (c) 2025
# This source code is licensed under MIT License.

"""
Caching mechanism for Local_Read.

Provides file-based caching for Intermediate JSON results to avoid
reprocessing the same files multiple times.
"""

import json
import os
import hashlib
import time
from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class CacheManager:
    """
    File-based cache manager for Intermediate JSON results.

    Uses file-based caching with configurable TTL (time-to-live).
    Cache keys are generated from file path and modification time.
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        default_ttl: int = 3600  # 1 hour default
    ):
        """
        Initialize the cache manager.

        Args:
            cache_dir: Directory to store cache files (defaults to .local_read_mcp/cache)
            default_ttl: Default time-to-live in seconds for cached items
        """
        if cache_dir is None:
            cache_dir = Path.cwd() / ".local_read_mcp" / "cache"

        self.cache_dir = Path(cache_dir)
        self.default_ttl = default_ttl

        # Create cache directory if it doesn't exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        logger.debug(f"Cache manager initialized with directory: {self.cache_dir}")

    def _get_cache_key(self, file_path: Path, backend: str = "auto") -> str:
        """
        Generate a cache key from a file path.

        The key includes:
        - File path (absolute)
        - File modification time
        - File size
        - Backend name

        Args:
            file_path: Path to the file
            backend: Name of the backend used

        Returns:
            Cache key string (SHA256 hash)
        """
        try:
            stat = file_path.stat()
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {file_path}") from None

        # Create a unique string combining all relevant attributes
        key_parts = [
            str(file_path.absolute()),
            str(stat.st_mtime),
            str(stat.st_size),
            backend
        ]

        key_string = "|".join(key_parts)

        # Hash to create a filename-safe key
        return hashlib.sha256(key_string.encode()).hexdigest()

    def _get_cache_path(self, cache_key: str) -> Path:
        """
        Get the file path for a cache key.

        Args:
            cache_key: Cache key from _get_cache_key()

        Returns:
            Path to the cache file
        """
        # Use subdirectories to avoid too many files in one directory
        subdir = cache_key[:2]
        return self.cache_dir / subdir / f"{cache_key}.json"

    def get(
        self,
        file_path: Path,
        backend: str = "auto",
        ttl: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get a cached result for a file.

        Args:
            file_path: Path to the file
            backend: Name of the backend used
            ttl: Time-to-live in seconds (overrides default)

        Returns:
            Cached Intermediate JSON dict, or None if not found or expired
        """
        if ttl is None:
            ttl = self.default_ttl

        try:
            cache_key = self._get_cache_key(file_path, backend)
            cache_path = self._get_cache_path(cache_key)

            if not cache_path.exists():
                logger.debug(f"Cache miss for: {file_path}")
                return None

            # Check if cache is expired
            cache_age = time.time() - cache_path.stat().st_mtime
            if cache_age > ttl:
                logger.debug(f"Cache expired for: {file_path} (age: {cache_age:.1f}s, ttl: {ttl}s)")
                # Delete expired cache
                try:
                    cache_path.unlink()
                except Exception:
                    pass
                return None

            # Read and parse cache
            with open(cache_path, 'r', encoding='utf-8') as f:
                result = json.load(f)

            logger.debug(f"Cache hit for: {file_path} (age: {cache_age:.1f}s)")
            return result

        except Exception as e:
            logger.debug(f"Cache read failed for {file_path}: {e}")
            return None

    def set(
        self,
        file_path: Path,
        result: Dict[str, Any],
        backend: str = "auto"
    ) -> bool:
        """
        Cache a result for a file.

        Args:
            file_path: Path to the file
            result: Intermediate JSON dict to cache
            backend: Name of the backend used

        Returns:
            True if cache was successfully written, False otherwise
        """
        try:
            cache_key = self._get_cache_key(file_path, backend)
            cache_path = self._get_cache_path(cache_key)

            # Create subdirectory if needed
            cache_path.parent.mkdir(parents=True, exist_ok=True)

            # Write to temporary file first, then rename for atomicity
            temp_path = cache_path.with_suffix(".tmp")

            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            # Atomic rename
            temp_path.rename(cache_path)

            logger.debug(f"Cache written for: {file_path}")
            return True

        except Exception as e:
            logger.debug(f"Cache write failed for {file_path}: {e}")
            # Clean up temp file if it exists
            try:
                temp_path = cache_path.with_suffix(".tmp")
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
            return False

    def invalidate(self, file_path: Path, backend: str = "auto") -> bool:
        """
        Invalidate (delete) cache for a file.

        Args:
            file_path: Path to the file
            backend: Name of the backend used

        Returns:
            True if cache was found and deleted, False otherwise
        """
        try:
            cache_key = self._get_cache_key(file_path, backend)
            cache_path = self._get_cache_path(cache_key)

            if cache_path.exists():
                cache_path.unlink()
                logger.debug(f"Cache invalidated for: {file_path}")
                return True

            return False

        except Exception as e:
            logger.debug(f"Cache invalidation failed for {file_path}: {e}")
            return False

    def clear_all(self) -> int:
        """
        Clear all cached items.

        Returns:
            Number of cache files deleted
        """
        count = 0
        try:
            for cache_file in self.cache_dir.rglob("*.json"):
                try:
                    cache_file.unlink()
                    count += 1
                except Exception:
                    pass

            # Also clean up empty subdirectories
            for subdir in self.cache_dir.iterdir():
                if subdir.is_dir() and not any(subdir.iterdir()):
                    try:
                        subdir.rmdir()
                    except Exception:
                        pass

            logger.debug(f"Cleared {count} cache files")
            return count

        except Exception as e:
            logger.debug(f"Cache clear failed: {e}")
            return count

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dict with cache statistics
        """
        total_files = 0
        total_size = 0
        oldest_time = None
        newest_time = None

        try:
            for cache_file in self.cache_dir.rglob("*.json"):
                try:
                    stat = cache_file.stat()
                    total_files += 1
                    total_size += stat.st_size

                    mtime = stat.st_mtime
                    if oldest_time is None or mtime < oldest_time:
                        oldest_time = mtime
                    if newest_time is None or mtime > newest_time:
                        newest_time = mtime

                except Exception:
                    pass

        except Exception:
            pass

        return {
            "cache_dir": str(self.cache_dir),
            "total_files": total_files,
            "total_size_bytes": total_size,
            "total_size_mb": total_size / (1024 * 1024) if total_size > 0 else 0,
            "oldest_age_seconds": time.time() - oldest_time if oldest_time else None,
            "newest_age_seconds": time.time() - newest_time if newest_time else None,
        }


# Global cache manager instance
_cache_manager: Optional[CacheManager] = None


def get_cache_manager(
    cache_dir: Optional[Path] = None,
    default_ttl: int = 3600
) -> CacheManager:
    """
    Get the global cache manager instance.

    Args:
        cache_dir: Directory to store cache files (only used on first call)
        default_ttl: Default time-to-live in seconds (only used on first call)

    Returns:
        Global CacheManager instance
    """
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager(cache_dir=cache_dir, default_ttl=default_ttl)
    return _cache_manager
