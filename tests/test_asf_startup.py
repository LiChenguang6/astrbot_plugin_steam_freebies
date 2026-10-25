"""ASF startup regression tests: Synology Docker, empty bot config, safe errors."""
import asyncio
import errno

import pytest

from steam_freebies.manager import ManagedASF, diagnose_start_failure


def test_start_failure_diagnostic_hints_do_not_leak_raw_credentials():
    secret = "SteamPassword=highly_secret_value"
    result = diagnose_start_failure(f"Process crashed\\nFailed to load system ICU\\n{secret}", 1)
    assert "libicu" in result
    assert secret not in result
    assert "SteamPassword" not in result
    assert "libssl" in diagnose_start_failure("Cannot load libssl.so.3", 1)
    assert "权限" in diagnose_start_failure(error=PermissionError(errno.EACCES, "Access denied"))
    assert "架构" in diagnose_start_failure("exec format error", 8)


def test_managed_asf_starts_with_process_required_without_bot(tmp_path, monkeypatch):
    manager = ManagedASF(tmp_path)
    manager.path.mkdir()
    manager.binary().write_bytes(b"fake elf")
    observed = {}

    class FakeProcess:
        returncode = None

    async def spawn(*args, **kwargs):
        observed["args"] = args
        observed["kwargs"] = kwargs
        return FakeProcess()

    async def fast_sleep(_):
        pass

    monkeypatch.setattr("steam_freebies.manager.asyncio.create_subprocess_exec", spawn)
    monkeypatch.setattr("steam_freebies.manager.asyncio.sleep", fast_sleep)
    asyncio.run(manager.start())
    assert observed["args"][1:] == ("--no-restart", "--process-required")
    assert manager.running()
    assert manager.status()["start_error"] == ""
    manager.log_handle.close()
    manager.log_handle = None


def test_immediate_exit_classifies_and_closes_handles(tmp_path, monkeypatch):
    manager = ManagedASF(tmp_path)
    manager.path.mkdir()
    manager.binary().write_bytes(b"fake elf")

    class DeadProcess:
        returncode = 1

    async def spawn(*args, **kwargs):
        with (tmp_path / "asf.log").open("ab") as log:
            log.write(b"Failed to load system ICU: libicu.so missing\\n")
        return DeadProcess()

    async def fast_sleep(_):
        pass

    monkeypatch.setattr("steam_freebies.manager.asyncio.create_subprocess_exec", spawn)
    monkeypatch.setattr("steam_freebies.manager.asyncio.sleep", fast_sleep)
    with pytest.raises(RuntimeError, match="ICU"):
        asyncio.run(manager.start())
    assert "libicu" in manager.status()["start_error"]
    assert manager.status()["last_exit_code"] == 1
    assert manager.log_handle is None
    assert manager.process is None


def test_subprocess_os_error_is_actionable(tmp_path, monkeypatch):
    manager = ManagedASF(tmp_path)
    manager.path.mkdir()
    manager.binary().write_bytes(b"fake elf")

    async def spawn(*args, **kwargs):
        raise PermissionError(errno.EACCES, "Permission denied", args[0])

    monkeypatch.setattr("steam_freebies.manager.asyncio.create_subprocess_exec", spawn)
    with pytest.raises(RuntimeError, match="权限"):
        asyncio.run(manager.start())
    assert manager.process is None
    assert manager.log_handle is None
