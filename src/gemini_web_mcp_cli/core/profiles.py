"""Profile management for multi-account support with cross-product sharing.

Profile resolution (unified view):
1. gemcli-native profiles at ~/.gemini-web-mcp-cli/profiles/<name>/
2. NotebookLM MCP profiles at ~/.notebooklm-mcp-cli/profiles/<name>/ (live, not copied)

When listing profiles, BOTH locations are shown. NLM profiles are live --
new profiles created in NLM automatically appear in gemcli.

When a user selects an NLM-sourced profile, gemcli:
- Reads the Chrome profile path from NLM's auth.json (shared browser session)
- Stores Gemini-specific auth tokens in gemcli's own location
- Never modifies NLM's auth data

gemcli-only profiles are stored exclusively at ~/.gemini-web-mcp-cli/profiles/.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from .constants import (
    AUTH_FILE,
    CONFIG_DIR_NAME,
    CONFIG_FILE,
    DEFAULT_PROFILE_NAME,
    ENV_PROFILE,
    NLM_CONFIG_DIR_NAME,
    PROFILES_DIR,
)
from .exceptions import ProfileError
from .json_io import read_json_dict, write_json_file


def _config_dir() -> Path:
    """Get the config directory path (~/.gemini-web-mcp-cli)."""
    return Path.home() / CONFIG_DIR_NAME


def _nlm_config_dir() -> Path:
    """Get the NotebookLM MCP config directory path."""
    return Path.home() / NLM_CONFIG_DIR_NAME


@dataclass
class ProfileInfo:
    """Metadata about a profile, including its source."""

    name: str
    source: str  # "gemcli" or "nlm"
    path: Path  # Directory containing this profile's data for its source product

    @property
    def display_name(self) -> str:
        if self.source == "nlm":
            return f"{self.name} (from NotebookLM)"
        return self.name


class ProfileManager:
    """Manages authentication profiles with live cross-product support.

    Provides a unified view of profiles from:
    1. ~/.gemini-web-mcp-cli/profiles/ (gemcli-native)
    2. ~/.notebooklm-mcp-cli/profiles/ (NLM, live reference)

    NLM profiles are never copied. gemcli piggybacks on the NLM Chrome
    profile for authentication, but stores its own Gemini-specific tokens
    separately.

    Active profile tracked in ~/.gemini-web-mcp-cli/config.json.
    Environment variable GEMCLI_PROFILE overrides the active profile.
    """

    def __init__(self, config_dir: Path | None = None, nlm_config_dir: Path | None = None):
        self.config_dir = config_dir or _config_dir()
        self.profiles_dir = self.config_dir / PROFILES_DIR
        self.config_file = self.config_dir / CONFIG_FILE
        self.nlm_config_dir = nlm_config_dir or _nlm_config_dir()
        self.nlm_profiles_dir = self.nlm_config_dir / PROFILES_DIR
        self._json_cache: dict[Path, tuple[int, dict]] = {}

    def _ensure_dirs(self) -> None:
        """Create config directories if they don't exist."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

    def _profile_dir(self, name: str) -> Path:
        """Get the gemcli-native directory for a specific profile."""
        return self.profiles_dir / name

    def _auth_file(self, name: str) -> Path:
        """Get the gemcli auth.json path for a specific profile."""
        return self._profile_dir(name) / AUTH_FILE

    def _nlm_profile_dir(self, name: str) -> Path:
        """Get the NLM directory for a specific profile."""
        return self.nlm_profiles_dir / name

    def _nlm_auth_file(self, name: str) -> Path:
        """Get the NLM auth.json path for a specific profile."""
        return self._nlm_profile_dir(name) / AUTH_FILE

    # ── Cached JSON reads ──────────────────────────────────────────────

    def _read_json_cached(self, path: Path) -> dict:
        """Read a JSON dict with mtime-based caching.

        Avoids repeated parse when the file hasn't changed on disk — useful
        in the MCP hot path where every tool call checks auth/config.
        """
        try:
            mtime_ns = path.stat().st_mtime_ns
        except (OSError, FileNotFoundError):
            self._json_cache.pop(path, None)
            return {}

        cached = self._json_cache.get(path)
        if cached and cached[0] == mtime_ns:
            return cached[1].copy()

        data = read_json_dict(path)
        self._json_cache[path] = (mtime_ns, data)
        return data.copy()

    def _invalidate_cache(self, path: Path) -> None:
        """Drop a cached entry after writing to the file."""
        self._json_cache.pop(path, None)

    # ── Config file management ──────────────────────────────────────────

    def _read_config(self) -> dict:
        """Read the config.json file."""
        return self._read_json_cached(self.config_file)

    def _write_config(self, config: dict) -> None:
        """Write the config.json file."""
        self._ensure_dirs()
        write_json_file(self.config_file, config, mkdir=False)
        self._invalidate_cache(self.config_file)

    # ── Active profile ──────────────────────────────────────────────────

    def get_active_profile(self) -> str:
        """Get the active profile name. Environment variable takes priority."""
        env_profile = os.environ.get(ENV_PROFILE)
        if env_profile:
            return env_profile

        config = self._read_config()
        return config.get("active_profile", DEFAULT_PROFILE_NAME)

    def set_active_profile(self, name: str) -> None:
        """Set the active profile. Must exist in either gemcli or NLM."""
        if not self.profile_exists(name):
            raise ProfileError(f"Profile '{name}' does not exist.")
        config = self._read_config()
        config["active_profile"] = name
        config["version"] = 1
        self._write_config(config)
        logger.info(f"Switched to profile: {name}")

    # ── Profile discovery (unified view) ────────────────────────────────

    def profile_exists(self, name: str) -> bool:
        """Check if a profile exists in either gemcli or NLM locations."""
        return self._profile_dir(name).is_dir() or self._nlm_profile_dir(name).is_dir()

    def _list_gemcli_profiles(self) -> list[str]:
        """List gemcli-native profile names."""
        if not self.profiles_dir.exists():
            return []
        return sorted(d.name for d in self.profiles_dir.iterdir() if d.is_dir())

    def _list_nlm_profiles(self) -> list[str]:
        """List NotebookLM MCP profile names (live, no copy)."""
        if not self.nlm_profiles_dir.exists():
            return []
        return sorted(d.name for d in self.nlm_profiles_dir.iterdir() if d.is_dir())

    def list_profiles(self) -> list[str]:
        """List all available profile names from both sources (deduplicated)."""
        gemcli = set(self._list_gemcli_profiles())
        nlm = set(self._list_nlm_profiles())
        return sorted(gemcli | nlm)

    def list_profiles_detailed(self) -> list[ProfileInfo]:
        """List all profiles with source information.

        If a profile exists in both gemcli and NLM, it shows as "gemcli"
        (gemcli-native takes precedence since it has Gemini-specific tokens).
        """
        profiles: dict[str, ProfileInfo] = {}

        # NLM profiles first (lower precedence)
        for name in self._list_nlm_profiles():
            profiles[name] = ProfileInfo(
                name=name,
                source="nlm",
                path=self._nlm_profile_dir(name),
            )

        # gemcli profiles override (higher precedence)
        for name in self._list_gemcli_profiles():
            profiles[name] = ProfileInfo(
                name=name,
                source="gemcli",
                path=self._profile_dir(name),
            )

        return sorted(profiles.values(), key=lambda p: p.name)

    def get_profile_source(self, name: str) -> str:
        """Get the source of a profile: 'gemcli', 'nlm', or raises."""
        if self._profile_dir(name).is_dir():
            return "gemcli"
        if self._nlm_profile_dir(name).is_dir():
            return "nlm"
        raise ProfileError(f"Profile '{name}' does not exist.")

    # ── Profile CRUD (gemcli-native only) ───────────────────────────────

    def create_profile(self, name: str) -> Path:
        """Create a new gemcli-native profile directory."""
        self._ensure_dirs()
        profile_dir = self._profile_dir(name)
        if profile_dir.exists():
            raise ProfileError(f"Profile '{name}' already exists.")
        profile_dir.mkdir(parents=True)
        logger.info(f"Created profile: {name}")
        return profile_dir

    def delete_profile(self, name: str) -> None:
        """Delete a gemcli-native profile. Cannot delete NLM-sourced profiles."""
        profile_dir = self._profile_dir(name)

        if not profile_dir.exists():
            if self._nlm_profile_dir(name).is_dir():
                raise ProfileError(
                    f"Profile '{name}' is from NotebookLM MCP. "
                    "Delete it from NotebookLM instead."
                )
            raise ProfileError(f"Profile '{name}' does not exist.")

        if self.get_active_profile() == name:
            raise ProfileError(
                f"Cannot delete the active profile '{name}'. Switch to another profile first."
            )

        import shutil
        shutil.rmtree(profile_dir)
        logger.info(f"Deleted profile: {name}")

    def rename_profile(self, old_name: str, new_name: str) -> None:
        """Rename a gemcli-native profile. Cannot rename NLM-sourced profiles.

        Renames:
        1. Profile directory (~/.gemini-web-mcp-cli/profiles/<name>)
        2. Chrome profile directory (~/.gemini-web-mcp-cli/chrome-profiles/<name>)
        3. Token Factory profile directory (<name>_tf)
        4. chrome_profile_path inside auth.json
        5. Active profile in config.json (if this was the active profile)
        """
        # Validate old profile exists and is gemcli-native
        old_profile_dir = self._profile_dir(old_name)
        if not old_profile_dir.exists():
            if self._nlm_profile_dir(old_name).is_dir():
                raise ProfileError(
                    f"Profile '{old_name}' is from NotebookLM MCP. "
                    "Rename it from NotebookLM instead."
                )
            raise ProfileError(f"Profile '{old_name}' does not exist.")

        # Validate new name doesn't conflict
        if not new_name or not new_name.strip():
            raise ProfileError("New profile name cannot be empty.")
        new_name = new_name.strip()
        if self.profile_exists(new_name):
            raise ProfileError(f"Profile '{new_name}' already exists.")

        # 1. Rename profile directory
        new_profile_dir = self._profile_dir(new_name)
        old_profile_dir.rename(new_profile_dir)
        logger.debug(f"Renamed profile dir: {old_name} -> {new_name}")

        # 2. Rename Chrome profile directory (if it exists)
        chrome_profiles_dir = self.config_dir / "chrome-profiles"
        old_chrome_dir = chrome_profiles_dir / old_name
        new_chrome_dir = chrome_profiles_dir / new_name
        if old_chrome_dir.exists():
            old_chrome_dir.rename(new_chrome_dir)
            logger.debug(f"Renamed Chrome profile: {old_name} -> {new_name}")

        # 3. Rename Token Factory profile directory (<name>_tf)
        old_tf_dir = chrome_profiles_dir / f"{old_name}_tf"
        new_tf_dir = chrome_profiles_dir / f"{new_name}_tf"
        if old_tf_dir.exists():
            old_tf_dir.rename(new_tf_dir)
            logger.debug(f"Renamed TF profile: {old_name}_tf -> {new_name}_tf")

        # 4. Update chrome_profile_path inside auth.json
        auth_file = self._auth_file(new_name)
        if auth_file.exists():
            try:
                data = read_json_dict(auth_file)
                old_path = data.get("chrome_profile_path", "")
                if old_path and old_name in old_path:
                    data["chrome_profile_path"] = old_path.replace(
                        f"/{old_name}", f"/{new_name}"
                    )
                    write_json_file(auth_file, data, mkdir=False)
                    self._invalidate_cache(auth_file)
                    logger.debug("Updated chrome_profile_path in auth.json")
            except OSError as e:
                logger.warning(f"Could not update auth.json: {e}")

        # 5. Update active profile if this was the active one
        if self.get_active_profile() == old_name:
            config = self._read_config()
            config["active_profile"] = new_name
            self._write_config(config)
            logger.debug(f"Updated active profile: {old_name} -> {new_name}")

        logger.info(f"Renamed profile: {old_name} -> {new_name}")

    # ── Auth data management ────────────────────────────────────────────

    def load_auth(self, name: str | None = None) -> dict:
        """Load auth data for a profile.

        Resolution order:
        1. gemcli-native auth.json (has Gemini-specific tokens)
        2. NLM auth.json (has Chrome profile path we can piggyback on)
        """
        profile_name = name or self.get_active_profile()

        gemcli_auth = self._auth_file(profile_name)
        if gemcli_auth.exists():
            data = self._read_json_cached(gemcli_auth)
            if data:
                return data
            logger.warning(f"Failed to load gemcli auth for '{profile_name}'")

        # Fall back to NLM -- compute the Chrome profile path from the profile name.
        # NLM stores Chrome profiles at ~/.notebooklm-mcp-cli/chrome-profiles/<name>/
        # (it doesn't put chrome_profile_path in auth.json -- the path is computed).
        nlm_chrome_dir = self.nlm_config_dir / "chrome-profiles" / profile_name
        if nlm_chrome_dir.is_dir():
            chrome_path = str(nlm_chrome_dir)
            logger.debug(f"Using NLM Chrome profile for '{profile_name}': {chrome_path}")
            return {
                "chrome_profile_path": chrome_path,
                "_source": "nlm",
                "_nlm_profile": profile_name,
            }

        return {}

    def save_auth(self, auth_data: dict, name: str | None = None) -> None:
        """Save auth data to gemcli-native location.

        Always saves to ~/.gemini-web-mcp-cli/profiles/<name>/auth.json,
        even if the profile originally came from NLM. This is where
        Gemini-specific cookies and tokens are stored.
        """
        profile_name = name or self.get_active_profile()
        self._ensure_dirs()

        profile_dir = self._profile_dir(profile_name)
        profile_dir.mkdir(parents=True, exist_ok=True)

        auth_file = self._auth_file(profile_name)
        write_json_file(auth_file, auth_data, mkdir=False)
        self._invalidate_cache(auth_file)
        logger.debug(f"Saved auth for profile: {profile_name}")

    def get_chrome_profile_path(self, name: str | None = None) -> str | None:
        """Get the Chrome profile path for a profile.

        Resolution order:
        1. gemcli-native auth.json (explicit chrome_profile_path)
        2. NLM chrome-profiles directory (~/.notebooklm-mcp-cli/chrome-profiles/<name>/)
        3. gemcli's own chrome-profiles directory
        """
        profile_name = name or self.get_active_profile()

        # Check gemcli auth.json for explicit path
        gemcli_auth = self._auth_file(profile_name)
        if gemcli_auth.exists():
            data = self._read_json_cached(gemcli_auth)
            if data.get("chrome_profile_path"):
                return data["chrome_profile_path"]

        # Check NLM chrome-profiles directory (where NLM stores its Chrome user data)
        nlm_chrome = self.nlm_config_dir / "chrome-profiles" / profile_name
        if nlm_chrome.is_dir():
            return str(nlm_chrome)

        return None

    # ── Cross-product detection ─────────────────────────────────────────

    def has_nlm_profiles(self) -> bool:
        """Check if any NotebookLM MCP profiles exist."""
        return bool(self._list_nlm_profiles())

    def is_first_run(self) -> bool:
        """Check if this is the first run (no gemcli-native profiles exist)."""
        return len(self._list_gemcli_profiles()) == 0
