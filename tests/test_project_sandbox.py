"""Contract tests for the isolated Work project sandbox."""
import asyncio
from types import SimpleNamespace

import pytest

from llink_api.services.project_sandbox import (
    ProjectSandboxSession,
    is_sensitive_project_path,
    safe_project_path,
)


def test_project_paths_are_relative_and_sensitive_files_are_excluded():
    assert safe_project_path("src/main.py") == "src/main.py"
    assert is_sensitive_project_path(".env")
    assert is_sensitive_project_path("certs/private.key")
    assert is_sensitive_project_path("src/service-account.json")
    assert is_sensitive_project_path("node_modules/package/index.js") is True
    assert is_sensitive_project_path("src/app.py") is False

    for path in ("../secret.txt", "/etc/passwd", "src/../../secret", "", "src//main.py"):
        with pytest.raises(ValueError):
            safe_project_path(path)


def test_project_run_returns_real_nonzero_exit_code_as_recoverable_result():
    class FakeCommands:
        def run(self, command, cwd, timeout, request_timeout):
            assert command == "python -m pytest -q"
            assert cwd == "/tmp/llink-workspace"
            return SimpleNamespace(exit_code=2, stdout="2 tests failed", stderr="AssertionError")

    async def run():
        session = ProjectSandboxSession(
            session_id="sandbox-session-123",
            sandbox=SimpleNamespace(commands=FakeCommands()),
            project_id="work-project",
            original_files={},
            allow_internet_access=False,
        )
        result = await session.run_command("python -m pytest -q", timeout_seconds=30)
        assert result["executed"] is True
        assert result["exit_code"] == 2
        assert result["passed"] is False
        assert "2 tests failed" in result["stdout"]
        assert "AssertionError" in result["stderr"]
        assert result["network_access"] == "disabled"

        with pytest.raises(ValueError, match="bloquée"):
            await session.run_command("sudo reboot")

    asyncio.run(run())


def test_closed_project_sandbox_rejects_further_commands():
    async def run():
        session = ProjectSandboxSession(
            session_id="sandbox-session-456",
            sandbox=SimpleNamespace(),
            project_id="work-project",
            original_files={},
            allow_internet_access=False,
            closed=True,
        )
        with pytest.raises(ValueError, match="fermé"):
            await session.run_command("python -V")

    asyncio.run(run())
