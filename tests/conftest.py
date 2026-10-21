import pytest


@pytest.fixture(autouse=True)
def _isolated_profile_locks(tmp_path, monkeypatch):
    """Keep per-profile lock files out of the real ~/.gemini-web-mcp-cli."""
    from gemini_web_mcp_cli.core import locks

    lock_dir = tmp_path / "locks"
    monkeypatch.setattr(locks, "_lock_path", lambda name: lock_dir / f"{name}.lock")
