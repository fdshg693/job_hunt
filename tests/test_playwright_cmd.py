"""Tests for run_playwright_cmd and _resolve_playwright_cli."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.browser_auth import (
    _resolve_playwright_cli,
    check_playwright_cli,
    run_playwright_cmd,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    _resolve_playwright_cli.cache_clear()
    yield
    _resolve_playwright_cli.cache_clear()


def test_run_playwright_cmd_passes_arguments_without_shell():
    """Verify that subprocess.run is called with shell=False and argv preserves special characters."""
    special_url = "https://www.openwork.jp/search?keyword=Python&p=2&sort=score|pipe%percent^caret with space"
    args = ["-s=openwork", "open", special_url, "--timeout=30"]

    with patch("scripts.common.browser_auth._resolve_playwright_cli", return_value=["node", "dummy_cli.js"]):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")
            code, stdout, stderr = run_playwright_cmd(args)

            assert code == 0
            assert stdout == "OK"
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args.kwargs
            call_args = mock_run.call_args.args[0]

            # 1. shell must be False
            assert call_kwargs.get("shell") is False

            # 2. Arguments must preserve special characters in a single element without shell splitting
            assert call_args[0] == "node"
            assert call_args[1] == "dummy_cli.js"
            assert call_args[2] == "-s=openwork"
            assert call_args[3] == "open"
            assert call_args[4] == special_url
            assert call_args[5] == "--timeout=30"


def test_run_playwright_cmd_entrypoint_not_found():
    """Verify that if resolution fails, run_playwright_cmd returns -1 and error message."""
    with patch(
        "scripts.common.browser_auth._resolve_playwright_cli",
        side_effect=FileNotFoundError("playwright-cli not found in test"),
    ):
        code, stdout, stderr = run_playwright_cmd(["open", "https://example.com"])
        assert code == -1
        assert stdout == ""
        assert "playwright-cli not found in test" in stderr


def test_check_playwright_cli():
    """Verify check_playwright_cli returns bool based on _resolve_playwright_cli."""
    with patch("scripts.common.browser_auth._resolve_playwright_cli", return_value=["node", "dummy.js"]):
        assert check_playwright_cli() is True

    with patch(
        "scripts.common.browser_auth._resolve_playwright_cli",
        side_effect=FileNotFoundError("not found"),
    ):
        assert check_playwright_cli() is False


def test_resolve_with_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify PLAYWRIGHT_CLI_JS environment variable overrides resolution."""
    fake_js = tmp_path / "custom_cli.js"
    fake_js.write_text("console.log('hi');", encoding="utf-8")

    monkeypatch.setenv("PLAYWRIGHT_CLI_JS", str(fake_js))
    res = _resolve_playwright_cli()
    assert len(res) == 2
    assert res[1] == str(fake_js.resolve())


def test_resolve_with_invalid_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify PLAYWRIGHT_CLI_JS pointing to non-existent file raises FileNotFoundError."""
    non_existent = tmp_path / "does_not_exist.js"
    monkeypatch.setenv("PLAYWRIGHT_CLI_JS", str(non_existent))

    with pytest.raises(FileNotFoundError, match="PLAYWRIGHT_CLI_JS points to non-existent file"):
        _resolve_playwright_cli()


def test_resolve_windows_shim_parsing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify extracting playwright-cli.js from .cmd shim on Windows."""
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    target_js = tmp_path / "lib" / "node_modules" / "@playwright" / "cli" / "playwright-cli.js"
    target_js.parent.mkdir(parents=True)
    target_js.write_text("// dummy js", encoding="utf-8")

    shim_file = shim_dir / "playwright-cli.cmd"
    # Relative path from shim_dir
    rel_path = r"..\lib\node_modules\@playwright\cli\playwright-cli.js"
    shim_content = f'@node "%~dp0\\{rel_path}" %*\n'
    shim_file.write_text(shim_content, encoding="utf-8")

    monkeypatch.delenv("PLAYWRIGHT_CLI_JS", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("shutil.which", lambda name: str(shim_file) if name == "playwright-cli" else "node.exe")

    res = _resolve_playwright_cli()
    assert len(res) == 2
    assert Path(res[1]).resolve() == target_js.resolve()


def test_run_playwright_cmd_real_execution():
    """Verify actual headless CLI execution via node + entrypoint without shell."""
    code, stdout, stderr = run_playwright_cmd(["--version"])
    assert code == 0
    assert "playwright-cli" in stdout or len(stdout.strip()) > 0

