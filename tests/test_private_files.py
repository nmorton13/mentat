"""Regression tests for owner-only sensitive outputs."""

import stat

from mentat.chat.session_store import ChatSessionStore
from mentat.core.private_files import ensure_private_directory, open_private_text


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_private_helpers_override_permissive_umask(tmp_path):
    directory = tmp_path / "private"
    old_umask = __import__("os").umask(0)
    try:
        ensure_private_directory(directory)
        file_path = directory / "sensitive.txt"
        with open_private_text(file_path) as file:
            file.write("secret")
    finally:
        __import__("os").umask(old_umask)

    assert _mode(directory) == 0o700
    assert _mode(file_path) == 0o600


def test_private_helpers_tighten_existing_paths(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o755)
    file_path = directory / "sensitive.txt"
    file_path.write_text("old secret", encoding="utf-8")
    file_path.chmod(0o644)

    ensure_private_directory(directory)
    with open_private_text(file_path) as file:
        file.write("new secret")

    assert _mode(directory) == 0o700
    assert _mode(file_path) == 0o600


def test_session_database_is_private(tmp_path):
    db_path = tmp_path / "sessions" / "chat.db"
    ChatSessionStore(db_path=str(db_path))

    assert _mode(db_path.parent) == 0o700
    assert _mode(db_path) == 0o600
