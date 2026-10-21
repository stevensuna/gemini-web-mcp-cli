"""Unknown chat models fail locally without authentication or file uploads."""

from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from gemini_web_mcp_cli.cli import cli


@pytest.mark.parametrize("args", [
    ["chat", "analyze", "-m", "gemini-9-flash", "-f", "missing.mp4"],
    ["chat", "-m", "gemini-9-flash"],
    ["research", "query", "-m", "gemini-9-flash"],
    ["image", "prompt", "-m", "gemini-9-flash"],
    ["video", "prompt", "-m", "gemini-9-flash"],
    ["music", "prompt", "-m", "gemini-9-flash"],
])
def test_unknown_model_is_a_clean_error_before_client_creation(monkeypatch, args):
    client = MagicMock(side_effect=AssertionError("must not authenticate"))
    monkeypatch.setattr("gemini_web_mcp_cli.cli.GeminiClient", client)
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 1
    assert "Unknown model:" in result.output
    assert "Available:" in result.output
    assert "Traceback" not in result.output
    client.assert_not_called()


def test_bad_configured_default_model_is_also_validated(monkeypatch):
    manager = MagicMock()
    manager._read_config.return_value = {"default_model": "not-a-model"}
    monkeypatch.setattr("gemini_web_mcp_cli.cli.ProfileManager", lambda: manager)
    single = MagicMock()
    monkeypatch.setattr("gemini_web_mcp_cli.cli._chat_single", single)
    result = CliRunner().invoke(cli, ["chat", "hello"])
    assert result.exit_code == 1
    assert "Unknown model:" in result.output
    single.assert_not_called()


@pytest.mark.parametrize(
    "model", ["flash", "gemini-3.7-flash", "gemini-3.8-flash", "gemini-4-argon", "pro"]
)
def test_valid_models_keep_the_existing_chat_route(monkeypatch, model):
    single = MagicMock()
    monkeypatch.setattr("gemini_web_mcp_cli.cli._chat_single", single)
    result = CliRunner().invoke(cli, ["chat", "hello", "-m", model])
    assert result.exit_code == 0
    single.assert_called_once()
    assert single.call_args.args[2] == model


@pytest.mark.parametrize("args", [
    ["music", "--list-styles"],
    ["music", "--list-styles", "-m", "gemini-3.8-flash"],
])
def test_list_styles_short_circuits_before_model_validation(monkeypatch, args):
    """--list-styles lists the presets and exits without touching auth or models."""
    client = MagicMock(side_effect=AssertionError("must not authenticate"))
    monkeypatch.setattr("gemini_web_mcp_cli.cli.GeminiClient", client)
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 0
    assert "Available music style presets" in result.output
    assert "Unknown model" not in result.output
    client.assert_not_called()
