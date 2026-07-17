"""
Shared utilities for file operation tools.

Provides path validation and safety checks to ensure file operations
are restricted to allowed directories.
"""

import os
from pathlib import Path
from typing import List, Optional, Tuple

# Directories the agent can read/write (relative to project root)
ALLOWED_DIRECTORIES: List[str] = [
    "data/",
    "docs/",
    "tmp/",
    "exports/",
]

# Exact file paths the non-coding tools may access.
ALLOWED_EXACT_PATHS: List[str] = []

# Maximum file size for read/write operations (1MB)
MAX_FILE_SIZE: int = 1024 * 1024

# File extensions that are blocked for security
BLOCKED_EXTENSIONS: set = {
    ".env",
    ".pem",
    ".key",
    ".secret",
    ".credentials",
    ".p12",
    ".pfx",
}

# Get project root (two levels up from this file: tools/ -> chat/ -> mentat/ -> project)
_THIS_DIR = Path(__file__).parent
PROJECT_ROOT = _THIS_DIR.parent.parent.parent


# Common absolute prefixes that LLMs hallucinate.
# Order matters: longer prefixes first so we strip the most specific match.
_HALLUCINATED_PREFIXES = [
    "/workspace/",
    "/home/user/",
    "/home/ubuntu/",
    "/root/",
    "/tmp/project/",
    "/app/",
    "/src/",
]


def normalize_path(path: str) -> str:
    """
    Strip common LLM-hallucinated absolute prefixes and return a clean
    relative path.  Idempotent — already-relative paths pass through
    unchanged.
    """
    if not path:
        return path
    cleaned = path.strip()
    for prefix in _HALLUCINATED_PREFIXES:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    return cleaned


def validate_path(
    path: str,
    allowed_directories: Optional[List[str]] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Validate a file path for safety.
    
    Checks:
    - Not empty
    - Not absolute
    - No parent traversal (..)
    - In allowed directory
    - Not a blocked extension
    - Not under .git
    
    Args:
        path: The relative path to validate
        allowed_directories: Optional list of allowed directory prefixes
        
    Returns:
        Tuple of (is_valid, error_message)
        If valid, error_message is None
    """
    # Check for empty path
    if not path or not path.strip():
        return False, "Path cannot be empty"
    
    # Strip hallucinated prefixes before any other checks
    path = normalize_path(path)
    
    # No absolute paths
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        return False, "Absolute paths are not allowed"
    
    # No parent directory traversal
    if ".." in path:
        return False, "Path traversal (..) is not allowed"
    
    # Allow exact paths explicitly (for narrow exceptions)
    if path in ALLOWED_EXACT_PATHS:
        path_obj = Path(path)

        # Block .git paths explicitly
        if ".git" in path_obj.parts:
            return False, "Paths under .git are not allowed"

        # Check for blocked extensions
        ext = path_obj.suffix.lower()
        if ext in BLOCKED_EXTENSIONS:
            return False, f"File extension {ext} is not allowed for security reasons"

        # Also check if filename starts with a dot (hidden files like .env)
        if path_obj.name.startswith("."):
            return False, "Hidden files (starting with .) are not allowed"

        return True, None

    # Must start with an allowed directory
    allowed = allowed_directories or ALLOWED_DIRECTORIES
    in_allowed = any(path.startswith(d) for d in allowed)
    if not in_allowed:
        allowed_list = ", ".join(allowed)
        exact_list = ", ".join(ALLOWED_EXACT_PATHS)
        return False, (
            "Path must be in an allowed directory "
            f"({allowed_list}) or match an allowed exact path ({exact_list})"
        )
    
    path_obj = Path(path)

    # Block .git paths explicitly
    if ".git" in path_obj.parts:
        return False, "Paths under .git are not allowed"
    
    # Check for blocked extensions
    ext = path_obj.suffix.lower()
    if ext in BLOCKED_EXTENSIONS:
        return False, f"File extension {ext} is not allowed for security reasons"
    
    # Also check if filename starts with a dot (hidden files like .env)
    if path_obj.name.startswith("."):
        return False, "Hidden files (starting with .) are not allowed"
    
    return True, None


def get_safe_absolute_path(relative_path: str) -> Optional[Path]:
    """
    Convert a relative path to a safe absolute path.
    
    Resolves the path and ensures it stays within the project root.
    
    Args:
        relative_path: Path relative to project root
        
    Returns:
        Absolute Path object, or None if path escapes project root
    """
    try:
        # Resolve to absolute path
        full_path = (PROJECT_ROOT / relative_path).resolve()
        
        # Ensure it's still under project root
        project_root_resolved = PROJECT_ROOT.resolve()
        if not str(full_path).startswith(str(project_root_resolved)):
            return None
        
        return full_path
    except Exception:
        return None


def ensure_parent_dirs(path: Path) -> None:
    """Create parent directories if they don't exist."""
    path.parent.mkdir(parents=True, exist_ok=True)


def get_file_size(path: Path) -> int:
    """Get file size in bytes, or 0 if file doesn't exist."""
    try:
        return path.stat().st_size if path.exists() else 0
    except OSError:
        return 0
