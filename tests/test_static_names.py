"""静的解析（未定義名・重複定義）回帰テスト.

ruff の F821（未定義名 / Undefined name）および F811（再定義 / Redefinition）
を常時検証し、リファクタ時の名前消失・スタブ残骸の再混入を防ぎます。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_ruff_no_undefined_or_redefined_names() -> None:
    """scripts, webui, tests 配下に F821 / F811 のエラーが 0 件であることを検証する."""
    try:
        import ruff  # noqa: F401
    except ImportError:
        pytest.skip("ruff is not installed in the current environment")

    cmd = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "scripts",
        "webui",
        "tests",
        "--select",
        "F821,F811",
        "--no-cache",
    ]
    res = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert res.returncode == 0, (
        f"ruff check F821,F811 detected errors (code {res.returncode}):\n"
        f"STDOUT:\n{res.stdout}\n"
        f"STDERR:\n{res.stderr}\n"
    )
