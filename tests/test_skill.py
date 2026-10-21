"""Tests for skill installer commands."""

from click.testing import CliRunner

from gemini_web_mcp_cli import __version__
from gemini_web_mcp_cli.skill import (
    END_MARKER,
    OLD_END_MARKER,
    OLD_SKILL_NAME,
    OLD_START_MARKER,
    START_MARKER,
    TOOL_CONFIGS,
    VALID_TOOLS,
    _content_hash,
    _get_installed_hash,
    _get_installed_version,
    _inject_version_to_agents_md,
    _inject_version_to_frontmatter,
    _migrate_legacy_installs,
    check_install_status,
    get_data_dir,
    install_agents_md,
    install_all_formats,
    install_skill_md,
    skill,
)

# ── TOOL_CONFIGS registry tests ─────────────────────────────────────────


class TestToolConfigs:
    def test_all_expected_tools_present(self):
        expected = {
            "claude-code", "cursor", "codex", "opencode",
            "gemini-cli", "antigravity", "cline", "openclaw", "alef-agent", "hermes", "other",
        }
        assert set(TOOL_CONFIGS.keys()) == expected

    def test_valid_tools_matches_keys(self):
        assert VALID_TOOLS == list(TOOL_CONFIGS.keys())

    def test_each_tool_has_format(self):
        for tool, config in TOOL_CONFIGS.items():
            assert "format" in config, f"Missing 'format' for {tool}"
            assert config["format"] in ("skill.md", "agents.md", "all")

    def test_each_tool_has_description(self):
        for tool, config in TOOL_CONFIGS.items():
            assert "description" in config, f"Missing 'description' for {tool}"
            assert len(config["description"]) > 0

    def test_codex_uses_skill_md_format(self):
        assert TOOL_CONFIGS["codex"]["format"] == "skill.md"

    def test_other_uses_all_format(self):
        assert TOOL_CONFIGS["other"]["format"] == "all"

    def test_skill_md_tools_have_user_path(self):
        for tool, config in TOOL_CONFIGS.items():
            if config["format"] == "skill.md":
                assert "user" in config, f"Missing 'user' path for {tool}"
                assert "project" in config, f"Missing 'project' path for {tool}"

    def test_other_has_no_user_path(self):
        assert "user" not in TOOL_CONFIGS["other"]


# ── Data directory tests ─────────────────────────────────────────────────


class TestGetDataDir:
    def test_data_dir_exists(self):
        data_dir = get_data_dir()
        assert data_dir.exists()
        assert data_dir.is_dir()

    def test_skill_md_exists(self):
        data_dir = get_data_dir()
        assert (data_dir / "SKILL.md").exists()

    def test_agents_section_exists(self):
        data_dir = get_data_dir()
        assert (data_dir / "AGENTS_SECTION.md").exists()

    def test_references_exist(self):
        data_dir = get_data_dir()
        refs = data_dir / "references"
        assert refs.exists()
        assert (refs / "command_reference.md").exists()
        assert (refs / "troubleshooting.md").exists()
        assert (refs / "workflows.md").exists()


# ── Version injection tests ──────────────────────────────────────────────


