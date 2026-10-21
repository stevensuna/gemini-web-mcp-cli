"""Tests for profile management with cross-product sharing."""

import json

import pytest

from gemini_web_mcp_cli.core.exceptions import ProfileError
from gemini_web_mcp_cli.core.profiles import ProfileManager


@pytest.fixture
def pm(tmp_path):
    """ProfileManager with isolated temp directories for both gemcli and NLM."""
    gemcli_dir = tmp_path / "gemcli"
    nlm_dir = tmp_path / "nlm"
    return ProfileManager(config_dir=gemcli_dir, nlm_config_dir=nlm_dir)


@pytest.fixture
def pm_with_nlm(tmp_path):
    """ProfileManager with pre-existing NLM profiles."""
    gemcli_dir = tmp_path / "gemcli"
    nlm_dir = tmp_path / "nlm"

    # Create NLM profiles (auth data)
    for name in ["default", "work"]:
        profile_dir = nlm_dir / "profiles" / name
        profile_dir.mkdir(parents=True)
        auth_file = profile_dir / "auth.json"
        auth_file.write_text(json.dumps({
            "cookies": {"__Secure-1PSID": f"nlm_cookie_{name}"},
        }), encoding="utf-8")

    # Create NLM Chrome profile directories (where NLM stores browser data)
    for name in ["default", "work"]:
        chrome_dir = nlm_dir / "chrome-profiles" / name
        chrome_dir.mkdir(parents=True)

    return ProfileManager(config_dir=gemcli_dir, nlm_config_dir=nlm_dir)


class TestProfileCRUD:
    def test_create_profile(self, pm):
        path = pm.create_profile("test")
        assert path.exists()

    def test_create_duplicate_raises(self, pm):
        pm.create_profile("test")
        with pytest.raises(ProfileError, match="already exists"):
            pm.create_profile("test")

    def test_list_empty(self, pm):
        assert pm.list_profiles() == []

    def test_list_gemcli_profiles(self, pm):
        pm.create_profile("alpha")
        pm.create_profile("beta")
        assert pm.list_profiles() == ["alpha", "beta"]

    def test_profile_exists_gemcli(self, pm):
        assert not pm.profile_exists("test")
        pm.create_profile("test")
        assert pm.profile_exists("test")

    def test_delete_profile(self, pm):
        pm.create_profile("test")
        pm.create_profile("other")
        pm.set_active_profile("other")
        pm.delete_profile("test")
        assert not pm.profile_exists("test")

    def test_delete_nonexistent_raises(self, pm):
        with pytest.raises(ProfileError, match="does not exist"):
            pm.delete_profile("nope")

    def test_delete_active_raises(self, pm):
        pm.create_profile("active")
        pm.set_active_profile("active")
        with pytest.raises(ProfileError, match="Cannot delete the active"):
            pm.delete_profile("active")


class TestActiveProfile:
    def test_default(self, pm):
        assert pm.get_active_profile() == "default"

    def test_set_and_get(self, pm):
        pm.create_profile("work")
        pm.set_active_profile("work")
        assert pm.get_active_profile() == "work"

    def test_set_nonexistent_raises(self, pm):
        with pytest.raises(ProfileError, match="does not exist"):
            pm.set_active_profile("nope")

    def test_env_var_overrides(self, pm, monkeypatch):
        pm.create_profile("prod")
        pm.set_active_profile("prod")
        monkeypatch.setenv("GEMCLI_PROFILE", "env_profile")
        assert pm.get_active_profile() == "env_profile"

    def test_config_persists(self, pm):
        pm.create_profile("persist")
        pm.set_active_profile("persist")
        pm2 = ProfileManager(config_dir=pm.config_dir, nlm_config_dir=pm.nlm_config_dir)
        assert pm2.get_active_profile() == "persist"


class TestAuthData:
    def test_save_and_load(self, pm):
        pm.create_profile("test")
        auth = {"cookies": {"__Secure-1PSID": "abc"}, "tokens": {"snlm0e": "xyz"}}
        pm.save_auth(auth, name="test")
        loaded = pm.load_auth("test")
        assert loaded["cookies"]["__Secure-1PSID"] == "abc"

    def test_load_missing_returns_empty(self, pm):
        assert pm.load_auth("nonexistent") == {}

    def test_save_creates_profile_dir(self, pm):
        pm.save_auth({"test": True}, name="auto_created")
        assert pm.profile_exists("auto_created")


