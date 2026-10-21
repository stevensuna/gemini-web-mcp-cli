# Cross-Product Profile Sharing

## Overview

Users who also use `notebooklm-mcp-cli` can share Chrome profiles between the two
products. Since both Gemini and NotebookLM use Google accounts, the same authenticated
Chrome profile works for both.

## Profile Storage Locations

| Product | Config Directory | Profile Storage |
|---------|-----------------|-----------------|
| gemini-web-mcp-cli | `~/.gemini-web-mcp-cli/` | `~/.gemini-web-mcp-cli/profiles/<name>/auth.json` |
| notebooklm-mcp-cli | `~/.notebooklm-mcp-cli/` | `~/.notebooklm-mcp-cli/profiles/<name>/auth.json` |

## First-Run Detection Flow

When the user runs `gemcli login` for the first time:

1. Check if `~/.notebooklm-mcp-cli/profiles/` exists
2. If found, list available profiles
3. Prompt: "NotebookLM MCP profiles detected: [default, work]. Would you like to reuse one? (Y/n)"
4. If yes: Import the Chrome profile path (not the auth tokens -- different tokens for different services)
5. If no: Create a fresh Chrome profile

## Profile Structure

```json
// ~/.gemini-web-mcp-cli/config.json
{
  "active_profile": "default",
  "version": 1
}

// ~/.gemini-web-mcp-cli/profiles/default/auth.json
{
  "cookies": {
    "__Secure-1PSID": "...",
    "__Secure-1PSIDTS": "..."
  },
  "tokens": {
    "snlm0e": "...",
    "cfb2h": "...",
    "fdrfje": "..."
  },
  "chrome_profile_path": "/path/to/chrome/profile",
  "created_at": "2026-02-15T...",
  "last_refreshed": "2026-02-15T..."
}
```

## Shared Chrome Profile

The Chrome profile (user data directory) can be shared between products. This means:
- User logs into Google once in the Chrome profile
- Both `gemcli login` and `nlm login` can use the same profile to extract cookies
- No need to maintain multiple browser sessions for the same Google account

## Environment Variable

`GEMCLI_PROFILE=work` overrides the active profile (useful for CI/automation and MCP server config).

## CLI Commands

```
gemcli profile list              # List all profiles (shows active)
gemcli profile switch <name>     # Switch active profile
gemcli profile create <name>     # Create new profile
gemcli profile delete <name>     # Delete profile
gemcli profile import --from nlm # Import NotebookLM MCP profile
gemcli login --profile <name>    # Login to specific profile
gemcli <any-command> --profile <name>  # Use specific profile for one command
```
