import os
import subprocess
import pytest
from pathlib import Path

# Define the root directory of the project
PROJECT_ROOT = Path(__file__).parent.parent
SOURCE_DIR = PROJECT_ROOT / "mentat"
LLM_WRAPPER = SOURCE_DIR / "core" / "llm.py"

def test_chat_completion_calls_stay_inside_llm_wrapper():
    """Feature code should use mentat.core.llm instead of direct chat completions."""
    offenders = []
    for path in SOURCE_DIR.rglob("*.py"):
        if path == LLM_WRAPPER:
            continue
        text = path.read_text(encoding="utf-8")
        if "chat.completions.create" in text:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []


def test_llm_wrapper_contains_the_only_direct_chat_completion_call():
    """Keep the static guard honest by ensuring the wrapper owns the raw call."""
    text = LLM_WRAPPER.read_text(encoding="utf-8")

    assert "chat.completions.create" in text


def test_no_unbound_local_errors():
    """
    Run pylint specifically checking for 'used-before-assignment' (E0601).
    This catches UnboundLocalError risks in source modules.
    """
    if not SOURCE_DIR.exists():
        pytest.skip(f"Source directory {SOURCE_DIR} not found")

    # E0601 is the code for "used-before-assignment"
    # We use --disable=all --enable=E0601 to ONLY check for this specific error
    cmd = [
        "pylint",
        "--disable=all",
        "--enable=E0601",
        "--score=n",
        str(SOURCE_DIR)
    ]

    try:
        # Run pylint
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False  # Don't raise exception on non-zero exit code immediately
        )
        
        # Pylint exit codes:
        # 0: No error
        # 1: Fatal error
        # 2: Error
        # 4: Warning
        # 8: Refactor
        # 16: Convention
        # 32: Usage error
        
        # We only care if it found errors (bit 1 set, i.e. return code has 2)
        if result.returncode & 2:
            pytest.fail(f"Pylint found UnboundLocalError risks:\n{result.stdout}")
            
    except FileNotFoundError:
        pytest.skip("pylint executable not found. Please run 'uv pip install pylint'")