class TestNLMCrossProduct:
    def test_nlm_profiles_appear_in_list(self, pm_with_nlm):
        """NLM profiles should be visible without any import step."""
        profiles = pm_with_nlm.list_profiles()
        assert "default" in profiles
        assert "work" in profiles

    def test_nlm_profile_exists(self, pm_with_nlm):
        assert pm_with_nlm.profile_exists("default")
        assert pm_with_nlm.profile_exists("work")

    def test_nlm_profiles_live(self, pm_with_nlm):
        """New NLM profiles should automatically appear."""
        # Add a new NLM profile
        new_dir = pm_with_nlm.nlm_profiles_dir / "personal"
        new_dir.mkdir(parents=True)
        (new_dir / "auth.json").write_text(
            json.dumps({"chrome_profile_path": "/tmp/p"}), encoding="utf-8"
        )

        profiles = pm_with_nlm.list_profiles()
        assert "personal" in profiles

    def test_load_auth_from_nlm_gives_chrome_path(self, pm_with_nlm):
        """Loading auth from an NLM profile should give us the Chrome profile path."""
        auth = pm_with_nlm.load_auth("work")
        assert "chrome-profiles/work" in auth["chrome_profile_path"]
        assert auth["_source"] == "nlm"

    def test_gemcli_auth_overrides_nlm(self, pm_with_nlm):
        """If gemcli has its own auth for a profile, it takes precedence."""
        pm_with_nlm.save_auth(
            {"cookies": {"__Secure-1PSID": "gemini_cookie"}},
            name="work",
        )
        auth = pm_with_nlm.load_auth("work")
        assert auth["cookies"]["__Secure-1PSID"] == "gemini_cookie"
        assert "_source" not in auth  # Not NLM anymore

    def test_set_active_to_nlm_profile(self, pm_with_nlm):
        """Should be able to set an NLM profile as active."""
        pm_with_nlm.set_active_profile("work")
        assert pm_with_nlm.get_active_profile() == "work"

    def test_cannot_delete_nlm_profile(self, pm_with_nlm):
        """NLM-sourced profiles cannot be deleted from gemcli."""
        pm_with_nlm.set_active_profile("default")  # make it active to test other path
        with pytest.raises(ProfileError, match="NotebookLM"):
            pm_with_nlm.delete_profile("work")

    def test_detailed_list_shows_source(self, pm_with_nlm):
        profiles = pm_with_nlm.list_profiles_detailed()
        sources = {p.name: p.source for p in profiles}
        assert sources["default"] == "nlm"
        assert sources["work"] == "nlm"

    def test_detailed_list_gemcli_overrides_nlm(self, pm_with_nlm):
        """If profile exists in both, gemcli source wins."""
        pm_with_nlm.save_auth({"test": True}, name="work")
        profiles = pm_with_nlm.list_profiles_detailed()
        sources = {p.name: p.source for p in profiles}
        assert sources["work"] == "gemcli"

    def test_mixed_profiles(self, pm_with_nlm):
        """gemcli-native and NLM profiles coexist."""
        pm_with_nlm.create_profile("gemcli_only")
        profiles = pm_with_nlm.list_profiles()
        assert "default" in profiles      # from NLM
        assert "work" in profiles          # from NLM
        assert "gemcli_only" in profiles   # gemcli-native

    def test_has_nlm_profiles(self, pm_with_nlm):
        assert pm_with_nlm.has_nlm_profiles()

    def test_is_first_run(self, pm_with_nlm):
        assert pm_with_nlm.is_first_run()
        pm_with_nlm.save_auth({"x": 1}, name="test")
        assert not pm_with_nlm.is_first_run()

    def test_get_chrome_profile_path(self, pm_with_nlm):
        path = pm_with_nlm.get_chrome_profile_path("work")
        assert path is not None
        assert "chrome-profiles/work" in path

    def test_no_nlm(self, pm):
        """When NLM is not installed, everything still works."""
        assert not pm.has_nlm_profiles()
        assert pm.list_profiles() == []
        assert pm.is_first_run()
