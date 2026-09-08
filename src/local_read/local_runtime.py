"""User-shared model caches and a Python-level offline execution boundary."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import platform
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


@contextmanager
def file_lock(path: Path, timeout: float = 120):
    """Process lock released by the OS on exit; retain the stable lock inode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()

            def acquire():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

            def release():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def acquire():
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            def release():
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

        deadline = time.monotonic() + timeout
        while True:
            try:
                acquire()
                break
            except (BlockingIOError, PermissionError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for Local_Read lock: {path}")
                time.sleep(0.05)
        try:
            yield
        finally:
            release()


def runtime_root() -> Path:
    configured = os.environ.get("LOCAL_READ_RUNTIME_DIR")
    root = Path(configured).expanduser() if configured else Path.home() / ".cache/local-read/runtime"
    if not root.is_absolute():
        raise ValueError("LOCAL_READ_RUNTIME_DIR must be an absolute path")
    return root.resolve()


def runtime_path(skill_root: Path) -> Path:
    """Identical skill releases share an environment independent of install/cwd."""
    digest = hashlib.sha256()
    digest.update(f"{platform.system()}:{platform.machine()}".encode())
    inputs = [skill_root / "pyproject.toml", skill_root / "uv.lock"]
    inputs += sorted((skill_root / "src/local_read").rglob("*.py"))
    for path in inputs:
        digest.update(path.relative_to(skill_root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
    return runtime_root() / digest.hexdigest()[:24]


def model_root() -> Path:
    """Use one model store across workspaces, with an explicit disk override."""
    configured = os.environ.get("LOCAL_READ_MODEL_DIR")
    root = Path(configured).expanduser() if configured else Path.home() / ".cache/local-read/models"
    if not root.is_absolute():
        raise ValueError("LOCAL_READ_MODEL_DIR must be an absolute path")
    return root.resolve()


def cache_environment() -> dict[str, str]:
    root = model_root()
    return {
        "HF_HOME": str(root / "huggingface"),
        "HF_HUB_CACHE": str(root / "huggingface/hub"),
        "MODELSCOPE_CACHE": str(root / "modelscope"),
        "TORCH_HOME": str(root / "torch"),
        "XDG_CACHE_HOME": str(root / "cache"),
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "DO_NOT_TRACK": "1",
    }


def _loopback(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="replace")
    if host in (None, "localhost"):
        return True
    try:
        return ipaddress.ip_address(str(host).split("%", 1)[0]).is_loopback
    except ValueError:
        return False


@contextmanager
def offline_execution(extra_env: dict[str, str] | None = None):
    """Block Python outbound sockets and model downloads for this CLI process.

    Loopback/Unix sockets remain usable by local inference engines. This is not
    an OS sandbox for native libraries or child processes.
    """
    env = (
        cache_environment()
        | {
            "MINERU_MODEL_SOURCE": "local",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
        | (extra_env or {})
    )
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    getaddrinfo = socket.getaddrinfo
    sendto = socket.socket.sendto

    def check(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and not _loopback(
            address[0]
        ):
            raise RuntimeError(
                "Offline document processing blocked an outbound connection"
            )

    def guarded_connect(sock, address):
        check(sock, address)
        return connect(sock, address)

    def guarded_connect_ex(sock, address):
        check(sock, address)
        return connect_ex(sock, address)

    def guarded_sendto(sock, data, *args):
        check(sock, args[-1])
        return sendto(sock, data, *args)

    def guarded_lookup(host, *args, **kwargs):
        if not _loopback(host):
            raise RuntimeError(
                "Offline document processing blocked an external DNS lookup"
            )
        return getaddrinfo(host, *args, **kwargs)

    with (
        patch.dict(os.environ, env),
        patch.object(socket.socket, "connect", guarded_connect),
        patch.object(socket.socket, "connect_ex", guarded_connect_ex),
        patch.object(socket.socket, "sendto", guarded_sendto),
        patch.object(socket, "getaddrinfo", guarded_lookup),
    ):
        yield
