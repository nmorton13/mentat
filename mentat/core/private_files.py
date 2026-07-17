"""Helpers for creating files that may contain private user data."""

import os
from pathlib import Path
from typing import IO, Union

PathLike = Union[str, os.PathLike[str]]


def ensure_private_directory(path: PathLike) -> Path:
    """Create a directory and ensure only its owner can access it."""
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    return directory


def open_private_text(path: PathLike, mode: str = "w", *, encoding: str = "utf-8") -> IO[str]:
    """Open a text file and enforce owner-only permissions on its inode."""
    if mode not in {"w", "a"}:
        raise ValueError("private text files may only be opened for writing or appending")
    flags = os.O_WRONLY | os.O_CREAT
    flags |= os.O_TRUNC if mode == "w" else os.O_APPEND
    fd = os.open(os.fspath(path), flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        return os.fdopen(fd, mode, encoding=encoding)
    except Exception:
        os.close(fd)
        raise


def create_private_file(path: PathLike) -> None:
    """Create (or tighten) a file without changing its contents."""
    fd = os.open(os.fspath(path), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