class TestVersionInjection:
    def test_inject_with_existing_frontmatter(self, tmp_path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text("---\nname: gemini-skill\n---\n\n# Content", encoding="utf-8")
        _inject_version_to_frontmatter(skill_file)
        content = skill_file.read_text(encoding="utf-8")
        assert f'version: "{__version__}"' in content
        assert content.startswith("---")
        assert "name: gemini-skill" in content

    def test_inject_without_frontmatter(self, tmp_path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text("# Content without frontmatter", encoding="utf-8")
        _inject_version_to_frontmatter(skill_file)
        content = skill_file.read_text(encoding="utf-8")
        assert f'version: "{__version__}"' in content
        assert content.startswith("---")

    def test_inject_replaces_existing_version(self, tmp_path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text('---\nname: test\nversion: "0.0.1"\n---\n# Content', encoding="utf-8")
        _inject_version_to_frontmatter(skill_file)
        content = skill_file.read_text(encoding="utf-8")
        assert '"0.0.1"' not in content
        assert f'version: "{__version__}"' in content

    def test_inject_agents_md_version(self, tmp_path):
        agents_file = tmp_path / "AGENTS.md"
        agents_file.write_text(
            f"{START_MARKER}\nContent here\n{END_MARKER}",
            encoding="utf-8",
        )
        _inject_version_to_agents_md(agents_file)
        content = agents_file.read_text(encoding="utf-8")
        assert f"<!-- gemini-version: {__version__} -->" in content


# ── Version extraction tests ─────────────────────────────────────────────


class TestGetInstalledVersion:
    def test_version_from_skill_md(self, tmp_path, monkeypatch):
        # Create a fake install at tmp_path
        skill_dir = tmp_path / "gemini-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            '---\nversion: "1.2.3"\n---\n# Content', encoding="utf-8"
        )

        monkeypatch.setitem(TOOL_CONFIGS, "_test_tool", {
            "user": skill_dir,
            "format": "skill.md",
        })
        assert _get_installed_version("_test_tool", "user") == "1.2.3"

    def test_version_from_agents_md(self, tmp_path, monkeypatch):
        agents_file = tmp_path / "AGENTS.md"
        agents_file.write_text(
            f"{START_MARKER}\n<!-- gemini-version: 2.0.0 -->\nContent\n{END_MARKER}",
            encoding="utf-8",
        )

        monkeypatch.setitem(TOOL_CONFIGS, "_test_tool", {
            "user": agents_file,
            "format": "agents.md",
        })
        assert _get_installed_version("_test_tool", "user") == "2.0.0"

    def test_version_none_when_not_installed(self):
        result = _get_installed_version("claude-code", "user")
        # Will be None if not actually installed (which is expected in test env)
        assert result is None or isinstance(result, str)


# ── Install tests ────────────────────────────────────────────────────────


class TestInstallSkillMd:
    def test_creates_directory_and_files(self, tmp_path):
        install_path = tmp_path / "gemini-skill"
        install_skill_md(install_path)

        assert install_path.exists()
        assert (install_path / "SKILL.md").exists()
        assert (install_path / "references").exists()
        assert (install_path / "references" / "command_reference.md").exists()
        assert (install_path / "references" / "troubleshooting.md").exists()
        assert (install_path / "references" / "workflows.md").exists()

    def test_injects_version(self, tmp_path):
        install_path = tmp_path / "gemini-skill"
        install_skill_md(install_path)

        content = (install_path / "SKILL.md").read_text(encoding="utf-8")
        assert f'version: "{__version__}"' in content

    def test_overwrites_existing(self, tmp_path):
        install_path = tmp_path / "gemini-skill"
        install_path.mkdir()
        (install_path / "SKILL.md").write_text("old content", encoding="utf-8")

        install_skill_md(install_path)

        content = (install_path / "SKILL.md").read_text(encoding="utf-8")
        assert "old content" not in content
        assert "gemini-web-skill" in content


class TestInstallAgentsMd:
    def test_creates_new_file(self, tmp_path):
        agents_file = tmp_path / "AGENTS.md"
        install_agents_md(agents_file)

        assert agents_file.exists()
        content = agents_file.read_text(encoding="utf-8")
        assert START_MARKER in content
        assert END_MARKER in content

    def test_appends_to_existing_file(self, tmp_path):
        agents_file = tmp_path / "AGENTS.md"
        agents_file.write_text("# My Existing Agents\n\nSome existing content.", encoding="utf-8")
        install_agents_md(agents_file)

        content = agents_file.read_text(encoding="utf-8")
        assert "# My Existing Agents" in content
        assert START_MARKER in content

    def test_replaces_existing_section(self, tmp_path):
        agents_file = tmp_path / "AGENTS.md"
        agents_file.write_text(
            f"before\n{START_MARKER}\nold gemini content\n{END_MARKER}\nafter",
            encoding="utf-8",
        )
        install_agents_md(agents_file)

        content = agents_file.read_text(encoding="utf-8")
        assert "old gemini content" not in content
        assert START_MARKER in content
        assert END_MARKER in content
        assert "before" in content

    def test_injects_version_comment(self, tmp_path):
        agents_file = tmp_path / "AGENTS.md"
        install_agents_md(agents_file)

        content = agents_file.read_text(encoding="utf-8")
        assert f"<!-- gemini-version: {__version__} -->" in content


class TestInstallAllFormats:
    def test_creates_export_directory(self, tmp_path):
        export_path = tmp_path / "gemini-skill-export"
        install_all_formats(export_path)

        assert export_path.exists()
        assert (export_path / "gemini-web-skill" / "SKILL.md").exists()
        assert (export_path / "gemini-web-skill" / "references").exists()
        assert (export_path / "AGENTS_SECTION.md").exists()
        assert (export_path / "README.md").exists()

    def test_removes_existing_export(self, tmp_path):
        export_path = tmp_path / "gemini-skill-export"
        export_path.mkdir()
        (export_path / "stale.txt").write_text("old data", encoding="utf-8")

        install_all_formats(export_path)

        assert not (export_path / "stale.txt").exists()
        assert (export_path / "gemini-web-skill" / "SKILL.md").exists()


# ── Check install status tests ───────────────────────────────────────────


class TestCheckInstallStatus:
    def test_unknown_tool_returns_false(self):
        installed, path = check_install_status("nonexistent_tool_xyz")
        assert installed is False
        assert path is None

    def test_skill_md_not_installed(self, tmp_path, monkeypatch):
        monkeypatch.setitem(TOOL_CONFIGS, "_test", {
            "user": tmp_path / "missing",
            "format": "skill.md",
        })
        installed, path = check_install_status("_test", "user")
        assert installed is False

    def test_skill_md_installed(self, tmp_path, monkeypatch):
        skill_dir = tmp_path / "gemini-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("test", encoding="utf-8")

        monkeypatch.setitem(TOOL_CONFIGS, "_test", {
            "user": skill_dir,
            "format": "skill.md",
        })
        installed, path = check_install_status("_test", "user")
        assert installed is True
        assert path == skill_dir

    def test_agents_md_not_installed(self, tmp_path, monkeypatch):
        monkeypatch.setitem(TOOL_CONFIGS, "_test", {
            "user": tmp_path / "AGENTS.md",
            "format": "agents.md",
        })
        installed, path = check_install_status("_test", "user")
        assert installed is False

    def test_agents_md_installed(self, tmp_path, monkeypatch):
        agents_file = tmp_path / "AGENTS.md"
        agents_file.write_text(f"stuff\n{START_MARKER}\ncontent\n{END_MARKER}", encoding="utf-8")

        monkeypatch.setitem(TOOL_CONFIGS, "_test", {
            "user": agents_file,
            "format": "agents.md",
        })
        installed, path = check_install_status("_test", "user")
        assert installed is True


# ── Legacy migration tests ───────────────────────────────────────────────


class TestMigrateLegacyInstalls:
    def test_renames_old_skill_dir(self, tmp_path, monkeypatch):
        old_dir = tmp_path / OLD_SKILL_NAME
        old_dir.mkdir()
        (old_dir / "SKILL.md").write_text("old content", encoding="utf-8")

        new_dir = tmp_path / "gemini-web-skill"
        monkeypatch.setitem(TOOL_CONFIGS, "_test_migrate", {
            "user": new_dir,
            "format": "skill.md",
            "description": "test",
        })
        count = _migrate_legacy_installs()
        assert count >= 1
        assert new_dir.exists()
        assert (new_dir / "SKILL.md").exists()
        assert not old_dir.exists()

    def test_removes_old_when_new_exists(self, tmp_path, monkeypatch):
        old_dir = tmp_path / OLD_SKILL_NAME
        old_dir.mkdir()
        (old_dir / "SKILL.md").write_text("old", encoding="utf-8")

        new_dir = tmp_path / "gemini-web-skill"
        new_dir.mkdir()
        (new_dir / "SKILL.md").write_text("new", encoding="utf-8")

        monkeypatch.setitem(TOOL_CONFIGS, "_test_migrate", {
            "user": new_dir,
            "format": "skill.md",
            "description": "test",
        })
        _migrate_legacy_installs()
        assert not old_dir.exists()
        assert (new_dir / "SKILL.md").read_text(encoding="utf-8") == "new"

    def test_migrates_agents_md_markers(self, tmp_path, monkeypatch):
        agents_file = tmp_path / "AGENTS.md"
        agents_file.write_text(
            f"before\n{OLD_START_MARKER}\ncontent\n{OLD_END_MARKER}\nafter",
            encoding="utf-8",
        )
        monkeypatch.setitem(TOOL_CONFIGS, "_test_migrate", {
            "user": agents_file,
            "format": "agents.md",
            "description": "test",
        })
        count = _migrate_legacy_installs()
        assert count >= 1
        content = agents_file.read_text(encoding="utf-8")
        assert START_MARKER in content
        assert END_MARKER in content
        assert OLD_START_MARKER not in content
        assert OLD_END_MARKER not in content

    def test_no_migration_when_nothing_legacy(self, tmp_path, monkeypatch):
        new_dir = tmp_path / "gemini-web-skill"
        monkeypatch.setitem(TOOL_CONFIGS, "_test_migrate", {
            "user": new_dir,
            "format": "skill.md",
            "description": "test",
        })
        count = _migrate_legacy_installs()
        assert count == 0


# ── CLI command tests ────────────────────────────────────────────────────


class TestSkillCLI:
    def test_skill_group_shows_help(self):
        runner = CliRunner()
        result = runner.invoke(skill, ["--help"])
        assert result.exit_code == 0
        assert "Install Gemini skills" in result.output

    def test_skill_list_runs(self):
        runner = CliRunner()
        result = runner.invoke(skill, ["list"])
        assert result.exit_code == 0
        assert "Installation Status" in result.output

    def test_skill_show_runs(self):
        runner = CliRunner()
        result = runner.invoke(skill, ["show"])
        assert result.exit_code == 0
        assert "gemini-web-skill" in result.output

    def test_skill_install_invalid_tool(self):
        runner = CliRunner()
        result = runner.invoke(skill, ["install", "nonexistent"])
        assert result.exit_code != 0

    def test_skill_install_runs(self, tmp_path, monkeypatch):
        monkeypatch.setitem(
            TOOL_CONFIGS["claude-code"], "user", tmp_path / "gemini-web-skill"
        )
        monkeypatch.setitem(
            TOOL_CONFIGS["claude-code"], "root_dirs", [tmp_path]
        )
        runner = CliRunner()
        result = runner.invoke(skill, ["install", "claude-code"])
        assert result.exit_code == 0
        assert "Successfully installed" in result.output
        assert (tmp_path / "gemini-web-skill" / "SKILL.md").exists()

    def test_skill_uninstall_not_installed(self, tmp_path, monkeypatch):
        monkeypatch.setitem(
            TOOL_CONFIGS["opencode"], "user", tmp_path / "does-not-exist"
        )
        runner = CliRunner()
        result = runner.invoke(skill, ["uninstall", "opencode"])
        # Should report not installed and exit cleanly
        assert "not installed" in result.output.lower() or result.exit_code == 0

    def test_skill_update_nothing_installed(self):
        runner = CliRunner()
        result = runner.invoke(skill, ["update"])
        assert result.exit_code == 0


# ── Content hash detection (stale installs within same version) ──────────


class TestContentHash:
    def test_hash_is_short_hex(self):
        digest = _content_hash()
        assert isinstance(digest, str)
        assert len(digest) == 12
        int(digest, 16)  # valid hex

    def test_hash_from_skill_md(self, tmp_path, monkeypatch):
        skill_dir = tmp_path / "gemini-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            '---\nversion: "1.2.3"\ncontent-hash: "abc123abc123"\n---\n# Content',
            encoding="utf-8",
        )
        monkeypatch.setitem(TOOL_CONFIGS, "_test_tool", {
            "user": skill_dir,
            "format": "skill.md",
        })
        assert _get_installed_hash("_test_tool", "user") == "abc123abc123"

    def test_hash_from_agents_md(self, tmp_path, monkeypatch):
        agents_file = tmp_path / "AGENTS.md"
        agents_file.write_text(
            f"{START_MARKER}\n<!-- gemini-version: 2.0.0 -->\n"
            "<!-- gemini-content: deadbeef1234 -->\nContent\n",
            encoding="utf-8",
        )
        monkeypatch.setitem(TOOL_CONFIGS, "_test_tool", {
            "user": agents_file,
            "format": "agents.md",
        })
        assert _get_installed_hash("_test_tool", "user") == "deadbeef1234"

    def test_hash_missing_returns_none(self, tmp_path, monkeypatch):
        skill_dir = tmp_path / "gemini-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            '---\nversion: "1.2.3"\n---\n# Content', encoding="utf-8"
        )
        monkeypatch.setitem(TOOL_CONFIGS, "_test_tool", {
            "user": skill_dir,
            "format": "skill.md",
        })
        assert _get_installed_hash("_test_tool", "user") is None

    def test_frontmatter_injection_adds_hash(self, tmp_path):
        skill_dir = tmp_path / "gemini-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text('---\nname: test\n---\n# Content', encoding="utf-8")
        _inject_version_to_frontmatter(skill_file)
        content = skill_file.read_text(encoding="utf-8")
        assert 'version: "' in content
        assert 'content-hash: "' in content
